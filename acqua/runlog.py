"""執行紀錄的持久化 —— 讓「上次跑到一半」在重開網頁/重啟伺服器後還找得回來。

為什麼需要:`SharedState` 全部在記憶體裡,伺服器一關就沒了。但一批量測可能跑幾小時,
中途關掉瀏覽器、伺服器重啟、或機器當掉都很常見。

做法:每完成一筆就寫進 `runs/current.json`(小檔、原子寫入),
      整批結束才標記 finished。下次開頁面時讀它,就知道有沒有跑一半的。
"""
import json
import os
import tempfile
import time
import threading

_LOCK = threading.RLock()


class RunLog:
    def __init__(self, base_dir: str):
        self.dir = os.path.join(base_dir, "runs")
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, "current.json")

    # ── 寫入 ────────────────────────────────────────
    def _write(self, data: dict):
        """原子寫入 —— 先寫暫存檔再 replace,避免中途斷電留下半個檔。"""
        with _LOCK:
            fd, tmp = tempfile.mkstemp(dir=self.dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            except Exception:                               # noqa: BLE001
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise

    def start(self, *, mode, database, project_group, project,
              measurement_object, planned, comment=""):
        """開跑時建立紀錄。planned = [{row_id, title}]

        `comment` 是這一批的名稱(使用者自己取的)—— 它同時是傳給 ACQUA 的
        ResultComment,所以事後能拿它去 ACQUA 對照同一批結果。
        """
        self._write({
            "state": "running",
            "mode": mode,
            "comment": comment,
            "database": database,
            "project_group": project_group,
            "project": project,
            "measurement_object": measurement_object,
            "started_at": time.time(),
            "updated_at": time.time(),
            "planned": planned,
            "done": [],
        })

    def record(self, row_id, title, status_name, passed, retries=0,
               code=None, path=""):
        """每完成一筆就寫一次 —— 這樣任何時間點斷掉都知道跑到哪。"""
        d = self.load() or {}
        if not d:
            return
        d["done"].append({
            "row_id": int(row_id), "title": title,
            "status": status_name,
            "code": (int(code) if code is not None else None),
            "path": path or "",
            "passed": bool(passed),
            "retries": retries, "ts": time.time(),
        })
        d["updated_at"] = time.time()
        self._write(d)

    def finish(self, canceled=False):
        d = self.load()
        if not d:
            return
        d["state"] = "canceled" if canceled else "finished"
        d["updated_at"] = time.time()
        self._write(d)

    # ── 讀取 ────────────────────────────────────────
    def load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def unfinished(self):
        """回傳「還沒跑完」的紀錄,附上剩下哪些沒跑。沒有就回 None。

        判定為未完成的情況:
          - state 還是 running(伺服器被砍掉、當機)
          - state 是 canceled 但還有沒跑的項目
        """
        d = self.load()
        if not d:
            return None
        if d.get("state") == "finished":
            return None

        done_ids = {x["row_id"] for x in d.get("done", [])}
        remaining = [p for p in d.get("planned", []) if p["row_id"] not in done_ids]
        if not remaining:
            return None

        failed = [x for x in d.get("done", []) if not x.get("passed")]
        return {
            **{k: d.get(k) for k in ("state", "mode", "database", "project_group",
                                     "project", "measurement_object",
                                     "started_at", "updated_at")},
            "total": len(d.get("planned", [])),
            "done_count": len(done_ids),
            "failed_count": len(failed),
            "remaining_count": len(remaining),
            "remaining": remaining,
            "done": d.get("done", []),
        }

    def clear(self):
        try:
            os.unlink(self.path)
        except OSError:
            pass
