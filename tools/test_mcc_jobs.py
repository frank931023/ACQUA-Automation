# -*- coding: utf-8 -*-
"""HttpCrane 對 MCC 移動作業 API 的測試 —— 不需要 ACQUA、服務或硬體。

在同一個行程裡起一個假 MCC(tools/fake_mcc.py,照 docs/MCC_MOTION_API.md 回應),
用**真的** HttpCrane 去打它,檢查:

    送出去的 body   名稱 + 每台 Pi 的目標,單位換算對不對,整組一次送
    等待            running 時 busy(),done 之後位置更新
    失敗            被拒絕(409 / 400 / 401)、作業 error、作業不見(404)、連不上
    最後一段        真的 SetupCoordinator 透過 HttpCrane 換擺位、記警告

    python tools/test_mcc_jobs.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from acqua.context import context_key                       # noqa: E402
from acqua.crane import AXES, HOME, HttpCrane, targets_by_device  # noqa: E402
from acqua.roomsetups import RoomSetups                     # noqa: E402
from acqua.setupcoord import SetupCoordinator               # noqa: E402
from acqua.state import SharedState                         # noqa: E402
from fake_mcc import FakeMCC                                # noqa: E402

fails = []


def check(name, ok, detail=""):
    print("   %-44s %s%s" % (name, "OK" if ok else "**FAIL**",
                             ("  " + detail) if detail and not ok else ""))
    if not ok:
        fails.append(name)


def wait_idle(bridge, limit=10.0):
    end = time.time() + limit
    while bridge.busy():
        if time.time() > end:
            return False
        time.sleep(0.05)
    return True


def crane_for(mcc, token=""):
    c = HttpCrane(mcc.url, token)
    c.poll_seconds = 0.05
    return c


# 任一台 Pi 上的線性軸 + 旋轉軸各一根,外加另一台 Pi 的一根 —— 不綁特定軸名
LINEAR = next(a for a in AXES.values() if a.unit == "m")
ROT = next((a for a in AXES.values() if a.unit == "deg"), None)
OTHER = next(a for a in AXES.values() if a.pi != LINEAR.pi)
MOVES = [(LINEAR.id, (LINEAR.lo + LINEAR.hi) / 2), (OTHER.id, OTHER.hi)]
if ROT:
    MOVES.append((ROT.id, 45.0))

mcc = FakeMCC(seconds=0.3).start()
try:
    print("=== 1. 送出去的內容 ===")
    c = crane_for(mcc)
    c.submit(MOVES, label="near field")
    body = mcc.received[-1] if mcc.received else {}
    tg = body.get("targets") or {}
    check("label 就是擺位名稱", body.get("label") == "near field", str(body.get("label")))
    check("依 Pi 分組", set(tg) == {a.pi for a in (LINEAR, OTHER)} | ({ROT.pi} if ROT else set()),
          str(sorted(tg)))
    check("鍵是韌體移動指令", tg.get(LINEAR.pi, {}).get(LINEAR.ch + "M") is not None,
          str(tg.get(LINEAR.pi)))
    check("線性軸換算成公釐(從 lo 起算)",
          tg.get(LINEAR.pi, {}).get(LINEAR.ch + "M") == LINEAR.to_device(MOVES[0][1]),
          "%s vs %s" % (tg.get(LINEAR.pi), LINEAR.to_device(MOVES[0][1])))
    if ROT:
        check("旋轉軸直接送度數", tg.get(ROT.pi, {}).get(ROT.ch + "M") == 45)
    check("跟 targets_by_device 一致", tg == targets_by_device(
        [(k, AXES[k].clamp(v)) for k, v in MOVES]))
    check("一個擺位只送一次", len(mcc.received) == 1, str(len(mcc.received)))

    print("\n=== 2. 等待與完成 ===")
    check("送出後 busy", c.busy())
    check("走完會停", wait_idle(c))
    snap = c.snapshot()
    check("作業狀態 done", (snap["job"] or {}).get("state") == "done", str(snap["job"]))
    got = snap["axes"][LINEAR.id]
    check("位置換成 MCC 回報的", abs(got["value"] - MOVES[0][1]) < 1e-3, str(got))
    check("有回報就不是推估", got["estimated"] is False, str(got))
    check("沒動到的軸維持推估",
          next(v["estimated"] for k, v in snap["axes"].items()
               if k not in dict(MOVES)) is True)

    mcc.report_positions = False
    c2 = crane_for(mcc)
    c2.submit([(LINEAR.id, LINEAR.lo)], label="x")
    wait_idle(c2)
    g2 = c2.snapshot()["axes"][LINEAR.id]
    check("沒回報 positions 就當作到了目標", abs(g2["value"] - LINEAR.lo) < 1e-3, str(g2))
    check("…但標成推估", g2["estimated"] is True)
    mcc.report_positions = True

    print("\n=== 3. 被拒絕 ===")
    c3 = crane_for(mcc)
    mcc.refuse = (409, "pi-xx is busy (manual move on the MCC page)")
    try:
        c3.submit(MOVES, label="near field")
        raised = ""
    except RuntimeError as exc:
        raised = str(exc)
    check("409 會丟例外", bool(raised))
    check("例外裡有 MCC 給的原因", "busy" in raised, raised)
    check("被拒絕不留作業", c3.snapshot()["job"] is None)
    check("被拒絕不算在動", not c3.busy())

    strict = FakeMCC(seconds=0.1, devices={"nobody"}).start()
    try:
        c4 = crane_for(strict)
        try:
            c4.submit(MOVES, label="x")
            msg = ""
        except RuntimeError as exc:
            msg = str(exc)
        check("裝置不存在 -> 400 例外", "no such device" in msg, msg)
    finally:
        strict.stop()

    locked = FakeMCC(seconds=0.1, token="s3cret").start()
    try:
        try:
            crane_for(locked).submit(MOVES, label="x")
            msg = ""
        except RuntimeError as exc:
            msg = str(exc)
        check("沒帶 token -> 401 例外", "401" in msg, msg)
        ct = crane_for(locked, token="s3cret")
        ct.submit(MOVES, label="x")
        check("帶對 token 就通過", wait_idle(ct)
              and ct.snapshot()["job"]["state"] == "done")
    finally:
        locked.stop()

    print("\n=== 4. 作業失敗 / 不見 / 連不上 ===")
    mcc.fail_with = "pi-003 SZM,3350: Exceeded Max travel (not homed?)"
    c5 = crane_for(mcc)
    c5.submit(MOVES, label="far")
    wait_idle(c5)
    j5 = c5.snapshot()["job"]
    check("error 會傳回來", j5["state"] == "error", str(j5))
    check("error 帶原因", "Exceeded" in (j5.get("error") or ""), str(j5.get("error")))
    check("失敗時位置不更新(維持開機時的假設)",
          abs(c5.snapshot()["axes"][OTHER.id]["value"] - HOME[OTHER.id]) < 1e-9,
          str(c5.snapshot()["axes"][OTHER.id]))
    mcc.fail_with = None

    c6 = crane_for(mcc)
    c6.submit(MOVES, label="gone")
    mcc.jobs.clear()                     # 像 MCC 重啟過
    wait_idle(c6)
    j6 = c6.snapshot()["job"]
    check("作業不見(404)算失敗", j6["state"] == "error", str(j6))

    dead = HttpCrane("http://127.0.0.1:9", "")
    try:
        dead.submit(MOVES, label="x")
        msg = ""
    except RuntimeError as exc:
        msg = str(exc)
    check("連不上 -> 例外講清楚", "Cannot reach" in msg, msg)

    print("\n=== 5. 真的擺位協調透過 MCC 換擺位 ===")
    with tempfile.TemporaryDirectory() as tmp:
        store = RoomSetups(tmp)
        store.save(name="A", axes={LINEAR.id: LINEAR.lo})
        store.save(name="B", axes={LINEAR.id: LINEAR.hi})
        state = SharedState()
        def row(rid, left, right, setup=None, folder=False):
            ad = ("<Properties><UserDefinedProperties><UserDefinedProperty "
                  'name="Setup">%s</UserDefinedProperty></UserDefinedProperties>'
                  "</Properties>" % setup) if setup else "<Properties/>"
            return dict(idTreeItem=rid, rItemType=2 if folder else 1,
                        Title="item %d" % rid, LeftNode=left, RightNode=right, ad=ad)
        tree = [row(1, 1, 6, folder=True), row(11, 2, 3, "B"), row(12, 4, 5, "Nope")]
        bridge = crane_for(mcc)
        coord = SetupCoordinator(state, store, lambda *_: tree, bridge=bridge,
                                 move_timeout=10, poll_seconds=0.05)
        ctx = context_key("server", "db", 1)
        mcc.received.clear()
        coord.prepare(ctx, [11, 12], [{"row_id": 11, "path": ""},
                                      {"row_id": 12, "path": ""}], regroup=False)
        coord.before_item({"row_id": 11, "title": "t1"})
        warn = state.snapshot().get("setup_not_applied") or []
        check("送給 MCC 的 label 是擺位名稱",
              [b.get("label") for b in mcc.received] == ["B"],
              str([b.get("label") for b in mcc.received]))
        check("到位後認得出是 B", coord.current() == "B", str(coord.current()))
        check("成功不記警告", warn == [], str(warn))

        coord.before_item({"row_id": 11, "title": "t1"})
        check("已經在 B 就不再送", len(mcc.received) == 1, str(len(mcc.received)))

        coord.before_item({"row_id": 12, "title": "t2"})
        warn = state.snapshot().get("setup_not_applied") or []
        check("找不到的名稱不送給 MCC", len(mcc.received) == 1)
        check("找不到的名稱記一筆", len(warn) == 1 and warn[0]["wanted"] == "Nope", str(warn))

        mcc.fail_with = "pi-001 SXM: Exceeded Max travel"
        store.save(name="C", axes={LINEAR.id: LINEAR.lo})
        tree[1] = row(11, 2, 3, "C")
        coord.prepare(ctx, [11], [{"row_id": 11, "path": ""}], regroup=False)
        coord.before_item({"row_id": 11, "title": "t1"})
        warn = state.snapshot().get("setup_not_applied") or []
        check("MCC 回報失敗會記警告", len(warn) == 1 and "Exceeded" in warn[0]["reason"],
              str(warn))
        mcc.fail_with = None
finally:
    mcc.stop()

print("\n" + ("結論:全部通過" if not fails
              else "結論:%d 項未通過 —— %s" % (len(fails), "、".join(fails))))
sys.exit(1 if fails else 0)
