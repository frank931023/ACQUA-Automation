"""ACQUA COM 介面的列舉常數。

✅ 全部數值已從本機安裝的 ACQUA 6.2.210 TypeLib 實測取得(2026-08-05)
   工具:tools/dump_typelib.py(唯讀走訪,不啟動 ACQUA)

⚠️ 與 Acqua3COM.chm(2012 年版)的差異已標記 —— CHM 有數處已經過時。
"""


class EUserReaction:
    """來源:Acqua3 TypeLib。OnFinishedSingleMeasurement 的 ByRef 輸出。"""
    NO_REACTION = 0
    DO_NEXT = 1
    REDO_THIS = 2          # 重測這一筆 —— 自動重試靠這個
    CANCEL_ALL = 3


class EMEEventType:
    """來源:Acqua3 TypeLib。OnEvent 的事件分級。"""
    INFORMATION = 0
    WARNING = 1
    ERROR = 2

    NAMES = {0: "INFO", 1: "WARN", 2: "ERROR"}


class EReportSelectionType:
    """來源:Acqua3 TypeLib。⚠️ 數值不連續 —— 不要拿清單索引直接當它用。

    ⚠️ EACH_MAIN (6) 是 ACQUA 6 新增的,CHM 沒有記載。
    """
    FIRST_POSITION = 0
    LAST_POSITION = 3
    ALL_POSITIONS = 4
    FOR_INDEX = 5
    EACH_MAIN = 6          # ← CHM 未記載


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
    def is_resolved(cls) -> bool:
        return True        # 數值已確認,保留此方法供舊呼叫端相容

    @classmethod
    def is_pass(cls, status) -> bool:
        return int(status) in cls.PASSING

    @classmethod
    def is_strict_pass(cls, status) -> bool:
        """嚴格模式:只有明確判定 OK 才算通過。"""
        return int(status) == cls.MEAS_DONE_OK

    @classmethod
    def describe(cls, status) -> str:
        s = int(status)
        if s in cls._OURS:
            return cls._OURS[s]
        return cls._NAMES.get(s, f"Unknown({status})")


class ESingleValueCheckState:
    """來源:HEADACQUAlyzer TypeLib。單一數值的極限檢查結果。

    讀取具體數值時(走 AcquaDBMask.SingleValue.Status)會用到。
    """
    UNDEFINED = 0
    UNCHECKED = 1
    CHECKED_OK = 2
    CHECKED_NOT_OK = 3
    NOT_OK_NOT_REQUIRED = 4

    _NAMES = {0: "未定義", 1: "未檢查", 2: "OK", 3: "NOT OK", 4: "NOT OK(非必要)"}

    @classmethod
    def describe(cls, s) -> str:
        return cls._NAMES.get(int(s), f"Unknown({s})")


class EShowDiagramMode:
    """來源:ACQUAReportGenerator TypeLib。"""
    ALL = 0
    SINGLE_RUN = 1
    NONE = 2


class EShowSettingMode:
    """來源:ACQUAReportGenerator TypeLib。"""
    ALL = 0
    ALL_BUT_LIMITS = 1
    ONLY_LIMITS = 2
    NONE = 3


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


class EADItemTypes:
    """來源:AcquaDBMask TypeLib。資料庫物件的型別代碼。

    這份清單同時也是 ACQUA 資料模型的權威說明:
        Project → Subproject → MmdsAndSmds → (MMD | SMD) → Run → MeasurementResult → SingleValue
    """
    UNKNOWN = 0
    FILE = 1
    FILES = 2
    MEASUREMENT_RESULT = 3
    MEASUREMENT_RESULTS = 4
    REFERENCE_RESULT = 5
    REFERENCE_RESULTS = 6
    RUN = 7
    RUNS = 8
    TABLE = 9
    TABLES = 10
    CELL = 11
    CELLS = 12
    SUBPROJECT = 13
    SUBPROJECTS = 14
    ICON = 15
    ICONS = 16
    SMD = 17
    MMD = 18
    MMDS_AND_SMDS = 19
    STANDARD = 20
    STANDARDS = 21
    PROJECT = 22
    PROJECTS = 23
    LOCAL_MEASUREMENT_OBJECT = 24
    LOCAL_MEASUREMENT_OBJECTS = 25
    GLOBAL_MEASUREMENT_OBJECT = 26
    GLOBAL_MEASUREMENT_OBJECTS = 27
    PARAMETER = 28
    SINGLE_VALUE = 29
    INFO_COLUMN = 30
    SMD_COLLECTION = 31
    USED_FILES = 32
    APPLICATION = 33


# ── COM 識別碼(本機註冊表實測,2026-08-05)────────────────
PROGID_ACQUA = "Acqua3.AcquaApplication"
PROGID_DBMASK = "AcquaDBMask.Application"
CLSID_ACQUA = "{6E29EB13-3EE4-4FED-B966-8C5A6EB41F90}"

TYPELIB_ACQUA3 = "{1E189209-517B-46E7-AF7D-269A505ABD2F}"          # 內部名稱 "Acqua4"
TYPELIB_HEADACQUALYZER = "{E7763016-A964-11D3-875C-00A024540BF1}"
TYPELIB_REPORTGENERATOR = "{82891022-D04B-4D90-BB9A-14F0A2118211}"
TYPELIB_ACQUADBMASK = "{CF42356C-CABD-4875-9875-EA06D1BB80D6}"     # v1.9
