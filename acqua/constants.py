"""ACQUA COM 介面的列舉常數。

✅ 全部數值已從本機安裝的 ACQUA 6.2.210 TypeLib 實測取得(2026-08-05)
   工具:tools/dump_typelib.py(唯讀走訪,不啟動 ACQUA)

⚠️ 與 Acqua3COM.chm(2012 年版)的差異已標記 —— CHM 有數處已經過時。
"""


class EMEEventType:
    """來源:Acqua3 TypeLib。OnEvent 的事件分級。"""
    INFORMATION = 0
    WARNING = 1
    ERROR = 2

    NAMES = {0: "INFO", 1: "WARN", 2: "ERROR"}


class EMEResult:
    """來源:HEADACQUAlyzer TypeLib。單筆量測的結果狀態。

    ⚠️ IGNORE (7) 與 DONE_NOT_OK_NOT_REQUIRED (8) 是 CHM 與 VB 範例都沒有的。
       DONE_NOT_OK_NOT_REQUIRED 特別重要 —— 它代表「沒過,但這項不是必要的」,
       判定時應該視為「不算失敗」,否則會產生假的 FAIL。
    """
    UNDEFINED = 0
    MEAS_DONE = 1
    MEAS_DONE_OK = 2                   # ← PASS
    MEAS_DONE_NOT_OK = 3               # ← FAIL
    MEAS_ERROR = 4
    USER_CANCELED = 5
    MEAS_NOT_POSSIBLE = 6
    IGNORE = 7                         # ← CHM 未記載
    MEAS_DONE_NOT_OK_NOT_REQUIRED = 8  # ← CHM 未記載

    _NAMES = {
        0: "Undefined", 1: "Done", 2: "OK", 3: "Not OK", 4: "Error",
        5: "User canceled", 6: "Not possible", 7: "Ignored",
        8: "Not OK (not required)",
    }

    #: 視為通過的狀態。DONE 代表「量測完成但沒有判定條件」,
    #: NOT_OK_NOT_REQUIRED 代表「沒過但非必要項」—— 兩者都不該算失敗。
    PASSING = frozenset({MEAS_DONE, MEAS_DONE_OK, IGNORE,
                         MEAS_DONE_NOT_OK_NOT_REQUIRED})

    # ── 我們自己標的狀態 ────────────────────────────
    #: ACQUA 沒有發結果事件時,由 run_smds 自己補的狀態。
    #: 刻意用負數 —— 跟 ACQUA 的 0-8 混在同一個號碼空間會分不出誰說的。
    NO_RESULT = -1        # 等到逾時都沒收到結果事件(純文件類的 Info 常這樣)
    BUSY      = -2        # ACQUA 持續忙碌,這一筆根本沒送出去
    EXCEPTION = -3        # 送出或等待時我們這邊丟了例外

    _OURS = {
        -1: "NoResult", -2: "Busy", -3: "Exception",
    }

    #: 「不知道」而不是「沒過」。NoResult 先前被算成 PASS —— 那是過度樂觀,
    #: 現在歸在未通過那一側,但用這個集合讓 UI 能標明它不是判定失敗。
    UNKNOWN = frozenset({NO_RESULT})

    @classmethod
    def is_ours(cls, status) -> bool:
        return int(status) < 0

    @classmethod
    def all_names(cls) -> dict:
        """{狀態碼: 名稱} —— ACQUA 的 0-8 加上我們自己標的負數。"""
        d = dict(cls._NAMES)
        d.update(cls._OURS)
        return d


    @classmethod
    def is_pass(cls, status) -> bool:
        return int(status) in cls.PASSING


    @classmethod
    def describe(cls, status) -> str:
        s = int(status)
        if s in cls._OURS:
            return cls._OURS[s]
        return cls._NAMES.get(s, f"Unknown({status})")


class EVariableType:
    """來源:HEADACQUAlyzer TypeLib。ACQUA 變數的資料型別。

    設 IVariable.Type 時用。⚠️ 型別跟 Value 必須相符,否則 ACQUA 讀不出來。
    """
    DOUBLE = 0
    BOOLEAN = 1
    STRING = 2
    INTEGER = 3
    CHANNEL_LIST = 4

    @classmethod
    def infer(cls, value):
        """從 Python 值推斷該用哪個 ACQUA 型別。注意 bool 要先於 int 判斷。"""
        if isinstance(value, bool):
            return cls.BOOLEAN
        if isinstance(value, int):
            return cls.INTEGER
        if isinstance(value, float):
            return cls.DOUBLE
        return cls.STRING


class EVariableState:
    """來源:HEADACQUAlyzer TypeLib。變數的來源狀態。

    自動化寫進去的值應該標成 USER_DEFINED —— 跟量測產生的值(MEASURED)區分開。
    """
    UNDEFINED = 0
    MEASURED = 1
    USER_DEFINED = 2

    _NAMES = {0: "未定義", 1: "量測產生", 2: "使用者設定"}

    @classmethod
    def describe(cls, s):
        return cls._NAMES.get(int(s), f"Unknown({s})")


# 本機註冊表實測(2026-08-05)。其他 ProgID / TypeLib GUID 見 ACQUA_COM_自動化開發指南.md
PROGID_ACQUA = "Acqua3.AcquaApplication"
