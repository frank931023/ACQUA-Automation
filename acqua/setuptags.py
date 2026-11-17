# -*- coding: utf-8 -*-
"""測項的擺位標籤 —— 讀取、分組、比對。

計畫書:acqua_scripts/SETUP_AUTOMATION_PLAN.md

規則(計畫書 5.0.4 定案)
────────────────────────
    1. 有 Setup 標籤,名稱找得到對應擺位   -> 移動過去
    2. 有 Setup 標籤,名稱找不到           -> 不移動,記一筆,繼續跑
    3. 沒有 Setup 標籤                     -> 沿用當下擺位

ACQUA 既有的 Room / DUTType / Position / TurningDevices / HHPSettingName
**全部原封不動**,不讀取、不推論、不參與擺位判斷。

為什麼不自己推論
────────────────
實測(計畫書 5.0.2):`Room=AR` 底下有 6 種不同的轉盤角度、`Room=RR` 有 7 種。
語意標籤描述的是**測試條件**,不是**物理擺位** —— 同一個房間同一種裝置,
機構可以擺成好幾種樣子。推論一定會錯,而且是靜默地錯。
"""
from __future__ import annotations

import re

#: 擺位標籤的名稱。只看這一個。
SETUP_TAG = "Setup"

_TAG_RE = re.compile(r'<UserDefinedProperty name="([^"]+)">([^<]*)<')


def tags_of(advanced_description) -> dict:
    """把 AdvancedDescription 的自訂屬性拆成 dict。"""
    return dict(_TAG_RE.findall(str(advanced_description or "")))


def read_setup_tags(server, database, row_ids, raw_query) -> dict:
    """回 {row_id: 擺位名稱}。沒標的不會出現在結果裡。

    `raw_query` 由呼叫端傳進來,這個模組不自己決定怎麼連資料庫 ——
    方便測試,也避免跟 sqlcat 互相 import。
    """
    ids = [int(r) for r in row_ids if str(r).strip().lstrip("-").isdigit()]
    if not ids:
        return {}

    out = {}
    # id 清單可能上千筆,分批查 —— SQL Server 的 IN 有長度上限
    for i in range(0, len(ids), 500):
        chunk = ",".join(str(x) for x in ids[i:i + 500])
        rows = raw_query(server, database, """
            select idTreeItem, cast(AdvancedDescription as nvarchar(max)) as ad
            from acqua.TreeItems
            where idTreeItem in (%s)""" % chunk)
        for r in rows:
            name = (tags_of(r["ad"]).get(SETUP_TAG) or "").strip()
            if name:
                out[int(r["idTreeItem"])] = name
    return out


def plan_for(row_ids, setup_by_row, known_names) -> dict:
    """算出這一批的擺位計畫。**不改變順序** —— 分組是之後的事。

    回:
        steps     [{row_id, wanted, resolved, change}]  每筆要不要移動
        switches  會切換幾次
        used      用到哪些擺位(有對應的)
        unknown   名稱找不到對應的 {名稱: [row_id, ...]}
    """
    known = {str(n).strip() for n in known_names if str(n).strip()}
    steps, used, unknown = [], [], {}
    current = None
    for r in row_ids:
        wanted = setup_by_row.get(int(r))
        resolved = None
        if wanted:
            if wanted in known:
                resolved = wanted
            else:
                unknown.setdefault(wanted, []).append(int(r))
        change = bool(resolved and resolved != current)
        if change:
            current = resolved
            used.append(resolved)
        steps.append({"row_id": int(r), "wanted": wanted,
                      "resolved": resolved, "change": change})
    return {"steps": steps, "switches": len(used),
            "used": sorted(set(used)), "unknown": unknown}


def reorder_if_better(row_ids, setup_by_row, mmd_by_row, known_names):
    """照擺位重排,**但只在真的比較好的時候才用**。

    為什麼需要這道保險:分組是以 MMD 群組為單位,而群組的擺位取「裡面
    第一個有標籤的」。群組本身混了兩個擺位時(實測約 6%),不管把它排到
    哪裡,群組內部還是要切換 —— 重排反而可能比原順序多切幾次。

    單元測試實際踩到:[10,11,12,20,21,30,31] 重排後從 3 次變 4 次。

    所以兩種順序都算一次,誰少用誰。相同就維持原順序 ——
    原順序是人安排的,沒有好處就不要動它。
    """
    before = plan_for(row_ids, setup_by_row, known_names)
    grouped = group_by_setup(row_ids, setup_by_row, mmd_by_row)
    after = plan_for(grouped, setup_by_row, known_names)
    if after["switches"] < before["switches"]:
        return grouped, after, before["switches"]
    return list(row_ids), before, before["switches"]


def group_by_setup(row_ids, setup_by_row, mmd_by_row) -> list:
    """照擺位重排,但**不拆散 MMD 群組**。

    為什麼不能拆:同一個群組裡常常是「錄音 -> 分析」,分析要讀錄音的
    結果。拆開跑會讓分析找不到東西。

    做法:以 MMD 群組為單位排序。一個群組的擺位 = 它裡面第一個有標籤的。
    群組內原本的順序完全保留。
    """
    order, members = [], {}
    for r in row_ids:
        key = mmd_by_row.get(int(r), ("__loose__", int(r)))
        if key not in members:
            members[key] = []
            order.append(key)
        members[key].append(int(r))

    def setup_of(key):
        for r in members[key]:
            s = setup_by_row.get(r)
            if s:
                return s
        return ""                    # 沒標 -> 排在最前面,沿用當下

    # sorted 是穩定的:同一個擺位的群組會保持原本的先後
    return [r for key in sorted(order, key=setup_of) for r in members[key]]
