"""執行緒安全的共用狀態。

COM 工作執行緒「寫」,Flask 的請求執行緒「讀」。
這是兩邊唯一的資料交會點 —— Flask 執行緒絕對不可以直接碰 COM 物件。
"""
import threading
import time
from collections import deque


class SharedState:
    def __init__(self, max_events: int = 2000):
        self._lock = threading.RLock()
        self._seq = 0
        self._events = deque(maxlen=max_events)

        # 連線
        self.backend_kind = "unknown"
        self.acqua_ready = False
        self.connected = False
        self.server = None
        self.database = None
        self.databases = []            # [{name, is_acqua, online, smds, mmds, results}]

        # 階層
        self.project_groups = []       # [{"name": str, "projects": [str]}]
        self.open_group = None
        self.open_project = None
        self.measurement_object = None

        # 測項
        self.smds = []                 # [{"row_id": int, "title": str}]

        # ⭐ 混合模式:ACQUA 變數(條件執行的依據)
        self.variables = []            # [{"name","value","type","state","state_text"}]
        self.run_mode = "selected"     # selected | conditional
        self.prediction = None         # 變數驅動的事前預測結果

        # 數值結果(走 SQL 讀回來的,含極限值)
        self.values = []               # [{smd, dut, status, values:[...]}]

        #: 執行紀錄(持久化)—— 由 app.py 在啟動時注入
        self.runlog = None

        # 執行狀態
        self.running = False
        self.cancel_requested = False
        self.current = None            # {"title": str, "index": int, "total": int}
        self.progress = None           # {"text": str, "value": int, "total": int}
        self.results = []              # [{"title","row_id","status","passed","retries","ts"}]

    # ── 事件串流(給 SSE 用)──────────────────────────
    def emit(self, kind: str, **payload):
        with self._lock:
            self._seq += 1
            self._events.append({"seq": self._seq, "kind": kind, "ts": time.time(), **payload})

    def events_since(self, seq: int):
        with self._lock:
            return [e for e in self._events if e["seq"] > seq]

    def log(self, text: str, level: str = "info"):
        self.emit("log", text=text, level=level)

    # ── 快照 ────────────────────────────────────────
    def snapshot(self) -> dict:
        with self._lock:
            passed = sum(1 for r in self.results if r["passed"])
            return {
                "backend": self.backend_kind,
                "acqua_ready": self.acqua_ready,
                "connected": self.connected,
                "server": self.server,
                "database": self.database,
                "databases": self.databases,
                "project_groups": self.project_groups,
                "open_group": self.open_group,
                "open_project": self.open_project,
                "measurement_object": self.measurement_object,
                "smds": self.smds,
                "variables": self.variables,
                "run_mode": self.run_mode,
                "prediction": self.prediction,
                "values": self.values,
                "running": self.running,
                "cancel_requested": self.cancel_requested,
                "current": self.current,
                "progress": self.progress,
                "results": self.results,
                "summary": {
                    "total": len(self.results),
                    "passed": passed,
                    "failed": len(self.results) - passed,
                },
                "seq": self._seq,
            }

    # ── 供工作執行緒更新 ─────────────────────────────
    def set(self, **kw):
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)
        self.emit("state")

    def add_result(self, title, row_id, status, passed, retries=0):
        with self._lock:
            self.results.append({
                "title": title, "row_id": row_id, "status": status,
                "passed": bool(passed), "retries": retries, "ts": time.time(),
            })
        self.emit("result", title=title, passed=bool(passed), status=status)

    def clear_results(self):
        with self._lock:
            self.results = []
        self.emit("state")
