# -*- coding: utf-8 -*-
"""測試計畫(使用者口中的「Project」)的本地儲存。

一個測試計畫 = 「這一批要跑哪些測項 + 當時的 DUT 設定」。

存在本地資料夾,**不寫回 ACQUA 資料庫** —— 這樣:
  ・不會弄髒別人的測項庫
  ・可以隨時刪掉重來
  ・之後要跑同一批,直接叫出來就好

檔案長這樣(plans/<id>.json):

    {
      "id": "20260821-143052-a3f1",
      "title": "Kong 第一輪",
      "description": "個人空間 USB,含 Premium",
      "created": "2026-08-21T14:30:52",
      "database": "...", "project": "...", "measurement_object": "...",
      "hardware_setting": "BK+GRAS Mouth_2talker_v5_HRPF off_251028",
      "variables": {"DUT_speakerphone_type": "Personal", ...},
      "items": [{"row_id": 3579, "title": "..."}, ...],
      "manual_excluded": [...]
    }

「暫存」與「正式儲存」是同一件事 —— 一律先寫檔再說,免得按了開始才發現
剛剛選的東西沒留下來。差別只在 title 有沒有填。
"""
from __future__ import annotations

import io
import json
import os
import re
import time
from datetime import datetime

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


class TestPlans:
    def __init__(self, base_dir: str):
        self.dir = os.path.join(base_dir, "plans")
        os.makedirs(self.dir, exist_ok=True)

    # ── 內部 ────────────────────────────────────────
    def _path(self, plan_id: str) -> str:
        safe = _SAFE.sub("_", str(plan_id))
        return os.path.join(self.dir, f"{safe}.json")

    @staticmethod
    def _new_id() -> str:
        return datetime.now().strftime("%Y%m%d-%H%M%S-") + f"{int(time.time() * 1000) % 0xFFFF:04x}"

    def _write(self, data: dict):
        """原子寫入 —— 先寫暫存檔再 replace,中途斷電不會留半個檔。"""
        path = self._path(data["id"])
        tmp = path + ".tmp"
        with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return path

    # ── 對外 ────────────────────────────────────────
    def save(self, *, title="", description="", items=None, variables=None,
             plan_id=None, **meta) -> dict:
        """新增或更新一個測試計畫。plan_id 給了就是更新。"""
        items = list(items or [])
        now = datetime.now().isoformat(timespec="seconds")

        data = None
        if plan_id:
            data = self.load(plan_id)
        if data is None:
            data = {"id": plan_id or self._new_id(), "created": now}

        data.update({
            "title": (title or "").strip() or "(未命名)",
            "description": (description or "").strip(),
            "updated": now,
            "items": items,
            "count": len(items),
            "variables": dict(variables or {}),
        })
        for k, v in meta.items():
            if v is not None:
                data[k] = v
        self._write(data)
        return data

    def load(self, plan_id: str):
        path = self._path(plan_id)
        if not os.path.exists(path):
            return None
        try:
            with io.open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:                                   # noqa: BLE001
            return None

    def list(self) -> list:
        """所有測試計畫,最新的排前面。只回摘要,不含完整 items。"""
        out = []
        for name in os.listdir(self.dir):
            if not name.endswith(".json"):
                continue
            try:
                with io.open(os.path.join(self.dir, name), encoding="utf-8") as f:
                    d = json.load(f)
            except Exception:                               # noqa: BLE001
                continue
            out.append({
                "id": d.get("id", name[:-5]),
                "title": d.get("title", ""),
                "description": d.get("description", ""),
                "created": d.get("created", ""),
                "updated": d.get("updated", ""),
                "count": d.get("count", len(d.get("items") or [])),
                "project": d.get("project", ""),
                "database": d.get("database", ""),
                "ctx": d.get("ctx", ""),      # 用來判斷能不能在目前專案跑
                "hardware_setting": d.get("hardware_setting", ""),
            })
        out.sort(key=lambda x: x.get("updated") or x.get("created") or "", reverse=True)
        return out

    def delete(self, plan_id: str) -> bool:
        path = self._path(plan_id)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False
