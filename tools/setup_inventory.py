# -*- coding: utf-8 -*-
"""擺位盤點 —— 這批測項需要哪些擺位、會切換幾次、哪裡有問題。**唯讀。**

這是 SETUP_AUTOMATION_PLAN.md 第 1 階段的工具。

它回答什麼
──────────
1. 已經標了 `Setup` 的測項,名稱對得上實際擺位嗎(對不上給模糊建議)
2. 照樹的順序跑,擺位要切換幾次
3. 哪些 MMD 群組裡標了兩個以上不同的擺位(分組時會被拆到)
4. **還沒標籤時最有用的**:根據既有語意標籤,建議哪些測項是轉折點、該標

為什麼要有第 4 項
─────────────────
`Setup` 標籤要人工一個一個下。但哪些測項該下?2302 個測項不可能一個個看。

既有的 `Room` / `DUTType` / `Position` 標籤雖然**不足以決定擺位**
(實測:`Room=AR` 底下有 6 種轉盤角度,見計畫書 5.0.2),
但拿來**圈出「這裡換場景了」的位置**綽綽有餘 —— 把 2302 個縮到 41 個候選。

人看那 41 個,決定要標什麼名字。這是建議,不是自動化。

讀取規則(計畫書 5.0.4 定案)
────────────────────────────
    1. 有 Setup 標籤,名稱找得到對應擺位   -> 用它
    2. 有 Setup 標籤,名稱找不到           -> 記一筆,但不中斷
    3. 沒有 Setup 標籤                     -> 沿用當下擺位

ACQUA 既有的標籤**全部原封不動**,只拿來做第 4 項的建議。

用法
────
    python tools/setup_inventory.py --project ZoomRooms_v2020Oct_v1
    python tools/setup_inventory.py --db 51_MS_Teams_Rev05_SP2 --project "...Speakerphone"
    python tools/setup_inventory.py --plan 20260821-163928-c34d
    python tools/setup_inventory.py --project ... --suggest    # 列出 41 個轉折點
    python tools/setup_inventory.py --project ... --json
"""
from __future__ import annotations

import argparse
import difflib
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from acqua import env                                      # noqa: E402
from acqua.sqlcat import raw_query                         # noqa: E402

#: 擺位標籤的名稱。計畫書 5.0 定案:只看這一個。
SETUP_TAG = "Setup"

#: 既有的語意標籤 —— **只拿來建議轉折點**,不參與擺位判斷。
#: 它們描述的是測試條件(哪個房間、什麼裝置),不是物理擺位。
HINT_TAGS = ("Room", "DUTType", "Position", "snd_distance", "rcv_distance")

TAG_RE = re.compile(r'<UserDefinedProperty name="([^"]+)">([^<]*)<')


def tags_of(advanced_description) -> dict:
    """把 AdvancedDescription 裡的自訂屬性拆成 dict。"""
    return dict(TAG_RE.findall(str(advanced_description or "")))


def saved_setups() -> list:
    """網頁上存好的擺位。直接讀檔,不需要服務在跑。"""
    folder = os.path.join(ROOT, "setups")
    out = []
    if not os.path.isdir(folder):
        return out
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):          # .gitkeep 之類的跳過
            continue
        try:
            d = json.load(io.open(os.path.join(folder, name), encoding="utf-8"))
        except Exception:                                   # noqa: BLE001
            continue
        out.append({"id": d.get("id") or name[:-5],
                    "name": (d.get("name") or "").strip(),
                    "axes": len(d.get("axes") or {})})
    return out


def load_tree(server, database, project_title):
    """讀出一個專案的整棵樹(測項 + 群組),照樹的順序。

    `raw_query` 不接受參數化查詢,所以標題要自己跳脫。
    只讀不寫,而且單引號加倍是 T-SQL 的標準跳脫 —— 專案名稱裡真的有
    單引號時也不會出事。
    """
    safe = str(project_title).replace("'", "''")
    return raw_query(server, database, """
        select t.idTreeItem, t.Title, t.LeftNode, t.RightNode, t.rItemType,
               p.Title as proj,
               cast(t.AdvancedDescription as nvarchar(max)) as ad
        from acqua.TreeItems t
        join acqua.Projects p on p.idProject = t.rProject
        where p.Title = '%s'
        order by t.LeftNode""" % safe)


def nearest_mmd(smds, mmds):
    """每個測項的最近 MMD 祖先。回 {測項 id: MMD 列}。"""
    by_item = {}
    ordered = sorted(mmds, key=lambda m: -m["LeftNode"])     # 由內而外
    for s in smds:
        for m in ordered:
            if m["LeftNode"] < s["LeftNode"] < m["RightNode"]:
                by_item[s["idTreeItem"]] = m
                break
    return by_item


def analyse(rows, setups, only_rows=None):
    """核心分析。only_rows 給定時只看那些 row_id（計畫模式)。"""
    smds = [r for r in rows if r["rItemType"] == 1]
    mmds = [r for r in rows if r["rItemType"] == 2]
    if only_rows is not None:
        want = set(only_rows)
        smds = [s for s in smds if s["idTreeItem"] in want]

    names = {s["name"] for s in setups if s["name"]}
    owner = nearest_mmd(smds, mmds)

    seq, unmatched, tagged = [], [], 0
    current = None
    for s in smds:
        t = tags_of(s["ad"])
        want = (t.get(SETUP_TAG) or "").strip()
        if want:
            tagged += 1
            if want in names:
                current = want
            else:
                unmatched.append({
                    "row_id": s["idTreeItem"], "title": s["Title"],
                    "wanted": want,
                    "suggestion": (difflib.get_close_matches(
                        want, sorted(names), n=1, cutoff=0.6) or [None])[0],
                })
                # 找不到 -> 不移動,沿用當下(計畫書 5.0.4 規則 2)
        seq.append({"row_id": s["idTreeItem"], "title": s["Title"],
                    "setup": current, "declared": want or None,
                    "mmd": (owner.get(s["idTreeItem"]) or {}).get("Title"),
                    "hints": {k: v for k, v in t.items() if k in HINT_TAGS}})

    switches = sum(1 for a, b in zip(seq, seq[1:])
                   if a["setup"] != b["setup"])
    used = Counter(x["setup"] for x in seq if x["setup"])

    # 同一個 MMD 裡宣告了兩個以上不同擺位 -> 分組時會被拆到
    per_mmd = defaultdict(set)
    for x in seq:
        if x["declared"] and x["mmd"]:
            per_mmd[x["mmd"]].add(x["declared"])
    mixed = {k: sorted(v) for k, v in per_mmd.items() if len(v) > 1}

    return {"total": len(smds), "tagged": tagged, "untagged": len(smds) - tagged,
            "switches": switches, "used": used, "unmatched": unmatched,
            "mixed_mmds": mixed, "sequence": seq}


def suggest_points(seq):
    """用語意標籤圈出「這裡換場景了」的位置 —— 標籤的候選清單。"""
    out, prev = [], None
    for x in seq:
        sig = tuple(sorted(x["hints"].items()))
        if not sig:
            continue                         # 沒語意標籤 = 輔助項,沿用
        if sig != prev:
            out.append({"row_id": x["row_id"], "title": x["title"],
                        "hints": x["hints"], "mmd": x["mmd"],
                        "declared": x["declared"]})
            prev = sig
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="資料庫(省略時用 config 的設定)")
    ap.add_argument("--project", help="專案標題")
    ap.add_argument("--plan", help="計畫 id（只看這個計畫的測項)")
    ap.add_argument("--suggest", action="store_true", help="列出建議的轉折點")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    cfg = json.load(io.open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
    env.apply_to(cfg, os.path.join(ROOT, ".env"))
    server = cfg["database"]["server"]

    db, project, only_rows = args.db, args.project, None
    if args.plan:
        p = json.load(io.open(os.path.join(ROOT, "plans", args.plan + ".json"),
                              encoding="utf-8"))
        db = db or p.get("database")
        project = project or p.get("project")
        only_rows = [i["row_id"] for i in (p.get("items") or [])]
    db = db or cfg["database"]["name"]
    if not project:
        ap.error("要給 --project 或 --plan")

    setups = saved_setups()
    rows = load_tree(server, db, project)
    if not rows:
        print("找不到專案「%s」(資料庫 %s)" % (project, db))
        return 1
    r = analyse(rows, setups, only_rows)

    if args.json:
        r["sequence"] = r["sequence"] if args.suggest else []
        r["used"] = dict(r["used"])
        r["suggestions"] = suggest_points(r["sequence"]) if args.suggest else []
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0

    print("資料庫 %s" % db)
    print("專案   %s%s" % (project, ("  （計畫 %s)" % args.plan) if args.plan else ""))
    print("測項   %d 個  （已標 %d ・ 未標 %d)"
          % (r["total"], r["tagged"], r["untagged"]))
    print()

    print("存好的擺位 %d 個:" % len(setups))
    for s in setups:
        print("   %-24s %d 軸" % (s["name"] or "(未命名)", s["axes"]))
    print()

    if r["used"]:
        print("這批會用到的擺位:")
        for name, n in r["used"].most_common():
            print("   %-24s %4d 個測項" % (name, n))
        print("照樹的順序跑,會切換 %d 次" % r["switches"])
    else:
        print("⚠️ 這批**沒有任何測項標了 %s**。" % SETUP_TAG)
        print("   擺位不會自動切換 —— 全程沿用當下位置。")
        print("   先用 --suggest 看哪些測項該標。")
    print()

    if r["unmatched"]:
        print("❌ %d 個測項的擺位名稱找不到對應(不會移動,但會繼續跑):"
              % len(r["unmatched"]))
        for u in r["unmatched"][:12]:
            tip = ("  → 最接近:「%s」" % u["suggestion"]) if u["suggestion"] \
                else "  → 沒有相近的名稱"
            print("   #%-6s 「%s」%s" % (u["row_id"], u["wanted"], tip))
            print("          %s" % str(u["title"])[:66])
        if len(r["unmatched"]) > 12:
            print("   ...另外 %d 個" % (len(r["unmatched"]) - 12))
        print()

    if r["mixed_mmds"]:
        print("⚠️ %d 個測項群組裡標了兩個以上不同的擺位:" % len(r["mixed_mmds"]))
        print("   (照擺位分組時這些會被拆開 —— 注意錄音→分析的相依)")
        for mmd, vals in list(r["mixed_mmds"].items())[:8]:
            print("   %-46s %s" % (str(mmd)[:46], " / ".join(vals)))
        print()

    if args.suggest:
        pts = suggest_points(r["sequence"])
        print("建議的轉折點 %d 個 —— 這些是「場景換了」的位置,值得標 %s:"
              % (len(pts), SETUP_TAG))
        print("(依據既有語意標籤。**這是建議不是答案** —— 語意標籤不足以")
        print(" 決定擺位,要人看過才知道該標什麼名字)")
        print()
        for p in pts:
            hint = " ".join("%s=%s" % kv for kv in sorted(p["hints"].items()))
            mark = ("  [已標 %s]" % p["declared"]) if p["declared"] else ""
            print("   #%-6s %-50s %s%s"
                  % (p["row_id"], str(p["title"])[:50], hint[:30], mark))
    else:
        print("用 --suggest 列出建議該標籤的測項。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
