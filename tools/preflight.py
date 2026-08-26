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
        print("結論:%d 項致命問題 —— 不要啟動,先修好" % len(bad))
        return 1
    if warn:
        print("結論:可以啟動,但有 %d 項要注意" % len(warn))
        return 2
    print("結論:全部就緒")
    return 0


# ── 1. Python 本身 ──────────────────────────────
def check_python():
    bits = struct.calcsize("P") * 8
    check("Python 位元數", OK if bits == 32 else FATAL, "%d 位元" % bits,
          "ACQUA 的 TypeLib 只註冊 win32 分支,一定要 32-bit 的 Python。"
          "用 HEAD 附的:C:/Program Files (x86)/Common Files/HEAD shared/Python39")

    for mod, why in [("flask", "網頁服務"), ("win32com", "COM 介面"),
                     ("pythoncom", "COM 執行緒")]:
        try:
            __import__(mod)
            check("套件 %s" % mod, OK, why)
        except ImportError:
            check("套件 %s" % mod, FATAL, "找不到",
                  "確認用的是 .venv 裡的 Python:.venv\\Scripts\\python.exe")


# ── 2. 設定 ─────────────────────────────────────
def check_config():
    path = os.path.join(ROOT, "config.json")
    if not os.path.exists(path):
        check("config.json", FATAL, "不存在",
              "複製 config.example.json 成 config.json")
        return None
    try:
        cfg = json.load(io.open(path, encoding="utf-8"))
    except Exception as exc:                                # noqa: BLE001
        check("config.json", FATAL, "格式壞掉:%s" % str(exc)[:50],
              "用 JSON 檢查器看一下,常見是多一個逗號")
        return None

    from acqua import env as env_settings
    applied = env_settings.apply_to(cfg, os.path.join(ROOT, ".env"))
    check("config.json", OK, "讀取成功")
    if os.path.exists(os.path.join(ROOT, ".env")):
        check(".env", OK, "覆寫 %d 項" % len(applied))
    else:
        check(".env", WARN, "不存在,完全照 config.json",
              "移機時複製 .env.example 成 .env,機器專屬的東西放那裡")

    db = cfg.get("database", {})
    if not db.get("server"):
        check("資料庫設定", FATAL, "沒有指定 server",
              "在 .env 設 ACQUA_DB_SERVER=機器名\\ACQUADBSERVER")
    else:
        check("資料庫設定", OK, "%s / %s" % (db.get("server"), db.get("name")))
    return cfg


# ── 3. 外部服務 ─────────────────────────────────
def check_sql(cfg):
    if not cfg:
        return
    db = cfg.get("database", {})
    server, name = db.get("server"), db.get("name")
    if not server:
        return
    try:
        from acqua.sqlcat import raw_query
        rows = raw_query(server, name or "master",
                         "SELECT DB_NAME() AS db, SUSER_NAME() AS usr")
        check("SQL Server", OK, "%s(使用者 %s)"
              % (rows[0]["db"], rows[0]["usr"]))
    except Exception as exc:                                # noqa: BLE001
        check("SQL Server", FATAL, str(exc)[:60],
              "確認 SQL Server 服務有在跑,而且資料庫名稱正確。"
              "不確定機器名的話,啟動後按網頁上的「掃描」")


def check_acqua():
    try:
        import pythoncom
        import win32com.client as w
        pythoncom.CoInitialize()
        app = w.Dispatch("Acqua3.AcquaApplication")
        _ = app.SelectedDatabaseName          # 碰一下確認真的活著
        check("ACQUA", OK, "已連上")
    except Exception as exc:                                # noqa: BLE001
        msg = str(exc)
        hint = "先把 ACQUA 開起來 —— 這個程式是附掛上去的,不會幫你啟動"
        if "無效的類別字串" in msg or "Invalid class string" in msg:
            hint += ";如果 ACQUA 開著仍然這樣,檢查 ACOPT18 授權與 dongle"
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
        check("網頁 port %d" % port, WARN, "已經有東西在用",
              "可能是上一份還開著。要嘛先關掉,要嘛在 .env 改 ACQUA_WEB_PORT")
    except Exception:                                       # noqa: BLE001
        check("網頁 port %d" % port, OK, "可用")


# ── 4. 本地資料 ─────────────────────────────────
def check_storage():
    for sub, why in [("plans", "測試計畫"), ("reports", "報告暫存"),
                     ("runs", "執行紀錄")]:
        p = os.path.join(ROOT, sub)
        try:
            os.makedirs(p, exist_ok=True)
            probe = os.path.join(p, ".write_probe")
            with io.open(probe, "w") as f:
                f.write("x")
            os.unlink(probe)
            n = len([x for x in os.listdir(p) if x.endswith(".json")])
            check("資料夾 %s" % sub, OK, "可寫入(%s ・ %d 筆)" % (why, n))
        except Exception as exc:                            # noqa: BLE001
            check("資料夾 %s" % sub, FATAL, str(exc)[:50],
                  "檢查資料夾權限,或這個路徑是不是在唯讀的位置")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="只印有問題的")
    args = ap.parse_args()

    print("啟動前自檢 ・ %s\n" % ROOT)
    check_python()
    cfg = check_config()
    check_storage()
    check_port(cfg)
    check_sql(cfg)
    check_acqua()
    return report(args.quiet)


if __name__ == "__main__":
    sys.exit(main())
