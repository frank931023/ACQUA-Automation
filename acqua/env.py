# -*- coding: utf-8 -*-
"""機器專屬的設定,從 .env 讀進來蓋掉 config.json。

為什麼要分兩個檔
────────────────
兩種設定的生命週期完全不同:

    config.json   **行為**設定 —— 哪些視窗要自動關、哪些測項需人工、
                  逾時多久。每一台機器都一樣,應該進版控、一起演進。

    .env          **這一台機器**的事實 —— SQL Server 叫什麼、
                  資料庫名稱、帳密、要開在哪個 port、報告放哪。
                  換一台機器就全部要改,而且含密碼,不該進版控。

混在一起的後果是:換機器要在一個大 JSON 裡東改西改,而且很容易
不小心把密碼推上去。

用法
────
    複製 .env.example 成 .env,改裡面的值。沒有 .env 也能跑 ——
    那就完全照 config.json,跟以前一樣。

    環境變數本身優先權最高(適合 CI 或臨時覆寫):
        set ACQUA_DB_NAME=別的庫 && python app.py
"""
from __future__ import annotations

import io
import os

#: 環境變數 → config.json 裡的位置。這張表就是「哪些東西算機器專屬」的定義。
MAPPING = {
    "ACQUA_BACKEND":          ("backend",),
    "ACQUA_DB_SERVER":        ("database", "server"),
    "ACQUA_DB_NAME":          ("database", "name"),
    "ACQUA_DB_WINDOWS_AUTH":  ("database", "use_windows_auth"),
    "ACQUA_DB_USER":          ("database", "username"),
    "ACQUA_DB_PASSWORD":      ("database", "password"),
    "ACQUA_WEB_HOST":         ("web", "host"),
    "ACQUA_WEB_PORT":         ("web", "port"),
    "ACQUA_REPORT_DIR":       ("report", "output_dir"),
    # 未來:序列中間的「移動治具」會發 HTTP 給這個控制器
    "ACQUA_SETUP_CONTROLLER": ("setup_controller", "url"),
}

#: 這幾個要轉型,不然 port 會變成字串、旗標會變成 "0" 這種永遠為真的東西
_BOOL = {"ACQUA_DB_WINDOWS_AUTH"}
_INT = {"ACQUA_WEB_PORT"}


def load_dotenv(path=".env") -> dict:
    """讀 .env。格式就是 KEY=VALUE,# 開頭是註解。

    刻意不依賴 python-dotenv —— 這個專案跑在 HEAD 附的 Python 上,
    能少一個套件就少一個移植時的變數。
    """
    out = {}
    if not os.path.exists(path):
        return out
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            # 允許 KEY="有空白的值"
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[k.strip()] = v
    return out


def _cast(key, raw):
    if key in _BOOL:
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if key in _INT:
        try:
            return int(raw)
        except ValueError:
            return raw
    return raw


def apply_to(config: dict, path=".env") -> list:
    """把 .env 與環境變數套進 config。回傳「改了哪些」給呼叫端寫進 log。

    優先權:真正的環境變數 > .env > config.json
    這個順序是刻意的 —— CI 或臨時覆寫不該被檔案蓋掉。
    """
    dotenv = load_dotenv(path)
    applied = []
    for key, where in MAPPING.items():
        raw = os.environ.get(key, dotenv.get(key))
        if raw is None or raw == "":
            continue                    # 空值 = 沒設定,不要蓋掉 config
        node = config
        for part in where[:-1]:
            node = node.setdefault(part, {})
        node[where[-1]] = _cast(key, raw)
        src = "環境變數" if key in os.environ else ".env"
        # 密碼不進 log
        shown = "***" if "PASSWORD" in key else node[where[-1]]
        applied.append("%s=%s(%s)" % (key, shown, src))
    return applied
