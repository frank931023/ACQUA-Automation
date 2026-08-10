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
import win32com.client

# ACQUA 的資料表都在 acqua schema 下,不是 dbo
_SCHEMA = "acqua"

_PROVIDERS = ("MSOLEDBSQL", "SQLOLEDB")


def _val(x):
    """ADO 的 NULL 會變成 None;順便把 COM 的日期等型別轉成好處理的形式。"""
    if x is None:
        return None
    return x


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
        cn = win32com.client.Dispatch("ADODB.Connection")
        last = None
        for prov in _PROVIDERS:
            try:
                cn.Open(f"Provider={prov};Data Source={self.server};"
                        f"Initial Catalog={self.database};Integrated Security=SSPI;"
                        f"TrustServerCertificate=yes")
                last = None
                break
            except Exception as exc:                        # noqa: BLE001
                last = exc
        if last is not None:
            raise RuntimeError(f"所有 OLE DB provider 都連不上:{last}")

        try:
            rs = cn.Execute(sql)[0]
            names = [rs.Fields.Item(i).Name for i in range(rs.Fields.Count)]
            out = []
            while not rs.EOF:
                out.append({n: _val(rs.Fields.Item(i).Value)
                            for i, n in enumerate(names)})
                rs.MoveNext()
            rs.Close()
            return out
        finally:
            try:
                cn.Close()
            except Exception:                               # noqa: BLE001
                pass

    # ── 測項樹 ──────────────────────────────────────
    def _load_tree(self, project_title=None):
        """一次把整棵 TreeItems 撈回來,在 Python 端組樹(193 筆,很輕)。

        ACQUA 用 nested set 存樹:某節點的祖先 = LeftNode 更小且 RightNode 更大的節點。
        """
        where = ""
        if project_title:
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

    def list_smds(self, project_title=None, search="") -> list:
        """列出測項。回傳 [{row_id, title, smd_type, group, path,
                            needs_ref, ref_file, conditional}]

        `row_id` 可直接用於 `IProjectSelected.StartSingleMeasurement()`。
        """
        rows = self._load_tree(project_title)
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

        回傳 [{smd, smd_row_id, dut, status, created,
                values:[{title, value, unit, precision, channel,
                         lower_limit, upper_limit, status, type}]}]

        ⚠️ [未驗證] 撰寫時資料庫裡還沒有任何量測結果(Results 表 0 筆),
           所以這段 SQL 的欄位對應是依 schema 推導的,跑過一次真實量測後要再核對。
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

        rows = self.query(f"""
            SELECT r.idResult, r.rSMDItem, r.rStatus AS ResultStatus, r.CreationDate,
                   ti.Title AS SMDTitle, mo.Title AS MOTitle,
                   sv.Title AS ValueTitle, sv.SingleValue, sv.Unit,
                   sv.DecimalPrecision, sv.ChannelName, sv.SingleValueType,
                   sv.LowerLimit, sv.UpperLimit, sv.rStatus AS ValueStatus
            FROM {_SCHEMA}.Results r
            JOIN {_SCHEMA}.TreeItems ti ON ti.idTreeItem = r.rSMDItem
            JOIN {_SCHEMA}.Projects  p  ON p.idProject   = ti.rProject
            LEFT JOIN {_SCHEMA}.MObjects mo ON mo.idMObject = r.rMObject
            LEFT JOIN {_SCHEMA}.ResultSingleValues sv ON sv.rResult = r.idResult
            {where}
            ORDER BY r.rSMDItem, r.CreationDate DESC, sv.idResultSingleValue
        """)

        by_result = {}
        order = []
        for r in rows:
            rid = r["idResult"]
            if rid not in by_result:
                by_result[rid] = {
                    "result_id": int(rid),
                    "smd": (r.get("SMDTitle") or "").strip(),
                    "smd_row_id": int(r["rSMDItem"]),
                    "dut": (r.get("MOTitle") or "").strip(),
                    "status": r.get("ResultStatus"),
                    "created": str(r.get("CreationDate") or ""),
                    "values": [],
                }
                order.append(rid)
            if r.get("ValueTitle") is not None or r.get("SingleValue") is not None:
                by_result[rid]["values"].append({
                    "title": (r.get("ValueTitle") or "").strip(),
                    "value": r.get("SingleValue"),
                    "unit": (r.get("Unit") or "").strip(),
                    "precision": r.get("DecimalPrecision"),
                    "channel": (r.get("ChannelName") or "").strip(),
                    "lower_limit": r.get("LowerLimit"),
                    "upper_limit": r.get("UpperLimit"),
                    "status": r.get("ValueStatus"),
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
