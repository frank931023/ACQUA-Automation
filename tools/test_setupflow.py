# -*- coding: utf-8 -*-
"""擺位流程的端對端測試 —— 不需要 ACQUA、資料庫或機構。

測的是**真正的程式碼**:setuptags(讀標籤、繼承)、setupcoord(動機構、
記警告)、RoomSetups(擺位存檔,放在暫存資料夾)、模擬後端、state、runlog。
只有兩樣換成假的:
    資料庫   一棵寫在這裡的測項樹(query 函式直接回它)
    機構     送出就瞬間到位的橋接 —— 可以設定成「移動失敗」

驗計畫書(acqua_scripts/SETUP_AUTOMATION_PLAN.md)的兩件事:
    5.0.4   有標就移、沒標往資料夾找、找不到名稱就記一筆照常量
    防線 ⑤  記下的警告活到最後:結果、摘要、runlog、跑完的訊息

    python tools/test_setupflow.py
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from acqua import backend_mock, setuptags                   # noqa: E402
from acqua.backend_mock import MockBackend                  # noqa: E402
from acqua.context import context_key                       # noqa: E402
from acqua.crane import AXES                                # noqa: E402
from acqua.roomsetups import RoomSetups                     # noqa: E402
from acqua.runlog import RunLog                             # noqa: E402
from acqua.setupcoord import SetupCoordinator               # noqa: E402
from acqua.state import SharedState                         # noqa: E402

# 模擬後端每筆會睡 1~2 秒。這裡測資料怎麼流,不是進度條。
backend_mock._MOCK_SECONDS_PER_SMD = (0.0, 0.0)

fails = []


def check(name, ok, detail=""):
    print("   %-44s %s%s" % (name, "OK" if ok else "**FAIL**",
                             ("  " + detail) if detail and not ok else ""))
    if not ok:
        fails.append(name)


# ── 測項樹 ─────────────────────────────────────────
def tag(value):
    return ('<Properties><UserDefinedProperties><UserDefinedProperty '
            'name="Setup">%s</UserDefinedProperty></UserDefinedProperties>'
            '</Properties>' % value)


def tree(spec):
    """把 [(id, 'folder'|標籤|None, [子項])] 轉成巢狀集合的列。

    跟 acqua.TreeItems 同形狀,所以 setuptags.resolve() 吃得下 ——
    不用手算 LeftNode / RightNode。
    """
    rows, counter = [], [0]

    def walk(items):
        for rid, what, children in items:
            counter[0] += 1
            left = counter[0]
            walk(children)
            counter[0] += 1
            is_folder = what == "folder"
            rows.append(dict(idTreeItem=rid, rItemType=2 if is_folder else 1,
                             Title="item %d" % rid, LeftNode=left,
                             RightNode=counter[0],
                             ad=tag(what) if what and not is_folder
                             else "<Properties/>"))
    walk(spec)
    return sorted(rows, key=lambda r: r["LeftNode"])


# 執行流程用的那棵:四筆測項、四種情況
RUN_TREE = tree([(1, "folder", [
    (2, "folder", [(101, "near", []), (102, "typo-nonexistent", [])]),
    (3, "folder", [(103, "far", [])]),
    (4, "folder", [(104, None, [])]),
])])
SMDS = [{"row_id": r, "title": "item %d" % r, "path": "p%d" % r}
        for r in (101, 102, 103, 104)]
CTX = context_key("server", "db", 1)

# 兩個擺位,只差第一根軸
AXIS = next(iter(AXES))
_LO, _HI = AXES[AXIS].lo, AXES[AXIS].hi
POSITIONS = {"near": _LO + 0.1 * (_HI - _LO), "far": _LO + 0.9 * (_HI - _LO)}


class FakeBridge:
    """送出就到位。fail=True 時作業以 error 結束、位置不變。"""

    def __init__(self, fail=False):
        self.pos = {AXIS: (_LO + _HI) / 2}
        self.moves, self.fail, self.job = [], fail, None

    def snapshot(self):
        return {"axes": {k: {"value": v, "estimated": False}
                         for k, v in self.pos.items()}, "job": self.job}

    def busy(self):
        return False

    def submit(self, moves, label=""):
        self.moves.append(label)
        if self.fail:
            self.job = {"state": "error", "error": "Pi 沒回應"}
        else:
            self.pos.update(dict(moves))
            self.job = {"state": "done"}
        return self.job


def make_run(tmp, bridge, tree_rows=RUN_TREE):
    state = SharedState()
    state.smds, state.ctx = list(SMDS), CTX
    state.runlog = RunLog(tmp)
    state.database, state.open_project, state.measurement_object = "db", "p", "mo"

    store = RoomSetups(tmp)
    for name, value in POSITIONS.items():
        store.save(name=name, axes={AXIS: value})

    coord = SetupCoordinator(state, store, lambda *_: tree_rows,
                             bridge=bridge, poll_seconds=0)
    be = MockBackend(state, {"mock": {"seconds_per_smd": [0.0, 0.0]}})
    be.before_item = coord.before_item
    return state, coord, be


def run(state, coord, be, row_ids=(101, 102, 103, 104)):
    order = coord.prepare(CTX, list(row_ids), SMDS, regroup=False)
    be.run_smds(order)
    return state.snapshot()


def logs(state):
    return [e.get("text", "") for e in state.events_since(0) if e["kind"] == "log"]


print("=== 1. 讀取規則(計畫書 5.0.4)===")
with tempfile.TemporaryDirectory() as tmp:
    bridge = FakeBridge()
    state, coord, be = make_run(tmp, bridge)
    snap = run(state, coord, be)
    warn = snap["setup_not_applied"]
    check("找得到的有移動", bridge.moves == ["near", "far"],
          str(bridge.moves))
    check("最後停在最後一個擺位", coord.current() == "far")
    check("找不到的沒移動,記一筆", [w["row_id"] for w in warn] == [102], str(warn))
    check("記的是想要哪個擺位", warn[0]["wanted"] == "typo-nonexistent")
    check("4 筆全部跑完,沒被擺位問題中斷", len(snap["results"]) == 4)

    print("\n=== 2. 防線 ⑤:警告活到最後 ===")
    byid = {r["row_id"]: r for r in snap["results"]}
    check("有疑慮的那筆結果帶標記", byid[102]["setup_warn"] == "typo-nonexistent")
    check("其他筆不帶標記", all(not byid[r]["setup_warn"] for r in (101, 103, 104)))
    check("摘要數得出疑慮筆數", snap["summary"]["setup_warn"] == 1, str(snap["summary"]))
    done = {x["row_id"]: x for x in (state.runlog.load() or {}).get("done", [])}
    check("runlog 也帶", done[102]["setup_warn"] == "typo-nonexistent")
    check("runlog 其他筆是空的", done[101]["setup_warn"] == "")
    text = logs(state)
    check("結束訊息帶疑慮筆數", any("1 筆擺位未套用" in x for x in text))
    check("跑完有列出是哪一筆", any("#102" in x for x in text))
    check("開跑前就說了名稱找不到", any("typo-nonexistent" in x and "找不到對應" in x
                                       for x in text))

print("\n=== 3. 已經在位置上就不白跑 ===")
with tempfile.TemporaryDirectory() as tmp:
    bridge = FakeBridge()
    state, coord, be = make_run(tmp, bridge)
    run(state, coord, be, (101,))
    run(state, coord, be, (101,))
    check("第二輪沒有再移動", bridge.moves == ["near"], str(bridge.moves))

print("\n=== 4. 機構出錯要記得是出錯 ===")
with tempfile.TemporaryDirectory() as tmp:
    state, coord, be = make_run(tmp, FakeBridge(fail=True))
    warn = run(state, coord, be, (101,))["setup_not_applied"]
    check("移動失敗有記", len(warn) == 1 and "移動失敗" in warn[0]["reason"], str(warn))
    check("帶著機構給的原因", "Pi 沒回應" in warn[0]["reason"])

with tempfile.TemporaryDirectory() as tmp:
    state, coord, be = make_run(tmp, None)
    warn = run(state, coord, be, (101,))["setup_not_applied"]
    check("沒有機構也照常量、有記",
          len(warn) == 1 and warn[0]["reason"] == "沒有機構橋接", str(warn))

print("\n=== 5. 乾淨的一輪、上一輪的殘留 ===")
with tempfile.TemporaryDirectory() as tmp:
    state, coord, be = make_run(tmp, FakeBridge())
    check("第一輪有 1 筆", len(run(state, coord, be)["setup_not_applied"]) == 1)
    snap = run(state, coord, be, (101, 103, 104))
    # 沒清乾淨的話,上一輪的警告會蓋到這一輪 —— 乾淨的一輪被標成有疑慮
    check("第二輪歸零", not snap["setup_not_applied"])
    check("第二輪的結果沒有被汙染", all(not r["setup_warn"] for r in snap["results"]))

with tempfile.TemporaryDirectory() as tmp:
    untagged = tree([(1, "folder", [(r, None, []) for r in (101, 102, 103, 104)])])
    state, coord, be = make_run(tmp, FakeBridge(), untagged)
    order = coord.prepare(CTX, [104, 101, 103], SMDS)
    check("沒有任何標籤的專案:順序不動", order == [104, 101, 103])
    be.run_smds(order)
    check("沒有任何標籤的專案:不出聲",
          not any("擺位" in x for x in logs(state)), str(logs(state)))

with tempfile.TemporaryDirectory() as tmp:
    state, coord, be = make_run(tmp, FakeBridge(), [])
    check("讀不到樹就當沒標,不丟例外", coord.prepare("壞掉的 ctx", [101], SMDS) == [101])

print("\n=== 6. 資料夾繼承 ===")
# ACQUA 介面不能對資料夾加標籤,所以「沒標就往上找」看的是同一個資料夾裡
# 其他測項的標籤。這棵樹把每條規則都踩一遍:
#
#   專案 ─┬ A ─┬ #10 Setup=near
#         │    ├ #11 (沒標)          -> 繼承 near
#         │    └ B ── #12 (沒標)     -> B 裡沒人標,再往上到 A -> near
#         ├ C ─┬ #20 Setup=near
#         │    ├ #21 Setup=far
#         │    └ #22 (沒標)          -> C 裡有兩種 -> 不猜
#         ├ D ── #30 (沒標)          -> 一路都沒有 -> 沿用當下
#         └ E ─┬ #40 Setup=far
#              └ #41 Setup=near      -> 自己標的永遠優先,即使資料夾混雜
INHERIT = tree([(1, "folder", [
    (2, "folder", [(10, "near", []), (11, None, []),
                   (3, "folder", [(12, None, [])])]),
    (4, "folder", [(20, "near", []), (21, "far", []), (22, None, [])]),
    (5, "folder", [(30, None, [])]),
    (6, "folder", [(40, "far", []), (41, "near", [])]),
])])
R = setuptags.resolve(INHERIT)


def is_(rid, setup, source):
    return (R[rid]["setup"], R[rid]["source"]) == (setup, source)


check("自己標的就用自己的", is_(10, "near", "own"))
check("沒標的跟著同資料夾", is_(11, "near", "folder"))
check("同資料夾沒人標就再往上一層", is_(12, "near", "folder")
      and R[12]["folder"] == "item 2")
check("資料夾裡有兩種擺位時不猜", is_(22, None, "ambiguous")
      and R[22]["choices"] == ["far", "near"])
check("一路都沒有 -> 沿用當下", is_(30, None, "none"))
check("自己標的優先於混雜的資料夾", is_(40, "far", "own") and is_(41, "near", "own"))

C = setuptags.check([10, 11, 12, 20, 21, 22, 30], R, {"near", "nera"})
check("檢查分得出自己標 / 繼承 / 沒標",
      (C["own"], C["inherited"], C["untagged"]) == (3, 2, 1), str(C))
check("檢查抓得到找不到的名稱", [u["name"] for u in C["unknown"]] == ["far"])
check("檢查抓得到判斷不出來的", [a["row_id"] for a in C["ambiguous"]] == [22])
check("打錯的名稱有建議", setuptags.suggest("naer", {"near", "far"}) == "near")
check("差太多就不亂建議", setuptags.suggest("xyz", {"near", "far"}) is None)

with tempfile.TemporaryDirectory() as tmp:
    state, coord, be = make_run(tmp, FakeBridge(), INHERIT)
    coord.prepare(CTX, [22], SMDS)
    coord.before_item({"row_id": 22, "title": "item 22"})
    warn = state.snapshot()["setup_not_applied"]
    check("判斷不出來的執行時有記一筆",
          len(warn) == 1 and "不只一種" in warn[0]["reason"], str(warn))

print("\n=== 7. 重排:只在真的比較少移動時 ===")
with tempfile.TemporaryDirectory() as tmp:
    state, coord, be = make_run(tmp, FakeBridge())
    smds = [{"row_id": 101, "path": "g1"}, {"row_id": 103, "path": "g2"},
            {"row_id": 104, "path": "g3"}]
    # near, far, (沒標) —— 沒標的排到最前面不會多切換,但也不會少,所以不動
    check("沒有好處就維持原順序",
          coord.prepare(CTX, [101, 103, 104], smds) == [101, 103, 104])

print("\n" + ("結論:全部通過" if not fails
              else "結論:%d 項未通過 —— %s" % (len(fails), "、".join(fails))))
sys.exit(1 if fails else 0)
