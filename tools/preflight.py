# -*- coding: utf-8 -*-
"""啟動前自檢:一次把「會讓它莫名其妙不動」的原因全部檢查完。

為什麼要有這支
──────────────
這個服務依賴一長串外部條件:32-bit Python、ACQUA 開著、dongle 插著、
SQL Server 連得到、port 沒被佔用。任何一項不成立,症狀都是
「網頁打得開,但按什麼都怪怪的」—— 而真正的原因埋在 log 深處。

包成開機自動啟動的服務之後更糟:沒有人在旁邊看 console,
出問題只會發現「今天的測試沒跑」。

所以開機先跑這支:每一項都給明確的判斷與**怎麼修**,
有紅字就不要啟動,直接把原因寫進紀錄。

用法
────
    python tools/preflight.py           檢查完印報告
    python tools/preflight.py --quiet   只印失敗的(給排程用)

回傳碼:0 = 可以啟動 ・ 1 = 有致命問題 ・ 2 = 有警告但能跑
"""
from __future__ import annotations

import argparse
import io
import json
import os
import socket
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

FATAL, WARN, OK = "fatal", "warn", "ok"
results = []


def check(name, level, detail="", fix=""):
    results.append({"name": name, "level": level, "detail": detail, "fix": fix})
    return level == OK


def report(quiet=False):
    bad = [r for r in results if r["level"] == FATAL]
    warn = [r for r in results if r["level"] == WARN]
    for r in results:
        if quiet and r["level"] == OK:
            continue
        mark = {"ok": "  OK  ", "warn": "  ??  ", "fatal": "  !!  "}[r["level"]]
        print("%s%-38s %s" % (mark, r["name"], r["detail"]))
        if r["fix"] and r["level"] != OK:
            print("        → %s" % r["fix"])
    print()
    if bad:
        print("%d fatal problem(s) - do not start until fixed" % len(bad))
        return 1
    if warn:
        print("Ready, with %d warning(s)" % len(warn))
        return 2
    print("All checks passed")
    return 0


# ── 1. Python 本身 ──────────────────────────────
def check_python():
    bits = struct.calcsize("P") * 8
    check("Python architecture", OK if bits == 32 else FATAL, "%d-bit" % bits,
          "ACQUA registers its TypeLib under win32 only - 32-bit Python is required. "
          "Use the one shipped with HEAD: C:/Program Files (x86)/Common Files/HEAD shared/Python39")

    for mod, why in [("flask", "web service"), ("win32com", "COM interface"),
                     ("pythoncom", "COM threading")]:
        try:
            __import__(mod)
            check("Package %s" % mod, OK, why)
        except ImportError:
            check("Package %s" % mod, FATAL, "not found",
                  "Make sure you are using .venv\\Scripts\\python.exe")


# ── 2. 設定 ─────────────────────────────────────
def check_config():
    path = os.path.join(ROOT, "config.json")
    if not os.path.exists(path):
        check("config.json", FATAL, "missing",
              "Copy config.example.json to config.json")
        return None
    try:
        cfg = json.load(io.open(path, encoding="utf-8"))
    except Exception as exc:                                # noqa: BLE001
        check("config.json", FATAL, "invalid JSON: %s" % str(exc)[:50],
              "Check the file - a trailing comma is the usual cause")
        return None

    from acqua import env as env_settings
    applied = env_settings.apply_to(cfg, os.path.join(ROOT, ".env"))
    check("config.json", OK, "loaded")
    if os.path.exists(os.path.join(ROOT, ".env")):
        check(".env", OK, "%d override(s)" % len(applied))
    else:
        check(".env", WARN, "not present - using config.json as-is",
              "Copy .env.example to .env and put machine-specific values there")

    db = cfg.get("database", {})
    if not db.get("server"):
        check("Database config", FATAL, "no server set",
              "Set ACQUA_DB_SERVER=MACHINE\\ACQUADBSERVER in .env")
    else:
        check("Database config", OK, "%s / %s" % (db.get("server"), db.get("name")))
    return cfg


# ── 3. 外部服務 ─────────────────────────────────
def check_sql(cfg):
    if not cfg:
        return
    db = cfg.get("database", {})
    server, name = db.get("server"), db.get("name")
    if not server:
        return
    # ⚠️ 重試而不是一次定生死:實測看過剛把舊行程砍掉之後,
    #    緊接著的第一次連線會失敗(連線池/SSPI 還沒回穩)。
    #    因為一次抖動就擋住啟動,是最惱人的那種假警報。
    from acqua.sqlcat import raw_query
    last = None
    for attempt in range(3):
        try:
            rows = raw_query(server, name or "master",
                             "SELECT DB_NAME() AS db, SUSER_NAME() AS usr")
            check("SQL Server", OK, "%s (user %s)%s"
                  % (rows[0]["db"], rows[0]["usr"],
                     "" if not attempt else " (after %d retries)" % attempt))
            return
        except Exception as exc:                            # noqa: BLE001
            last = exc
            if attempt < 2:
                import time
                time.sleep(1.5)
    check("SQL Server", FATAL, str(last)[:60],
          "Check that SQL Server is running and the database name is right. "
          "If unsure of the machine name, use Scan in the web UI")


def check_acqua():
    try:
        import pythoncom
        import win32com.client as w
        pythoncom.CoInitialize()
        app = w.Dispatch("Acqua3.AcquaApplication")
        _ = app.SelectedDatabaseName          # 碰一下確認真的活著
        check("ACQUA", OK, "reachable over COM")
    except Exception as exc:                                # noqa: BLE001
        msg = str(exc)
        hint = "Start ACQUA first - this service attaches to it, it does not launch it"
        if "無效的類別字串" in msg or "Invalid class string" in msg:
            hint += "; if ACQUA is open and this still fails, check the ACOPT18 licence and dongle"
        check("ACQUA", FATAL, msg[:60], hint)


def check_port(cfg):
    web = (cfg or {}).get("web", {})
    host = web.get("host", "127.0.0.1")
    port = int(web.get("port", 5000))
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect((host if host != "0.0.0.0" else "127.0.0.1", port))
        s.close()
        check("Web port %d" % port, WARN, "already in use",
              "Another copy may be running. Stop it, or change ACQUA_WEB_PORT in .env")
    except Exception:                                       # noqa: BLE001
        check("Web port %d" % port, OK, "free")


# ── 4. 本地資料 ─────────────────────────────────
def check_storage():
    for sub, why in [("plans", "test plans"), ("reports", "report staging"),
                     ("runs", "run records")]:
        p = os.path.join(ROOT, sub)
        try:
            os.makedirs(p, exist_ok=True)
            probe = os.path.join(p, ".write_probe")
            with io.open(probe, "w") as f:
                f.write("x")
            os.unlink(probe)
            n = len([x for x in os.listdir(p) if x.endswith(".json")])
            check("Folder %s" % sub, OK, "writable (%s, %d file(s))" % (why, n))
        except Exception as exc:                            # noqa: BLE001
            check("Folder %s" % sub, FATAL, str(exc)[:50],
                  "Check folder permissions, or whether this path is read-only")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="only print problems")
    args = ap.parse_args()

    print("Pre-flight  %s\n" % ROOT)
    check_python()
    cfg = check_config()
    check_storage()
    check_port(cfg)
    check_sql(cfg)
    check_acqua()
    return report(args.quiet)


if __name__ == "__main__":
    sys.exit(main())
