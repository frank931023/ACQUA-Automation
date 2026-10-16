# -*- coding: utf-8 -*-
"""把 ACQUA 資料庫裡的 Python 腳本解出來存成檔案。**唯讀。**

為什麼需要這支
──────────────
ACQUA 會執行使用者寫的 Python 腳本,但那些腳本**不在檔案系統上** ——
它們壓成 ZIP 存在 SQL 的 `acqua.BinData` 裡,要執行時才解到
`C:\\ACQUA_Files\\File_Cache\\` 當快取。

結果是:想看腳本寫了什麼、比較兩個資料庫的差異、或做版本控制,
都沒有東西可以看。這支把它們解出來。

兩種腳本,用途差很多
────────────────────
    FT_Script         生命週期掛鉤。**每一筆量測都會跑**。
                      before_each_measurement / after_each_measurement /
                      after_canceled_measurement
    FT_SMDUsedFile    掛在單一 SMD 上,跑到那個測項才執行。

怎麼找到某個腳本屬於哪個測項
────────────────────────────
    SMDs.rFileCollection -> FileCollectionLists.rFileCollection
                         -> Files.idFile
    SMDs.idSMDItem == TreeItems.idTreeItem   （同一個 id 空間)
再用 TreeItems 的巢狀集合(LeftNode/RightNode)往上爬就是樹狀路徑。

⚠️ 只讀,不寫
─────────────
這支**不會**改資料庫。要改腳本請用 ACQUA 自己的編輯器 —— 存檔時它會
處理壓縮、FileSize、CRCValue、ChangeDate,少寫一個欄位 ACQUA 可能
就讀不到或靜默用舊版。

用法
────
    python tools/export_acqua_scripts.py                  全部資料庫
    python tools/export_acqua_scripts.py --db 51_MS_...   指定一個
    python tools/export_acqua_scripts.py --out some/dir   指定輸出位置
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from acqua import env                                      # noqa: E402
from acqua.sqlcat import raw_query                         # noqa: E402

#: 這兩種才是 Python 腳本。其餘(.dat/.tol/.fft)是量測資料與容差。
SCRIPT_TYPES = ("FT_Script", "FT_SMDUsedFile")


def unzip(blob, filename):
    """BinData 是 ZIP。回傳原始碼,解不開就回 None。"""
    if not blob:
        return None
    raw = bytes(blob)
    if raw[:2] != b"PK":
        return raw.decode("utf-8", "replace")      # 沒壓縮的情況
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        name = filename if filename in z.namelist() else z.namelist()[0]
        return z.read(name).decode("utf-8", "replace")
    except Exception:                                       # noqa: BLE001
        return None


def tree_path(rows_by_id, item_id):
    """用巢狀集合往上爬,回傳 ['群組', '子群組', ...] 的標題串。"""
    me = rows_by_id.get(item_id)
    if not me:
        return []
    out = []
    for r in rows_by_id.values():
        if (r["rProject"] == me["rProject"]
                and r["LeftNode"] < me["LeftNode"]
                and r["RightNode"] > me["RightNode"]):
            out.append((r["LeftNode"], r["Title"]))
    return [t for _, t in sorted(out)]


def scripts_of(server, database):
    """回傳這個資料庫裡所有 Python 腳本的中繼資料 + 原始碼。"""
    files = raw_query(server, database, """
        select f.idFile, f.Filename, f.rProject, t.Name as ftype,
               f.ChangeDate, b.BinData
        from acqua.Files f
        join acqua.TFileTypes t on t.idFileType = f.rFileType
        left join acqua.BinData b on b.rFile = f.idFile
        where f.Filename like '%.py'
          and t.Name in ('FT_Script', 'FT_SMDUsedFile')
        order by t.Name, f.Filename""")
    if not files:
        return []

    projects = {r["idProject"]: r["Title"] for r in
                raw_query(server, database,
                          "select idProject, Title from acqua.Projects")}

    # 哪個 SMD 用了哪個檔(只有 FT_SMDUsedFile 需要)
    users = {}
    for r in raw_query(server, database, """
            select l.rFile, s.idSMDItem
            from acqua.SMDs s
            join acqua.FileCollectionLists l
              on l.rFileCollection = s.rFileCollection"""):
        users.setdefault(r["rFile"], []).append(r["idSMDItem"])

    tree = {r["idTreeItem"]: r for r in raw_query(server, database, """
            select idTreeItem, rProject, Title, LeftNode, RightNode
            from acqua.TreeItems""")}

    out = []
    for f in files:
        src = unzip(f["BinData"], f["Filename"])
        if src is None:
            continue
        smds = []
        for sid in users.get(f["idFile"], []):
            node = tree.get(sid)
            if node:
                smds.append({"row_id": sid, "title": node["Title"],
                             "path": tree_path(tree, sid)})
        out.append({
            "database": database,
            "id_file": f["idFile"],
            "filename": f["Filename"],
            "file_type": f["ftype"],
            "project": projects.get(f["rProject"], ""),
            "changed": str(f["ChangeDate"])[:19],
            "used_by": smds,
            "source": src,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="只處理這一個資料庫")
    ap.add_argument("--out", default=os.path.join(ROOT, "acqua_scripts"),
                    help="輸出資料夾")
    args = ap.parse_args()

    cfg = json.load(io.open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
    env.apply_to(cfg, os.path.join(ROOT, ".env"))
    server = cfg["database"]["server"]

    dbs = [args.db] if args.db else [
        r["name"] for r in raw_query(server, "master",
                                     "select name from sys.databases "
                                     "where database_id > 4 order by name")]

    index = []
    for db in dbs:
        try:
            items = scripts_of(server, db)
        except Exception as exc:                            # noqa: BLE001
            print("%-26s 讀不到:%s" % (db, str(exc)[:60]))
            continue
        if not items:
            print("%-26s 沒有 Python 腳本" % db)
            continue

        folder = os.path.join(args.out, db)
        os.makedirs(folder, exist_ok=True)
        for it in items:
            # 同名不同庫不會撞(各自一個資料夾);同庫同名用 idFile 區隔
            same = [x for x in items if x["filename"] == it["filename"]]
            name = it["filename"]
            if len(same) > 1:
                stem, ext = os.path.splitext(name)
                name = "%s__%s%s" % (stem, it["id_file"], ext)
            # newline="" —— 保留原始換行。資料庫裡存的是 CRLF,
            # 用 newline="\n" 寫會悄悄改掉,之後就比對不回原檔了。
            io.open(os.path.join(folder, name), "w",
                    encoding="utf-8", newline="").write(it["source"])
            index.append({k: v for k, v in it.items() if k != "source"}
                         | {"saved_as": "%s/%s" % (db, name)})
        print("%-26s %d 個腳本 -> %s" % (db, len(items), folder))

    if index:
        os.makedirs(args.out, exist_ok=True)
        # 完整索引(含每個專案的副本)給 annotate 用,寫在暫存檔;
        # 留在資料夾裡的是精簡目錄 —— 同一支腳本在各專案的副本合成一筆,
        # 1.1 MB 變 33 KB,而且人看得懂。
        io.open(os.path.join(args.out, "index.full.json"), "w",
                encoding="utf-8", newline="\n").write(
            json.dumps(index, ensure_ascii=False, indent=2))

        agg = {}
        for it in index:
            key = (it["database"], it["filename"])
            a = agg.setdefault(key, {
                "database": it["database"], "filename": it["filename"],
                "file_type": it["file_type"], "copies": 0,
                "used_by_total": 0, "projects": [], "changed": it["changed"]})
            a["copies"] += 1
            a["used_by_total"] += len(it["used_by"])
            if it["project"] and it["project"] not in a["projects"]:
                a["projects"].append(it["project"])
        catalogue = sorted(agg.values(),
                           key=lambda x: (x["database"], -x["used_by_total"],
                                          x["filename"]))
        io.open(os.path.join(args.out, "index.json"), "w",
                encoding="utf-8", newline="\n").write(
            json.dumps(catalogue, ensure_ascii=False, indent=2))
        print("\n目錄:%d 支相異腳本 -> index.json" % len(catalogue))
    return 0


if __name__ == "__main__":
    sys.exit(main())
