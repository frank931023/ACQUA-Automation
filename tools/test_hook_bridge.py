# -*- coding: utf-8 -*-
"""不用 ACQUA 也能測 `acqua_scripts/HOOK_setup_bridge.py`。

做法:把 ACQUA 腳本環境的 `ACQUAlyzer`(Tags / Smd)換成假的,
其餘**一行都不改**地跑真正的掛鉤程式。驗到的是:

    掛鉤讀標籤 -> 打 /api/room/current -> /api/room/apply(用名稱)
    -> 輪詢等到位 -> 驗證真的到了 -> 失敗時打 /api/room/not-applied

也就是「ACQUA 讀到標籤 -> 外部移動 -> 回去量測」那條回路的**外部半邊**。
ACQUA 那半邊(掛鉤能不能卡住幾分鐘)只能上真機測,見計畫書第 0 階段。

用服務上任意兩個位置不同的擺位,不綁特定名稱。
前置:服務要在跑(python app.py --backend com 或 mock 都可以)。

    python tools/test_hook_bridge.py [--service http://127.0.0.1:5000]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import types
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "acqua_scripts", "HOOK_setup_bridge.py")
HOOK_DEFAULT_SERVICE = 'SERVICE = "http://127.0.0.1:5000"'
MISSING = "__no_such_setup__"

ap = argparse.ArgumentParser()
ap.add_argument("--service", default="http://127.0.0.1:5000")
SERVICE = ap.parse_args().service.rstrip("/")

fails = []


def check(name, ok, detail=""):
    print("   %-46s %s%s" % (name, "OK" if ok else "**FAIL**",
                             ("  " + detail) if detail and not ok else ""))
    if not ok:
        fails.append(name)


def get(path):
    with urllib.request.urlopen(SERVICE + path, timeout=30) as r:
        return json.load(r)


def post(path, body):
    req = urllib.request.Request(SERVICE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def warnings():
    return get("/acqua/api/status")["setup_not_applied"]


def current():
    return get("/api/room/current")


def wait_still():
    while current()["moving"]:
        time.sleep(0.5)


def run_hook(tag_value, service=SERVICE):
    """用假的 Tags 跑一次真正的掛鉤。回 (印出的訊息, 例外或 None)。"""
    fake = types.ModuleType("ACQUAlyzer")
    fake.Tags = type("Tags", (), {
        "Exists": staticmethod(lambda n: tag_value is not None and n == "Setup"),
        "Value": staticmethod(lambda n: tag_value)})
    fake.Smd = type("Smd", (), {"Title": "fake smd"})
    sys.modules["ACQUAlyzer"] = fake

    with open(HOOK, encoding="utf-8") as fh:
        src = fh.read().replace(HOOK_DEFAULT_SERVICE, 'SERVICE = "%s"' % service)
    lines = []
    g = {"__name__": "__hook__",
         "print": lambda *a: lines.append(" ".join(map(str, a)))}
    try:
        exec(compile(src, HOOK, "exec"), g)                 # noqa: S102
        return lines, None
    except Exception as exc:                                # noqa: BLE001
        return lines, exc


def two_distinct_setups():
    """兩個位置真的不同的擺位 —— 位置一樣的話「移過去」測不出東西。"""
    setups = get("/api/room/setups")["setups"]
    for i, a in enumerate(setups):
        for b in setups[i + 1:]:
            if a["name"] != b["name"] and a.get("axes") != b.get("axes"):
                return a["name"], b["name"]
    return None


# ── 前置 ───────────────────────────────────────────
try:
    current()
except Exception as exc:                                    # noqa: BLE001
    sys.exit("服務沒有在跑(%s)—— 先啟動 app.py 再跑這支" % exc)
assert HOOK_DEFAULT_SERVICE in open(HOOK, encoding="utf-8").read(), \
    "掛鉤的 SERVICE 那一行改過了,這支要跟著改"
pair = two_distinct_setups()
if pair is None:
    sys.exit("需要至少兩個位置不同的擺位才能測切換 —— 先在 /setups 建立")
A, B = pair
print("用這兩個擺位測:「%s」與「%s」\n" % (A, B))

print("=== 1. 沒有 Setup 標籤 -> 什麼都不做 ===")
before = len(warnings())
out, err = run_hook(None)
check("不移動也不回報", len(warnings()) == before)
check("不印多餘訊息", not out, str(out))

print("\n=== 2. 擺位找得到 -> 移動過去 ===")
post("/api/room/apply", {"setup_name": A})
wait_still()
check("先把機構放到第一個擺位", current()["setup"] == A, str(current()["setup"]))
out, err = run_hook(B)
cur = current()
check("掛鉤把機構移到第二個擺位", cur["setup"] == B, str(cur["setup"]))
check("掛鉤回報已就位", any("已就位" in x for x in out), str(out))
check("移動完 moving 回 False", cur["moving"] is False)

print("\n=== 3. 已經在位置上 -> 不白跑一次移動 ===")
out, err = run_hook(B)
check("認得出已經在位置上", any("已經在" in x for x in out), str(out))
check("位置沒變", current()["setup"] == B)

print("\n=== 4. 擺位找不到 -> 不移動、記一筆、繼續 ===")
before = warnings()
out, err = run_hook(MISSING)
after = warnings()
check("多記了一筆", len(after) == len(before) + 1, "%d -> %d" % (len(before), len(after)))
check("記的是那個找不到的名稱", bool(after) and after[-1]["wanted"] == MISSING)
check("機構沒有亂動", current()["setup"] == B)
check("掛鉤沒有丟例外", err is None, str(err))

print("\n=== 5. 服務連不上 -> 一樣不擋量測 ===")
out, err = run_hook(A, service="http://127.0.0.1:59999")   # 沒人在聽的 port
check("服務不在時不丟例外", err is None, str(err))
check("有講出是連不上服務", any("連不上" in x or "回報" in x for x in out), str(out))

print("\n" + ("結論:全部通過" if not fails
              else "結論:%d 項未通過 —— %s" % (len(fails), "、".join(fails))))
sys.exit(1 if fails else 0)
