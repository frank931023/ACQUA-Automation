"""ACQUA 測試自動化 —— COM 介面封裝層。"""

from .state import SharedState
from .worker import AcquaWorker, make_worker

__all__ = ["SharedState", "AcquaWorker", "make_worker"]
