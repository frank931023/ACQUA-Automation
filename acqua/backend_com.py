"""真實的 ACQUA COM 後端。

⚠️ 這個檔案尚未在真實環境驗證過 —— 撰寫時這台機器上沒有可用的 Python,
   也還沒有 ACQUA 資料庫。凡是標 [未驗證] 的地方請在階段 2~5 逐一實測。

前置需求:
  1. 32-bit Python + pywin32
  2. ACQUA 已安裝且 ACOPT18 授權有效
  3. ACQUA 資料庫已建立(DBAdmin.exe),且裡面有定義好的專案與 SMD
  4. acqua/constants.py 的 EMEResult 數值已填入(執行 tools/dump_typelib.py)

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

    # ── 純資訊 ──────────────────────────────────────
    def OnProgress(self, Description, ProgressCounter, TotalCount):
        if ProgressCounter != -1 and TotalCount not in (-1, 0):
            self._st().set(progress={"text": Description,
                                     "value": int(ProgressCounter),
                                     "total": int(TotalCount)})
        else:
            self._st().set(progress=None)

    def OnEvent(self, Description, EventType):
        level = {0: "info", 1: "warn", 2: "error"}.get(int(EventType), "info")
        tag = EMEEventType.NAMES.get(int(EventType), "?")
        self._st().log(f"<{tag}> {Description}", level)

    def OnBeginMeasurements(self, SelectedProject, MeasurementObject, NbrOfMeasurements):
        self._st().log(f"ACQUA 回報:即將進行 {NbrOfMeasurements} 筆量測")

    def OnBeginSingleMeasurement(self, SMDTitle, Progress, NbrOfMeasurements):
        self._st().log(f"  ACQUA 開始:{SMDTitle}")

    # ── 決策點:ByRef 輸出用「回傳值」給回 ACQUA ────────
    def OnFinishedSingleMeasurement(self, SMDTitle, ResultStatus,
                                    Progress, NbrOfMeasurements, UserReaction):
        # [未驗證] pywin32 對 ByRef out 參數的慣例是「以 return 回傳」。
        #          階段 4 必須實測確認 —— 若不生效,ACQUA 會停在這裡等回應。
        self.backend._on_single_finished(SMDTitle, ResultStatus)
        if self._st().cancel_requested:
            return EUserReaction.CANCEL_ALL
        return EUserReaction.DO_NEXT

    def OnFinishedMeasurements(self, SelectedProject, MeasurementObject,
                               NbrOfMeasurements, NbrOfMeasurementsFinished,
                               Canceled, ResultOverview):
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
        self.dbmask = None             # AcquaDBMask —— 列舉 SMD 與讀數值用
        self._pythoncom = None
        self._last_result = None       # (title, status)
        self._measuring_done = False

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
        self.state.log(f"建立 COM 物件:{PROGID_ACQUA} …")
        self.app = win32com.client.DispatchWithEvents(PROGID_ACQUA, _Events)

        self.state.log("等待 ACQUA 啟動(AppLoadFinished)…")
        self._wait_until(lambda: self.app.AppLoadFinished, timeout=300, what="AppLoadFinished")
        self.state.set(acqua_ready=True)
        self.state.log("ACQUA 已就緒")

        if not EMEResult.is_resolved():
            self.state.log("⚠️ EMEResult 數值尚未填入 —— pass/fail 判定會失敗。"
                           "請先執行 tools/dump_typelib.py", "error")

    def pump(self):
        if self._pythoncom is not None:
            self._pythoncom.PumpWaitingMessages()

    def shutdown(self):
        self.app = None
        self.project = None
        self.mo = None
        if self._pythoncom is not None:
            try:
                self._pythoncom.CoUninitialize()
            except Exception:
                pass

    # ── 內部工具 ────────────────────────────────────
    def _wait_until(self, predicate, timeout=120.0, interval=0.05, what="condition"):
        """等待期間必須持續打訊息幫浦,否則 COM 事件永遠不會送達。"""
        deadline = time.monotonic() + timeout
        while not predicate():
            self.pump()
            time.sleep(interval)
            if time.monotonic() > deadline:
                raise TimeoutError(f"等待逾時({timeout}s):{what}")

    def _on_single_finished(self, title, status):
        self._last_result = (str(title), int(status))

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
        mos = self.project.MeasurementObjects
        titles = [str(mos.Item(i).Title) for i in range(mos.Count)]
        if title not in titles and create_if_missing:
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

    def list_smds(self, search=""):
        """列出專案內的 SMD。

        主要路徑:AcquaDBMask.Subproject.GetSMDsRecursive() —— 會回傳「標題」。
        備援路徑:Acqua3 的 FindFirstSMD/FindNextSMD —— 只回傳 RowID,沒有標題。

        Acqua3 介面本身沒有純列舉的方法(FindFirstSMD 是搜尋,不是列舉),
        所以要做「勾選清單」的 UI,DBMask 這條路幾乎是必經的。
        """
        if self.project is None:
            raise RuntimeError("尚未開啟專案")

        smds = self._list_smds_via_dbmask(search)
        if smds is None:
            smds = self._list_smds_via_find(search)

        self.state.set(smds=smds)
        return smds

    def _list_smds_via_dbmask(self, search=""):
        """走 AcquaDBMask —— 拿得到標題,這是首選。失敗時回傳 None 讓呼叫端走備援。"""
        try:
            if self.dbmask is None:
                from .dbmask import DbMask
                self.dbmask = DbMask(self.state)
                if not self.dbmask.connect(self.state.server, self.state.database):
                    self.dbmask = None
                    return None

            sub = self.dbmask.find_subproject(self.state.open_group, self.state.open_project)
            if sub is None:
                self.state.log("[DBMask] 找不到對應的 Subproject", "warn")
                return None

            smds = self.dbmask.list_smds(sub)
            if search:
                smds = [s for s in smds if search.lower() in s["title"].lower()]
            self.state.log(f"[DBMask] 列出 {len(smds)} 個 SMD")
            return smds
        except Exception as exc:                            # noqa: BLE001
            self.state.log(f"[DBMask] 列舉失敗,改用 FindFirstSMD 備援:{exc}", "warn")
            self.dbmask = None
            return None

    def _list_smds_via_find(self, search=""):
        """備援:Acqua3 的搜尋式走訪。只有 RowID,沒有標題。"""
        smds, seen = [], set()
        row_id = self.project.FindFirstSMD(search)
        guard = 0
        while int(row_id) != -1:
            rid = int(row_id)
            if rid in seen:
                break                                # 防禦:避免 API 循環回繞
            seen.add(rid)
            smds.append({"row_id": rid, "title": f"SMD #{rid}"})
            row_id = self.project.FindNextSMD()
            guard += 1
            if guard > 5000:
                self.state.log("SMD 列舉超過 5000 筆,強制中斷", "warn")
                break

        if not smds:
            self.state.log(f"FindFirstSMD({search!r}) 沒有找到任何 SMD —— "
                           "若搜尋字串為空,代表空字串不等於「全部符合」", "warn")
        return smds

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
                    # ⚠️ 簽章以 TypeLib 實測為準,比 CHM 多一個 ResultComment 參數:
                    #    StartSingleMeasurement(SMDRowID, UseMMDSettings,
                    #                           MeasurementObject, ResultComment)
                    self.project.StartSingleMeasurement(
                        smd["row_id"], use_mmd, self.mo.Title, result_comment)

                    # ⚠️ [未驗證] StartSingleMeasurement 是非同步的。
                    #    先給 ACQUA 一點時間把 IsMeasuring 翻成 True,再等它翻回 False。
                    #    若這裡有 race condition,改成等 self._measuring_done。
                    time.sleep(0.5)
                    self._wait_until(
                        lambda: (not self.app.IsMeasuring) or self._measuring_done,
                        timeout=timeout, what=f"量測完成:{smd['title']}")

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
                self.state.log(f"    → {'PASS' if passed else 'FAIL'}"
                               f"({EMEResult.describe(status)})",
                               "info" if passed else "error")

                if not passed and stop_on_fail:
                    self.state.log("設定為失敗即停 —— 中止剩餘測項", "error")
                    break
                i += 1
        finally:
            self.state.set(running=False, current=None, progress=None)
            snap = self.state.snapshot()["summary"]
            self.state.log(f"=== 結束:{snap['passed']} PASS / {snap['failed']} FAIL ===")

    def create_report(self, output_path, selection_type):
        if self.project is None or self.mo is None:
            raise RuntimeError("尚未開啟專案或選定量測物件")
        # CreateReportForMO 吃的是 RowID,不是名稱
        self.project.CreateReportForMO(self.mo.RowID, int(selection_type), output_path, 0)
        self.state.log(f"已產生報告:{output_path}")

    # ── ⭐ 混合模式:變數驅動 ────────────────────────
    def _variables(self):
        """取得 ACQUA 的變數集合(IVariables)。

        路徑:IProjectSelected.MeasurementEngine.UsedVariables
        ⚠️ [未驗證] MeasurementEngine 另有 ResultVariables。兩者的差別是:
           UsedVariables   —— 專案在用的變數(條件執行讀的應該是這組)
           ResultVariables —— 量測產生的結果變數
           階段 4 要實測確認條件執行到底讀哪一組。
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
            self.project.StartMeasurements(use_mmd, self.mo.Title, result_comment)
            time.sleep(0.5)
            self._wait_until(
                lambda: (not self.app.IsMeasuring) or self._measuring_done,
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
