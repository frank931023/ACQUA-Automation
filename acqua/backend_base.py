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
    def run_smds(self, row_ids: list) -> None:
        """依序執行指定的 SMD。這個方法會阻塞工作執行緒直到跑完或被取消。

        實作必須:
          - 每一輪檢查 self.state.cancel_requested
          - 等待時持續呼叫 self.pump()
          - 每筆結果呼叫 self.state.add_result(...)
        """

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
    def run_all(self) -> None:
        """跑「整個專案」(StartMeasurements)。

        搭配 set_variables() 使用 —— ACQUA 會依 ConditionalExecution
        自動略過不符條件的 SMD,所以實際跑的是變數篩選後的子集。
        """
