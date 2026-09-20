"""後端介面定義。

兩個實作:
  backend_mock.py — 模擬,不需要 ACQUA。用來開發 Web UI 與流程邏輯。
  backend_com.py  — 真實連接 ACQUA COM。

所有方法都只會在 COM 工作執行緒上被呼叫,實作時不需要自己加鎖
(除了讀取 state.cancel_requested,那是別的執行緒寫的,但 bool 讀取是安全的)。
"""
from abc import ABC, abstractmethod

from .state import SharedState


class AcquaBackend(ABC):
    def __init__(self, state: SharedState, config: dict):
        self.state = state
        self.config = config

    # ── 生命週期 ────────────────────────────────────
    @abstractmethod
    def initialize(self) -> None:
        """在工作執行緒上初始化(CoInitialize、建立 COM 物件、等待 ACQUA 啟動)。"""

    @abstractmethod
    def pump(self) -> None:
        """訊息幫浦。工作執行緒閒置時會頻繁呼叫,必須是非阻塞的。"""

    @abstractmethod
    def shutdown(self) -> None:
        ...

    # ── 操作 ────────────────────────────────────────
    @abstractmethod
    def connect(self, server: str, database: str, win_auth: bool,
                username: str = "", password: str = "") -> bool:
        ...

    @abstractmethod
    def list_databases(self, server: str) -> list:
        """列出伺服器上的資料庫。不需要先連線 ACQUA。"""

    @abstractmethod
    def refresh_project_groups(self) -> list:
        """回傳 [{"name": str, "projects": [str]}]"""

    @abstractmethod
    def open_project(self, group: str, project: str) -> None:
        """SelectAsActive + 等待 SelectedProjectLoaded"""

    @abstractmethod
    def select_measurement_object(self, title: str, create_if_missing: bool = True) -> None:
        ...

    @abstractmethod
    def write_metadata(self, props: dict) -> None:
        """透過 IAcquaBaseObject.UpdateProperty 寫入自訂欄位。"""

    @abstractmethod
    def list_smds(self, search: str = "") -> list:
        """回傳 [{"row_id": int, "title": str}]。search 為空表示「全部」。"""


    @abstractmethod
    def create_report(self, output_path: str, selection_type: int) -> None:
        ...

    # ── ⭐ 混合模式:變數驅動 ────────────────────────
    @abstractmethod
    def list_variables(self) -> list:
        """回傳 [{"name","value","type","state","state_text","comment"}]。"""

    @abstractmethod
    def set_variables(self, values: dict) -> int:
        """寫入/更新 ACQUA 變數,回傳成功筆數。

        這些變數會被專案樹的 ConditionalExecution 讀取,決定哪些 SMD 會被執行。
        """

    @abstractmethod
    def read_results(self, latest_only: bool = True, smd_row_ids=None) -> list:
        """讀出量測的實際數值(含極限值)。Acqua3 介面做不到,走 SQL。"""

    @abstractmethod
    def predict_run_set(self, variables: dict) -> dict:
        """不啟動量測,預測這組變數會跑哪些測項。"""

    @abstractmethod
    def run_smds(self, row_ids: list) -> None:
        """⭐ 逐項執行指定的測項(StartSingleMeasurement)。

        實作必須:
          - 每一輪檢查 self.state.cancel_requested(中止)與 self.state.paused(暫停)
          - 等待時持續呼叫 self.pump()
          - 每筆結果呼叫 self.state.add_result(...)

        中止在這裡是**真的中止** —— 排隊的是 Python 迴圈,不送下一筆就停了。
        """

    @abstractmethod
    def run_measurements(self, variables: dict = None) -> None:
        """⭐ 唯一的執行入口:整批跑(StartMeasurements)。

        搭配 set_variables() 使用 —— ACQUA 會依 ConditionalExecution
        自動略過不符條件的 SMD,所以實際跑的是變數篩選後的子集。

        實作必須:
          - 阻塞工作執行緒直到跑完或被暫停
          - 等待時持續呼叫 self.pump()
          - 每筆結果呼叫 self.state.add_result(...)

        ⚠️ 不再有「逐項執行」。實測 pywin32 的 ByRef 回傳送不到 ACQUA,
           所以 UserReaction 無法控制流程;範圍改由變數條件決定,
           流程停走改由 acqua/winwatch.py 控制。
        """

    def answer_blocking_window(self, hwnd, action) -> bool:
        """回覆擋住流程的 ACQUA 對話框。沒有視窗監看能力的後端回 False。"""
        return False

    def wizard_options(self) -> list:
        """從專案樹反推精靈選項。回傳 [{title, items:[{name,kind,values,used_by}]}]。"""
        return []

    def list_hardware_settings(self) -> list:
        """列出硬體設定 [{"name","active","saved"}]。"""
        return []

    def set_hardware_setting(self, name: str) -> list:
        """切換硬體設定。"""
        return []

    def active_hardware_setting(self):
        """目前選用的硬體設定名稱。"""
        return None

    # ── 需要人工操作的測項 ──────────────────────────
    # 兩個後端本來各有一份一模一樣的實作。判斷規則只跟 config 有關,
    # 跟走 COM 還是模擬完全無關,所以放在這裡。
    def _classifier(self):
        """回傳一個函式:這個測項屬於哪一類。

        兩層,因為「會不會開視窗」沒有單一欄位可以判斷:

            "manual"  已確認會開視窗(標題在設定裡)。自動勾選一律排除,
                      否則整批就沒辦法無人值守。
            "script"  SMDType 是腳本型別但沒被確認。**照常可跑** ——
                      實測 ZoomRooms 的 `switch devices`(同樣是腳本)
                      跑得完且不開任何視窗。只在開跑前提醒。
            ""        一般測項。

        為什麼不能只靠標題:盤點發現三個已確認的互動項全是 SMDType 43,
        但同樣是 43 的 `Select automatic/manual volume control` 卻不在
        清單裡 —— 靠人維護標題清單一定會漏。
        為什麼不能只靠型別:43 只代表「腳本」,不代表一定互動。
        """
        import fnmatch
        m = self.config.get("manual_items") or {}
        titles = {str(x).strip() for x in (m.get("titles") or [])}
        pats = [str(x) for x in (m.get("title_patterns") or [])]
        script_types = {int(x) for x in (m.get("script_smd_types") or [])}

        def classify(smd):
            t = (smd.get("title") or "").strip()
            if t in titles or any(fnmatch.fnmatch(t, p) for p in pats):
                return "manual"
            if int(smd.get("smd_type", -1)) in script_types:
                return "script"
            return ""
        return classify

    def _manual_matcher(self):
        """只看標題判斷「要不要人工操作」—— 拿不到 SMDType 時用。"""
        classify = self._classifier()
        return lambda title: classify({"title": title}) == "manual"
