# ACQUA 測試自動化

用 Python + Flask 透過 ACOPT18 COM 介面自動化 HEAD acoustics ACQUA。
核心情境:**從專案的眾多測項中勾選 n 項,讓它自己依序跑完,收集 pass/fail 與數值結果。**

---

## 快速開始

```powershell
# 環境已經建好了(.venv 用的是 HEAD 內建的 32-bit Python 3.9)
.\.venv\Scripts\python.exe app.py --backend mock
# 開瀏覽器 → http://127.0.0.1:5000
```

模擬模式**不需要 ACQUA、不需要資料庫、不需要量測硬體**,可以直接把整套流程與 UI 跑一遍。

切換到真實 ACQUA:

```powershell
copy config.example.json config.json     # 填入資料庫名稱等資訊
.\.venv\Scripts\python.exe app.py --backend com
```

---

## 這台機器的環境現況(2026-08-05 實測)

| 項目 | 狀態 |
|---|---|
| ACQUA | ✅ 已安裝 `C:\Program Files (x86)\HEAD Analyzer ACQUA\Acqua6.exe` **v6.2.210** |
| COM 註冊 | ✅ ProgID `Acqua3.AcquaApplication` → LocalServer32 → `Acqua6.exe` |
| SQL Server | ✅ 執行個體 `ACQUADBSERVER`(SQL Server 2019)運行中 |
| **ACQUA 資料庫** | ❌ **不存在** —— 只有 4 個系統資料庫,沒有任何 ACQUA 庫 |
| Python | ✅ HEAD 內建 **32-bit Python 3.9.13**,已含 pywin32 |
| 本專案 venv | ✅ `.venv`(Python 3.9.13 32-bit + Flask 3.1.3 + pywin32 312) |
| ACOPT18 授權 | ❓ **未確認** —— 沒有它 `Dispatch()` 會失敗 |
| 量測硬體 | ❓ 未確認(已裝 HEAD device drivers) |

### 資料庫(2026-08-06 更新)

已建立兩個,專案目前設定用 **`61_Demo_SMDs_Rev07`**:

| 資料庫 | 位置 | 內容 |
|---|---|---|
| **`61_Demo_SMDs_Rev07`** ✅ 使用中 | `C:\ACQUA_DB` | HEAD 官方示範庫,**132 個 SMD / 61 個 MMD** |
| `AUTOMATION_TEST_0806` | `C:\Users\autom\ACQUA_Databases` | 5 個空專案,**0 個 SMD**(暫不使用) |

完整測項清單見 `../61_Demo_SMDs_Rev07_測項清單.md`。

### 🟠 已知問題:demo 專案是「孤兒」

```sql
-- 61_Demo_SMDs_Rev07
acqua.ProjectGroups:  idProjectGroup=1  "Standards"
acqua.Projects:       idProject=1  rProjectGroup=NULL  "ACQUA Demo SMDs Rev.07"
                                   ^^^^^^^^^^^^^^^^^^ 沒有掛在任何群組下
```

**影響:** COM 的走訪路徑是 `app.ProjectGroups.Item(i).Projects.Item(j)`,
專案沒有父群組 → **這條路徑很可能列舉不到它**,`open_project` 會找不到。

ACQUA GUI 自己開得起來(MRU 有紀錄),但 COM 列舉是不是也看得到,**必須實測**。

修法(一行,可逆):

```sql
USE [61_Demo_SMDs_Rev07];
UPDATE acqua.Projects SET rProjectGroup = 1 WHERE idProject = 1;  -- 掛到 "Standards"
-- 還原:UPDATE acqua.Projects SET rProjectGroup = NULL WHERE idProject = 1;
```

### 其他待辦

- ❓ **ACOPT18 授權未確認** —— 沒有它 `Dispatch()` 會失敗
- ⚠️ **132 個測項各自需要對應的 ACOPT 模組授權**(6819/6820/6844/6857…)
- ⚠️ **17 個測項需要外部參考檔**(`.dat`/`.fft`),開跑前應先檢查存在
- ⚠️ SQL Server 是 **Express 版**,單一資料庫上限 10 GB

---

## 架構

```
瀏覽器 ──HTTP/SSE──> Flask(多執行緒)
                        │  worker.submit(命令)
                        ↓
                  [ 命令佇列 Queue ]
                        │
                        ↓
         ⭐ AcquaWorker(單一 STA 執行緒)
            - CoInitializeEx(APARTMENTTHREADED)
            - 獨佔 AcquaApplication 物件
            - 閒置時跑 PumpWaitingMessages()
            - 唯一碰 COM 的地方
                        │
                        ↓
                  [ SharedState(有鎖)]
                        │
              Flask 讀取 ←┘
```

**為什麼一定要這樣拆:**

| 衝突 | 說明 |
|---|---|
| COM 事件需要 STA + 訊息幫浦 | 沒有幫浦,`OnFinishedSingleMeasurement` 永遠不會觸發,程式看起來像當掉 |
| Flask 每個請求跑在不同執行緒 | COM 物件不能隨意跨執行緒使用 |
| 量測是長時間阻塞操作 | 不能綁在 HTTP 請求上,必須非同步 + SSE 推播進度 |

**規則:`app.py` 裡的任何程式碼都不可以直接碰 COM 物件。** 一律走 `worker.submit()`。

### 檔案

```
ACQUA Automation/
├── app.py                    Flask 入口與 REST API
├── config.example.json       設定範本(複製成 config.json)
├── requirements.txt
├── acqua/
│   ├── constants.py          ✅ 列舉常數(數值已從 TypeLib 實測取得)
│   ├── state.py              執行緒安全的共用狀態
│   ├── worker.py             ⭐ COM 工作執行緒
│   ├── backend_base.py       後端介面定義
│   ├── backend_mock.py       模擬後端(無 ACQUA 也能開發)
│   ├── backend_com.py        真實 COM 後端
│   └── dbmask.py             ⭐ AcquaDBMask —— 列舉 SMD、讀數值、建 MMD/SMD
├── templates/index.html      Web UI(勾選測項 + 即時日誌)
├── tools/dump_typelib.py     ⭐ 唯讀走訪 TypeLib(不啟動 ACQUA)
└── .venv/                    32-bit Python 3.9 + Flask + pywin32
```

---

## ⭐ 重要發現:CHM 文件已經過時

`Acqua3COM.chm` 是 2012 年的,安裝的是 ACQUA 6.2.210。用 `tools/dump_typelib.py`
實測後發現數處差異 —— **以 TypeLib 為準,不要相信 CHM**。

### 方法簽章不同

| CHM 寫的 | TypeLib 實際 |
|---|---|
| `StartMeasurements(UseMMDSettings, MeasurementObject)` | `StartMeasurements(UseMMDSettings, MeasurementObject, **ResultComment**)` |
| `StartSingleMeasurement(SMDRowID, UseMMDSettings, MeasurementObject)` | `StartSingleMeasurement(SMDRowID, UseMMDSettings, MeasurementObject, **ResultComment**)` |
| (無) | **`Close()`** |
| (無) | **`DeleteAllResultsOfActiveMeasObj()`** |

### 列舉多了成員

```
EReportSelectionType:  erstEachMain = 6                      ← CHM 沒有
EMEResult:             emeresultIgnore = 7                   ← CHM 沒有
                       emeresultMeasDoneNotOkNotRequired = 8 ← CHM 沒有
```

### ⭐ EMEResult 實際數值(pass/fail 判定的核心)

```
emeresultUndefined                = 0
emeresultMeasDone                 = 1
emeresultMeasDoneOk               = 2   ← PASS
emeresultMeasDoneNotOk            = 3   ← FAIL
emeresultMeasError                = 4
emeresultUserCanceled             = 5
emeresultMeasNotPossible          = 6
emeresultIgnore                   = 7
emeresultMeasDoneNotOkNotRequired = 8   ← 沒過但「非必要項」,不該算失敗
```

> ⚠️ `emeresultMeasDoneNotOkNotRequired = 8` 特別重要。如果只用
> `status == 2` 判定通過,非必要項會被誤判成 FAIL,產生假的失敗。
> 見 `constants.py` 的 `EMEResult.PASSING`。

---

## ⭐ 兩種執行模式(都已實作)

| | `selected` 逐項勾選 | `conditional` 變數驅動 |
|---|---|---|
| 誰決定跑哪些 | **你的程式** | **ACQUA** |
| COM 呼叫 | `StartSingleMeasurement` 逐項 | `StartMeasurements` 一次 |
| 篩選依據 | 你勾的 SMD RowID 清單 | 專案樹的 `ConditionalExecution` 讀變數 |
| 適合 | 重跑失敗項、抽測、CI 指定子集 | 依 DUT 屬性自動決定完整測試計畫 |
| 進度回報 | 每項一個事件 | 整批事件 |

**混合用法(推薦):**

```
COM 寫入 DUT 屬性變數  →  StartMeasurements  →  ACQUA 自動篩選並依序跑完
       ↑                                              ↓
   取代 HEAD 的問卷精靈                          事件回報每項 pass/fail
```

這樣既保有 HEAD 官方測試套件的設計(變數 + 條件執行),又能無人值守。

### 變數怎麼設

```python
me = project.MeasurementEngine       # HEADACQUAlyzer.IMeasurementEngine
vs = me.UsedVariables                # IVariables 集合

v = vs.Add()                         # 沒有 AddNamed(),只能 Add() 再設 Name
v.Name  = "DUT_speakerphone_type"
v.Type  = 2                          # evtString
v.Value = "Shared"
v.State = 2                          # evsUserDefined
vs.Save()
```

變數名稱建議沿用 HEAD 官方精靈(`SMD/dut_meas_wizard.py`)用的那組:
`DUT_speakerphone_type`、`DUT_connection_type`、`DUT_is_deskphone`、
`DUT_premium_reqs`、`DUT_pickup_range_*`、`DUT_stereo_calling` 等。

### ⭐ 還有第三條路:`RunScript`

`IMeasurementEngine` 有 **`RunScript(Language, Code)`** 和 `PythonAvailable` —— 
可以**從 COM 直接執行 ACQUA 內部的 Python**。這等於打通了 COM(層級 2)
與 ACQUA 內建腳本(層級 3),能呼叫只有內部才拿得到的 API。

另外 `DoMeasurementEx2(..., ScriptBeforeFilename, ScriptAfterFilename)`
可以在單筆量測前後掛腳本。

---

## ⭐ 兩套物件模型 —— 名詞會打架

| Acqua3(控制用) | AcquaDBMask(資料用) | VB6 範例 UI |
|---|---|---|
| `ProjectGroup` | `Project` | "project group" |
| `Project` | **`Subproject`** | **"Selected Subproject"** |
| `MeasurementObject` | `LocalMeasurementObject` | "Measurement Object" |

VB6 範例把 Acqua3 的 Project 標成 "Subproject",就是因為底層是 Subproject。

**連線的參數順序也相反:**

```python
Acqua3     : SelectDatabase(SQLServerName, DatabaseName, winAuth, user, pwd)
AcquaDBMask: Connect(DatabaseName, SQLServerName)          # ← 資料庫在前!
```

### 什麼時候用哪一套

| 需求 | 用哪個 |
|---|---|
| 啟動量測、收事件、產 Word 報告 | **Acqua3** |
| 列舉 SMD(要標題) | **AcquaDBMask** — `Subproject.GetSMDsRecursive()` |
| 讀出數值(POLQA 分數、Loudness…) | **AcquaDBMask** — `SingleValue.Value / .Unit / .Status` |
| 程式化建立 MMD / SMD | **AcquaDBMask** — `MmdsAndSmds.AddMMD() / .AddSMD()` |

### 資料模型(TypeLib 實測確認)

```
Application
 └─ Projects              ← Acqua3 叫 ProjectGroup
     └─ Subprojects       ← Acqua3 叫 Project        「大測試」
         ├─ LocalMeasurementObjects                  受測物 DUT
         └─ MmdsAndSmds
             ├─ MMD       測試群組
             └─ SMD       ⭐ 單一測項                 「小測試」
                 └─ MeasurementResults
                     ├─ Status  (OK / NotOK / Done)
                     ├─ SingleValue1 / SingleValue2   ⭐ 數值在這
                     │     .Value .Unit .Title .Status .Precision
                     └─ Runs
```

---

## 開發順序

| 階段 | 內容 | 狀態 |
|:---:|---|:---:|
| 0 | 環境準備(Python / venv / Flask) | ✅ 完成 |
| 1 | dump TypeLib 取得真實 API 與列舉數值 | ✅ 完成 |
| — | **建立 ACQUA 資料庫 + 在 GUI 定義專案與 SMD** | 🔴 **待你操作** |
| 2 | 最小連通性:`Dispatch()` + `AppLoadFinished` | ⬜ |
| 3 | 唯讀瀏覽 + SMD 列舉、驗證 DBMask 的 ID 是否等於 SMDRowID | ⬜ |
| 4 | 事件接線(驗證 ByRef 回傳、dump `ResultOverview`) | ⬜ |
| 5 | 實際量測 + pass/fail | ⬜ |
| 6 | 讀取數值結果(DBMask SingleValue) | ⬜ |

### 階段 2~5 必須實測驗證的項目

程式碼裡標了 `[未驗證]` 的地方:

- [ ] `DispatchWithEvents` + 類別屬性注入的寫法是否正常運作
- [ ] **ByRef 輸出參數**(`UserReaction`、`Continue`)是否真的用 return 回傳
- [ ] `StartSingleMeasurement` 之後等 `IsMeasuring` 翻轉有沒有 race condition
- [ ] ⭐ **DBMask 的 `SMD.ID` 是否等於 `StartSingleMeasurement(SMDRowID)` 要的 RowID**
      (兩者都是資料庫 row id,理論上相同 —— 但一定要用一筆實測確認)
- [ ] `OnFinishedMeasurements` 的 `ResultOverview` 到底是什麼結構
- [ ] `AddSMD(strTitle, strDescription, strSMDType, strSMDCompleteFileName)`
      後兩個參數的合法值(建議先在 GUI 建一個,再讀它的 `SMDType` 當範本)

---

## 工具

```powershell
# 唯讀走訪 TypeLib —— 不會啟動 ACQUA,不產生快取檔
.\.venv\Scripts\python.exe tools\dump_typelib.py
.\.venv\Scripts\python.exe tools\dump_typelib.py --enums-only
.\.venv\Scripts\python.exe tools\dump_typelib.py --grep SingleValue
```

---

## 陷阱清單

| # | 陷阱 |
|:-:|---|
| 1 | **忘記 `PumpWaitingMessages()`** —— 事件永遠不會來,程式像當掉 |
| 2 | **位元數** —— ACQUA 是 x86,TypeLib 只註冊 win32。必須 32-bit Python |
| 3 | **ByRef 輸出參數** —— pywin32 用 return 回傳,不是改參數 |
| 4 | **`DispatchWithEvents` 不呼叫 `__init__`** —— 相依物件要用類別屬性注入 |
| 5 | **索引基準不一致** —— Acqua3 集合從 **0** 開始;`MfeX.Settings.Names(i)` 從 **1** 開始 |
| 6 | **`IProject` ≠ `IProjectSelected`** —— 要先 `SelectAsActive()` 再拿 `app.SelectedProject` |
| 7 | **`EReportSelectionType` 數值不連續**(0,3,4,5,6)—— 別拿清單索引當它用 |
| 8 | **兩套模型名詞打架** —— Acqua3 的 Project = DBMask 的 Subproject |
| 9 | **`Connect()` 參數順序相反** —— DBMask 是資料庫在前 |
| 10 | **`emeresultMeasDoneNotOkNotRequired`** 不該算 FAIL |
| 11 | **Flask 的 reloader 要關掉** —— 否則 COM 執行緒會被開兩份 |

---

## 授權與安全

- `config.json` 可能含資料庫密碼 —— **不要提交進版控**
- 建議一律用 Windows 驗證(`use_windows_auth: true`),不要存明碼密碼
- Flask 預設只綁 `127.0.0.1`。要開放給區網前請先加上認證
