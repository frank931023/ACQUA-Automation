# -*- coding: utf-8 -*-
"""記住「每個資料庫上次用什麼」—— 讓換庫不必每次重點四遍。

為什麼需要
──────────
換資料庫會把所有繫於舊上下文的東西作廢(見 acqua/context.py),那是對的。
但作廢的代價是使用者得重新:選專案 → 選量測物件 → 載入測項。
在兩個庫之間來回時特別煩。

所以這裡記住每個 (server, database) 上次開的是什麼,連上就接回去。
記的是「意圖」(標題),不是 row_id —— 標題跨庫比對才有意義,
而且接回去的每一步都會重新驗證,對不上就跳過,不會硬套。

檔案:prefs.json
    {
      "by_database": {
        "SERVER|DB": {"group": "...", "project": "...", "mo": "...",
                      "used": "2026-08-21T18:00:00"}
      },
      "report_dir": "D:/報告/2026"
    }
"""
from __future__ import annotations

import io
import json
import os
import threading
from datetime import datetime

_LOCK = threading.Lock()


class Prefs:
    def __init__(self, base_dir: str):
        self.path = os.path.join(base_dir, "prefs.json")

    # ── 讀寫 ────────────────────────────────────────
    def load(self) -> dict:
        try:
            with io.open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:                                   # noqa: BLE001
            return {}                                       # 壞檔就當沒有,不要擋住流程

    def _save(self, d: dict):
        """原子寫入 —— 這個檔隨時可能被覆寫,不值得為半個檔冒風險。"""
        with _LOCK:
            tmp = self.path + ".tmp"
            with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)

    # ── 每個資料庫上次用什麼 ────────────────────────
    @staticmethod
    def _key(server, database) -> str:
        return "{0}|{1}".format(server or "", database or "")

    def remember(self, server, database, **kw):
        """記下 group / project / mo。只更新給了值的欄位。"""
        d = self.load()
        by = d.setdefault("by_database", {})
        cur = by.setdefault(self._key(server, database), {})
        for k, v in kw.items():
            if v:
                cur[k] = v
        cur["used"] = datetime.now().isoformat(timespec="seconds")
        self._save(d)

    def recall(self, server, database) -> dict:
        return (self.load().get("by_database") or {}).get(
            self._key(server, database)) or {}

    def forget(self, server, database):
        d = self.load()
        (d.get("by_database") or {}).pop(self._key(server, database), None)
        self._save(d)

    # ── 報告存放位置 ────────────────────────────────
    def report_dir(self) -> str:
        return str(self.load().get("report_dir") or "")

    def set_report_dir(self, path):
        d = self.load()
        d["report_dir"] = str(path or "")
        self._save(d)
