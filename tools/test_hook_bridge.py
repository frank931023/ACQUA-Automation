# -*- coding: utf-8 -*-
"""不用 ACQUA 也能測 `acqua_scripts/HOOK_setup_bridge.py`。

做法:把 ACQUA 腳本環境的 `ACQUAlyzer`(Tags / Smd)換成假的,
其餘**一行都不改**地跑真正的掛鉤程式。所以驗到的是:

    掛鉤讀標籤 -> 打 /api/room/current -> /api/room/apply(用名稱)
    -> 輪詢等到位 -> 驗證真的到了 -> 失敗時打 /api/room/not-applied

也就是「ACQUA 內部讀到 -> 丟給外部 -> 外部處理完 -> 回去量測」那條回路
的**外部那半邊**。ACQUA 那半邊(掛鉤能不能卡住幾分鐘)只能上真機測,
見計畫書第 0 階段。

前置:服務要在跑(python app.py --backend com 或 mock 都可以)。

    python tools/test_hook_bridge.py
"""
from __future__ import annotations

import json
import os
import sys
import types
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SERVICE = "http://127.0.0.1:5000"
HOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "acqua_scripts", "HOOK_setup_bridge.py")

fails = []


def check(name, ok, detail=""):
    print("   %-46s %s%s" % (name, "OK" if ok else "**FAIL**",
                             ("  " + detail) if detail and not ok else ""))
    if not ok:
        fails.append(name)


def get(path):
    return json.load(urllib.request.urlopen(SERVICE + path, timeout=30))


def post(path, body):
    req = urllib.request.Request(
        SERVICE + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def run_hook(tag_value, title="fake smd"):
    """用假的 Tags 跑一次真正的掛鉤,回傳它印出來的訊息。"""
    fake = types.ModuleType("ACQUAlyzer")

    class _Tags:
        @staticmethod
        def Exists(name):
            return tag_value is not None and name == "Setup"

        @staticmethod
        def Value(name):
            return tag_value

    class _Smd:
        Title = title

    fake.Tags, fake.Smd = _Tags, _Smd
    sys.modules["ACQUAlyzer"] = fake

    lines = []
    g = {"__name__": "__hook__", "print": lambda *a: lines.append(" ".join(map(str, a)))}
    with open(HOOK, encoding="utf-8") as fh:
        exec(compile(fh.read(), HOOK, "exec"), g)     # noqa: S102
    return lines


# ── 前置檢查 ────────────────────────────────────────
try:
    get("/api/room/current")
except Exception as exc:                                    # noqa: BLE001
    print("服務沒有在跑(%s)—— 先啟動 app.py 再跑這支" % exc)
    sys.exit(2)

names = [s["name"] for s in get("/api/room/setups")["setups"]]
print("可用的擺位:", names)
if "location1" not in names or "location2" not in names:
    print("需要 location1 與 location2 這兩個擺位才能測切換,請先建立")
    sys.exit(2)

print()
print("=== 1. 沒有 Setup 標籤 -> 什麼都不做(規則 3)===")
post("/api/room/not-applied", {"wanted": "__clear_probe__", "reason": "x"})
before = len(get("/api/room/current") and
              json.load(urllib.request.urlopen(
                  SERVICE + "/acqua/api/status", timeout=30))["setup_not_applied"])
out = run_hook(None)
after = json.load(urllib.request.urlopen(
    SERVICE + "/acqua/api/status", timeout=30))["setup_not_applied"]
check("不移動也不回報", len(after) == before, "%d -> %d" % (before, len(after)))
check("不印多餘訊息", not out, str(out))

print()
print("=== 2. 擺位找得到 -> 移動過去(規則 1)===")
post("/api/room/apply", {"setup_name": "location1"})
while get("/api/room/current")["moving"]:
    pass
check("先把機構放到 location1", get("/api/room/current")["setup"] == "location1")

out = run_hook("location2")
cur = get("/api/room/current")
check("掛鉤把機構移到 location2", cur["setup"] == "location2", str(cur["setup"]))
check("掛鉤回報已就位", any("已就位" in x for x in out), str(out))
check("移動完 moving 回 False", cur["moving"] is False)

print()
print("=== 3. 已經在位置上 -> 不白跑一次移動 ===")
out = run_hook("location2")
check("認得出已經在位置上", any("已經在" in x for x in out), str(out))
check("沒有再移動一次", get("/api/room/current")["setup"] == "location2")

print()
print("=== 4. 擺位找不到 -> 不移動、記一筆、繼續(規則 2)===")
before = json.load(urllib.request.urlopen(
    SERVICE + "/acqua/api/status", timeout=30))["setup_not_applied"]
out = run_hook("RR-SHAR-does-not-exist")
after = json.load(urllib.request.urlopen(
    SERVICE + "/acqua/api/status", timeout=30))["setup_not_applied"]
check("多記了一筆", len(after) == len(before) + 1,
      "%d -> %d" % (len(before), len(after)))
check("記的是那個找不到的名稱",
      after and after[-1]["wanted"] == "RR-SHAR-does-not-exist", str(after[-1:]))
check("機構沒有亂動", get("/api/room/current")["setup"] == "location2")
# 最重要的一條:掛鉤不能把量測擋掉
check("掛鉤沒有丟例外", True)

print()
print("=== 5. 服務連不上 -> 一樣不擋量測 ===")

src = open(HOOK, encoding="utf-8").read().replace(
    'SERVICE = "http://127.0.0.1:5000"',
    'SERVICE = "http://127.0.0.1:59999"')          # 沒人在聽的 port
fake = types.ModuleType("ACQUAlyzer")
fake.Tags = type("T", (), {"Exists": staticmethod(lambda n: True),
                           "Value": staticmethod(lambda n: "location1")})
fake.Smd = type("S", (), {"Title": "offline test"})
sys.modules["ACQUAlyzer"] = fake
lines = []
g = {"__name__": "__hook__", "print": lambda *a: lines.append(" ".join(map(str, a)))}
try:
    exec(compile(src, HOOK, "exec"), g)                      # noqa: S102
    check("服務不在時不丟例外", True)
except Exception as exc:                                    # noqa: BLE001
    check("服務不在時不丟例外", False, str(exc))
check("有講出是連不上服務",
      any("連不上" in x or "回報" in x for x in lines), str(lines))

print("\n" + ("結論:全部通過" if not fails
              else "結論:%d 項未通過 —— %s" % (len(fails), "、".join(fails))))
sys.exit(1 if fails else 0)
