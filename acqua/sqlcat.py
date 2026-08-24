"""直接查 ACQUA 的 SQL 資料庫 —— 列舉測項與讀取數值結果。

## 為什麼是這條路(2026-08-10 實機驗證後的決定)

原本規劃走 `AcquaDBMask`,但實測發現:

- `AcquaDBMask.Application.Connect()` **四種參數組合全部回傳 False**,連不上
- `GetActiveObject("AcquaDBMask.Application")` 也失敗(不在 ROT 裡)

而 Acqua3 自己的 `FindFirstSMD` 只能「搜尋」不能「列舉」:

- `FindFirstSMD("")` → **0 個**(空字串不等於全部)
- 只回傳 RowID,**不回傳標題**,做不出勾選清單

所以改直接查 SQL。關鍵前提已經實測確認:

```
✅ acqua.TreeItems.idTreeItem  ==  Acqua3 的 SMDRowID
   驗證方式:FindFirstSMD("3QUEST") 回傳的 20 個 RowID
             與 SQL 查出的 20 個 idTreeItem 完全一致(交集 20/20)
```

也就是說,SQL 查到的 `row_id` 可以直接餵給 `StartSingleMeasurement(SMDRowID, ...)`。

## 連線方式

用 ADODB(pywin32 內建,不需要額外裝驅動)。因為是 COM 物件,
**只能在已經 CoInitialize 的執行緒上使用** —— 也就是 AcquaWorker 那條。
"""
import threading

import win32com.client

# ACQUA 的資料表都在 acqua schema 下,不是 dbo
_SCHEMA = "acqua"

_PROVIDERS = ("MSOLEDBSQL", "SQLOLEDB")


def _val(x):
    """ADO 的 NULL 會變成 None;順便把 COM 的日期等型別轉成好處理的形式。"""
    if x is None:
        return None
    return x


_COM_READY = threading.local()


def _ensure_com():
    """確保這條執行緒有 COM 可用。

    ADODB 是 COM。工作執行緒啟動時就 CoInitialize 過了,但 Flask 的請求
    執行緒沒有 —— 直接 Dispatch 會失敗(2026-08-24:DUT 選單的路由就是
    這樣回「連不上」)。

    ⚠️ **初始化之後不要 CoUninitialize。**
       試過「用完就收」,結果把 apartment 拆掉,連帶讓工作執行緒對 ACQUA
       的 proxy 斷線,之後每個 COM 呼叫都丟
       (-2147220995, '物件未連接到伺服器')。
       Flask 的執行緒是長期重用的,留著 COM 沒有代價。
    """
    if getattr(_COM_READY, "done", False):
        return
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:                                       # noqa: BLE001
        pass            # 已經初始化過就算了
    _COM_READY.done = True


def raw_query(server: str, database: str, sql: str) -> list:
    """對指定的 server/database 執行查詢。任何執行緒都可以呼叫。"""
    _ensure_com()
    return _raw_query(server, database, sql)


def _raw_query(server: str, database: str, sql: str) -> list:
    cn = win32com.client.Dispatch("ADODB.Connection")
    last = None
    for prov in _PROVIDERS:
        try:
            cn.Open(f"Provider={prov};Data Source={server};"
                    f"Initial Catalog={database};Integrated Security=SSPI;"
                    f"TrustServerCertificate=yes")
            last = None
            break
        except Exception as exc:                            # noqa: BLE001
            last = exc
    if last is not None:
        raise RuntimeError(f"所有 OLE DB provider 都連不上:{last}")
    try:
        rs = cn.Execute(sql)[0]
        names = [rs.Fields.Item(i).Name for i in range(rs.Fields.Count)]
        out = []
        while not rs.EOF:
            out.append({n: _val(rs.Fields.Item(i).Value) for i, n in enumerate(names)})
            rs.MoveNext()
        rs.Close()
        return out
    finally:
        try:
            cn.Close()
        except Exception:                                   # noqa: BLE001
            pass


def list_databases(server: str) -> list:
    """列出伺服器上的資料庫,標出哪些是 ACQUA 庫並附測項數量。

    判斷依據:有沒有 `acqua.AcquaDB` 這張表(ACQUA 建庫時一定會建)。
    用三段式名稱 OBJECT_ID('[db].acqua.AcquaDB') 跨資料庫檢查,不用逐一連線。
    """
    # 第一步:只拿清單與狀態。⚠️ 這裡不能碰 OBJECT_ID —— 一旦有資料庫處於
    # RESTORING / OFFLINE / RECOVERING,查詢會直接丟例外把整個列表打掉。
    rows = raw_query(server, "master", """
        SELECT d.name, d.state_desc, d.create_date
        FROM sys.databases d
        WHERE d.database_id > 4
        ORDER BY d.name
    """)

    online = [r["name"] for r in rows
              if str(r.get("state_desc", "")) == "ONLINE"
              and "'" not in r["name"] and "]" not in r["name"]]

    # 第二步:只對「上線中」的庫做 ACQUA 判定與計數,一次查完
    info = {}
    if online:
        union = " UNION ALL ".join(
            f"SELECT '{n}' AS db, "
            f"CASE WHEN OBJECT_ID('[{n}].acqua.AcquaDB') IS NOT NULL THEN 1 ELSE 0 END AS is_acqua, "
            f"(SELECT COUNT(*) FROM [{n}].acqua.SMDs) AS smds, "
            f"(SELECT COUNT(*) FROM [{n}].acqua.MMDs) AS mmds, "
            f"(SELECT COUNT(*) FROM [{n}].acqua.Results) AS results"
            for n in online)
        try:
            for c in raw_query(server, "master", union):
                info[c["db"]] = c
        except Exception:                                   # noqa: BLE001
            # 有可能某個 ONLINE 的庫沒有 acqua schema,整句 UNION 就編譯失敗。
            # 退回逐一查詢 —— 慢一點但不會全滅。
            for n in online:
                try:
                    r = raw_query(server, "master",
                                  f"SELECT 1 AS is_acqua, "
                                  f"(SELECT COUNT(*) FROM [{n}].acqua.SMDs) AS smds, "
                                  f"(SELECT COUNT(*) FROM [{n}].acqua.MMDs) AS mmds, "
                                  f"(SELECT COUNT(*) FROM [{n}].acqua.Results) AS results")
                    info[n] = r[0]
                except Exception:                           # noqa: BLE001
                    info[n] = {"is_acqua": 0}

    out = []
    for r in rows:
        name = r["name"]
        state = str(r.get("state_desc", ""))
        c = info.get(name, {})
        out.append({
            "name": name,
            "is_acqua": bool(c.get("is_acqua")),
            "online": state == "ONLINE",
            "state": state,
            "smds": int(c.get("smds") or 0),
            "mmds": int(c.get("mmds") or 0),
            "results": int(c.get("results") or 0),
        })
    return out


class SqlCatalog:
    def __init__(self, state):
        self.state = state
        self.server = None
        self.database = None
        self._tree_cache = None

    # ── 連線 ────────────────────────────────────────
    def connect(self, server: str, database: str) -> bool:
        self.server, self.database = server, database
        self._tree_cache = None
        try:
            rows = self.query("SELECT DB_NAME() AS db, SUSER_NAME() AS usr")
            self.state.log(f"[SQL] 已連線 {server} / {rows[0]['db']}(使用者 {rows[0]['usr']})")
            return True
        except Exception as exc:                            # noqa: BLE001
            self.state.log(f"[SQL] 連線失敗:{exc}", "error")
            return False

    def query(self, sql: str) -> list:
        """執行查詢,回傳 [dict]。每次都開新連線 —— ADO 連線很輕,不值得為此管生命週期。"""
        return raw_query(self.server, self.database, sql)

    # ── 測項樹 ──────────────────────────────────────
    def _load_tree(self, project_title=None, project_id=None):
        """一次把整棵 TreeItems 撈回來,在 Python 端組樹。

        ACQUA 用 nested set 存樹:某節點的祖先 = LeftNode 更小且 RightNode 更大的節點。

        ⚠️ **優先用 project_id,不要用標題。**
           資料庫裡會有同名專案 —— Standards 群組的「標準範本」跟實際執行的
           專案標題一模一樣(實測 idProject 3 與 6 都叫
           "MS Teams v5 Rev05 SP2 - Speakerphone",各 1151 個 SMD)。
           用標題篩會兩個都撈到,測項數量直接變兩倍。

           project_id 來自 COM 的 IProjectSelected.RowID,那是 ACQUA
           當下真正在用的那一個,不會有歧義。
        """
        where = ""
        if project_id is not None:
            where = f"WHERE ti.rProject = {int(project_id)}"
        elif project_title:
            safe = str(project_title).replace("'", "''")
            where = f"WHERE p.Title = N'{safe}'"
        rows = self.query(f"""
            SELECT ti.idTreeItem, ti.Title, ti.LeftNode, ti.RightNode,
                   it.name AS ItemType, ti.ConditionalExecution,
                   p.Title AS ProjectTitle,
                   s.SMDType, s.NeedsRef, s.CreatesRef, s.RefFilename
            FROM {_SCHEMA}.TreeItems ti
            JOIN {_SCHEMA}.TItemTypes it ON it.idItemType = ti.rItemType
            JOIN {_SCHEMA}.Projects   p  ON p.idProject   = ti.rProject
            LEFT JOIN {_SCHEMA}.SMDs  s  ON s.idSMDItem   = ti.idTreeItem
            {where}
            ORDER BY ti.LeftNode
        """)
        for r in rows:
            r["Title"] = (r.get("Title") or "").strip()
        return rows

    def list_mobjects(self, project_id=None, project_title=None) -> list:
        """某個專案底下現有的量測物件(DUT)標題。

        走 SQL 而不是 COM —— 這是為了讓「選 DUT」這個動作不需要先把 ACQUA
        切到那個專案。跨庫排序列時,使用者是在還沒切過去之前就要選的。
        """
        if project_id is not None:
            where = "WHERE m.rProject = %d" % int(project_id)
        elif project_title:
            safe = str(project_title).replace("'", "''")
            where = "WHERE p.Title = N'%s'" % safe
        else:
            return []
        rows = self.query(f"""
            SELECT m.Title, m.idMObject
            FROM {_SCHEMA}.MObjects m
            JOIN {_SCHEMA}.Projects p ON p.idProject = m.rProject
            {where}
            ORDER BY m.idMObject
        """)
        return [str(r["Title"] or "").strip() for r in rows
                if str(r["Title"] or "").strip()]

    def list_smds(self, project_title=None, search="", project_id=None) -> list:
        """列出測項。回傳 [{row_id, title, smd_type, group, path,
                            needs_ref, ref_file, conditional}]

        `row_id` 可直接用於 `IProjectSelected.StartSingleMeasurement()`。
        """
        rows = self._load_tree(project_title, project_id)
        self._tree_cache = rows
        mmds = [r for r in rows if r["ItemType"] == "IType_MMD"]

        out = []
        for r in rows:
            if r["ItemType"] != "IType_SMD":
                continue
            # 祖先 = 包住它的 MMD,依 LeftNode 排序即為由外而內
            anc = [m["Title"] for m in mmds
                   if m["LeftNode"] < r["LeftNode"] and m["RightNode"] > r["RightNode"]]
            cond = r.get("ConditionalExecution")
            out.append({
                "row_id": int(r["idTreeItem"]),
                "title": r["Title"],
                "smd_type": int(r["SMDType"]) if r.get("SMDType") is not None else -1,
                "group": anc[-1] if anc else "",          # 直屬 MMD
                "path": " / ".join(anc),
                "needs_ref": bool(r.get("NeedsRef")),
                "ref_file": (r.get("RefFilename") or "").strip(),
                "conditional": bool(cond and str(cond).strip()),
            })

        if search:
            s = search.lower()
            out = [x for x in out
                   if s in x["title"].lower() or s in x["path"].lower()]
        return out

    def predict_run_set(self, project_title=None, variables=None, project_id=None) -> dict:
        """預測「照這組變數,StartMeasurements 會跑哪些測項」。

        完全不啟動量測 —— 純粹讀 TreeItems.ConditionalExecution 自己算。
        詳見 acqua/condeval.py 的語意說明與未確定之處。
        """
        from .condeval import predict
        rows = self._load_tree(project_title, project_id)
        for r in rows:
            r["ConditionalExecution"] = (
                str(r["ConditionalExecution"]) if r.get("ConditionalExecution") else "")
        return predict(rows, variables or {})

    def missing_reference_files(self, smds: list) -> list:
        """回傳需要參考檔、但檔案在系統上找不到的測項。

        ⚠️ [未驗證] 參考檔的搜尋路徑未知 —— ACQUA 可能有自己的 reference 目錄。
        目前只做「有沒有標記需要參考檔」的彙整,不做實際檔案存在檢查。
        """
        need = [s for s in smds if s["needs_ref"] and s["ref_file"]]
        by_file = {}
        for s in need:
            by_file.setdefault(s["ref_file"], []).append(s["title"])
        return [{"ref_file": k, "smds": v} for k, v in sorted(by_file.items())]

    # ── 數值結果 ────────────────────────────────────
    def read_results(self, project_title=None, mo_title=None,
                     latest_only=True, smd_row_ids=None) -> list:
        """讀出量測的實際數值(含極限值)。

        回傳 [{smd, smd_row_id, dut, status, status_name, passed, created,
                values:[{title, value, unit, precision, channel,
                         lower_limit, upper_limit, status, status_name,
                         passed, type}]}]

        ✅ 已用 51_MS_Teams_Rev05_SP2 的真實結果驗證(2026-08-10):
           Results / TreeItems / MObjects / TStatusTypes 的 join 正確。
           過程中修掉一個會導致判定相反的 bug —— `rStatus` 是 TStatusTypes 的
           **外鍵**(idStatusType 1..5),不是狀態值(0/1/2/4/8)。

        ⚠️ [仍未驗證] `ResultSingleValues` 的欄位對應 —— 用來驗證的那 3 筆結果
           來自腳本型 SMD,沒有產生任何數值(ResultSingleValues 為 0 筆)。
           要等有真正的量測結果才能核對 value/unit/limit 這幾欄。
        """
        conds = []
        if project_title:
            conds.append(f"p.Title = N'{str(project_title)}'".replace("''", "'"))
        if mo_title:
            safe = str(mo_title).replace("'", "''")
            conds.append(f"mo.Title = N'{safe}'")
        if smd_row_ids:
            ids = ",".join(str(int(i)) for i in smd_row_ids)
            conds.append(f"r.rSMDItem IN ({ids})")
        where = ("WHERE " + " AND ".join(conds)) if conds else ""

        # ⚠️ r.rStatus / sv.rStatus 是 TStatusTypes 的**外鍵**(idStatusType),
        #    不是狀態值本身。必須 join 出 Name/Value,直接拿 rStatus 當狀態會判定相反。
        #      idStatusType 1..5  →  Value 0/1/2/4/8
        rows = self.query(f"""
            SELECT r.idResult, r.rSMDItem, r.CreationDate,
                   ti.Title AS SMDTitle, mo.Title AS MOTitle,
                   rst.Name AS ResultStatusName, rst.Value AS ResultStatusValue,
                   sv.Title AS ValueTitle, sv.SingleValue, sv.Unit,
                   sv.DecimalPrecision, sv.ChannelName, sv.SingleValueType,
                   sv.LowerLimit, sv.UpperLimit,
                   vst.Name AS ValueStatusName, vst.Value AS ValueStatusValue
            FROM {_SCHEMA}.Results r
            JOIN {_SCHEMA}.TreeItems ti ON ti.idTreeItem = r.rSMDItem
            JOIN {_SCHEMA}.Projects  p  ON p.idProject   = ti.rProject
            LEFT JOIN {_SCHEMA}.MObjects mo ON mo.idMObject = r.rMObject
            LEFT JOIN {_SCHEMA}.TStatusTypes rst ON rst.idStatusType = r.rStatus
            LEFT JOIN {_SCHEMA}.ResultSingleValues sv ON sv.rResult = r.idResult
            LEFT JOIN {_SCHEMA}.TStatusTypes vst ON vst.idStatusType = sv.rStatus
            {where}
            ORDER BY r.rSMDItem, r.CreationDate DESC, sv.idResultSingleValue
        """)

        by_result = {}
        order = []
        for r in rows:
            rid = r["idResult"]
            if rid not in by_result:
                sname = str(r.get("ResultStatusName") or "")
                by_result[rid] = {
                    "result_id": int(rid),
                    "smd": (r.get("SMDTitle") or "").strip(),
                    "smd_row_id": int(r["rSMDItem"]),
                    "dut": (r.get("MOTitle") or "").strip(),
                    "status": r.get("ResultStatusValue"),      # 0/1/2/4/8
                    "status_name": sname,                      # Status_OK / Status_NotOK …
                    "passed": sname in ("Status_OK", "Status_Done",
                                        "Status_NotOKNotRequired"),
                    "created": str(r.get("CreationDate") or ""),
                    "values": [],
                }
                order.append(rid)
            if r.get("ValueTitle") is not None or r.get("SingleValue") is not None:
                vname = str(r.get("ValueStatusName") or "")
                by_result[rid]["values"].append({
                    "title": (r.get("ValueTitle") or "").strip(),
                    "value": r.get("SingleValue"),
                    "unit": (r.get("Unit") or "").strip(),
                    "precision": r.get("DecimalPrecision"),
                    "channel": (r.get("ChannelName") or "").strip(),
                    "lower_limit": r.get("LowerLimit"),
                    "upper_limit": r.get("UpperLimit"),
                    "status": r.get("ValueStatusValue"),
                    "status_name": vname,
                    "passed": vname in ("Status_OK", "Status_NotOKNotRequired"),
                    "type": r.get("SingleValueType"),
                })

        results = [by_result[i] for i in order]
        if latest_only:
            seen, keep = set(), []
            for x in results:                # 已依 CreationDate DESC 排序
                if x["smd_row_id"] in seen:
                    continue
                seen.add(x["smd_row_id"])
                keep.append(x)
            results = keep
        return results
