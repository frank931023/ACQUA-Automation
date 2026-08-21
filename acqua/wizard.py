# -*- coding: utf-8 -*-
"""從專案樹反推「精靈」該長什麼樣子。

為什麼要反推
────────────
ACQUA 的 DUT & Measurement Wizard 是 Tcl/Tk 寫的,選項內容讀不到 ——
但那些選項最後都會變成變數,而**每個變數的可能值都寫在
`TreeItems.ConditionalExecution` 的條件式裡**。

    <Condition>
      <Variable>DUT_speakerphone_type</Variable>
      <Relation>0</Relation>          ← 0 = 等於
      <Value>Shared</Value>
    </Condition>

把全專案的條件式掃一遍,就能得出:
    DUT_speakerphone_type 有 Personal / Shared 兩種值,影響 N 個測項
    DUT_speaker_range_1.5m 是布林(Relation 7 = 為真),影響 M 個測項

這樣網頁上就能自己生出等效的精靈,不必去點 ACQUA 那個視窗。

⚠️ 這是**從資料反推**,不是 ACQUA 官方定義。變數如果從來沒被任何條件式
   用過,這裡就看不到它 —— 但那種變數本來也不影響要跑哪些測項。
"""
from __future__ import annotations

from collections import defaultdict

from .condeval import parse, REL_EQ, REL_NE, REL_IS_TRUE, REL_IS_FALSE

# 這些前綴的變數才會端到精靈上 —— 其餘多半是 ACQUA 內部或量測產生的
# BGN* 是 BGN Wizard 的變數 —— 那個精靈也在我們要取代的名單裡
DEFAULT_PREFIXES = ("DUT_", "HRT_", "HRR_", "HHP_", "TEST_", "BGN")


def scan_variables(tree_rows, prefixes=DEFAULT_PREFIXES):
    """掃出專案裡所有被條件式用到的變數。

    回傳 [{
        "name":     變數名
        "kind":     "choice"(有列舉值)/ "bool"(為真/為假)/ "number"
        "values":   ["Personal", "Shared"]     kind == choice 才有
        "used_by":  被幾個節點的條件式引用
        "relations": [0, 1, ...]               出現過哪些關係運算子
    }]
    依「影響幾個測項」由多到少排序 —— 影響最大的擺前面,人比較好選。
    """
    vals = defaultdict(set)
    rels = defaultdict(set)
    used = defaultdict(int)

    for r in tree_rows:
        xml = r.get("ConditionalExecution") or ""
        spec = parse(str(xml)) if xml else None
        if not spec:
            continue
        for c in spec["conditions"]:
            name = (c.get("var") or "").strip()
            if not name:
                continue
            used[name] += 1
            rels[name].add(c.get("rel"))
            v = (c.get("val") or "").strip()
            if v:
                vals[name].add(v)

    out = []
    for name, n in used.items():
        if prefixes and not name.startswith(tuple(prefixes)):
            continue
        rset = rels[name]
        vset = sorted(vals[name])
        if vset and (REL_EQ in rset or REL_NE in rset):
            kind = "choice"
        elif REL_IS_TRUE in rset or REL_IS_FALSE in rset:
            kind = "bool"
        else:
            kind = "number"
        out.append({
            "name": name,
            "kind": kind,
            "values": vset if kind == "choice" else [],
            "used_by": n,
            "relations": sorted(rset),
        })
    out.sort(key=lambda x: (-x["used_by"], x["name"]))
    return out


def group_variables(items):
    """把變數分成幾組,讓精靈畫面有結構,不是一長串。

    分組規則是從命名看出來的(DUT_speaker_range_1.5m、DUT_pickup_range_2.3m …),
    沒有官方定義,純粹為了好讀。
    """
    groups = [
        ("量測範圍", lambda n: n in ("DUT_speakerphone_type",)),
        ("連接方式", lambda n: "connection" in n),
        ("收音距離", lambda n: "pickup_range" in n),
        ("播放距離", lambda n: "speaker_range" in n),
        ("DUT 特性", lambda n: n.startswith("DUT_")),
        ("背景噪音 BGN", lambda n: n.startswith("BGN")),
        ("可用硬體", lambda n: n.startswith(("HRT_", "HRR_", "HHP_"))),
    ]
    out, taken = [], set()
    for title, pred in groups:
        picked = [x for x in items if x["name"] not in taken and pred(x["name"])]
        for x in picked:
            taken.add(x["name"])
        if picked:
            out.append({"title": title, "items": picked})
    rest = [x for x in items if x["name"] not in taken]
    if rest:
        out.append({"title": "其他", "items": rest})
    return out
