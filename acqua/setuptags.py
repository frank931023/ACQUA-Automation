# -*- coding: utf-8 -*-
"""測項的擺位標籤 —— 讀取、繼承、分組、比對。

計畫書:acqua_scripts/SETUP_AUTOMATION_PLAN.md

規則(計畫書 5.0.4 定案,2026-11-17 加上資料夾繼承)
────────────────────────────────────────────────
    1. 測項自己有 Setup                     -> 用自己的
    2. 沒有 -> 看**同一個資料夾**的其他測項:
          只出現一種擺位                    -> 用它
          出現兩種以上                      -> 不猜,記一筆
          一個都沒有                        -> 再往上一層資料夾,同樣規則
    3. 一路到專案根部都沒有                 -> 沿用當下擺位

    名稱找不到對應的擺位                    -> 不移動,記一筆,繼續跑

為什麼繼承是看「同資料夾的其他測項」而不是看資料夾本身
──────────────────────────────────────────────────
ACQUA 介面**不能對資料夾加標籤**(使用者實測)。資料庫裡也證實了:
SP2 標了 1858 個測項,資料夾一個都沒有。所以只能讓資料夾裡標了的那幾筆
代表這個資料夾 —— 實際效果是每個資料夾標一筆就夠。

為什麼不是「沿用上一筆」(照順序往前找)
──────────────────────────────────────
順序一變,結果就安靜地跟著變 —— 有人在 ACQUA 裡拖動測項,擺位就換了,
沒有任何跡象。用資料夾判斷只跟「在哪個資料夾」有關,跟順序無關。

ACQUA 既有的 Room / DUTType / Position / TurningDevices / HHPSettingName
**全部原封不動**,不讀取、不推論、不參與擺位判斷。

為什麼不自己推論
────────────────
實測(計畫書 5.0.2):`Room=AR` 底下有 6 種不同的轉盤角度、`Room=RR` 有 7 種。
語意標籤描述的是**測試條件**,不是**物理擺位** —— 同一個房間同一種裝置,
機構可以擺成好幾種樣子。推論一定會錯,而且是靜默地錯。
"""
from __future__ import annotations

import difflib
import re

#: 擺位標籤的名稱。只看這一個。
SETUP_TAG = "Setup"

_TAG_RE = re.compile(r'<UserDefinedProperty name="([^"]+)">([^<]*)<')

#: 每一筆的擺位是從哪來的。
OWN, FOLDER, AMBIGUOUS, NONE = "own", "folder", "ambiguous", "none"


def tags_of(advanced_description) -> dict:
    """把 AdvancedDescription 的自訂屬性拆成 dict。"""
    return dict(_TAG_RE.findall(str(advanced_description or "")))


def setup_of(advanced_description) -> str:
    """這一筆自己標的擺位名稱。沒標回空字串。"""
    return (tags_of(advanced_description).get(SETUP_TAG) or "").strip()


def load_tree(server, database, project_id, raw_query) -> list:
    """一個專案的整棵樹(測項 + 資料夾),照樹的順序。

    繼承要看兄弟與祖先,所以一定要整棵讀 —— 只讀那幾筆是算不出來的。
    一個專案最多幾千列,一次查完比逐層查快得多。

    `raw_query` 由呼叫端傳進來:方便測試,也避免跟 sqlcat 互相 import。
    """
    return raw_query(server, database, """
        select idTreeItem, rItemType, Title, LeftNode, RightNode,
               cast(AdvancedDescription as nvarchar(max)) as ad
        from acqua.TreeItems
        where rProject = %d
        order by LeftNode""" % int(project_id))


def resolve(tree) -> dict:
    """每一筆測項最終要用哪個擺位。回 {row_id: {...}}:

        setup    擺位名稱;判斷不出來是 None
        source   OWN / FOLDER / AMBIGUOUS / NONE
        folder   繼承自哪個資料夾(source 是 FOLDER 或 AMBIGUOUS 時)
        choices  同一個資料夾裡出現的擺位(AMBIGUOUS 時看得到是哪幾個)

    `tree` 是 load_tree() 的結果,或任何有 idTreeItem / rItemType /
    LeftNode / RightNode / Title / ad 的列。rItemType 1 = 測項、2 = 資料夾。
    """
    rows = sorted(tree, key=lambda r: r["LeftNode"])

    # 每個資料夾「直接」裝的測項標了哪些擺位
    direct, parent, stack = {}, {}, []
    for r in rows:
        while stack and stack[-1]["RightNode"] < r["LeftNode"]:
            stack.pop()
        rid = int(r["idTreeItem"])
        parent[rid] = int(stack[-1]["idTreeItem"]) if stack else None
        if int(r["rItemType"]) == 2:
            direct.setdefault(rid, set())
            stack.append(r)
        elif parent[rid] is not None:
            name = setup_of(r["ad"])
            if name:
                direct.setdefault(parent[rid], set()).add(name)

    title = {int(r["idTreeItem"]): r["Title"] for r in rows}
    out = {}
    for r in rows:
        if int(r["rItemType"]) != 1:
            continue
        rid = int(r["idTreeItem"])
        own = setup_of(r["ad"])
        if own:
            out[rid] = {"setup": own, "source": OWN}
            continue

        res = {"setup": None, "source": NONE}
        folder = parent.get(rid)
        while folder is not None:
            seen = direct.get(folder) or set()
            if len(seen) == 1:
                res = {"setup": next(iter(seen)), "source": FOLDER,
                       "folder": title.get(folder)}
                break
            if len(seen) > 1:
                # 不猜。往上找也不對 —— 上層離得更遠,只會更不準
                res = {"setup": None, "source": AMBIGUOUS,
                       "folder": title.get(folder), "choices": sorted(seen)}
                break
            folder = parent.get(folder)
        out[rid] = res
    return out


def suggest(name, known_names):
    """名稱找不到時,最接近的那個擺位(防線 ②)。沒有夠像的回 None。"""
    hit = difflib.get_close_matches(str(name), sorted(known_names), n=1,
                                    cutoff=0.6)
    return hit[0] if hit else None


def check(row_ids, resolved, known_names) -> dict:
    """開跑前的標籤檢查(防線 ①②)。**只報告,不擋。**

    回:
        total / own / inherited / untagged    各有幾筆
        unknown    [{name, rows, suggestion}]  名稱找不到對應擺位
        ambiguous  [{row_id, folder, choices}] 資料夾裡擺位不只一種,判斷不出來
        switches   照目前順序會切換幾次
        used       會用到哪些擺位
    """
    known = {str(n).strip() for n in known_names if str(n).strip()}
    counts = {OWN: 0, FOLDER: 0, NONE: 0, AMBIGUOUS: 0}
    unknown, ambiguous = {}, []
    for r in row_ids:
        info = resolved.get(int(r)) or {"setup": None, "source": NONE}
        counts[info["source"]] += 1
        if info["source"] == AMBIGUOUS:
            ambiguous.append({"row_id": int(r), "folder": info.get("folder"),
                              "choices": info.get("choices") or []})
        elif info["setup"] and info["setup"] not in known:
            unknown.setdefault(info["setup"], []).append(int(r))

    plan = plan_for(row_ids, by_row(resolved), known)
    return {
        "total": len(row_ids),
        "own": counts[OWN], "inherited": counts[FOLDER],
        "untagged": counts[NONE],
        "unknown": [{"name": n, "rows": rows, "suggestion": suggest(n, known)}
                    for n, rows in sorted(unknown.items())],
        "ambiguous": ambiguous,
        "switches": plan["switches"], "used": plan["used"],
    }


def by_row(resolved) -> dict:
    """{row_id: 擺位名稱} —— 只留判斷得出來的。排序與執行都吃這個形狀。"""
    return {rid: v["setup"] for rid, v in resolved.items() if v.get("setup")}


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

    def group_setup(key):
        for r in members[key]:
            s = setup_by_row.get(r)
            if s:
                return s
        return ""                    # 沒標 -> 排在最前面,沿用當下

    # sorted 是穩定的:同一個擺位的群組會保持原本的先後
    return [r for key in sorted(order, key=group_setup) for r in members[key]]
