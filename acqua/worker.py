"""COM 工作執行緒。

⭐ 這是整個架構的核心,原因是 COM 與 Flask 的執行緒模型互相衝突:

  - COM 事件需要 STA(單執行緒公寓)+ 持續運轉的訊息幫浦
  - Flask 每個 HTTP 請求跑在不同的執行緒上
  - COM 物件不能隨意跨執行緒使用(要 marshaling)

解法:讓「一條」專屬執行緒獨佔 COM 物件,Flask 只能透過命令佇列跟它溝通。

    瀏覽器 ──HTTP──> Flask(多執行緒)
                        │  submit(命令)
                        ↓
                  [ 命令佇列 Queue ]
                        │
                        ↓
             ⭐ AcquaWorker(單一 STA 執行緒)
                - CoInitializeEx(APARTMENTTHREADED)
                - 獨佔 AcquaApplication 物件
                - 閒置時跑訊息幫浦
                - 唯一碰 COM 的地方
                        │
                        ↓
                  [ SharedState(有鎖)]
                        │
              Flask 讀取 ←┘
"""
import queue
import threading
import traceback

from .state import SharedState


class Command:
    """一個待執行的命令,附帶可等待的結果。"""

    def __init__(self, name: str, kwargs: dict):
        self.name = name
        self.kwargs = kwargs
        self.done = threading.Event()
        self.result = None
        self.error = None

    def wait(self, timeout=None):
        if not self.done.wait(timeout):
            raise TimeoutError(f"命令逾時:{self.name}")
        if self.error:
            raise self.error
        return self.result


class AcquaWorker(threading.Thread):
    def __init__(self, backend_factory, state: SharedState, config: dict):
        super().__init__(name="acqua-com-worker", daemon=True)
        self._q = queue.Queue()
        self._backend_factory = backend_factory
        self._config = config
        self.state = state
        self.backend = None
        self._stop = threading.Event()
        self.ready = threading.Event()
        self.init_error = None

    # ── 給 Flask 執行緒呼叫 ──────────────────────────
    def submit(self, name: str, **kwargs) -> Command:
        """把命令排進佇列。非阻塞 —— 呼叫端要不要 .wait() 自己決定。"""
        cmd = Command(name, kwargs)
        self._q.put(cmd)
        return cmd

    def request_cancel(self):
        """中止不走佇列 —— 因為 run 正在阻塞工作執行緒,佇列排不進去。

        直接設旗標,由 backend.run_smds 的迴圈自己檢查。
        對 bool 做跨執行緒讀寫在 CPython 是安全的。
        """
        self.state.set(cancel_requested=True)
        self.state.log("已送出中止要求 —— 會在當前這筆測項結束後生效", "warn")

    def stop(self):
        self._stop.set()

    # ── 工作執行緒本體 ──────────────────────────────
    def run(self):
        try:
            self.backend = self._backend_factory(self.state, self._config)
            self.backend.initialize()
            self.ready.set()
        except Exception as exc:                       # noqa: BLE001
            self.init_error = exc
            self.state.log(f"後端初始化失敗:{exc}", "error")
            self.state.log(traceback.format_exc(), "error")
            self.ready.set()
            return

        while not self._stop.is_set():
            try:
                cmd = self._q.get(timeout=0.05)
            except queue.Empty:
                # 沒事做的時候打訊息幫浦 —— COM 事件靠這個進來
                try:
                    self.backend.pump()
                except Exception as exc:               # noqa: BLE001
                    self.state.log(f"訊息幫浦錯誤:{exc}", "error")
                continue

            self._dispatch(cmd)

        try:
            self.backend.shutdown()
        except Exception:                              # noqa: BLE001
            pass

    def _dispatch(self, cmd: Command):
        handlers = {
            "connect": lambda **kw: self.backend.connect(**kw),
            "list_databases": lambda **kw: self.backend.list_databases(**kw),
            "refresh_groups": lambda **kw: self.backend.refresh_project_groups(),
            "open_project": lambda **kw: self.backend.open_project(**kw),
            "select_mo": lambda **kw: self.backend.select_measurement_object(**kw),
            "write_metadata": lambda **kw: self.backend.write_metadata(**kw),
            "list_smds": lambda **kw: self.backend.list_smds(**kw),
            "run_smds": lambda **kw: self.backend.run_smds(**kw),
            "create_report": lambda **kw: self.backend.create_report(**kw),
            # ⭐ 混合模式
            "list_variables": lambda **kw: self.backend.list_variables(),
            "set_variables": lambda **kw: self.backend.set_variables(**kw),
            "run_all": lambda **kw: self.backend.run_all(),
            "predict_run_set": lambda **kw: self.backend.predict_run_set(**kw),
            "read_results": lambda **kw: self.backend.read_results(**kw),
        }
        handler = handlers.get(cmd.name)
        try:
            if handler is None:
                raise ValueError(f"未知的命令:{cmd.name}")
            cmd.result = handler(**cmd.kwargs)
        except Exception as exc:                       # noqa: BLE001
            cmd.error = exc
            self.state.log(f"命令 {cmd.name} 失敗:{exc}", "error")
            self.state.log(traceback.format_exc(), "error")
        finally:
            cmd.done.set()


def make_worker(config: dict, state: SharedState) -> AcquaWorker:
    kind = str(config.get("backend", "mock")).lower()
    if kind == "com":
        from .backend_com import ComBackend
        factory = ComBackend
    elif kind == "mock":
        from .backend_mock import MockBackend
        factory = MockBackend
    else:
        raise ValueError(f"config.backend 只能是 'mock' 或 'com',收到:{kind!r}")
    return AcquaWorker(factory, state, config)
