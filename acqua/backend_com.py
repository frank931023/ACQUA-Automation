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
        # ACQUA 已經算完這批要跑幾筆(依 ConditionalExecution 篩過)。
        # 這是唯一能拿到總數的地方。
        self.backend._batch_total = int(NbrOfMeasurements or 0)
        self.backend._batch_index = 0
        self._st().log(f"ACQUA 回報:即將進行 {NbrOfMeasurements} 筆量測")

    def OnBeginSingleMeasurement(self, SMDTitle, Progress, NbrOfMeasurements):
        # ⚠️ Progress 參數實測永遠回 1,不能用 —— 自己數。
        self._tick()
        b = self.backend
        b._meas_started = True

        # 逐項模式的進度由 run_smds 的迴圈自己維護 —— 這裡不能插手。
        # 實測:ACQUA 對單筆量測也會發 OnBeginSingleMeasurement(而且
        # NbrOfMeasurements 回 1),照著加會把 20 筆的進度打成 1/1。
        if b._per_item:
            return

        b._batch_index += 1
        if not b._batch_total:
            b._batch_total = int(NbrOfMeasurements or 0)
        self._st().set(current={"title": str(SMDTitle),
                                "index": b._batch_index,
                                "total": b._batch_total})
        self._st().log(f"[{b._batch_index}/{b._batch_total}] {SMDTitle}")

    # ── 決策點:ByRef 輸出用「回傳值」給回 ACQUA ────────
    def OnFinishedSingleMeasurement(self, SMDTitle, ResultStatus,
                                    Progress, NbrOfMeasurements, UserReaction):
        # ⚠️ 這裡**不能**用回傳值控制流程。
        #
        # 實測(2026-08-20,MS Teams SP2 Speakerphone / 1151 筆):
        #     回 REDO_THIS(2)  → 沒有任何一筆重跑
        #     回 CANCEL_ALL(3) → 照樣跑下一筆
        # pywin32 的 ByRef 回傳沒有送達 ACQUA。
        #
        # 舊註解宣稱「已驗證 DO_NEXT 生效」是假陽性 —— DO_NEXT 就是預設行為,
        # 回不回傳結果一樣,那個測試分辨不出任何事。
        #
        # 流程控制改由 acqua/winwatch.py 負責(關不關阻塞視窗)。
        self._tick()
        self.backend._on_single_finished(SMDTitle, ResultStatus)

    def OnFinishedMeasurements(self, SelectedProject, MeasurementObject,
                               NbrOfMeasurements, NbrOfMeasurementsFinished,
                               Canceled, ResultOverview):
        self._tick()
        self.backend._measuring_done = True
        self.backend._batch_canceled = bool(Canceled)
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
        # ACQUA 詢問使用者決策。回傳值同樣走 ByRef,
        # 依 2026-08-20 的實測**很可能也沒送達** —— 所以只當成情報記錄,
        # 真正會擋住流程的是視窗,由 winwatch 處理。
        self._tick()
        self._st().log(f"[CALLBACK] {EventDescription}", "warn")
        return True


class ComBackend(AcquaBackend):
    def __init__(self, state, config):
        super().__init__(state, config)
        self.app = None
        # 整批進度:Progress 參數不可信(永遠回 1),自己數
        self._batch_total = 0
        self._batch_index = 0
        self._batch_canceled = False
        self._per_item = False
        self._watcher = None
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
        # 先把視窗監看器收掉 —— 不然它會繼續關 ACQUA 的對話框
        w = getattr(self, "_watcher", None)
        if w:
            try:
                w.stop()
            except Exception:                               # noqa: BLE001
                pass
            self._watcher = None
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

    def _record(self, smd, status_name, passed, code):
        """記一筆「我們自己判定」的結果 —— state 與 runlog 都要寫。

        以前這幾處只寫 state,所以 runs/current.json 漏掉 NoResult / Busy /
        Exception(2026-08-21 實測:219 筆結果只對上 191 筆紀錄)。
        """
        rid, title = smd["row_id"], smd["title"]
        path = smd.get("path", "")
        self.state.add_result(title, rid, status_name, passed,
                              code=code, path=path)
        rl = self.state.runlog
        if rl:
            try:
                rl.record(rid, title, status_name, passed, code=code, path=path)
            except Exception:                               # noqa: BLE001
                pass

    def _path_of(self, row_id):
        """這個測項在專案樹裡的位置。給結果報表鑽進去看是哪幾筆用的。"""
        for s in (self.state.smds or []):
            if s.get("row_id") == row_id:
                return s.get("path") or s.get("group") or ""
        return ""

    def _on_single_finished(self, title, status):
        """記下一筆結果。

        ⚠️ 整批模式下**只有這裡**會寫結果 —— 舊版是 run_smds 的 Python 迴圈
           在每一輪自己呼叫 add_result,那個迴圈已經沒有了。
           漏掉的話 summary 會一直是 0(2026-08-20 真機實測踩到過)。
        """
        title, status = str(title), int(status)
        self._last_result = (title, status)
        passed = EMEResult.is_pass(status)
        desc = EMEResult.describe(status)

        rid = getattr(self, "_current_row_id", None) or self._batch_index
        self.state.add_result(title, rid, desc, passed,
                              code=status, path=self._path_of(rid))
        rl = self.state.runlog
        if rl:
            try:
                rl.record(rid, title, desc, passed,
                          code=status, path=self._path_of(rid))
            except Exception:                               # noqa: BLE001
                pass
        self.state.log(f"    → {'PASS' if passed else 'FAIL'}({desc})",
                       "info" if passed else "error")

    # ── 操作 ────────────────────────────────────────
    def connect(self, server, database, win_auth, username="", password=""):
        prev = self.state.database
        ok = bool(self.app.SelectDatabase(server, database, win_auth, username, password))
        if ok:
            self.state.set(connected=True,
                           server=str(self.app.SelectedSQLServerName),
                           database=str(self.app.SelectedDatabaseName))
            # SelectDatabase 一定會讓舊庫的專案物件失效,所以無條件作廢 ——
            # 不去判斷「有沒有換」,因為那個判斷本身就是先前 bug 的來源。
            self._reset_context(
                "database",
                ("資料庫由 %s 換成 %s" % (prev, self.state.database)) if prev
                else ("連線至 %s" % self.state.database))
            self._update_context()
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

    def _find_project(self, group, project):
        """在 ProjectGroups 裡找這個專案的 IProject。

        ⚠️ ProjectGroups 是活的 COM 集合 —— 連續開好幾個專案之後,
           用索引走訪會偶發抓不到(2026-08-24 全專案掃描時 Speakerphone
           就這樣消失過)。所以找不到時重讀一次再找。

        ⚠️ 標題比對要去頭尾空白 —— 實測群組標題有
           'MS Teams v5 Rev05 SP2 - Handset '(尾巴帶空格)這種。
        """
        want_g, want_p = str(group or "").strip(), str(project or "").strip()
        for attempt in (1, 2):
            pgs = self.app.ProjectGroups
            for i in range(pgs.Count):
                pg = pgs.Item(i)
                if str(pg.Title).strip() != want_g:
                    continue
                projects = pg.Projects
                for j in range(projects.Count):
                    pj = projects.Item(j)
                    if str(pj.Title).strip() == want_p:
                        return pj
            if attempt == 1:
                self.state.log("[專案] 第一次沒找到,重讀 ProjectGroups 再試", "warn")
                self.pump()
        return None

    def open_project(self, group, project):
        target = self._find_project(group, project)
        if target is None:
            raise RuntimeError(
                f"找不到專案:{group} / {project} —— "
                "請按「重新讀取」更新專案清單")

        # 開新專案前先作廢舊專案的一切(含 COM 的 MO 物件)
        self._reset_context("project", "切換專案至 %s" % project)
        try:
            target.SelectAsActive()                 # 這裡拿到的是 IProject,只能做這件事
        except Exception as exc:                    # noqa: BLE001
            msg = str(exc)
            if "cannot be modified" in msg or "is a standard" in msg:
                raise RuntimeError(
                    f"「{project}」是 Standards 群組裡的標準範本,ACQUA 不允許直接執行。"
                    "請在 ACQUA 裡把它複製成一個實際專案,再回來選那一個。") from exc
            raise

        # ⚠️ SelectAsActive 是非同步的。SelectedProjectLoaded 在「上一個專案
        #    還開著」時就已經是 True —— 只等它會讀到舊專案,而且完全不報錯。
        #    2026-08-24 實測:要求 Headset 拿到 Handset,API 還回 ok=True。
        #    所以要等到標題真的變成我們要的那一個。
        want = str(project or "").strip()

        def arrived():
            if not self.app.SelectedProjectLoaded:
                return False
            try:
                return str(self.app.SelectedProject.Title).strip() == want
            except Exception:                       # noqa: BLE001
                return False

        try:
            self._wait_until(arrived, timeout=300, what=f"專案切換到 {want}")
        except Exception:                           # noqa: BLE001
            got = ""
            try:
                got = str(self.app.SelectedProject.Title).strip()
            except Exception:                       # noqa: BLE001
                pass
            raise RuntimeError(
                f"ACQUA 沒有切到「{project}」"
                + (f",目前仍是「{got}」" if got else "")
                + " —— 請到 ACQUA 視窗看看有沒有對話框在等人")

        self.project = self.app.SelectedProject     # ⭐ 現在才是 IProjectSelected
        self.state.set(open_group=group, open_project=str(self.project.Title))
        self._update_context()
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
                # 訊息要講「怎麼辦」而不是內部設定名 —— 而且 ACQUA 的
                # AddMeasurementObject 實測建不起來(見下方),所以唯一的
                # 出路就是去 ACQUA 裡建。
                raise RuntimeError(
                    f"這個專案裡沒有量測物件「{title}」。"
                    + (f"現有的是:{'、'.join(titles)}。" if titles else "")
                    + "請先在 ACQUA 裡建立它,再回來選。")
            if mos is None:
                mos = self.project.MeasurementObjects   # 讓它再丟一次,錯誤才看得到
            # ⚠️ TypeLib 說它回傳「新物件的索引」,-1 = 失敗。
            #    實測 2026-08-24:兩個資料庫、三種參數組合一律回 -1,
            #    而且資料庫裡完全沒有新資料。以前沒檢查回傳值,還印了
            #    「已新增量測物件」—— 那行 log 是假的,後面才在
            #    SelectActiveMeasurementObject 回 None 時才炸,很難查。
            idx = mos.AddMeasurementObject(title, "由自動化建立")
            if idx is None or int(idx) < 0:
                raise RuntimeError(
                    f"ACQUA 不接受新增量測物件「{title}」"
                    f"(AddMeasurementObject 回傳 {idx})。"
                    "請先在 ACQUA 裡建立這個量測物件,再回來選它。")
            self.state.log(f"已新增量測物件:{title}(索引 {idx})")

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

    def wizard_options(self):
        """從專案樹的條件式反推「精靈」該有哪些選項。

        ACQUA 的 DUT & Measurement Wizard 是 Tcl/Tk 的,內容讀不到 ——
        但它的選項最後都會變成變數,而每個變數的可能值都寫在
        ConditionalExecution 裡。掃一遍就能自己生出等效的精靈。
        """
        from .wizard import scan_variables, group_variables
        rows = self._catalog()._load_tree(
            project_title=self.state.open_project, project_id=self._project_id())
        for r in rows:
            r["ConditionalExecution"] = (str(r["ConditionalExecution"])
                                         if r.get("ConditionalExecution") else "")
        items = scan_variables(rows)
        groups = group_variables(items)
        self.state.set(wizard_groups=groups,
                       wizard_scopes=self.config.get("wizard_scopes") or {})
        self.state.log(f"[精靈] 從條件式反推出 {len(items)} 個變數,分成 {len(groups)} 組")
        return groups

    def _manual_matcher(self):
        """回傳一個判斷式:這個標題是不是「需要人工操作」的測項。

        這類項目跑到就會開視窗等人(例如 DUT & Measurement Wizard),
        自動勾選時要排除掉,否則整批就沒辦法無人值守。
        """
        import fnmatch
        m = self.config.get("manual_items") or {}
        titles = {str(x).strip() for x in (m.get("titles") or [])}
        pats = [str(x) for x in (m.get("title_patterns") or [])]

        def is_manual(title):
            t = (title or "").strip()
            if t in titles:
                return True
            return any(fnmatch.fnmatch(t, p) for p in pats)
        return is_manual

    def _project_id(self):
        """目前作用中專案的 idProject。

        資料庫裡有同名專案(標準範本 vs 實際專案),只能靠 ID 分辨。
        COM 的 IProjectSelected.RowID 就是權威答案。
        """
        try:
            return int(self.project.RowID)
        except Exception:                                   # noqa: BLE001
            return None

    def _reset_context(self, scope, reason):
        """上下文變了 —— 把繫於舊上下文的所有東西一次作廢。

        這是唯一該做這件事的地方。以前是各個函式各自記得清誰,結果每加一個
        狀態欄位就多一個漏網的機會(2026-08-21 就是這樣載到舊庫的測項)。
        名單在 acqua/context.py,那裡有檢查程式看守。

        scope: "database" 換資料庫 / "project" 換專案
        """
        from . import context as _ctx
        fields = (_ctx.DATABASE_SCOPED if scope == "database"
                  else _ctx.PROJECT_SCOPED)
        if scope == "database":
            self.project = None      # 舊庫的 COM 專案物件已無意義
            self.sql = None          # SQL 目錄綁在舊庫,絕不能留
        self.mo = None
        self.state.set(ctx=None, **_ctx.clear_values(fields))
        self.state.log("[上下文] %s —— 已作廢 %d 項衍生資料"
                       % (reason, len(fields)), "warn")

    def _update_context(self):
        """重算並公布目前的上下文 key。"""
        from . import context as _ctx
        key = _ctx.context_key(self.state.server, self.state.database,
                               self._project_id())
        self.state.set(ctx=key)
        return key

    def resolve_items(self, items):
        """把計畫裡存的測項對應到「目前這個專案」的 row_id。

        計畫可能是在別的資料庫建立的。row_id 跨庫必然重疊、而且指到完全
        不同的測項(見 acqua/context.py),所以絕不能直接拿來用 ——
        這裡改用「路徑 + 標題」重新對應。

        對不上的明白列出來,不猜、不自動略過:少跑一項比跑錯一項難發現。
        """
        smds = self.state.smds or []
        if not smds:
            raise RuntimeError("目前沒有載入任何測項,無法對應計畫內容")

        by_key, by_title = {}, {}
        for s in smds:
            title = str(s.get("title") or "").strip()
            path = str(s.get("path") or "").strip()
            by_key.setdefault((path, title), s)
            by_title.setdefault(title, []).append(s)

        resolved, missing, ambiguous = [], [], []
        for it in (items or []):
            title = str(it.get("title") or "").strip()
            path = str(it.get("path") or "").strip()
            hit, how = by_key.get((path, title)), "路徑+名稱"
            if hit is None:
                cands = by_title.get(title) or []
                if len(cands) == 1:
                    hit, how = cands[0], "名稱"
                elif len(cands) > 1:
                    # 同名多筆又沒有路徑可分辨 —— 猜錯就是跑錯測項
                    ambiguous.append({"title": title, "path": path,
                                      "count": len(cands)})
                    continue
            if hit is None:
                missing.append({"title": title, "path": path,
                                "row_id": it.get("row_id")})
                continue
            resolved.append({"row_id": int(hit["row_id"]),
                             "title": hit.get("title", ""),
                             "path": hit.get("path", ""),
                             "matched_by": how})

        self.state.log(
            "[計畫] 對應 %d 項:成功 %d ・ 找不到 %d ・ 同名無法分辨 %d"
            % (len(items or []), len(resolved), len(missing), len(ambiguous)),
            "info" if not (missing or ambiguous) else "warn")
        return {"resolved": resolved, "missing": missing,
                "ambiguous": ambiguous, "ctx": self.state.ctx}

    def check_rows(self, row_ids):
        """公開版的歸屬驗證,給 /api/run 在送出前同步呼叫。

        run_smds 裡面也有一份 —— 這不是重複,是兩個不同的目的:
        這裡是為了「早點把錯誤回給使用者」,那裡是「不管誰呼叫都擋得住」。
        """
        self._assert_rows_in_project(row_ids)
        return True

    def _assert_rows_in_project(self, row_ids):
        """最後一道閘:這批 row_id 真的屬於目前這個專案嗎?

        跨資料庫的 idTreeItem 必然重疊 —— 送錯不會報錯,只會安靜地跑到
        別的測項。就算前面每一層作廢都漏了,這裡會擋下來。
        """
        from .sqlcat import _SCHEMA
        want = [int(r) for r in row_ids]
        if not want:
            raise RuntimeError("沒有指定要跑的測項")
        pid = self._project_id()
        if pid is None:
            raise RuntimeError("讀不到目前專案的 idProject,無法驗證測項歸屬")
        rows = self._catalog().query(
            "SELECT idTreeItem FROM %s.TreeItems WHERE rProject = %d "
            "AND idTreeItem IN (%s)"
            % (_SCHEMA, int(pid), ",".join(str(x) for x in want)))
        have = {int(r["idTreeItem"]) for r in rows}
        bad = [x for x in want if x not in have]
        if bad:
            raise RuntimeError(
                "有 %d 筆測項不屬於目前的專案「%s」(%s)。前幾筆:%s。"
                "請重新載入測項後再跑。"
                % (len(bad), self.state.open_project, self.state.database,
                   ", ".join(str(x) for x in bad[:5])))

    def _catalog(self):
        """取得 SQL 目錄(延遲連線,且會跟著目前的資料庫走)。

        ⚠️ 2026-08-21 實機抓到的坑:原本只判斷 `self.sql is None`,
           所以使用者在網頁上換了資料庫之後,目錄還連在舊的那一顆。
           症狀是「載入測項」看起來有成功、也真的回了 309 筆 ——
           但那 309 筆是舊庫 51_MS_Teams_Rev05_SP2 的 idProject=1
           (MS Teams Handset),而 ACQUA 當下開的是
           ACQUA_auto_v2026Aug 的 ZoomRooms(1477 筆)。

           兩個庫的 idTreeItem 各自從小編號開始、必然重疊,
           所以這些 row_id 送進 StartSingleMeasurement 不會報錯,
           只會安靜地跑到別的測項 —— 比直接失敗還糟。
        """
        from .sqlcat import SqlCatalog
        srv, db = self.state.server, self.state.database
        if self.sql is not None and (self.sql.server, self.sql.database) != (srv, db):
            self.state.log(f"[SQL] 資料庫已換成 {db},目錄重新連線", "warn")
            self.sql = None
        if self.sql is None:
            cat = SqlCatalog(self.state)
            if not cat.connect(srv, db):
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
                project_title=self.state.open_project, search=search,
                project_id=self._project_id())
            is_manual = self._manual_matcher()
            for s in smds:
                s["manual"] = is_manual(s.get("title"))
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
            project_title=self.state.open_project, variables=variables,
            project_id=self._project_id())
        # ⭐ 前端要拿 row_id 去勾選,不只是數量。
        #    需要人工操作的項目一律排除 —— 它們會開視窗等人,
        #    留著就沒辦法「開跑後不用管」。
        is_manual = self._manual_matcher()
        run_ids, manual_hits = [], []
        for x in r["will_run"]:
            if is_manual(x.get("title")):
                manual_hits.append({"row_id": x["row_id"], "title": x["title"]})
            else:
                run_ids.append(x["row_id"])
        self.state.set(prediction={
            "will_run": len(run_ids),
            "run_ids": run_ids,
            "manual_excluded": manual_hits,
            "skipped": len(r["skipped"]),
            "uncertain": len(r["uncertain"]),
            "uncertain_items": [{"row_id": x["row_id"], "title": x["title"]}
                                for x in r["uncertain"]][:50],
            "total": r["total_smds"],
            "sample_skipped": r["skipped"][:40],
        })
        self.state.log(
            f"[預測] {len(run_ids)}/{r['total_smds']} 個測項會執行"
            + (f",排除 {len(manual_hits)} 個需人工操作的" if manual_hits else "")
            + (f",{len(r['uncertain'])} 個判定沒把握" if r["uncertain"] else ""))
        return r

    def _wait_item(self, title, timeout):
        """等單筆量測真的結束。回傳 True = 有拿到結果事件。

        ACQUA 對單筆量測的事件行為(2026-08-21 實測整理)
        ────────────────────────────────────────────────
            OnFinishedSingleMeasurement   有時發,有時不發
            OnFinishedMeasurements        **單筆也會發**,訊息像「完成 1/1」
                                          —— 這是最可靠的完成訊號
            OnBeginSingleMeasurement      有時完全不發(所以不能依賴 _meas_started)
            IsMeasuring                   會先翻回 False,但 ACQUA 內部還沒收尾完

        踩過的兩個坑
        ────────────
        ・依賴 _meas_started → 那筆沒發 Begin 事件時**永遠等不到**,卡死。
        ・只看 IsMeasuring + 短寬限 → 太早返回,下一筆送出時被丟
          "Acqua is busy.",而且一旦搶快就會一路忙到底
          (20 筆有 18 筆 Busy,耗時從 80 秒變成 246 秒)。

        所以:事件優先,IsMeasuring 只當「事件都沒來」時的保險絲,
        而且要求**連續**多次確認閒置,不是看一次就算。
        """
        SETTLE = 1.0        # 剛送出,先給 ACQUA 一點時間動起來
        IDLE_NEED = 5.0     # 事件沒來時,IsMeasuring 要連續閒置這麼久才敢算結束

        t0 = time.monotonic()
        deadline = t0 + timeout
        idle_since = None

        while True:
            # ① 最可靠:這一筆的結果事件
            if self._last_result is not None:
                break
            # ② 次可靠:ACQUA 自己說這批(單筆也算一批)結束了
            if self._measuring_done:
                break

            # ③ 保險絲:兩個事件都沒來,靠 IsMeasuring 連續閒置判斷
            busy = None
            try:
                busy = self.app.IsMeasuring
            except Exception:                                # noqa: BLE001
                pass                                         # COM 忙,下一圈再問

            if busy is False and time.monotonic() - t0 > SETTLE:
                if idle_since is None:
                    idle_since = time.monotonic()
                elif time.monotonic() - idle_since > IDLE_NEED:
                    break
            elif busy:
                idle_since = None

            self.pump()
            time.sleep(0.05)
            if time.monotonic() > deadline:
                self.state.log(f"    ✗ 等待 {timeout:.0f} 秒逾時:{title}", "error")
                return False

        # 收尾:確定 ACQUA 真的閒了才讓呼叫端送下一筆。
        # 事件到了不代表它內部處理完 —— 這一步就是在防 "Acqua is busy."。
        self._settle()
        return self._last_result is not None

    def _settle(self, need=1.2, limit=30.0):
        """等 ACQUA 真的閒下來(IsMeasuring 連續 need 秒為 False)。"""
        t0 = time.monotonic()
        idle_since = None
        while time.monotonic() - t0 < limit:
            try:
                busy = self.app.IsMeasuring
            except Exception:                                # noqa: BLE001
                busy = True                                  # 問不到就當它還在忙
            if busy:
                idle_since = None
            else:
                if idle_since is None:
                    idle_since = time.monotonic()
                elif time.monotonic() - idle_since >= need:
                    return True
            self.pump()
            time.sleep(0.05)
        return False

    def run_smds(self, row_ids, comment=None):
        """⭐ 逐項執行勾選的測項。

        跟 run_measurements 的差別:
            run_smds          你勾什麼跑什麼,順序由你決定,**可以真的中止**
            run_measurements  ACQUA 依 ConditionalExecution 決定跑哪些

        中止之所以在這裡有效:排隊的是 Python 的 for 迴圈,
        不送下一筆就停了 —— 不需要 ACQUA 配合。
        """
        if self.project is None or self.mo is None:
            raise RuntimeError("尚未開啟專案或選定量測物件")

        # ⭐ 最後一道閘 —— 理由見 acqua/context.py。
        #    寧可在這裡明白擋下,也不要讓它安靜地跑到別的專案的測項。
        self._assert_rows_in_project(row_ids)

        run_cfg = self.config.get("run", {})
        use_mmd = bool(run_cfg.get("use_mmd_settings", True))
        # 這一批的名字。傳進 StartSingleMeasurement 的 ResultComment,
        # ACQUA 會存成每筆結果的 Description —— 也就是你們在 ACQUA 裡看到的
        # run 名稱(實測:同一批的每一筆都拿到同一個字串)。
        result_comment = (str(comment).strip() if comment
                          else str(run_cfg.get("result_comment", "")))
        timeout = float(run_cfg.get("item_timeout_sec", 900))

        by_id = {s["row_id"]: s for s in self.state.smds}
        targets = [by_id.get(r, {"row_id": r, "title": f"SMD #{r}"}) for r in row_ids]
        total = len(targets)

        watcher = self._start_watcher()
        self._per_item = True
        self._batch_total = total
        self._batch_index = 0

        self.state.clear_results()
        self.state.set(running=True, cancel_requested=False, paused=False, current=None)
        hw = self.active_hardware_setting()
        self.state.log(f"=== 開始逐項執行:共 {total} 筆 ===")
        self.state.log(f"    這批的名稱:{result_comment or '(未命名)'}")
        self.state.log(f"    硬體設定:{hw or '(讀不到)'}")

        rl = self.state.runlog
        if rl:
            rl.start(mode="selected", comment=result_comment,
                     database=self.state.database,
                     project_group=self.state.open_group,
                     project=self.state.open_project,
                     measurement_object=self.state.measurement_object,
                     planned=[{"row_id": s["row_id"], "title": s["title"]}
                              for s in targets])

        stopped = False
        try:
            for i, smd in enumerate(targets):
                # ── 真正的中止:不送下一筆就結束了 ──
                if self.state.cancel_requested:
                    self.state.log(f"■ 已中止 —— 跑了 {i} / {total} 筆", "warn")
                    stopped = True
                    break

                # ── 暫停:停在兩筆之間,不影響已送出的那筆 ──
                while self.state.paused and not self.state.cancel_requested:
                    self.pump()
                    time.sleep(0.1)
                if self.state.cancel_requested:
                    self.state.log(f"■ 已中止 —— 跑了 {i} / {total} 筆", "warn")
                    stopped = True
                    break

                self._batch_index = i + 1
                self._last_result = None
                self._measuring_done = False
                self._meas_started = False
                self.state.set(current={"title": smd["title"],
                                        "index": i + 1, "total": total})
                self.state.log(f"[{i + 1}/{total}] {smd['title']}")

                self._current_row_id = smd["row_id"]

                # ⚠️ 單筆出錯**不能**拖垮整批。
                #    實測(2026-08-21):第 11 筆送出時 ACQUA 丟 "Acqua is busy.",
                #    例外一路往上炸,剩下的測項全部沒跑(送 12 只跑了 10)。
                try:
                    # ── 送出。ACQUA 可能還在收尾,忙就等一下重送 ──
                    # 送出前先確認 ACQUA 閒著 —— 被拒絕再重試代價高很多
                    self._settle()
                    sent = False
                    for attempt in range(6):
                        try:
                            # 簽章以 TypeLib 為準,比 CHM 多一個 ResultComment
                            self.project.StartSingleMeasurement(
                                smd["row_id"], use_mmd, self.mo.Title, result_comment)
                            sent = True
                            break
                        except Exception as exc:            # noqa: BLE001
                            if "busy" not in str(exc).lower():
                                raise
                            self.state.log(
                                f"    ACQUA 還在忙,等它閒下來再重送({attempt + 1}/6)",
                                "warn")
                            self._settle(need=1.5, limit=20.0)

                    if not sent:
                        self.state.log("    ✗ ACQUA 持續忙碌,跳過這一筆", "error")
                        self._record(smd, "Busy", False, EMEResult.BUSY)
                        continue

                    self._wait_item(smd["title"], timeout)

                    if self._last_result is None:
                        # ACQUA 對某些測項(例如純文件的 Info)不發結果事件。
                        # 這不代表失敗 —— 標成 NoResult 讓它跟真正的 FAIL 分開。
                        # ⚠️ 這裡以前記成 passed=True —— 那是過度樂觀。
                        #    「沒收到結果」不等於「通過」,它是「不知道」。
                        #    算成通過會讓總結數字虛高(2026-08-21 那批 28 筆)。
                        self.state.log(
                            "    → ACQUA 沒有回報結果(這類測項通常不產生資料)", "warn")
                        self._record(smd, "NoResult", False, EMEResult.NO_RESULT)
                except Exception as exc:                    # noqa: BLE001
                    self.state.log(
                        f"    ✗ 這一筆出錯:{self._explain_com_error(exc)}", "error")
                    self._record(smd, "Exception", False, EMEResult.EXCEPTION)
        finally:
            if watcher:
                watcher.stop()
            self.state.set(running=False, current=None, progress=None, paused=False)
            self._per_item = False
            if rl:
                rl.finish(canceled=stopped)
            snap = self.state.snapshot()["summary"]
            self.state.log(f"=== 結束:{snap['passed']} PASS / {snap['failed']} FAIL ===")

    def run_measurements(self, variables=None):
        """⭐ 唯一的執行入口:整批跑,由 ACQUA 依 ConditionalExecution 決定範圍。

        執行模型(2026-08-20 實測後定案)
        ────────────────────────────────
            ACQUA 排隊     StartMeasurements 一次送出,它自己決定跑哪些、什麼順序
            事件只讀       OnBegin/OnFinished 用來更新進度,**不能**用回傳值下指令
            winwatch 控流  關不關阻塞視窗 = 走或停

        為什麼不用回傳值:見 _Events.OnFinishedSingleMeasurement 的註解。
        """
        if self.project is None or self.mo is None:
            raise RuntimeError("尚未開啟專案或選定量測物件")

        run_cfg = self.config.get("run", {})
        use_mmd = bool(run_cfg.get("use_mmd_settings", True))
        result_comment = str(run_cfg.get("result_comment", ""))
        timeout = float(run_cfg.get("full_run_timeout_sec", 28800))

        watcher = self._start_watcher()
        self._per_item = False

        self._batch_total = 0
        self._batch_index = 0
        self._batch_canceled = False
        self._current_row_id = None
        self._measuring_done = False
        self._meas_started = False
        self._last_result = None
        self._last_event_at = time.monotonic()

        self.state.clear_results()
        self.state.set(running=True, cancel_requested=False, current=None)

        hw = self.active_hardware_setting()
        self.state.log("=== 開始整批量測 ===")
        self.state.log(f"    專案:{self.state.open_project} / 量測物件:{self.mo.Title}")
        self.state.log(f"    硬體設定:{hw or '(讀不到)'}")

        rl = self.state.runlog
        if rl:
            rl.start(mode="batch", database=self.state.database,
                     project_group=self.state.open_group,
                     project=self.state.open_project,
                     measurement_object=self.state.measurement_object,
                     planned=[])          # 事前不知道清單,ACQUA 才知道

        try:
            # ⚠️ 簽章以 TypeLib 為準,比 CHM 多一個 ResultComment
            self.project.StartMeasurements(use_mmd, self.mo.Title, result_comment)

            deadline = time.monotonic() + timeout
            while True:
                self.pump()
                time.sleep(0.05)

                if self._measuring_done:
                    break

                # ACQUA 結束但沒發事件(例如整批被 GUI 取消)
                if self._meas_started:
                    try:
                        if not self.app.IsMeasuring:
                            break
                    except Exception:                       # noqa: BLE001
                        pass

                # 暫停/恢復都是靠 winwatch 的開關 ——
                # 它停了,ACQUA 的對話框就沒人關,量測自然停在那裡。
                if watcher:
                    want_running = not self.state.cancel_requested
                    is_running = bool(watcher._thread)
                    if is_running and not want_running:
                        watcher.stop()
                        self.state.log(
                            "⏸ 已暫停 —— 停止自動關閉 ACQUA 的對話框,"
                            "量測會停在下一個視窗。按「繼續」可以接回去。", "warn")
                    elif want_running and not is_running:
                        watcher.start()
                        self.state.log("▶ 已繼續 —— 重新開始處理 ACQUA 的對話框")

                if time.monotonic() > deadline:
                    self.state.log(f"整批量測超過 {timeout:.0f} 秒上限,停止等待", "error")
                    break
        finally:
            if watcher:
                watcher.stop()
            self.state.set(running=False, current=None, progress=None)
            if rl:
                rl.finish(canceled=bool(self._batch_canceled
                                        or self.state.cancel_requested))
            snap = self.state.snapshot()["summary"]
            self.state.log(
                f"=== 結束:{snap['passed']} PASS / {snap['failed']} FAIL"
                f"(ACQUA 回報總數 {self._batch_total})===")


    def _start_watcher(self):
        """啟動視窗監看器 —— 這是唯一的流程控制手段,見 acqua/winwatch.py。"""
        try:
            from .winwatch import WindowWatcher, DEFAULT_RULES
        except Exception as exc:                            # noqa: BLE001
            self.state.log(f"視窗監看器載入失敗:{exc}", "warn")
            return None

        rules = self.config.get("blocking_windows") or DEFAULT_RULES

        def on_blocked(info):
            btns = info.get("buttons") or []
            self.state.set(blocking_window={
                "hwnd": info["hwnd"], "cls": info["cls"],
                "title": info["title"], "buttons": btns,
                "message": info.get("message", ""),
            })
            self.state.log(
                f"⏸ ACQUA 開了視窗在等人:[{info['cls']}] {info['title']}"
                + (f" ・按鈕:{' / '.join(btns)}" if btns else ""), "warn")

        w = WindowWatcher(rules=rules, log=self.state.log, on_blocked=on_blocked)
        self._watcher = w
        return w.start()

    def answer_blocking_window(self, hwnd, action):
        """UI 回覆某個擋住流程的視窗要怎麼處理。

        ⚠️ 這個方法會被 **Flask 的請求執行緒**直接呼叫(不走命令佇列),
           因為 run_measurements 正阻塞著工作執行緒。所以這裡
           **只能碰 Win32 與有鎖的資料結構,絕對不能碰 COM 物件**。
        """
        w = getattr(self, "_watcher", None)
        if not w:
            self.state.log("沒有正在運作的視窗監看器,無法回覆", "warn")
            return False
        ok = w.answer(int(hwnd), action)
        self.state.set(blocking_window=None)
        return ok

    def active_hardware_setting(self):
        """目前選用的硬體設定名稱。跑之前記進 log,事後才查得到用了什麼。"""
        try:
            return str(self.project.MeasurementEngine.HardwareConfig
                       .Settings.ActiveSetting)
        except Exception:                                   # noqa: BLE001
            return None

    def list_hardware_settings(self):
        """列出所有硬體設定,標出目前選用的那組。"""
        try:
            S = self.project.MeasurementEngine.HardwareConfig.Settings
            active = str(S.ActiveSetting)
            out = []
            for i in range(S.Count):
                try:
                    nm = str(S.Names(i))
                except Exception:                           # noqa: BLE001
                    continue
                item = {"name": nm, "active": nm == active}
                try:
                    item["saved"] = str(S.SaveDates(i))[:19]
                except Exception:                           # noqa: BLE001
                    pass
                out.append(item)
            self.state.set(hardware_settings=out, hardware_active=active)
            return out
        except Exception as exc:                            # noqa: BLE001
            self.state.log(f"讀硬體設定失敗:{exc}", "warn")
            return []

    def set_hardware_setting(self, name):
        """切換硬體設定。ISettings.ActiveSetting 可寫,已實測。"""
        S = self.project.MeasurementEngine.HardwareConfig.Settings
        S.ActiveSetting = str(name)
        self.state.log(f"硬體設定已切換為:{name}")
        return self.list_hardware_settings()

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
