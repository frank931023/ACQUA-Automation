# -*- coding: utf-8 -*-
"""量測進行中,整個介面還能不能用?——以及各種防呆有沒有擋住。

為什麼要有這支
──────────────
這個系統最核心的承諾是:**按下執行就可以走人**。量測跑在伺服器的
工作執行緒裡,瀏覽器只是看板 —— 換頁、關頁、縮小都不該影響它,
而且使用者應該還能繼續做別的事。

但這個承諾很容易破:工作執行緒是**單執行緒**,所有 COM 命令排同一個
佇列。量測一跑起來佇列就塞住,任何「要排進佇列才能回答」的 API 都會
卡到量測結束。那時候整個網頁看起來就像當掉了。

所以要分清楚兩種 API:
    不排佇列   status / health / plans / 頁面    <- 量測中必須照常回應
    要排佇列   run / open-project / list-smds    <- 量測中本來就該被擋

這支把兩種都在「真的有量測在跑」的狀態下打一遍,量回應時間。

用法
────
    python tools/test_nonblocking.py              跑完整輪(會真的量測)
    python tools/test_nonblocking.py --guards     只跑防呆,不啟動量測
    python tools/test_nonblocking.py --smd 5324   指定要跑哪一項
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:5000"
RESULTS = []


def call(path, body=None, timeout=30, raw=False):
    """回 (http 狀態碼, 內容, 耗時秒)。連不上回 (0, 錯誤字串, 耗時)。"""
    url = BASE + path
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if body is not None else "GET")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read().decode("utf-8", "replace")
            out = txt if raw else json.loads(txt or "{}")
            return r.status, out, time.time() - t0
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(txt or "{}"), time.time() - t0
        except Exception:                                   # noqa: BLE001
            return e.code, txt, time.time() - t0
    except Exception as exc:                                # noqa: BLE001
        return 0, str(exc), time.time() - t0


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print("   %-52s %s%s" % (name, "OK" if ok else "!! 失敗",
                             ("  " + detail) if detail else ""))
    return ok


def status():
    _, s, _ = call("/acqua/api/status")
    return s if isinstance(s, dict) else {}


# ── 防呆:這些都該被擋下來,而且要講清楚為什麼 ──────────
def test_guards():
    print("\n=== A. 防呆(都應該被擋,而且要有說明)===")

    code, body, _ = call("/acqua/api/run", {"row_ids": []})
    check("沒勾測項就執行 → 擋下", code == 400 and body.get("error"),
          "HTTP %s %s" % (code, body.get("error", "")))

    # ⚠️ ctx 這道防線要有「目前的 ctx」可以比對才會啟動。沒開專案時
    #    會是更前面的「沒有專案」先擋下 —— 那也是對的,但測的不是同一件事。
    cur_ctx = status().get("ctx")
    if not cur_ctx:
        print("   %-52s （略過:要先開專案才驗得到)" % "在別的專案挑的測項 → 擋下")
    else:
        code, body, _ = call("/acqua/api/run",
                             {"row_ids": [1], "ctx": cur_ctx + "-bogus"})
        check("在別的專案挑的測項 → 擋下", code == 409, "HTTP %s" % code)

    code, body, _ = call("/acqua/api/mic-power", {"pair": "9-9"})
    check("麥克風通道組給錯 → 擋下", code == 400,
          "HTTP %s %s" % (code, body.get("error", "")))

    code, body, _ = call("/acqua/api/plans/no-such-plan-xyz/prepare", {})
    check("不存在的計畫 → 404", code == 404, "HTTP %s" % code)

    code, body, _ = call("/acqua/api/run",
                         {"row_ids": [999999999], "ctx": status().get("ctx")})
    check("測項不屬於這個專案 → 擋下", code >= 400,
          "HTTP %s %s" % (code, str(body.get("error", ""))[:60]))


# ── 非阻塞:量測進行中,這些必須照常回應 ────────────────
NONBLOCKING = [
    ("/acqua/api/status", None),
    ("/acqua/api/health", None),
    ("/acqua/api/plans", None),
    ("/acqua/api/mic-power", None),
    ("/acqua/api/blocking", None),
    ("/acqua/api/status-codes", None),
    ("/acqua/api/last-run", None),
]
PAGES = ["/acqua/", "/acqua/plans", "/", "/setups", "/soundproofroom"]


def hammer(seconds, out):
    """量測進行中持續打唯讀 API,記下最慢的一次。"""
    end = time.time() + seconds
    while time.time() < end:
        for path, body in NONBLOCKING:
            code, _, dt = call(path, body, timeout=20)
            out.append((path, code, dt))
        time.sleep(0.5)


def test_during_run(smd):
    print("\n=== B. 量測進行中的行為 ===")
    s = status()
    if not s.get("open_project") or not s.get("measurement_object"):
        check("前置:專案與 DUT 已就緒", False,
              "請先連線/開專案/選 DUT 再跑這支")
        return
    if s.get("running"):
        check("前置:目前沒有量測在跑", False, "已經有一批在跑了")
        return

    code, body, _ = call("/acqua/api/run",
                         {"row_ids": [smd], "ctx": s.get("ctx"),
                          "run_name": "non-blocking-test"})
    if not check("送出執行", code == 200 and body.get("ok"),
                 "HTTP %s %s" % (code, str(body.get("error", ""))[:70])):
        return

    # 等它真的跑起來
    for _ in range(40):
        if status().get("running"):
            break
        time.sleep(0.5)
    check("後端確實進入執行中", status().get("running"))

    # ── 唯讀 API 在量測中的回應時間 ──────────────
    samples = []
    th = threading.Thread(target=hammer, args=(12, samples), daemon=True)
    th.start()
    th.join(timeout=40)

    worst = {}
    for path, code, dt in samples:
        p = worst.setdefault(path, {"max": 0, "bad": 0, "n": 0})
        p["n"] += 1
        p["max"] = max(p["max"], dt)
        if code != 200:
            p["bad"] += 1
    print("   —— 量測中唯讀 API 的回應(取樣 %d 次)——" % len(samples))
    for path, v in sorted(worst.items()):
        print("      %-28s 最慢 %5.2fs   非 200:%d / %d"
              % (path, v["max"], v["bad"], v["n"]))
    check("唯讀 API 全程沒有失敗",
          all(v["bad"] == 0 for v in worst.values()))
    check("唯讀 API 最慢也在 3 秒內",
          all(v["max"] < 3.0 for v in worst.values()),
          "最慢 %.2fs" % max(v["max"] for v in worst.values()))

    # ── 量測中載入其他頁面 ──────────────────────
    print("   —— 量測中載入頁面 ——")
    page_ok = True
    for p in PAGES:
        code, _, dt = call(p, timeout=25, raw=True)
        print("      %-20s HTTP %s  %5.2fs" % (p, code, dt))
        page_ok = page_ok and code == 200 and dt < 5.0
    check("量測中五個頁面都載得動(5 秒內)", page_ok)

    # ── 會排佇列的 API:應該被擋,不是卡住 ────────
    code, body, dt = call("/acqua/api/run",
                          {"row_ids": [smd], "ctx": s.get("ctx")}, timeout=20)
    check("量測中再按執行 → 立刻擋下(不是卡住)",
          code == 409 and dt < 3.0, "HTTP %s %.2fs" % (code, dt))

    code, body, dt = call("/acqua/api/shutdown", {}, timeout=20)
    check("量測中要求關閉服務 → 拒絕",
          code == 409, "HTTP %s %s" % (code, str(body.get("error", ""))[:50]))

    # ── 中止 ────────────────────────────────────
    code, body, dt = call("/acqua/api/cancel", {}, timeout=20)
    check("中止請求有被接受", code == 200, "HTTP %s" % code)

    t0 = time.time()
    while time.time() - t0 < 240:
        if not status().get("running"):
            break
        time.sleep(2)
    check("量測最終有結束", not status().get("running"),
          "等了 %.0fs" % (time.time() - t0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--guards", action="store_true", help="只跑防呆")
    ap.add_argument("--smd", type=int, default=5324,
                    help="要執行的測項 row_id（預設 5324 = Record 類)")
    args = ap.parse_args()

    code, _, _ = call("/acqua/api/health", timeout=10)
    if code != 200:
        print("服務沒有回應(%s)—— 先啟動服務再跑這支" % code)
        return 1

    test_guards()
    if not args.guards:
        test_during_run(args.smd)

    bad = [n for n, ok, _ in RESULTS if not ok]
    print("\n%d / %d 通過" % (len(RESULTS) - len(bad), len(RESULTS)))
    for n in bad:
        print("   !! %s" % n)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
