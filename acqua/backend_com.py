"""真實的 ACQUA COM 後端。

## 實機驗證狀態(2026-08-10,ACOPT18 dongle 已插入)

已驗證可用:
  ✅ Dispatch / DispatchWithEvents(ACQUA 已在執行時會接上現有實例,0.02s)
  ✅ AppLoadFinished / SelectedProject / SelectedProjectLoaded
  ✅ ProjectGroups 走訪 —— 沒有群組的專案會出現在 ACQUA 合成的
     「(Unsorted Projects)」群組下,rProjectGroup 為 NULL 不影響列舉
  ✅ MeasurementEngine:Mfe4~Mfe11 / Labcore / TurnTable / HardwareConfig 都拿得到
  ✅ 變數讀寫:UsedVariables.Add() → 設 Name/Type/Value/State → Save() → 讀得回來
  ✅ RunScript("Python", code):可執行,且腳本例外會以 COM 錯誤傳回

尚未驗證(需要實際跑一次量測):
  ⬜ ByRef 輸出參數(UserReaction / Continue)是否真的用 return 回傳
  ⬜ StartSingleMeasurement 之後等 IsMeasuring 翻轉有沒有 race condition
  ⬜ OnFinishedMeasurements 的 ResultOverview 結構
  ⬜ sqlcat.read_results() 的欄位對應(撰寫時資料庫還沒有任何量測結果)

已知不可用:
  ❌ AcquaDBMask.Application.Connect() 一律回傳 False(四種參數組合都試過)
     → 列舉 SMD 與讀數值改走 SQL,見 acqua/sqlcat.py
  ❌ FindFirstSMD("") 回傳 0 個 —— 空字串不等於「全部」,且不回傳標題

前置需求:
  1. 32-bit Python + pywin32(HEAD 原廠已內建)
  2. ACQUA 已安裝且 ACOPT18 授權有效
  3. 資料庫裡有定義好的專案與 SMD

執行緒約束:本類別的所有方法只能在 AcquaWorker 那一條執行緒上呼叫。
"""
import time

from .backend_base import AcquaBackend
from .constants import (PROGID_ACQUA, EMEEventType, EMEResult, EUserReaction,
                        EVariableState, EVariableType)


class _Events:
    """COM 事件接收器。

    ⚠️ pywin32 的 DispatchWithEvents 不會呼叫 __init__,
       所以相依物件用「類別屬性注入」的方式傳進來。
       因為只有單一工作執行緒會用它,這樣做是安全的。
    """
    backend = None      # ← 由 ComBackend.initialize() 注入

    def _st(self):
        return self.backend.state

    def _tick(self):
        """任何事件進來都戳一下 —— 用來判斷 ACQUA 是不是沒回應了。"""
        self.backend._last_event_at = time.monotonic()

    # ── 純資訊 ──────────────────────────────────────
    def OnProgress(self, Description, ProgressCounter, TotalCount):
        self._tick()
        if ProgressCounter != -1 and TotalCount not in (-1, 0):
            self._st().set(progress={"text": Description,
                                     "value": int(ProgressCounter),
                                     "total": int(TotalCount)})
        else:
            self._st().set(progress=None)

    def OnEvent(self, Description, EventType):
        self._tick()
        level = {0: "info", 1: "warn", 2: "error"}.get(int(EventType), "info")
        tag = EMEEventType.NAMES.get(int(EventType), "?")
        self._st().log(f"<{tag}> {Description}", level)

    def OnBeginMeasurements(self, SelectedProject, MeasurementObject, NbrOfMeasurements):
        self._st().log(f"ACQUA 回報:即將進行 {NbrOfMeasurements} 筆量測")

    def OnBeginSingleMeasurement(self, SMDTitle, Progress, NbrOfMeasurements):
        self._tick()
        self.backend._meas_started = True
        self._st().log(f"  ACQUA 開始:{SMDTitle}")

    # ── 決策點:ByRef 輸出用「回傳值」給回 ACQUA ────────
    def OnFinishedSingleMeasurement(self, SMDTitle, ResultStatus,
                                    Progress, NbrOfMeasurements, UserReaction):
        # ✅ 已驗證(2026-08-10,SP2 / SMD#3579):pywin32 用 return 回傳 ByRef out 參數
        #    確實生效 —— 回傳後 ACQUA 有繼續往下走到 "Measurements done"。
        self._tick()
        self.backend._on_single_finished(SMDTitle, ResultStatus)
        if self._st().cancel_requested:
            return EUserReaction.CANCEL_ALL
        return EUserReaction.DO_NEXT

    def OnFinishedMeasurements(self, SelectedProject, MeasurementObject,
                               NbrOfMeasurements, NbrOfMeasurementsFinished,
                               Canceled, ResultOverview):
        self._tick()
        self.backend._measuring_done = True
        # ⭐ ResultOverview 是 Variant,CHM 沒有說明結構。
        #    這是唯一可能一次拿到整批數值的地方 —— 階段 4 務必把它 dump 出來研究。
        self._st().log(f"ACQUA 回報:完成 {NbrOfMeasurementsFinished}/{NbrOfMeasurements}"
                       f"{'(已取消)' if Canceled else ''}")
        try:
            self._st().log(f"  ResultOverview type={type(ResultOverview).__name__} "
                           f"value={ResultOverview!r}"[:500], "warn")
        except Exception:
            pass

    def OnCallbackEvent(self, EventDescription, Continue):
        # ACQUA 詢問使用者決策(例如「請接上治具後繼續」)。
        # 無人值守一律回 True;要人工介入的話,這裡要改成推到 UI 等待回應。
        self._st().log(f"[CALLBACK] {EventDescription} → 自動繼續", "warn")
        return True


class ComBackend(AcquaBackend):
    def __init__(self, state, config):
        super().__init__(state, config)
        self.app = None
        self.project = None            # IProjectSelected
        self.mo = None                 # IMObject
        self.sql = None                # SqlCatalog —— 列舉 SMD 與讀數值(實測後改走這條)
        self._pythoncom = None
        self._last_result = None       # (title, status)
        self._measuring_done = False
        self._meas_started = False
        self._last_event_at = 0.0      # 最後一次收到 ACQUA 事件的時間

    # ── 生命週期 ────────────────────────────────────
    def initialize(self):
        import pythoncom
        import win32com.client
        import struct

        self._pythoncom = pythoncom
        bits = struct.calcsize("P") * 8
        self.state.set(backend_kind="com")
        self.state.log(f"Python {bits}-bit;ACQUA 為 32-bit")
        if bits != 32:
            self.state.log("⚠️ 建議改用 32-bit Python —— TypeLib 只註冊了 win32 分支", "warn")

        # COM 事件需要 STA(單執行緒公寓)。這一步必須在本執行緒上做。
        pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)

        _Events.backend = self

        # 先看 ACQUA 在不在 —— 不在的話 COM 會自己去啟動,但那要等很久
        running = self._acqua_is_running()
        if running:
            self.state.log("偵測到 ACQUA 已在執行,將接上現有實例")
        else:
            self.state.log("⚠️ ACQUA 沒有在執行。COM 會嘗試自動啟動它,"
                           "但這可能要 1~3 分鐘,而且不一定成功。"
                           "建議先手動開啟 ACQUA 再啟動本程式。", "warn")

        self.state.log(f"建立 COM 物件:{PROGID_ACQUA} …")
        try:
            self.app = win32com.client.DispatchWithEvents(PROGID_ACQUA, _Events)
        except Exception as exc:                            # noqa: BLE001
            raise RuntimeError(self._explain_com_error(exc, "建立 COM 物件失敗")) from exc

        self.state.log("等待 ACQUA 啟動(AppLoadFinished)…")
        try:
            # ⚠️ Dispatch 成功 ≠ 物件可用。ACQUA 還在初始化時,
            #    讀任何屬性都會丟 RPC 錯誤 —— 這裡要容忍並重試。
            self._wait_until(lambda: self.app.AppLoadFinished,
                             timeout=300, what="AppLoadFinished",
                             tolerate_com_errors=True)
        except Exception as exc:                            # noqa: BLE001
            raise RuntimeError(self._explain_com_error(exc, "等待 ACQUA 就緒失敗")) from exc

        self.state.set(acqua_ready=True)
        self.state.log("ACQUA 已就緒")

        try:
            self.state.log(f"ACQUA 目前:{self.app.SelectedSQLServerName} / "
                           f"{self.app.SelectedDatabaseName}")
        except Exception:                                   # noqa: BLE001
            pass

    def pump(self):
        if self._pythoncom is not None:
            self._pythoncom.PumpWaitingMessages()

    def shutdown(self):
        self.app = None
        self.project = None
        self.mo = None
        self.sql = None
        if self._pythoncom is not None:
            try:
                self._pythoncom.CoUninitialize()
            except Exception:
                pass

    # ── 內部工具 ────────────────────────────────────
    @staticmethod
    def _acqua_is_running() -> bool:
        """用 WMI 看 Acqua6.exe 在不在。查不到就當作「不確定」回 False。"""
        try:
            import win32com.client
            wmi = win32com.client.GetObject("winmgmts:")
            q = ("SELECT ProcessId FROM Win32_Process "
                 "WHERE Name LIKE 'Acqua%.exe'")
            return len(list(wmi.ExecQuery(q))) > 0
        except Exception:                                   # noqa: BLE001
            return False

    @staticmethod
    def _explain_com_error(exc, prefix="") -> str:
        """把難懂的 COM 錯誤碼換成看得懂的說明。"""
        code = getattr(exc, "hresult", None) or getattr(exc, "args", [None])[0]
        try:
            code = int(code) & 0xFFFFFFFF
        except Exception:                                   # noqa: BLE001
            code = None
        table = {
            0x800706BA: ("RPC 伺服器無法使用",
                         "ACQUA 沒有在執行,或啟動到一半失敗。"),
            0x800706BE: ("遠端程序呼叫失敗",
                         "ACQUA 還在初始化,或中途當掉了。"),
            0x80080005: ("伺服器執行失敗",
                         "COM 啟動 ACQUA 失敗 —— 常見於授權未生效或 dongle 沒插。"),
            0x80040154: ("類別未註冊",
                         "ACQUA 的 COM 沒註冊,或你用的是 64-bit Python(必須 32-bit)。"),
            0x80070005: ("存取被拒",
                         "權限問題 —— 試試看以相同使用者身分執行,或關掉以系統管理員執行。"),
        }
        name, hint = table.get(code, (str(exc), ""))
        msg = f"{prefix}:{name}"
        if hint:
            msg += f"\n  可能原因:{hint}"
        msg += ("\n  建議:1) 先手動開啟 ACQUA 並等它完全載入"
                "  2) 確認 dongle 已插入、ACOPT18 授權有效"
                "  3) 用 --backend mock 確認程式本身沒問題")
        return msg

    def _wait_until(self, predicate, timeout=120.0, interval=0.05, what="condition",
                    tolerate_com_errors=False):
        """等待期間必須持續打訊息幫浦,否則 COM 事件永遠不會送達。

        tolerate_com_errors=True 時,會忽略等待過程中的 COM 例外 ——
        ACQUA 啟動期間讀屬性會丟 RPC 錯誤,那是暫時的,重試就好。
        """
        deadline = time.monotonic() + timeout
        last_exc = None
        notified = False
        while True:
            try:
                if predicate():
                    return
                last_exc = None
            except Exception as exc:                        # noqa: BLE001
                if not tolerate_com_errors:
                    raise
                last_exc = exc
                if not notified:
                    self.state.log("ACQUA 尚未回應(啟動中),持續重試…", "warn")
                    notified = True
            self.pump()
            time.sleep(max(interval, 0.2) if last_exc is not None else interval)
            if time.monotonic() > deadline:
                if last_exc is not None:
                    raise last_exc
                raise TimeoutError(f"等待逾時({timeout}s):{what}")

    def _on_single_finished(self, title, status):
        self._last_result = (str(title), int(status))

    def _wait_until_measured(self, title, timeout, stall_warn=45):
        """等單筆量測結束,並在 ACQUA 長時間沒回應時提醒。

        完成的判定(任一成立):
          - 收到 OnFinishedSingleMeasurement
          - 收到 OnFinishedMeasurements
          - 已經開始過,而且 IsMeasuring 翻回 False
        """
        deadline = time.monotonic() + timeout
        warned = 0
        while True:
            if self._last_result is not None or self._measuring_done:
                return True
            try:
                if self._meas_started and not self.app.IsMeasuring:
                    return True
            except Exception:                               # noqa: BLE001
                pass                                        # COM 暫時忙,下一圈再試

            self.pump()
            time.sleep(0.05)

            # 停滯提醒 —— Info 型 SMD 會開文件視窗等人關閉,這時完全不會有事件
            idle = time.monotonic() - self._last_event_at
            if idle > stall_warn * (warned + 1):
                warned += 1
                self.state.log(
                    f"    ⏳ ACQUA 已經 {int(idle)} 秒沒有任何回應 —— "
                    "常見原因:它開了說明文件/對話框在等人關閉。"
                    "請切到 ACQUA 視窗看看。", "warn")

            if time.monotonic() > deadline:
                self.state.log(
                    f"    ✗ 等待 {timeout} 秒逾時:{title}(視為失敗,繼續下一項)", "error")
                return False

    # ── 操作 ────────────────────────────────────────
    def connect(self, server, database, win_auth, username="", password=""):
        ok = bool(self.app.SelectDatabase(server, database, win_auth, username, password))
        if ok:
            self.state.set(connected=True,
                           server=str(self.app.SelectedSQLServerName),
                           database=str(self.app.SelectedDatabaseName))
            self.state.log(f"已連線 {self.state.server} / {self.state.database}")
        else:
            self.state.log("資料庫連線失敗(SelectDatabase 回傳 False)", "error")
        return ok

    def list_databases(self, server=""):
        from .sqlcat import list_databases as _ls
        srv = server or self.state.server or self.config.get("database", {}).get("server", "")
        if not srv:
            raise RuntimeError("沒有指定 SQL Server")
        dbs = _ls(srv)
        n = sum(1 for d in dbs if d["is_acqua"])
        self.state.set(databases=dbs)
        self.state.log(f"[SQL] {srv} 上有 {len(dbs)} 個資料庫,其中 {n} 個是 ACQUA 庫")
        return dbs

    def refresh_project_groups(self):
        groups = []
        pgs = self.app.ProjectGroups
        for i in range(pgs.Count):                 # ⚠️ Item() 索引從 0 開始
            pg = pgs.Item(i)
            projects = [pg.Projects.Item(j).Title for j in range(pg.Projects.Count)]
            groups.append({"name": str(pg.Title), "projects": [str(p) for p in projects]})
        self.state.set(project_groups=groups)
        return groups

    def open_project(self, group, project):
        pgs = self.app.ProjectGroups
        target = None
        for i in range(pgs.Count):
            pg = pgs.Item(i)
            if str(pg.Title) != group:
                continue
            for j in range(pg.Projects.Count):
                pj = pg.Projects.Item(j)
                if str(pj.Title) == project:
                    target = pj
                    break
        if target is None:
            raise RuntimeError(f"找不到專案:{group} / {project}")

        target.SelectAsActive()                     # 這裡拿到的是 IProject,只能做這件事
        self._wait_until(lambda: self.app.SelectedProjectLoaded,
                         timeout=300, what="SelectedProjectLoaded")
        self.project = self.app.SelectedProject     # ⭐ 現在才是 IProjectSelected
        self.state.set(open_group=group, open_project=str(self.project.Title),
                       measurement_object=None, smds=[])
        self.state.log(f"已開啟專案:{group} / {self.project.Title}")

    def select_measurement_object(self, title, create_if_missing=True):
        if self.project is None:
            raise RuntimeError("尚未開啟專案")
        # ⚠️ 實測(2026-08-10):專案底下一個 MO 都沒有時,
        #    存取 .MeasurementObjects 本身就會丟 "Index out of range",
        #    不是回傳空集合。所以整段都要包起來。
        mos, titles = None, []
        try:
            mos = self.project.MeasurementObjects
            titles = [str(mos.Item(i).Title) for i in range(mos.Count)]
        except Exception as exc:                            # noqa: BLE001
            self.state.log(f"量測物件清單讀取失敗(通常代表一個都沒有):{exc}", "warn")

        if title not in titles:
            if not create_if_missing:
                raise RuntimeError(
                    f"找不到量測物件「{title}」,而且 create_mo_if_missing 是 false")
            if mos is None:
                mos = self.project.MeasurementObjects   # 讓它再丟一次,錯誤才看得到
            mos.AddMeasurementObject(title, "由自動化建立")
            self.state.log(f"已新增量測物件:{title}")

        # SelectActiveMeasurementObject 接受「索引或名稱」(Variant)
        self.mo = self.project.SelectActiveMeasurementObject(title)
        if self.mo is None:
            raise RuntimeError(f"選取量測物件失敗:{title}")
        self.state.set(measurement_object=str(self.mo.Title))
        self.state.log(f"已選定量測物件:{self.mo.Title}")

    def write_metadata(self, props):
        if self.mo is None:
            raise RuntimeError("尚未選定量測物件")
        for k, v in props.items():
            if not v or k.startswith("_"):
                continue
            self.mo.UpdateProperty(str(k), str(v))   # 欄位不存在會自動建立
            self.state.log(f"  UpdateProperty({k!r}, {v!r})")

    def _catalog(self):
        """取得 SQL 目錄(延遲連線)。"""
        if self.sql is None:
            from .sqlcat import SqlCatalog
            cat = SqlCatalog(self.state)
            if not cat.connect(self.state.server, self.state.database):
                raise RuntimeError("SQL 目錄連線失敗")
            self.sql = cat
        return self.sql

    def list_smds(self, search=""):
        """列出專案內的 SMD(含標題與 MMD 階層)。

        ⭐ 實機驗證後改走 SQL,原因見 acqua/sqlcat.py 的說明:
           - AcquaDBMask.Connect() 一律回 False,連不上
           - Acqua3 的 FindFirstSMD 是「搜尋」不是「列舉」,
             FindFirstSMD("") 回傳 0 個,而且不給標題
           - 已驗證 SQL 的 idTreeItem == Acqua3 的 SMDRowID(20/20 完全一致)

        備援仍保留 FindFirstSMD —— 但只在 SQL 不可用且使用者有給搜尋字串時有意義。
        """
        if self.project is None:
            raise RuntimeError("尚未開啟專案")

        try:
            smds = self._catalog().list_smds(
                project_title=self.state.open_project, search=search)
            self.state.log(f"[SQL] 列出 {len(smds)} 個 SMD")

            need = self._catalog().missing_reference_files(smds)
            if need:
                total = sum(len(x["smds"]) for x in need)
                self.state.log(
                    f"⚠️ 其中 {total} 個測項需要外部參考檔("
                    + ", ".join(x["ref_file"] for x in need[:4])
                    + (" …" if len(need) > 4 else "") + ")", "warn")
        except Exception as exc:                            # noqa: BLE001
            self.state.log(f"[SQL] 列舉失敗,改用 FindFirstSMD 備援:{exc}", "warn")
            smds = self._list_smds_via_find(search)

        self.state.set(smds=smds)
        return smds

    def _list_smds_via_find(self, search=""):
        """備援:Acqua3 的搜尋式走訪。

        ⚠️ 實測限制:
           - `FindFirstSMD("")` 回傳 **0 個** —— 空字串不等於「全部」
           - 只回傳 RowID,**不回傳標題**
           所以這條路做不出勾選清單,只能在「已知關鍵字」時當退路。
        """
        if not search:
            self.state.log("FindFirstSMD 備援需要搜尋字串(空字串會回傳 0 個)", "error")
            return []

        smds, seen = [], set()
        row_id = self.project.FindFirstSMD(search)
        guard = 0
        while int(row_id) != -1:
            rid = int(row_id)
            if rid in seen:
                break                                # 防禦:避免 API 循環回繞
            seen.add(rid)
            smds.append({"row_id": rid, "title": f"SMD #{rid}", "group": "",
                         "path": "", "smd_type": -1,
                         "needs_ref": False, "ref_file": "", "conditional": False})
            row_id = self.project.FindNextSMD()
            guard += 1
            if guard > 5000:
                self.state.log("SMD 列舉超過 5000 筆,強制中斷", "warn")
                break
        return smds

    def read_results(self, latest_only=True, smd_row_ids=None):
        """讀出量測的實際數值(含極限值)。走 SQL —— DBMask 連不上。"""
        rows = self._catalog().read_results(
            project_title=self.state.open_project,
            mo_title=self.state.measurement_object,
            latest_only=latest_only, smd_row_ids=smd_row_ids)
        self.state.set(values=rows)
        n = sum(len(r["values"]) for r in rows)
        self.state.log(f"[SQL] 讀到 {len(rows)} 筆結果、共 {n} 個數值")
        return rows

    def run_smds(self, row_ids):
        """逐一執行指定的 SMD。

        用 StartSingleMeasurement 而非 StartMeasurements —— 這樣才能只跑選中的測項,
        而且重試邏輯可以放在 Python 這一層,比用 EUserReaction.REDO_THIS 好控制。
        """
        if self.project is None or self.mo is None:
            raise RuntimeError("尚未開啟專案或選定量測物件")

        run_cfg = self.config.get("run", {})
        use_mmd = bool(run_cfg.get("use_mmd_settings", True))
        max_retries = int(run_cfg.get("max_retries", 0))
        stop_on_fail = bool(run_cfg.get("stop_on_first_failure", False))
        timeout = float(run_cfg.get("single_measurement_timeout_sec", 1800))
        result_comment = str(run_cfg.get("result_comment", ""))

        by_id = {s["row_id"]: s for s in self.state.smds}
        targets = [by_id.get(r, {"row_id": r, "title": f"SMD #{r}"}) for r in row_ids]
        total = len(targets)

        self.state.clear_results()
        self.state.set(running=True, cancel_requested=False)
        self.state.log(f"=== 開始:共 {total} 筆測項 ===")

        # 寫執行紀錄 —— 中途斷掉時才知道跑到哪
        rl = self.state.runlog
        if rl:
            rl.start(mode="selected", database=self.state.database,
                     project_group=self.state.open_group,
                     project=self.state.open_project,
                     measurement_object=self.state.measurement_object,
                     planned=[{"row_id": s["row_id"], "title": s["title"]}
                              for s in targets])

        try:
            i = 0
            while i < total:
                if self.state.cancel_requested:
                    self.state.log("使用者要求中止", "warn")
                    break

                smd = targets[i]
                attempt = 0
                while True:
                    self.state.set(current={"title": smd["title"], "index": i + 1, "total": total})
                    self.state.log(f"[{i + 1}/{total}] 量測中:{smd['title']}"
                                   + (f"(重試 {attempt})" if attempt else ""))

                    self._last_result = None
                    self._measuring_done = False
                    self._meas_started = False
                    # ⚠️ 簽章以 TypeLib 實測為準,比 CHM 多一個 ResultComment 參數:
                    #    StartSingleMeasurement(SMDRowID, UseMMDSettings,
                    #                           MeasurementObject, ResultComment)
                    self.project.StartSingleMeasurement(
                        smd["row_id"], use_mmd, self.mo.Title, result_comment)

                    # ⭐ 等待邏輯(2026-08-11 再修正)
                    #    1. IsMeasuring 約 1 秒後才翻成 True —— 不能一 start 就等它變 False
                    #    2. 完成訊號有**三種**,任一到達就算完成:
                    #         _last_result     ← OnFinishedSingleMeasurement
                    #         _measuring_done  ← OnFinishedMeasurements  ⚠️ 之前漏掉這個!
                    #         IsMeasuring 翻回 False
                    #       實測發現單筆量測**也會**觸發 OnFinishedMeasurements
                    #       (先前判斷它不會,是因為測試視窗只等了 90 秒)。
                    #       漏掉它會讓程式一路等到 timeout(預設 1800 秒)才往下走。
                    self._last_event_at = time.monotonic()
                    try:
                        self._wait_until(
                            lambda: self._meas_started or self.app.IsMeasuring,
                            timeout=60, what=f"量測啟動:{smd['title']}")
                    except TimeoutError:
                        self.state.log("    → 等不到量測啟動的訊號,可能 ACQUA 拒絕了這一項",
                                       "error")

                    self._wait_until_measured(smd["title"], timeout)

                    # 事件可能比 IsMeasuring 慢一點點,給它一小段時間補送
                    if self._last_result is None:
                        grace = time.monotonic() + 3.0
                        while self._last_result is None and time.monotonic() < grace:
                            self.pump()
                            time.sleep(0.05)

                    if self._last_result is None:
                        self.state.log("    → 沒有收到 OnFinishedSingleMeasurement 事件"
                                       "(訊息幫浦或事件接線有問題)", "error")
                        passed, status = False, -1
                    else:
                        title, status = self._last_result
                        smd["title"] = title or smd["title"]
                        passed = EMEResult.is_pass(status)

                    if not passed and attempt < max_retries:
                        attempt += 1
                        self.state.log(f"    → {EMEResult.describe(status)},"
                                       f"重試({attempt}/{max_retries})", "warn")
                        continue
                    break

                self.state.add_result(smd["title"], smd["row_id"],
                                      EMEResult.describe(status), passed, attempt)
                if rl:
                    rl.record(smd["row_id"], smd["title"],
                              EMEResult.describe(status), passed, attempt)
                self.state.log(f"    → {'PASS' if passed else 'FAIL'}"
                               f"({EMEResult.describe(status)})",
                               "info" if passed else "error")

                if not passed and stop_on_fail:
                    self.state.log("設定為失敗即停 —— 中止剩餘測項", "error")
                    break
                i += 1
        finally:
            self.state.set(running=False, current=None, progress=None)
            if rl:
                rl.finish(canceled=self.state.cancel_requested)
            snap = self.state.snapshot()["summary"]
            self.state.log(f"=== 結束:{snap['passed']} PASS / {snap['failed']} FAIL ===")

    def create_report(self, output_path, selection_type, result_index=0,
                      settle_timeout=600):
        """產生 Word 報告。

        ⚠️ `CreateReportForMO` 不可靠的原因(實測):
           - 它會開 Word,而且**呼叫可能在檔案寫完之前就返回**
           - Word 視窗會搶焦點,有時還會跳對話框卡住
           - 沒有回傳值,失敗與成功都一樣安靜

        改法:
           1. 先把報告產生器設成隱藏,避免 Word 搶焦點
           2. 呼叫前先確認真的有結果可以出報告
           3. 呼叫後**輪詢檔案**,等它出現且大小不再變動才算完成
        """
        import os

        if self.project is None or self.mo is None:
            raise RuntimeError("尚未開啟專案或選定量測物件")

        # 先確認有結果 —— 沒有結果時 ACQUA 常常安靜地產出空檔或什麼都不做
        try:
            res = self._catalog().read_results(
                project_title=self.state.open_project,
                mo_title=self.state.measurement_object, latest_only=True)
            if not res:
                raise RuntimeError(
                    f"量測物件「{self.state.measurement_object}」目前沒有任何結果,"
                    "產出的報告會是空的。請先跑過量測。")
            self.state.log(f"確認有 {len(res)} 筆結果可出報告")
        except RuntimeError:
            raise
        except Exception as exc:                            # noqa: BLE001
            self.state.log(f"結果檢查略過({exc})", "warn")

        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        if os.path.exists(output_path):
            try:
                os.unlink(output_path)      # 先刪掉舊的,才能靠「檔案出現」判斷完成
            except OSError as exc:
                raise RuntimeError(
                    f"舊報告檔刪不掉,可能正被 Word 開著:{output_path}") from exc

        # 把報告產生器藏起來,避免 Word 跳到最前面搶走鍵盤
        try:
            rg = self.app.ReportGenerator
            rg.Visible = False
            self.state.log("已將報告產生器設為隱藏")
        except Exception as exc:                            # noqa: BLE001
            self.state.log(f"無法設定報告產生器可見性({exc}),繼續", "warn")

        self.state.log(f"產生報告中…(selection_type={selection_type})")
        self.project.CreateReportForMO(self.mo.RowID, int(selection_type),
                                       output_path, int(result_index))

        # ⭐ 輪詢檔案:先等它出現,再等大小連續 3 次不變(代表寫完了)
        deadline = time.monotonic() + settle_timeout
        last_size, stable = -1, 0
        while time.monotonic() < deadline:
            self.pump()
            time.sleep(0.5)
            if not os.path.exists(output_path):
                continue
            size = os.path.getsize(output_path)
            if size > 0 and size == last_size:
                stable += 1
                if stable >= 3:
                    self.state.log(f"報告完成:{output_path}({size:,} bytes)")
                    return output_path
            else:
                stable = 0
            last_size = size

        if os.path.exists(output_path):
            self.state.log(f"⚠️ 報告檔已存在但大小仍在變動,可能還沒寫完:{output_path}",
                           "warn")
            return output_path
        raise TimeoutError(
            f"等了 {settle_timeout} 秒仍沒看到報告檔。"
            "請切到 ACQUA / Word 視窗看看有沒有跳出對話框。")

    # ── ⭐ 混合模式:變數驅動 ────────────────────────
    def _variables(self):
        """取得 ACQUA 的變數集合(IVariables)。

        路徑:IProjectSelected.MeasurementEngine.UsedVariables

        ✅ 已驗證(2026-08-10):Add() → 設 Name/Type/Value/State → Save() → 讀得回來。
        變數實際存放位置:
           UsedVariables   → %TEMP%/AcquaTmp/UsedVars.ini
           ResultVariables → %TEMP%/AcquaTmp/ResultVars.ini
        ⚠️ [未驗證] ConditionalExecution 到底讀哪一組 —— 需要有設條件的專案才能測。
        """
        if self.project is None:
            raise RuntimeError("尚未開啟專案")
        me = self.project.MeasurementEngine
        return me.UsedVariables

    def list_variables(self):
        out = []
        try:
            vs = self._variables()
            for i in range(vs.Count):
                v = vs.Item(i)
                st = int(getattr(v, "State", 0) or 0)
                out.append({
                    "name": str(v.Name),
                    "value": v.Value,
                    "type": int(getattr(v, "Type", 2) or 2),
                    "state": st,
                    "state_text": EVariableState.describe(st),
                    "comment": str(getattr(v, "Comment", "") or ""),
                })
        except Exception as exc:                            # noqa: BLE001
            self.state.log(f"讀取變數失敗:{exc}", "error")
        self.state.set(variables=out)
        return out

    def set_variables(self, values: dict):
        """寫入 ACQUA 變數。存在就更新,不存在就新增。

        ⚠️ [未驗證] IVariables 沒有 AddNamed(name) —— 只有 Add()。
           所以流程是「Add() 拿到新物件 → 設 .Name」。
           若 ACQUA 要求先 Save() 才生效,這裡已經有呼叫。
        """
        if not values:
            return 0

        vs = self._variables()
        existing = {}
        for i in range(vs.Count):
            try:
                existing[str(vs.Item(i).Name)] = vs.Item(i)
            except Exception:                               # noqa: BLE001
                continue

        n = 0
        for name, value in values.items():
            if name.startswith("_"):
                continue
            try:
                v = existing.get(name)
                if v is None:
                    v = vs.Add()
                    v.Name = name
                v.Type = EVariableType.infer(value)
                v.Value = value
                v.State = EVariableState.USER_DEFINED
                v.Comment = "set by automation"
                n += 1
                self.state.log(f"  變數 {name} = {value!r}")
            except Exception as exc:                        # noqa: BLE001
                self.state.log(f"  ✗ 設定變數 {name} 失敗:{exc}", "error")

        try:
            vs.Save()
        except Exception as exc:                            # noqa: BLE001
            self.state.log(f"變數 Save() 失敗:{exc}", "warn")

        self.state.log(f"已寫入 {n} 個變數")
        self.list_variables()
        return n

    def predict_run_set(self, variables=None):
        """預測這組變數會跑哪些測項 —— 純 SQL 計算,不碰 ACQUA。"""
        if variables is None:
            variables = {v["name"]: v["value"] for v in self.state.variables}
        r = self._catalog().predict_run_set(
            project_title=self.state.open_project, variables=variables)
        self.state.set(prediction={
            "will_run": len(r["will_run"]),
            "skipped": len(r["skipped"]),
            "uncertain": len(r["uncertain"]),
            "total": r["total_smds"],
            "run_ids": [x["row_id"] for x in r["will_run"]],
            "sample_skipped": r["skipped"][:40],
        })
        self.state.log(f"[預測] {len(r['will_run'])}/{r['total_smds']} 個測項會執行"
                       + (f",{len(r['uncertain'])} 個判定沒把握" if r["uncertain"] else ""))
        return r

    def run_all(self):
        """⭐ 混合模式:跑整個專案,由 ConditionalExecution 依變數自動篩選。

        跟 run_smds 的差別:
          run_smds —— 我們決定跑哪幾項(StartSingleMeasurement 逐項)
          run_all  —— ACQUA 決定跑哪幾項(StartMeasurements 一次,依變數條件)
        """
        if self.project is None or self.mo is None:
            raise RuntimeError("尚未開啟專案或選定量測物件")

        run_cfg = self.config.get("run", {})
        use_mmd = bool(run_cfg.get("use_mmd_settings", True))
        result_comment = str(run_cfg.get("result_comment", ""))
        timeout = float(run_cfg.get("full_run_timeout_sec", 28800))

        self.state.clear_results()
        self.state.set(running=True, cancel_requested=False)
        self.state.log("=== 開始:整個專案(由變數條件決定實際跑哪些)===")

        try:
            # ⚠️ 簽章以 TypeLib 為準,比 CHM 多一個 ResultComment
            self._measuring_done = False
            self._meas_started = False
            self.project.StartMeasurements(use_mmd, self.mo.Title, result_comment)

            # 同樣不要一 start 就等 IsMeasuring 變 False —— 先等它真的開始
            try:
                self._wait_until(lambda: self._meas_started or self.app.IsMeasuring,
                                 timeout=120, what="整批量測啟動")
            except TimeoutError:
                self.state.log("等不到量測啟動的訊號 —— 可能沒有任何測項符合條件", "warn")

            self._wait_until(
                lambda: self._measuring_done
                or (self._meas_started and not self.app.IsMeasuring),
                timeout=timeout, what="整批量測完成")
        finally:
            self.state.set(running=False, current=None, progress=None)
            snap = self.state.snapshot()["summary"]
            self.state.log(f"=== 結束:{snap['passed']} PASS / {snap['failed']} FAIL ===")

    def check_preconditions(self):
        """開跑前檢查(硬體、校正、參考檔等)。ACQUA 6 提供的方法,CHM 沒寫。"""
        try:
            r = self.project.MeasurementEngine.CheckPreconditions()
            self.state.log(f"CheckPreconditions → {r!r}")
            return r
        except Exception as exc:                            # noqa: BLE001
            self.state.log(f"CheckPreconditions 失敗:{exc}", "warn")
            return None

    def run_script(self, code: str, language: str = "Python"):
        """⭐ 直接在 ACQUA 內部執行腳本(層級 3 的入口)。

        來源:IMeasurementEngine.RunScript(Language, Code)
        這是 COM 與 ACQUA 內建 Python 之間的橋 —— 可以從外部呼叫
        HSL.save_var() 之類只有內部才拿得到的 API。

        ⚠️ [未驗證] 回傳值格式與錯誤處理方式未知。
        """
        me = self.project.MeasurementEngine
        if not me.PythonAvailable:
            raise RuntimeError("這套 ACQUA 沒有啟用 Python 腳本引擎")
        result = me.RunScript(language, code)
        self.state.log(f"RunScript 回傳:{result!r}")
        return result
