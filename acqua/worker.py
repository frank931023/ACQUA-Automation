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
        #: 正在執行的命令名稱(閒置時為 None)。
        #: 用來分辨「state.running 是真的在跑」還是「上一輪死掉留下的旗標」。
        self._running_cmd = None

    # ── 給 Flask 執行緒呼叫 ──────────────────────────
    def submit(self, _name: str, **kwargs) -> Command:
        """把命令排進佇列。非阻塞 —— 呼叫端要不要 .wait() 自己決定。

        參數名加底線前綴:指令的 kwargs 裡本來就可能有 name
        (例如 set_hardware(name=...)),同名會撞成 TypeError。
        """
        cmd = Command(_name, kwargs)
        self._q.put(cmd)
        return cmd

    def busy(self) -> bool:
        """工作執行緒現在真的在執行命令嗎?

        state.running 是 backend 自己設的旗標 —— 行程被砍或例外沒收乾淨時
        會留下 True。要判斷「殘留」還是「真的在跑」得看這裡。
        """
        return self._running_cmd is not None

    def running_command(self):
        return self._running_cmd

    def request_cancel(self):
        """中止不走佇列 —— 因為 run 正在阻塞工作執行緒,佇列排不進去。

        直接設旗標,由 backend.run_smds 的迴圈自己檢查。
        逐項模式下這是**真的中止** —— 排隊的是 Python 的 for 迴圈,
        不送下一筆就結束了。在途的那一筆會跑完(強行打斷會留半筆資料)。
        對 bool 做跨執行緒讀寫在 CPython 是安全的。
        """
        self.state.set(cancel_requested=True, paused=False)
        self.state.log("■ 已送出中止 —— 目前這筆跑完就停,不會再送下一筆", "warn")

    def request_pause(self):
        """暫停。逐項模式停在兩筆之間;整批模式停止關對話框。"""
        self.state.set(paused=True)
        self.state.log("⏸ 已暫停", "warn")

    def request_resume(self):
        """從暫停恢復。跟 request_cancel 一樣不走佇列。

        暫停的實作是「停掉視窗監看器」,恢復就是把它開回來 ——
        run_smds 的迴圈每一圈都會比對這個旗標。
        """
        self.state.set(cancel_requested=False, paused=False)
        self.state.log("▶ 已繼續", "info")

    def answer_blocking(self, hwnd, action):
        """回答 ACQUA 的阻塞對話框。**不走佇列**。

        原因跟 request_cancel 一樣:run_smds 正在阻塞這條執行緒,
        排進佇列的命令要等整批跑完才會被處理 —— 但阻塞視窗偏偏只在
        量測進行中才出現,排隊等於永遠不會被回答。

        安全性:只碰 Win32 訊息與 winwatch 內部有鎖的 dict,不碰 COM,
        所以不需要在 STA 執行緒上執行。
        """
        if self.backend is None:
            return False
        return self.backend.answer_blocking_window(hwnd, action)

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

            self._running_cmd = cmd.name
            try:
                self._dispatch(cmd)
            finally:
                self._running_cmd = None

        # 收工時如果還在跑,講清楚 —— 事件接收端一死,ACQUA 會卡在
        # IsMeasuring=True 回不來(2026-08-17 實測過)。
        if self.state.running:
            self.state.log(
                "⚠️ 工作執行緒結束時仍有量測在進行 —— "
                "ACQUA 可能會停在 IsMeasuring=True。"
                "請到 ACQUA 視窗確認並取消。", "error")
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
            "create_report": lambda **kw: self.backend.create_report(**kw),
            # ⭐ 混合模式
            "list_variables": lambda **kw: self.backend.list_variables(),
            "set_variables": lambda **kw: self.backend.set_variables(**kw),
            # 開跑前的歸屬驗證(同步呼叫,錯誤要能回到 HTTP)
            "check_rows": lambda **kw: self.backend.check_rows(**kw),
            "run_smds": lambda **kw: self.backend.run_smds(**kw),
            "answer_blocking": lambda **kw: self.backend.answer_blocking_window(**kw),
            "wizard_options": lambda **kw: self.backend.wizard_options(),
            "list_hardware": lambda **kw: self.backend.list_hardware_settings(),
            "set_hardware": lambda **kw: self.backend.set_hardware_setting(**kw),
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
