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


def new_setup(name="", note="", params=None) -> dict:
    """一個「setup 位置」。

    ⚠️ 細節尚未底定 —— 未來會對應 soundproofroom 的座標,由 Flask 發 HTTP
       給 Raspberry Pi 驅動馬達。現在只存下來並在執行序列中間停下來等人,
       等規格定了再把 params 接上去,不用改動計畫檔的結構。
    """
    return {"name": name or "", "note": note or "",
            "params": dict(params or {}),
            "_note": "尚未自動化:目前只會在序列中間停下來提示人工調整"}


def source_of(snap) -> dict:
    """從目前狀態記下「這批測項是在哪裡挑的」。

    ・ctx        判斷能不能直接用 row_id(同專案才行)
    ・database   跨庫執行時知道要切到哪裡
    ・指紋       判斷專案樹在存檔之後有沒有被動過 ——
                 測項的序號是依樹狀順序算的,樹一改就整組位移,
                 而位移之後身分鍵**仍然對得上**,只是對到別的測項。
                 沒有這個獨立證據就察覺不到。
    """
    from .sqlcat import fingerprint_of
    return {
        "server": snap.get("server"), "database": snap.get("database"),
        "group": snap.get("open_group"), "project": snap.get("open_project"),
        "measurement_object": snap.get("measurement_object"),
        "ctx": snap.get("ctx"),
        "tree_fingerprint": fingerprint_of(snap.get("smds") or []),
    }


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
        # setup 沒給就保留原本的(編輯標題時不該把位置設定洗掉)
        data.setdefault("setup", new_setup())
        self._write(data)
        return data

    @staticmethod
    def _migrate(d: dict) -> dict:
        """把舊格式補成新格式。

        舊檔把 database / project 攤在最上層,而且測項只有 row_id + title。
        缺路徑就沒辦法跨庫對應 —— 但至少用名稱還能對,所以不丟掉舊檔,
        只是把欄位搬到 source 底下,讓後面的程式只需要認一種形狀。
        """
        if not isinstance(d, dict):
            return d
        # 用 falsy 判斷而不是「有沒有這個鍵」—— 實測有計畫檔存成
        # "source": null,那種情況一樣要從舊的扁平欄位補回來。
        if not d.get("source"):
            d["source"] = {
                "server": d.get("server"), "database": d.get("database"),
                "group": d.get("project_group"), "project": d.get("project"),
                "measurement_object": d.get("measurement_object"),
                "ctx": d.get("ctx"),
            }
        d.setdefault("setup", new_setup())
        d["items"] = [dict(x) if isinstance(x, dict) else {"row_id": x}
                      for x in (d.get("items") or [])]
        return d

    def load(self, plan_id: str):
        path = self._path(plan_id)
        if not os.path.exists(path):
            return None
        try:
            with io.open(path, encoding="utf-8") as f:
                return self._migrate(json.load(f))
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
            d = self._migrate(d)
            src = d.get("source") or {}
            out.append({
                "id": d.get("id", name[:-5]),
                "source": src,
                "setup": d.get("setup") or {},
                "title": d.get("title", ""),
                "description": d.get("description", ""),
                "created": d.get("created", ""),
                "updated": d.get("updated", ""),
                "count": d.get("count", len(d.get("items") or [])),
                # 這三個保留扁平欄位 —— 舊頁面與舊計畫檔都還在讀
                "project": src.get("project") or "",
                "database": src.get("database") or "",
                "ctx": src.get("ctx") or "",
            })
        out.sort(key=lambda x: x.get("updated") or x.get("created") or "", reverse=True)
        return out

    def delete(self, plan_id: str) -> bool:
        path = self._path(plan_id)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False
