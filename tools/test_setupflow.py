# -*- coding: utf-8 -*-
"""擺位流程的端對端測試 —— 不需要 ACQUA、不需要資料庫、不需要機構。

驗的是計畫書(acqua_scripts/SETUP_AUTOMATION_PLAN.md)兩件事:

  5.0.4 讀取規則   有標籤找得到 -> 移動;找不到 -> 不移動、記一筆、繼續
  防線 ⑤          那一筆警告要活到**最後**:結果、摘要、runlog、CSV、
                   跑完的訊息,每一處都要看得出是哪幾筆有疑慮

為什麼要有這支:這條鏈跨了 5 個檔(setuptags / app / backend / state /
runlog),每一段單獨看都對,串起來漏一處就變成「靜默產生可能錯誤的數據」
—— 而那正好是整個設計最不能出錯的地方。用模擬後端跑,所以 CI 跟沒有
機器的開發環境都測得到。

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
from acqua.runlog import RunLog                             # noqa: E402
from acqua.state import SharedState                         # noqa: E402

# 模擬後端每筆要睡 0.8~2.2 秒。這裡測的是資料怎麼流,不是進度條,
# 所以把它關掉 —— 不然 3 輪 12 筆要跑快 20 秒。
backend_mock._MOCK_SECONDS_PER_SMD = (0.0, 0.0)

fails = []


def check(name, ok, detail=""):
    print("   %-44s %s%s" % (name, "OK" if ok else "**FAIL**",
                             ("  " + detail) if detail and not ok else ""))
    if not ok:
        fails.append(name)


# ── 佈景:4 筆測項,兩筆指定找得到的擺位,一筆指定找不到的,一筆沒標 ──
SMDS = [{"row_id": 101, "title": "Sending Loudness", "path": "A"},
        {"row_id": 102, "title": "Receiving Loudness", "path": "A"},
        {"row_id": 103, "title": "POLQA Sending", "path": "B"},
        {"row_id": 104, "title": "Frequency Response", "path": "B"}]

BY_ROW = {101: "monday", 102: "typo-nonexistent", 103: "math"}
KNOWN = {"monday", "math"}


def make_backend(tmp):
    state = SharedState()
    state.smds = list(SMDS)
    state.runlog = RunLog(tmp)
    state.database = "testdb"
    state.open_project = "proj"
    state.measurement_object = "mo"
    be = MockBackend(state, {"mock": {"seconds_per_smd": [0.0, 0.0]}})
    return state, be


def install_hook(state, be):
    """裝一個跟 app._ensure_setup_before_item 同規則的鉤子(不碰真機構)。"""
    moved = []

    def note(row_id, title, wanted, reason):
        rows = list(state.snapshot().get("setup_not_applied") or [])
        rows.append({"row_id": row_id, "title": title,
                     "wanted": wanted, "reason": reason})
        state.set(setup_not_applied=rows)

    def before_item(smd):
        wanted = BY_ROW.get(int(smd["row_id"]))
        if not wanted:
            return                                  # 規則 3:沿用當下
        if wanted not in KNOWN:
            note(smd["row_id"], smd["title"], wanted, "找不到這個擺位")
            return                                  # 規則 2:不移動,繼續
        moved.append((smd["row_id"], wanted))        # 規則 1:移動過去

    be.before_item = before_item
    return moved


print("=== 1. 讀取規則(計畫書 5.0.4)===")
plan = setuptags.plan_for([s["row_id"] for s in SMDS], BY_ROW, KNOWN)
check("找得到的才算切換", plan["switches"] == 2, str(plan["switches"]))
check("用到的擺位列得出來", plan["used"] == ["math", "monday"], str(plan["used"]))
check("找不到的被挑出來", list(plan["unknown"]) == ["typo-nonexistent"])
check("沒標的不產生步驟",
      plan["steps"][3]["wanted"] is None and not plan["steps"][3]["change"])

print("\n=== 2. 鉤子的行為 ===")
with tempfile.TemporaryDirectory() as tmp:
    state, be = make_backend(tmp)
    moved = install_hook(state, be)
    state.set(setup_not_applied=[])
    be.run_smds([s["row_id"] for s in SMDS])

    warn = state.snapshot()["setup_not_applied"]
    check("找得到的有移動", moved == [(101, "monday"), (103, "math")], str(moved))
    check("找不到的沒移動,記一筆", len(warn) == 1 and warn[0]["row_id"] == 102)
    check("記的是想要哪個擺位", warn[0]["wanted"] == "typo-nonexistent")
    # 整批沒跑完的話,擺位問題就不是「一筆可疑」而是「幾小時白跑」
    check("4 筆全部跑完,沒被擺位問題中斷",
          len(state.snapshot()["results"]) == 4)

    print("\n=== 3. 防線 ⑤:警告活到最後 ===")
    snap = state.snapshot()
    byid = {r["row_id"]: r for r in snap["results"]}
    check("有疑慮的那筆結果帶標記",
          byid[102]["setup_warn"] == "typo-nonexistent")
    check("其他筆不帶標記",
          all(not byid[r]["setup_warn"] for r in (101, 103, 104)))
    check("摘要數得出疑慮筆數", snap["summary"]["setup_warn"] == 1,
          str(snap["summary"]))

    done = {x["row_id"]: x for x in (state.runlog.load() or {}).get("done", [])}
    check("runs/current.json 也帶",
          done[102]["setup_warn"] == "typo-nonexistent")
    check("runlog 其他筆是空的", done[101]["setup_warn"] == "")

    # 跑完的訊息 —— 無人值守的人回來只看最後幾行
    logs = [e.get("text", "") for e in state.events_since(0)
            if e["kind"] == "log"]
    tail = "\n".join(logs)
    check("結束訊息帶疑慮筆數", "1 筆擺位未套用" in tail)
    check("跑完有列出是哪一筆", any("#102" in x for x in logs))
    check("說明了為什麼要在意",
          any("可能是在錯誤的位置量到的" in x for x in logs))

print("\n=== 4. 乾淨的一輪不該出現警告 ===")
with tempfile.TemporaryDirectory() as tmp:
    state, be = make_backend(tmp)
    be.before_item = None                   # 完全沒標籤的專案
    state.set(setup_not_applied=[])
    be.run_smds([s["row_id"] for s in SMDS])
    snap = state.snapshot()
    check("沒有警告", not snap["setup_not_applied"])
    check("結果都沒有標記", all(not r["setup_warn"] for r in snap["results"]))
    check("摘要是 0", snap["summary"]["setup_warn"] == 0)
    logs = [e.get("text", "") for e in state.events_since(0)
            if e["kind"] == "log"]
    check("結束訊息不多嘴", not any("擺位未套用" in x for x in logs))

print("\n=== 5. 上一輪的警告不會跟到這一輪 ===")
with tempfile.TemporaryDirectory() as tmp:
    state, be = make_backend(tmp)
    install_hook(state, be)
    state.set(setup_not_applied=[])
    be.run_smds([s["row_id"] for s in SMDS])
    check("第一輪有 1 筆", len(state.snapshot()["setup_not_applied"]) == 1)

    # 第二輪:/api/run 會先清掉(app.py),這裡照樣做
    be.before_item = None
    state.set(setup_not_applied=[])
    be.run_smds([s["row_id"] for s in SMDS])
    snap = state.snapshot()
    check("第二輪歸零", not snap["setup_not_applied"])
    # 沒清乾淨的話,這裡會把上一輪的 typo 蓋到這一輪的 #102 上 ——
    # 症狀是「乾淨的一輪被標成有疑慮」,而且沒有任何線索。
    check("第二輪的結果沒有被上一輪汙染",
          all(not r["setup_warn"] for r in snap["results"]))

print("\n" + ("結論:全部通過" if not fails
              else "結論:%d 項未通過 —— %s" % (len(fails), "、".join(fails))))
sys.exit(1 if fails else 0)
