# -*- coding: utf-8 -*-
"""涵蓋率盤點:我們的假設,在這台機器上的所有資料庫裡站得住腳嗎?

為什麼要有這支
──────────────
先前的修法是「使用者踩到一個洞,就補一個洞」。那不會收斂 ——
因為我們從來沒有量過「外面到底有多少種樣子」。

這支把所有資料庫、所有專案掃一遍,對每一條**程式裡的假設**給出證據:
站得住腳、或是在哪幾筆資料上站不住。它不修東西,只回報。

檢查的假設
──────────
  A. 資料庫的 schema 都長一樣嗎(缺表就整條路走不通)
  B. 專案:同名、空白、Standards、沒有 MO 的
  C. 樹狀結構:path + title 在專案內唯一嗎  ← 計畫跨庫還原靠這個
  D. SMDType 的分佈,以及我們對每一種的處理
  E. ConditionalExecution 的值域:Relation / Action / MatchConditions
  F. 測項分類(需人工 / 腳本)涵蓋得到嗎
  G. 條件式變數的命名空間

用法:  python tools/survey.py            (掃全部資料庫)
       python tools/survey.py --db X     (只掃一個)
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

import io                                                   # noqa: E402
import json                                                 # noqa: E402

from acqua.sqlcat import raw_query, list_databases          # noqa: E402

CFG = json.load(io.open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
SERVER = CFG.get("database", {}).get("server", "")

# 嚴重度分兩種,不要混在一起:
#   "!"  程式的缺陷 —— 我們要改
#   "?"  環境的事實 —— 使用者要處理(建 MO、整理專案),程式只能講清楚
#   "."  只是資訊
findings = []


def note(sev, msg):
    findings.append((sev, msg))
    print("      %s %s" % ({"!": "!!", "?": "??", ".": "  "}[sev], msg))


def hr(title):
    print("\n" + "=" * 66)
    print(title)
    print("=" * 66)


# ══════════════════════════════════════════════════════════
# A. 資料庫層
# ══════════════════════════════════════════════════════════
NEEDED = ["Projects", "TreeItems", "TItemTypes", "SMDs", "MObjects", "Results"]


def survey_databases(only=None):
    hr("A. 資料庫")
    dbs = [d for d in list_databases(SERVER) if d["is_acqua"]]
    if only:
        dbs = [d for d in dbs if d["name"] == only]
    print("   %s 上有 %d 個 ACQUA 資料庫" % (SERVER, len(dbs)))

    usable = []
    for d in dbs:
        name = d["name"]
        print("\n   ── %s(SMD %s ・ 結果 %s)" % (name, d["smds"], d["results"]))
        if not d["online"]:
            note("!", "不是 ONLINE,跳過")
            continue
        try:
            tables = {r["TABLE_NAME"] for r in raw_query(
                SERVER, name,
                "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA='acqua'")}
        except Exception as exc:                            # noqa: BLE001
            note("!", "查不到 schema:%s" % str(exc)[:70])
            continue
        miss = [t for t in NEEDED if t not in tables]
        if miss:
            note("!", "缺少表:%s —— 這個庫用不了" % "、".join(miss))
            continue
        note(".", "schema 齊全(%d 張表)" % len(tables))
        usable.append(name)
    return usable


# ══════════════════════════════════════════════════════════
# B. 專案層
# ══════════════════════════════════════════════════════════
def survey_projects(db):
    rows = raw_query(SERVER, db, """
        SELECT p.idProject, p.Title,
          (SELECT COUNT(*) FROM acqua.TreeItems t
             JOIN acqua.TItemTypes it ON it.idItemType=t.rItemType
            WHERE t.rProject=p.idProject AND it.name='IType_SMD') AS smds,
          (SELECT COUNT(*) FROM acqua.MObjects m
            WHERE m.rProject=p.idProject) AS mos
        FROM acqua.Projects p ORDER BY p.idProject""")
    print("   %d 個專案" % len(rows))

    titles = collections.Counter(str(r["Title"] or "").strip() for r in rows)
    dup = [t for t, n in titles.items() if n > 1]
    if dup:
        # ACQUA 的常態:Standards 的範本跟實際專案同名。
        # 程式全程用 idProject,不受影響 —— 這裡只是讓人知道。
        note(".", "同名專案 %d 組(Standards 範本 vs 實際專案)—— 全程用 idProject 分辨"
             % len(dup))

    for r in rows:
        raw = str(r["Title"] or "")
        if raw != raw.strip():
            note("?", "專案標題有頭尾空白:%r" % raw)
        if r["smds"] and not r["mos"]:
            # 環境事實,不是程式缺陷:ACQUA 的 AddMeasurementObject 建不出來
            #(實測一律回 -1),所以只能請人在 ACQUA 裡建。
            note("?", "id=%s「%s」%d 個測項但沒有量測物件 —— 要先在 ACQUA 裡建一個"
                 % (r["idProject"], raw.strip()[:30], r["smds"]))
    return rows


# ══════════════════════════════════════════════════════════
# C. 樹狀結構:path + title 唯一嗎
# ══════════════════════════════════════════════════════════
def survey_tree(db, projects):
    """驗測項的身分鍵。

    身分鍵是 (路徑, 名稱, 序號)。序號 = 依樹狀順序在「同路徑同名」這組裡
    的第幾個 —— 因為 (路徑, 名稱) 本身**不唯一是常態**(實測 ZoomRooms
    有 11% 這樣),光靠它跨庫還原會漏掉一成的測項。

    這裡兩件事都驗:同名的比例(當資訊),以及加了序號之後有沒有撞號
    (那才是會出事的)。
    """
    worst = 0
    for p in projects:
        pid, ptitle = p["idProject"], str(p["Title"] or "").strip()
        if not p["smds"]:
            continue
        rows = raw_query(SERVER, db, """
            SELECT ti.idTreeItem, ti.Title, ti.LeftNode, ti.RightNode,
                   it.name AS ItemType
            FROM acqua.TreeItems ti
            JOIN acqua.TItemTypes it ON it.idItemType = ti.rItemType
            WHERE ti.rProject = %d ORDER BY ti.LeftNode""" % pid)
        mmds = [r for r in rows if r["ItemType"] == "IType_MMD"]
        keys, titles_only = collections.Counter(), collections.Counter()
        for r in rows:
            if r["ItemType"] != "IType_SMD":
                continue
            anc = [str(m["Title"] or "").strip() for m in mmds
                   if m["LeftNode"] < r["LeftNode"] and m["RightNode"] > r["RightNode"]]
            path = " / ".join(anc)
            title = str(r["Title"] or "").strip()
            keys[(path, title)] += 1
            titles_only[title] += 1

        dup_key = sum(n - 1 for n in keys.values() if n > 1)
        total = sum(keys.values())
        if dup_key:
            pct = dup_key * 100.0 / max(1, total)
            note(".", "「%s」%d/%d(%.0f%%)測項同路徑同名 —— 由序號分辨"
                 % (ptitle[:30], dup_key, total, pct))
            worst = max(worst, dup_key)

        # 序號照定義必然唯一。實際算一次,免得哪天 list_smds 的產生方式被改壞。
        occ_keys, seen = collections.Counter(), {}
        for r in rows:
            if r["ItemType"] != "IType_SMD":
                continue
            anc = [str(m["Title"] or "").strip() for m in mmds
                   if m["LeftNode"] < r["LeftNode"] and m["RightNode"] > r["RightNode"]]
            k = (" / ".join(anc), str(r["Title"] or "").strip())
            occ = seen.get(k, 0)
            seen[k] = occ + 1
            occ_keys[k + (occ,)] += 1
        clash = [k for k, n in occ_keys.items() if n > 1]
        if clash:
            note("!", "「%s」加了序號還是撞號 %d 筆 —— 身分鍵不成立"
                 % (ptitle[:30], len(clash)))
    return worst


# ══════════════════════════════════════════════════════════
# D. SMDType
# ══════════════════════════════════════════════════════════
def survey_smdtypes(db):
    rows = raw_query(SERVER, db, """
        SELECT s.SMDType, COUNT(*) AS n,
               SUM(CASE WHEN s.NeedsRef=1 THEN 1 ELSE 0 END) AS needs_ref
        FROM acqua.SMDs s GROUP BY s.SMDType ORDER BY COUNT(*) DESC""")
    print("   SMDType 分佈:")
    for r in rows:
        print("      type %-4s %6d 筆%s"
              % (r["SMDType"], r["n"],
                 ("  需參考檔 %d" % r["needs_ref"]) if r["needs_ref"] else ""))
    return {r["SMDType"]: r["n"] for r in rows}


# ══════════════════════════════════════════════════════════
# E. ConditionalExecution 的值域
# ══════════════════════════════════════════════════════════
RE_COND = re.compile(r"<Condition>(.*?)</Condition>", re.S)
RE_VAR = re.compile(r"<Variable>(.*?)</Variable>", re.S)
RE_REL = re.compile(r"<Relation>(.*?)</Relation>", re.S)
RE_ACT = re.compile(r"<Action>(.*?)</Action>", re.S)
RE_MATCH = re.compile(r"<MatchConditions>(.*?)</MatchConditions>", re.S)


def survey_conditions(db):
    rows = raw_query(SERVER, db, """
        SELECT CAST(ConditionalExecution AS NVARCHAR(MAX)) AS ce
        FROM acqua.TreeItems
        WHERE DATALENGTH(CAST(ConditionalExecution AS NVARCHAR(MAX))) > 20""")
    if not rows:
        print("   沒有任何條件式")
        return set(), set(), set(), collections.Counter()

    rels, acts, matches = collections.Counter(), collections.Counter(), collections.Counter()
    prefixes = collections.Counter()
    for r in rows:
        ce = str(r["ce"] or "")
        a = RE_ACT.search(ce)
        m = RE_MATCH.search(ce)
        if a:
            acts[a.group(1).strip()] += 1
        if m:
            matches[m.group(1).strip()] += 1
        for c in RE_COND.findall(ce):
            v, rel = RE_VAR.search(c), RE_REL.search(c)
            if not (v and rel):
                continue
            name = v.group(1).strip()
            if not name:
                continue
            rels[rel.group(1).strip()] += 1
            prefixes[name.split("_")[0] + "_" if "_" in name else name] += 1

    print("   %d 筆條件式" % len(rows))
    print("      Relation      %s" % dict(rels))
    print("      Action        %s" % dict(acts))
    print("      Match         %s" % dict(matches))
    return set(rels), set(acts), set(matches), prefixes


# ══════════════════════════════════════════════════════════
# F/G. 我們的規則涵蓋得到嗎
# ══════════════════════════════════════════════════════════
def survey_rules(db, prefixes):
    """測項分類的涵蓋率。

    分類是兩層的(見 backend_com._classifier):
        manual  標題在設定裡 = 已確認會開視窗,自動勾選排除
        script  SMDType 是腳本型別 = 可能會開,只提醒
    這裡找的是「看起來很像互動、卻兩層都沒抓到」的漏網之魚。
    """
    import fnmatch
    m = CFG.get("manual_items") or {}
    titles = {str(x).strip() for x in (m.get("titles") or [])}
    pats = [str(x) for x in (m.get("title_patterns") or [])]
    script_types = {int(x) for x in (m.get("script_smd_types") or [])}

    rows = raw_query(SERVER, db, """
        SELECT t.Title, s.SMDType FROM acqua.TreeItems t
        JOIN acqua.TItemTypes it ON it.idItemType=t.rItemType
        LEFT JOIN acqua.SMDs s ON s.idSMDItem = t.idTreeItem
        WHERE it.name='IType_SMD'""")

    # Info: 類測項會開 PDF 檢視器(TfrmDocViewer),但 winwatch 的規則會
    # 自動關掉它,不需要人 —— 所以不算「漏網的互動項」。
    auto_closed = tuple(
        str(r.get("title", "")).strip("*")
        for r in (CFG.get("blocking_windows") or [])
        if r.get("action") == "close")
    n_manual = n_script = n_auto = 0
    uncovered = set()
    SUSPECT = ("wizard", "dialog", "prompt", "please ", "manual",
               "user input", "select ", "choose ", "setup ")
    for r in rows:
        title = str(r["Title"] or "").strip()
        stype = int(r["SMDType"]) if r["SMDType"] is not None else -1
        if title in titles or any(fnmatch.fnmatch(title, p) for p in pats):
            n_manual += 1
        elif stype in script_types:
            n_script += 1
        elif title.startswith("Info:"):
            n_auto += 1                 # 開文件檢視器,winwatch 自動關
        elif any(k in title.lower() for k in SUSPECT):
            uncovered.add(title)

    print("   測項分類:需人工 %d ・ 腳本 %d ・ 文件類(自動關)%d"
          % (n_manual, n_script, n_auto))
    if uncovered:
        note("?", "看起來像互動、型別卻不是腳本、也不在清單裡:%s"
             % "、".join(sorted(uncovered)[:3]))

    if prefixes:
        # 前綴不再是篩選條件(改看關係運算子,見 wizard.scan_variables),
        # 這裡只回報有哪些命名空間,當作認識資料用。
        print("   條件式變數的命名空間:%s"
              % "、".join(sorted(prefixes)[:10]))


# ══════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="只掃這一個資料庫")
    args = ap.parse_args()

    usable = survey_databases(args.db)
    all_rels, all_acts, all_match = set(), set(), set()
    all_pref = collections.Counter()

    for db in usable:
        hr("資料庫:%s" % db)
        print("\n   B. 專案")
        projects = survey_projects(db)
        print("\n   C. 樹狀結構(path + title 唯一性)")
        survey_tree(db, projects)
        print("\n   D. SMDType")
        survey_smdtypes(db)
        print("\n   E. 條件式")
        rels, acts, match, pref = survey_conditions(db)
        all_rels |= rels
        all_acts |= acts
        all_match |= match
        all_pref.update(pref)
        print("\n   F/G. 我們的規則")
        survey_rules(db, pref)

    hr("跨資料庫總結")
    from acqua.condeval import REL_EQ, REL_NE, REL_IS_FALSE, REL_IS_TRUE
    known_rel = {REL_EQ, REL_NE, REL_IS_FALSE, REL_IS_TRUE, "2", "3", "4", "5"}
    unknown = sorted(all_rels - known_rel)
    print("   Relation 出現過:%s" % sorted(all_rels))
    if unknown:
        note("!", "沒實作的 Relation:%s" % unknown)
    else:
        print("      全部都有實作")
    print("   Action 出現過:%s   Match 出現過:%s"
          % (sorted(all_acts), sorted(all_match)))
    if all_acts - {"0", "1"}:
        note("!", "沒看過的 Action:%s" % sorted(all_acts - {"0", "1"}))
    if all_match - {"0", "1"}:
        note("!", "沒看過的 MatchConditions:%s" % sorted(all_match - {"0", "1"}))

    hr("結論")
    bad = [m for s, m in findings if s == "!"]
    warn = sorted(set(m for s, m in findings if s == "?"))
    print("   程式缺陷:%d 項 ・ 環境待處理:%d 項" % (len(bad), len(warn)))
    if bad:
        print("\n   ── 程式要改 ──")
        for m in bad:
            print("      !! %s" % m)
    if warn:
        print("\n   ── 環境要處理(程式只能講清楚)──")
        for m in warn:
            print("      ?? %s" % m)
    if not bad:
        print("\n   ✅ 沒有程式缺陷")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
