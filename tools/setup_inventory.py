# -*- coding: utf-8 -*-
"""擺位盤點 —— 一個專案(或一個計畫)的 Setup 標籤狀況。**唯讀。**

適用任何 ACQUA 資料庫、任何專案。判斷規則跟執行時完全同一份
(acqua/setuptags.py),所以這裡看到的就是跑起來會發生的。

它回答什麼
──────────
1. 幾筆自己標、幾筆從資料夾繼承、幾筆沒有
2. 哪些名稱對不上存好的擺位(附最接近的名稱)
3. 哪些測項判斷不出來(所在資料夾裡標了不只一種擺位)
4. 照樹的順序跑會切換幾次
5. --suggest:還沒標的專案,哪些測項是「場景換了」的轉折點,值得標

第 5 項怎麼來的
───────────────
既有的語意標籤(Room / DUTType / Position ...)不足以**決定**擺位 ——
實測同一個 Room 底下有 6~7 種轉盤角度(計畫書 5.0.2)。但拿來圈出
「這裡換場景了」的位置很夠用:實測把 2302 筆縮到 41 個候選。
這是給人看的建議,不參與執行時的判斷。

用法
────
    python tools/setup_inventory.py --project "專案標題"
    python tools/setup_inventory.py --project-id 6 --db 某資料庫
    python tools/setup_inventory.py --plan 20260821-163928-c34d
    python tools/setup_inventory.py --project "..." --suggest
    python tools/setup_inventory.py --project "..." --json

同一個資料庫裡可能有同名的專案 —— 用標題找到不只一個時會列出來,
請改用 --project-id。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

from acqua import env, setuptags                           # noqa: E402
from acqua.context import parse_ctx                        # noqa: E402
from acqua.roomsetups import RoomSetups                    # noqa: E402
from acqua.sqlcat import raw_query                         # noqa: E402

#: 拿來建議轉折點的既有標籤。**只用在 --suggest**,不參與擺位判斷。
HINT_TAGS = ("Room", "DUTType", "Position", "snd_distance", "rcv_distance")


def projects_titled(server, database, title) -> list:
    """標題完全相符的專案。raw_query 不收參數,單引號加倍跳脫。"""
    safe = str(title).replace("'", "''")
    return raw_query(server, database,
                     "select idProject, Title from acqua.Projects "
                     "where Title = '%s' order by idProject" % safe)


def target_of(args, cfg):
    """(server, database, idProject, 只看哪些 row_id 或 None, 說明)。"""
    server, database = cfg["database"]["server"], args.db or cfg["database"]["name"]
    if args.plan:
        with io.open(os.path.join(ROOT, "plans", args.plan + ".json"),
                     encoding="utf-8") as f:
            plan = json.load(f)
        s, d, pid = parse_ctx((plan.get("source") or {}).get("ctx"))
        if pid is None:
            sys.exit("計畫 %s 沒有記專案(舊格式),請改用 --project" % args.plan)
        rows = [int(i["row_id"]) for i in plan.get("items") or []]
        return s or server, d or database, pid, rows, "計畫 %s" % args.plan
    if args.project_id is not None:
        return server, database, args.project_id, None, "專案 #%d" % args.project_id
    if not args.project:
        sys.exit("要給 --project、--project-id 或 --plan")
    hits = projects_titled(server, database, args.project)
    if not hits:
        sys.exit("資料庫 %s 裡找不到專案「%s」" % (database, args.project))
    if len(hits) > 1:
        sys.exit("「%s」有 %d 個同名專案,請用 --project-id 指定:\n%s"
                 % (args.project, len(hits),
                    "\n".join("   %d" % h["idProject"] for h in hits)))
    return server, database, hits[0]["idProject"], None, args.project


def turning_points(tree, resolved, only=None) -> list:
    """依既有語意標籤,「場景換了」的測項 —— 值得標 Setup 的候選。"""
    out, prev = [], None
    for r in tree:
        rid = int(r["idTreeItem"])
        if int(r["rItemType"]) != 1 or (only is not None and rid not in only):
            continue
        hints = {k: v for k, v in setuptags.tags_of(r["ad"]).items()
                 if k in HINT_TAGS}
        sig = tuple(sorted(hints.items()))
        if sig and sig != prev:            # 沒語意標籤 = 輔助項,不算轉折
            out.append({"row_id": rid, "title": r["Title"], "hints": hints,
                        "setup": resolved[rid]["setup"],
                        "source": resolved[rid]["source"]})
            prev = sig
    return out


def print_report(where, database, report, names, points):
    print("資料庫 %s ・ %s" % (database, where))
    print("測項   %d 筆:自己標 %d ・ 從資料夾繼承 %d ・ 沒有 %d ・ 判斷不出來 %d"
          % (report["total"], report["own"], report["inherited"],
             report["untagged"], len(report["ambiguous"])))
    print("擺位   存好的:%s" % ("、".join(sorted(names)) or "(沒有)"))
    if report["used"]:
        print("       會用到:%s ・ 照樹的順序切換 %d 次"
              % ("、".join(report["used"]), report["switches"]))
    else:
        print("       ⚠️ 沒有任何測項有擺位 —— 全程沿用當下位置。用 --suggest 看哪些該標")
    print()

    for u in report["unknown"]:
        tip = ("最接近「%s」" % u["suggestion"]) if u["suggestion"] else "沒有相近的名稱"
        print("❌ 「%s」不是存好的擺位(%d 筆,不會移動、照常量)—— %s"
              % (u["name"], len(u["rows"]), tip))
    for a in report["ambiguous"][:12]:
        print("⚠️ #%-6s 資料夾「%s」裡有 %s —— 請在這一筆自己標"
              % (a["row_id"], a["folder"], " / ".join(a["choices"])))
    if len(report["ambiguous"]) > 12:
        print("   ...另外 %d 筆" % (len(report["ambiguous"]) - 12))

    if points is not None:
        print("\n建議的轉折點 %d 個(依既有語意標籤,**是建議不是答案**):" % len(points))
        for p in points:
            hint = " ".join("%s=%s" % kv for kv in sorted(p["hints"].items()))
            mark = ("  [%s:%s]" % ("已標" if p["source"] == setuptags.OWN else "繼承",
                                   p["setup"])) if p["setup"] else ""
            print("   #%-6s %-50s %s%s" % (p["row_id"], str(p["title"])[:50],
                                         hint[:30], mark))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", help="資料庫(省略時用 config 的設定)")
    ap.add_argument("--project", help="專案標題")
    ap.add_argument("--project-id", type=int, help="專案 idProject(有同名專案時用)")
    ap.add_argument("--plan", help="計畫 id(只看這個計畫的測項,資料庫與專案取自計畫)")
    ap.add_argument("--suggest", action="store_true", help="列出建議的轉折點")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    with io.open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    env.apply_to(cfg, os.path.join(ROOT, ".env"))

    server, database, pid, only, where = target_of(args, cfg)
    tree = setuptags.load_tree(server, database, pid, raw_query)
    if not tree:
        sys.exit("專案 #%d 在資料庫 %s 裡沒有任何測項" % (pid, database))
    resolved = setuptags.resolve(tree)
    row_ids = only if only is not None else \
        [int(r["idTreeItem"]) for r in tree if int(r["rItemType"]) == 1]
    names = RoomSetups(ROOT).names()
    report = setuptags.check(row_ids, resolved, names)
    points = turning_points(tree, resolved, set(only) if only else None) \
        if args.suggest else None

    if args.json:
        print(json.dumps(dict(report, database=database, project_id=pid,
                              suggestions=points or []),
                         ensure_ascii=False, indent=2))
    else:
        print_report(where, database, report, names, points)
    return 0


if __name__ == "__main__":
    sys.exit(main())
