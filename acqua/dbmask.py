"""AcquaDBMask —— ACQUA 的第二套 COM 物件模型,直接對資料庫操作。

為什麼需要它(Acqua3 介面做不到的事):
  1. ⭐ 列舉專案底下所有 SMD 並取得標題(Acqua3 只有 FindFirstSMD 搜尋,且不回傳標題)
  2. ⭐ 讀出量測的「數值」結果(Acqua3 只給 OK / NOT OK)
  3. ⭐ 程式化建立 MMD / SMD(Acqua3 完全沒有這個能力)

⚠️⚠️ 兩套模型的名詞不一樣,這是最容易搞混的地方:

    Acqua3 說的            AcquaDBMask 說的       VB6 範例 UI 上寫的
    ─────────────────────────────────────────────────────────────
    ProjectGroup      =    Project           →   "project group"
    Project           =    Subproject        →   "Selected Subproject"  ←!
    MeasurementObject =    LocalMeasurementObject

    (VB6 範例把 Acqua3 的 Project 標成 "Subproject",就是因為底層是 Subproject)

⚠️ Connect() 的參數順序跟 Acqua3.SelectDatabase() 相反:
       Acqua3     : SelectDatabase(SQLServerName, DatabaseName, ...)
       AcquaDBMask: Connect(DatabaseName, SQLServerName)      ← 資料庫在前!

結構(全部經 TypeLib 實測確認):
    Application
      .Connect(db, server) / .Disconnect()
      .Projects                    → Count, Item(i), Exists(title), Add(title, desc)
         .Item(i)                  → Project(Title, ID, Subprojects, Items)
            .Subprojects.Item(j)   → Subproject
               .GetSMDsRecursive()          ⭐ 列出所有 SMD
               .GetNbrOfSMDsRecursive()
               .MmdsAndSmds                 → AddSMD/AddMMD/Item/Count/Remove
               .LocalMeasurementObjects     → DUT 清單
    SMD
      .Title .ID .SMDType .NumberOfMeasurementResults .MeasurementResults
    MeasurementResult
      .Title .Status .SingleValue1 .SingleValue2 .MeasurementObjectName .Runs
    SingleValue
      .Value .Unit .Title .Status .Precision .HasValue     ⭐ 數值在這裡
"""
from .constants import PROGID_DBMASK, ESingleValueCheckState


def _safe(obj, name, default=None):
    """COM 屬性讀取常常會因為狀態不對而丟例外,統一包起來。"""
    try:
        v = getattr(obj, name)
        return v() if callable(v) else v
    except Exception:                                       # noqa: BLE001
        return default


class DbMask:
    """AcquaDBMask.Application 的薄封裝。

    ⚠️ 跟 ComBackend 一樣,只能在 COM 工作執行緒上使用。
    """

    def __init__(self, state):
        self.state = state
        self.app = None

    # ── 連線 ────────────────────────────────────────
    def connect(self, server: str, database: str) -> bool:
        import win32com.client
        self.app = win32com.client.Dispatch(PROGID_DBMASK)
        # ⚠️ 參數順序:資料庫在前,伺服器在後
        self.app.Connect(database, server)
        ok = bool(_safe(self.app, "ConnectedDatabaseName"))
        if ok:
            self.state.log(f"[DBMask] 已連線 {_safe(self.app, 'ConnectedSQLServerName')}"
                           f" / {_safe(self.app, 'ConnectedDatabaseName')}"
                           f"(使用者 {_safe(self.app, 'ConnectedUser')})")
        else:
            self.state.log("[DBMask] 連線失敗", "error")
        return ok

    def disconnect(self):
        if self.app is not None:
            try:
                self.app.Disconnect()
            except Exception:                               # noqa: BLE001
                pass
            self.app = None

    # ── 階層走訪 ────────────────────────────────────
    def find_subproject(self, group_title: str, project_title: str):
        """用 Acqua3 的詞彙找:group_title = ProjectGroup, project_title = Project。

        對應到 DBMask 就是 Project → Subproject。
        """
        if self.app is None:
            raise RuntimeError("[DBMask] 尚未連線")
        projects = self.app.Projects
        for i in range(projects.Count):
            proj = projects.Item(i)
            if str(_safe(proj, "Title", "")) != group_title:
                continue
            subs = proj.Subprojects
            for j in range(subs.Count):
                sub = subs.Item(j)
                if str(_safe(sub, "Title", "")) == project_title:
                    return sub
        return None

    # ── ⭐ SMD 列舉 ─────────────────────────────────
    def list_smds(self, subproject) -> list:
        """回傳 [{"row_id", "title", "smd_type", "n_results"}]。

        用 GetSMDsRecursive() —— 這是 Acqua3 介面沒有的能力。

        ⚠️ [待驗證] 這裡回傳的 SMD.ID 是否等於 Acqua3
           StartSingleMeasurement(SMDRowID) 所要的 RowID?
           兩者都是資料庫的 row id,理論上相同,但務必在階段 3 用一筆實測確認:
           挑一個 SMD,用它的 ID 去跑 StartSingleMeasurement,看跑的是不是同一項。
        """
        out = []
        try:
            smds = subproject.GetSMDsRecursive()
        except Exception as exc:                            # noqa: BLE001
            self.state.log(f"[DBMask] GetSMDsRecursive 失敗:{exc}", "error")
            return out

        # 回傳的可能是集合物件,也可能是陣列 —— 兩種都處理
        try:
            n = smds.Count
            items = (smds.Item(i) for i in range(n))
        except Exception:                                   # noqa: BLE001
            items = iter(smds)

        for smd in items:
            rid = _safe(smd, "ID")
            if rid is None:
                continue
            out.append({
                "row_id": int(rid),
                "title": str(_safe(smd, "Title", f"SMD #{rid}")),
                "smd_type": str(_safe(smd, "SMDType", "")),
                "n_results": int(_safe(smd, "NumberOfMeasurementResults", 0) or 0),
            })
        return out

    # ── ⭐ 讀取數值結果 ─────────────────────────────
    def read_results(self, subproject, measurement_object: str = None,
                     latest_only: bool = True) -> list:
        """讀出量測的實際數值。

        回傳 [{"smd", "result", "dut", "status", "values": [
                  {"title","value","unit","status","status_text"} ]}]

        這是 Acqua3 介面完全做不到、必須走 AcquaDBMask 的部分。
        """
        results = []
        try:
            smds = subproject.GetSMDsRecursive()
            n = smds.Count
            smd_iter = (smds.Item(i) for i in range(n))
        except Exception as exc:                            # noqa: BLE001
            self.state.log(f"[DBMask] 讀取結果失敗:{exc}", "error")
            return results

        for smd in smd_iter:
            smd_title = str(_safe(smd, "Title", "?"))
            mrs = _safe(smd, "MeasurementResults")
            if mrs is None:
                continue
            try:
                count = mrs.Count
            except Exception:                               # noqa: BLE001
                continue

            indices = [count - 1] if (latest_only and count) else range(count)
            for k in indices:
                try:
                    mr = mrs.Item(k)
                except Exception:                           # noqa: BLE001
                    continue
                dut = str(_safe(mr, "MeasurementObjectName", ""))
                if measurement_object and dut != measurement_object:
                    continue

                values = []
                for prop in ("SingleValue1", "SingleValue2"):
                    sv = _safe(mr, prop)
                    if sv is None or not _safe(sv, "HasValue", False):
                        continue
                    st = _safe(sv, "Status", 0)
                    values.append({
                        "title": str(_safe(sv, "Title", prop)),
                        "value": _safe(sv, "Value"),
                        "unit": str(_safe(sv, "Unit", "")),
                        "status": int(st or 0),
                        "status_text": ESingleValueCheckState.describe(st or 0),
                    })

                results.append({
                    "smd": smd_title,
                    "result": str(_safe(mr, "Title", "")),
                    "dut": dut,
                    "status": _safe(mr, "Status"),
                    "values": values,
                })
        return results

    # ── ⭐ 建立自訂 MMD / SMD ───────────────────────
    def add_mmd(self, subproject, title: str, description: str = ""):
        """在 Subproject 底下建立一個 MMD(測試群組)。

        ⚠️ [未驗證] 會寫入資料庫。請先在測試用的資料庫上試,不要直接對正式庫操作。
        """
        return subproject.MmdsAndSmds.AddMMD(title, description)

    def add_smd(self, parent, title: str, description: str,
                smd_type: str, smd_file: str):
        """在 MMD 或 Subproject 底下建立一個 SMD(單一測項)。

        簽章(TypeLib 實測):
            AddSMD(strTitle, strDescription, strSMDType, strSMDCompleteFileName)

        ⚠️ [未驗證] strSMDType 與 strSMDCompleteFileName 的合法值未知。
           最可靠的做法:先在 ACQUA GUI 裡手動建一個 SMD,再用 list_smds()
           把它的 SMDType 讀出來當範本。
        ⚠️ 會寫入資料庫。
        """
        container = parent.MmdsAndSmds if hasattr(parent, "MmdsAndSmds") else parent
        return container.AddSMD(title, description, smd_type, smd_file)
