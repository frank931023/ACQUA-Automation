# -*- coding: utf-8 -*-
"""量測擺位(setup)的本地儲存。

一個 setup = 「這一次量測,房間裡每個東西站在哪裡」。

跟 plans/ 裡的測試計畫是兩回事,刻意分開存:
    測試計畫  要跑哪些測項(ACQUA 那一側的事)
    setup     機構擺在哪裡(天車那一側的事)
同一個 setup 會被好幾個測試計畫共用(例如「近場 0.5 m」跑三批不同測項),
綁在一起的話改一個位置要去改三個計畫檔。

檔案長這樣(setups/<id>.json):

    {
      "id": "20260915-143052-a3f1",
      "name": "近場 0.5 m ・ HATS 前傾 17°",
      "description": "MS Teams Rev05 用",
      "created": "2026-09-15T14:30:52",
      "updated": "2026-09-15T14:31:10",
      "axes": {"hats.mrp": 1.2, "hats.head": 17.0, ...},
      "source": "setup"          ← 這組數字是設定模式畫的,還是實機讀回來的
    }

axes 的鍵就是 acqua/crane.py 的 AXES 鍵,也是 soundproofroom/src/axes.js
的控制項 id。三邊同一組字串 —— 所以存檔能直接餵給天車,不需要任何轉換表。
**改那些 id 會讓存好的 setup 對不上**,要改就得寫搬移。
"""
from __future__ import annotations

import io
import json
import os
import re
import threading
import time
from datetime import datetime

from .crane import AXES

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")
_LOCK = threading.Lock()


def clean_axes(raw) -> dict:
    """只留認得的軸,而且值一律夾到行程內。

    為什麼在存檔這一層就夾:setup 是會被直接送去驅動機構的。存進來一個
    超出行程的數字,問題會在幾天後某次「套用到實機」才爆,而且看起來像
    是天車的錯。寧願存檔當下就修掉並記在 dropped 裡。
    """
    out, dropped = {}, []
    for k, v in (raw or {}).items():
        ax = AXES.get(str(k))
        if ax is None:
            dropped.append(str(k))
            continue
        try:
            out[ax.id] = round(ax.clamp(float(v)), 4)
        except (TypeError, ValueError):
            dropped.append(str(k))
    return {"axes": out, "dropped": dropped}


class RoomSetups:
    def __init__(self, base_dir: str, folder: str = "setups"):
        """base_dir 底下的 setups/。folder 傳空字串就直接用 base_dir 本身 ——
        測試要把資料丟到自己的暫存目錄時用得到。"""
        self.dir = os.path.join(base_dir, folder) if folder else base_dir
        os.makedirs(self.dir, exist_ok=True)

    # ── 內部 ────────────────────────────────────────
    def _path(self, setup_id: str) -> str:
        return os.path.join(self.dir, _SAFE.sub("_", str(setup_id)) + ".json")

    @staticmethod
    def _new_id() -> str:
        return (datetime.now().strftime("%Y%m%d-%H%M%S-")
                + "%04x" % (int(time.time() * 1000) % 0xFFFF))

    def _write(self, data: dict):
        """原子寫入 —— 先寫暫存檔再 replace。半個 JSON 等於整份擺位沒了。"""
        path = self._path(data["id"])
        with _LOCK:
            tmp = path + ".tmp"
            with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        return path

    # ── 對外 ────────────────────────────────────────
    @staticmethod
    def _now() -> str:
        """時間戳到**毫秒**,不是秒。

        清單是「最新的在前」排的。存到秒的話,同一秒內存兩個擺位(改個名字
        再存一次就會)時間戳會一模一樣,排序落回檔名順序 —— 結果最舊的跑到
        最前面。這不是理論問題,實測就會踩到。
        """
        return datetime.now().isoformat(timespec="milliseconds")

    def save(self, *, name="", description="", axes=None, setup_id=None,
             source="setup") -> dict:
        """新增或更新。setup_id 給了就是更新(沿用原本的 created)。"""
        now = self._now()
        cleaned = clean_axes(axes)

        data = self.load(setup_id) if setup_id else None
        if data is None:
            data = {"id": setup_id or self._new_id(), "created": now}

        data.update({
            "name": (name or "").strip() or "(未命名擺位)",
            "description": (description or "").strip(),
            "updated": now,
            "axes": cleaned["axes"],
            "count": len(cleaned["axes"]),
            "source": source,
        })
        if cleaned["dropped"]:
            data["dropped"] = cleaned["dropped"]
        self._write(data)
        return data

    def load(self, setup_id: str):
        path = self._path(setup_id)
        if not os.path.exists(path):
            return None
        try:
            with io.open(path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:                                   # noqa: BLE001
            return None            # 壞檔就當沒有,不要擋住整個清單
        return d if isinstance(d, dict) else None

    def list(self) -> list:
        """所有擺位,最新的排前面。含完整 axes —— 一個 setup 最多 19 個
        浮點數,為了省這點量再多打一趟 API 不值得。"""
        out = []
        for name in os.listdir(self.dir):
            if not name.endswith(".json"):
                continue
            d = self.load(name[:-5])
            if not d:
                continue
            d.setdefault("id", name[:-5])
            d.setdefault("axes", {})
            d["count"] = len(d["axes"])
            out.append(d)
        # id 當最後的比較依據 —— 舊檔的時間戳只有到秒,同秒的還是會撞。
        # id 開頭就是時間,所以拿它排跟時間排是一致的。
        out.sort(key=lambda x: (x.get("updated") or x.get("created") or "",
                                x.get("id") or ""), reverse=True)
        return out

    def delete(self, setup_id: str) -> bool:
        path = self._path(setup_id)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False
