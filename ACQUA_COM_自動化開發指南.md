# ACQUA COM Interface (ACOPT18) — 資料夾解析與自動化開發指南

> 目標:用 Python(或 C++)透過 ACOPT18 COM 介面自動化 HEAD acoustics ACQUA 量測
> 初版:2026-08-05 ・ 最後更新:2026-08-10
> 資料來源:本資料夾內容 + `Acqua3COM.chm` 解開後的 API 參考 + **TypeLib 實測** + 資料庫實查

---

## 📌 文件定位與現況

| 文件 | 內容 | 什麼時候看 |
|---|---|---|
| **本文件** | COM 介面的**觀念與 API 參考** | 想理解 ACQUA COM 怎麼運作 |
| `ACQUA Automation/README.md` | **實作專案**的架構、環境、待辦 | 要動程式碼、看目前進度 |
| `61_Demo_SMDs_Rev07_測項清單.md` | 資料庫裡 **132 個測項**的完整清單 | 要挑測項、查授權模組 |

**2026-08-10 更新摘要** —— 初版有幾處推論已被實測推翻,已在文中修正:

- ✅ **不需要另外安裝 Python** —— HEAD 原廠已內建 32-bit Python 3.9 + pywin32
- ✅ **`EMEResult` 數值已取得**(初版標示為未知),且比 CHM 多 2 個成員
- ✅ **「無法列舉 SMD」已解決** —— `AcquaDBMask` 的 `GetSMDsRecursive()`
- ✅ **「讀不到數值」已解決** —— `AcquaDBMask` 的 `SingleValue.Value / .Unit / .Status`
- ✅ **多個方法簽章與 CHM 不符** —— 已依 TypeLib 修正
- ⭐ **新增第三條路** —— `RunScript()` 可從 COM 直接執行 ACQUA 內部 Python

---

## 0. 先讀這段:三個會改變你做法的發現

### 發現 1 — 你的機器上裝的是 ACQUA 6,但範例是 ACQUA 3 時代的

| 項目 | 實際狀況 |
|---|---|
| 安裝路徑 | `C:\Program Files (x86)\HEAD Analyzer ACQUA` |
| 主程式 | `Acqua6.exe`,版本 **6.2.210.33798** |
| SDK 範例假設的主程式 | `Acqua3.exe`(範例來自 2005–2012 年) |
| CHM 文件版權年 | 2012 |

**但好消息是:向後相容有保住。** 註冊表實測結果:

```
HKLM\SOFTWARE\Classes\WOW6432Node\CLSID\{6E29EB13-3EE4-4FED-B966-8C5A6EB41F90}
    LocalServer32 = "C:\Program Files (x86)\HEAD Analyzer ACQUA\Acqua6.exe"
    ProgID        = Acqua3.AcquaApplication
    TypeLib       = {1E189209-517B-46E7-AF7D-269A505ABD2F}
```

也就是說:

- ProgID **仍然叫 `Acqua3.AcquaApplication`**,不要因為裝的是 ACQUA 6 就去猜 `Acqua6.xxx`
- 它由 `Acqua6.exe` 實作 → 範例程式碼原則上可以直接用
- TypeLib 內部名稱是 **`Acqua4`**(HEAD 跨版本沿用同一個 GUID)

⚠️ **但 CHM 是 2012 年的,ACQUA 6 的 TypeLib 很可能多了 CHM 沒寫的成員。**
所以第一件事不是讀 CHM,是**從 `Acqua6.exe` 把當前 TypeLib dump 出來**(見 §6 階段 1)。CHM 當作「有註解的參考」,TypeLib 當作「真相來源」。

### 發現 2 — LocalServer32(行程外伺服器)→ 位元數限制比想像中寬鬆

`Acqua6.exe` 是 **out-of-process COM server**(`LocalServer32`,不是 `InprocServer32`)。
COM 會跨行程 marshaling,所以理論上 64-bit Python 也能呼叫 32-bit 的 ACQUA。

**但是** TypeLib 只註冊了 `win32` 這個分支:

```
TypeLib\{1E189209-...}\1.0\0\win32 = ...\Acqua6.exe     ← 只有 win32,沒有 win64
```

早期繫結(makepy / `#import` / tlbimp)需要載入 TypeLib,64-bit 行程去查會先找 `win64`。

👉 **結論:用 32-bit Python。** 而且好消息是 —— **不用自己裝。**

> ⭐ **HEAD 原廠已內建一套 32-bit Python 3.9.13,而且 pywin32 已經裝好了:**
> ```
> C:\Program Files (x86)\Common Files\HEAD shared\Python39\python.exe
> ```
> 位元數剛好對得上 ACQUA(x86),還附了 numpy / scipy / pandas / matplotlib /
> librosa / openpyxl / requests 等完整科學運算套件。
>
> 本專案的 `.venv` 就是用它建的(只另外補了 Flask)。
> 系統 PATH 上的 `python` 是 Microsoft Store 的空殼,**不能用**。

### 發現 3 — ⭐ CHM 記載的 Acqua3 介面「無法讀取量測數值」

> **✅ 2026-08-10 更新:此限制已找到解法。**
> `AcquaDBMask` 的 `SingleValue.Value / .Unit / .Title / .Status` 可以讀出實際數值,
> 走 `Subproject → SMD → MeasurementResults → SingleValue1/2`。詳見 §11。
> 下面這段仍然成立 —— 它說明的是**為什麼**需要第二套物件模型。

這是做測試自動化最重要的一點。把 CHM 全部翻完之後,`Acqua3` 這組介面能做的事情是:

| 能做 | 不能做 |
|---|---|
| 連資料庫、瀏覽 ProjectGroup / Project / MO | ❌ 讀出量測結果數值 |
| 選定 active project / active MO | ❌ 讀 SMD 的極限值 / 容差 |
| 新增 MO | ❌ 取得 pass/fail 的細項數據 |
| 啟動全部量測 / 單一 SMD 量測 | ❌ 查詢歷史 run 的結果 |
| 收事件(進度、單筆結果 OK/NOT OK) | ❌ 存取 SingleValue / MeasurementResult |
| 產生 Word 報告 | |

**單筆的 OK / NOT OK 可以從 `OnFinishedSingleMeasurement` 的 `ResultStatus` 拿到**,
所以「跑完整個專案,判斷每個 SMD 過或不過」這件事,光用 Acqua3 介面是做得到的。

但如果你要「取得 POLQA 分數是 3.87」、「讀出頻響曲線」、「跟上次結果比對」——
就必須用另一個**沒有寫在這份 CHM 裡**、但本機已註冊的物件模型:

```
AcquaDBMask.Application
  ├─ Projects / Subprojects
  ├─ MMD / SMD / MmdsAndSmds
  ├─ Runs
  ├─ MeasurementResults / MeasurementResult
  ├─ ReferenceResults / ReferenceResult
  ├─ SingleValue          ← 單一數值(你要的數字在這)
  ├─ GlobalMeasurementObjects / LocalMeasurementObjects
  ├─ Standards / Tables / Cells / Files / Parameter
```

**規劃架構時就要把這件事考慮進去**,不要寫到一半才發現拿不到數字。

---

## 1. 資料夾內容清單

```
ACOPT18 ACQUA COM Interface\
├── Acqua3COM.chm                                   50 KB  ⭐ API 參考(已解開,見 §4)
│
├── ACQUA_COM_自動化開發指南.md                              ← 本文件
├── 61_Demo_SMDs_Rev07_測項清單.md                          ⭐ 132 個測項的完整清單
│
├── SMD\                                                   ⭐ 後來收到的官方腳本型 SMD
│   ├── DUT & Measurement Wizard.aqs             146 B     SMD 定義(XML,指向下面的 .py)
│   └── dut_meas_wizard.py                      12.6 KB    ACQUA 內建 Python 腳本(見 §11.4)
│
├── ACQUA Automation\                                      ⭐ 自動化實作專案(見其 README.md)
│   ├── app.py / config.json / requirements.txt
│   ├── acqua\  (constants, state, worker, backend_com, backend_mock, dbmask)
│   ├── templates\index.html
│   ├── tools\dump_typelib.py                             唯讀走訪 TypeLib
│   └── .venv\                                            32-bit Python 3.9 + Flask + pywin32
│
└── Example Applications\
    ├── VB6\
    │   ├── COM Interface Example.vbp                      ⭐ 參考清單(TypeLib GUID 在這)
    │   ├── COM Interface Example.vbw                      IDE 視窗位置,無用
    │   └── frmMain.frm                          ~1030 行  ⭐⭐ 功能最完整的範例
    └── VB.Net\
        ├── Acqua3COMDemo.sln
        └── Acqua3COMDemo\
            ├── Acqua3COMDemo.vbproj                       ⭐⭐ COM 參考全清單(§5.1)
            ├── Acqua3COMDemo.vbproj.user                  本機設定,無用
            ├── frmMain.vb                        253 行  ⭐ 精簡版範例(有 bug,見 §5.3)
            ├── frmMain.Designer.vb                        UI 版面,無用
            ├── frmMain.resx                               資源,無用
            ├── ApplicationEvents.vb                       空的樣板,無用
            ├── app.config                                 .NET 設定,無用
            └── My Project\
                ├── AssemblyInfo.vb                        無用
                ├── app.manifest                           UAC 資訊清單,無用
                ├── Application.Designer.vb / .myapp       無用
                ├── Resources.Designer.vb / .resx          無用
                ├── Settings.Designer.vb / .settings       只存 server/db 名稱
                └── DataSources\
                    └── Acqua3.IProjectSelected.datasource VS 資料繫結用,無用
```

### 該注意的檔案 — 只有 4 個

| 優先 | 檔案 | 為什麼重要 |
|:---:|---|---|
| 1 | `Acqua3COM.chm` | 唯一的官方 API 文件。**注意:是 2012 年版,已落後於安裝的 ACQUA 6** |
| 2 | `VB6\frmMain.frm` | 功能最完整的參考實作:MFE 設定、取消量測、報告產生器全選項、事件處理全部都有 |
| 3 | `VB.Net\...\Acqua3COMDemo.vbproj` | **列出了 12 個 COM TypeLib 參考** — 這是 CHM 沒給你的全景圖(§5.1) |
| 4 | `VB.Net\...\frmMain.vb` | 較好讀的入門版,但功能較少且**有一個原廠 bug** |

其餘檔案都是 IDE 自動產生的樣板,對開發沒有參考價值。

### 關於 `.chm` 讀不到的原因

`.chm` = Compiled HTML Help,是二進位容器(ITSF 格式,內含一堆 HTML + 索引,LZX 壓縮)。
**沒有加密也沒有保護**,只是格式需要解。從網路/OneDrive 來的 CHM 還會被 Windows 標記封鎖,
不解除封鎖的話雙擊會每頁空白。

解法:
```powershell
# 方法 A:解除封鎖後直接看
#   右鍵 → 內容 → 勾「解除封鎖」→ 套用 → 雙擊

# 方法 B:整份解壓成 HTML(本文件的 API 章節就是這樣產出的)
hh.exe -decompile C:\out\ Acqua3COM.chm
```

---

## 2. COM 物件模型全圖

```
Acqua3.AcquaApplication                    ← CoCreate 從這裡開始
  │  (CLSID {6E29EB13-3EE4-4FED-B966-8C5A6EB41F90}, LocalServer32 → Acqua6.exe)
  │
  ├─ IAcquaApplication          ← 你呼叫它
  └─ IAcquaApplicationEvents    ← 它回呼你(source interface)

IAcquaApplication
  ├─ AppLoadFinished        : Bool     ← 建立實例後必須先等這個變 True
  ├─ SelectDatabase(...)    : Bool
  ├─ SelectedSQLServerName  : String
  ├─ SelectedDatabaseName   : String
  ├─ ConnectToLastSelectedProject()
  ├─ IsMeasuring            : Bool
  ├─ ProjectGroups          : IProjectgroups
  ├─ SelectedProject        : IProjectSelected   ← 沒選時為 NULL
  ├─ SelectedProjectLoaded  : Bool               ← 切換專案後要等這個
  ├─ SelectedMeasurementObject : IMObject        ← 沒選時為 NULL
  └─ ReportGenerator        : ACQUAReportGenerator.IRepGen   ← 跨 TypeLib!

階層:
IProjectgroups ──Item(i)──> IProjectgroup ──Projects──> IProjects
                                                            │
                                                        Item(i)
                                                            ↓
                                                        IProject ──SelectAsActive()──┐
                                                                                      ↓
                                                                          app.SelectedProject
                                                                                      ↓
                                                                            IProjectSelected
                                                                     (才有 量測 / 報告 / MFE 能力)

繼承關係:
IAcquaBaseObject (RowID, QueryProperty, UpdateProperty)
  ├─ IProjectBase (+ Title, Description, MeasurementObjects)
  │    ├─ IProject          (+ SelectAsActive)
  │    └─ IProjectSelected  (+ StartMeasurements, StartSingleMeasurement,
  │                            SelectActiveMeasurementObject, CreateReportForMO,
  │                            FindFirstSMD, FindNextSMD, MeasurementEngine)
  ├─ IProjectgroup (+ Title, Description, CreationDate, Projects)
  └─ IMObject      (+ Title, Description, CreationDate, CreatedByUser,
                      CreatedOnComputer, SerialNumber,
                      ManufacturerName, ManufacturerDescription)
```

**注意 `IProject` 和 `IProjectSelected` 是兩個不同的介面。**
`IProject`(從集合裡拿到的)只能 `SelectAsActive()`;
要量測、產報告、動 MFE 設定,必須用 `app.SelectedProject` 拿到的 `IProjectSelected`。
這是初學最容易撞牆的地方。

---

## 3. 列舉常數(數值已確認)

### EReportSelectionType — 報告要包含哪些結果
| 名稱 | 值 | 說明 |
|---|---:|---|
| `erstFirstPosition` | **0** | 每個 SMD 的第一筆 |
| `erstLastPosition` | **3** | 每個 SMD 的最後一筆 |
| `erstAllPositions` | **4** | 全部 |
| `erstForIndex` | **5** | 指定 ResultIndex 那筆 |
| `erstEachMain` | **6** | 每個主項目 ⚠️ **CHM 未記載,ACQUA 6 新增** |

⚠️ **數值不連續(0, 3, 4, 5, 6)** — 絕對不要用 ListBox 的 SelectedIndex 直接當這個列舉值傳進去。

### EMEEventType — `OnEvent` 的事件類型
| 名稱 | 值 |
|---|---:|
| `emeetInformation` | 0 |
| `emeetWarning` | 1 |
| `emeetError` | 2 |

### EUserReaction — `OnFinishedSingleMeasurement` 的回傳決策
| 名稱 | 值 | 說明 |
|---|---:|---|
| `eurNoReactionNeeded` | 0 | 不介入 |
| `eurDoNextMeasurement` | 1 | 繼續下一筆 |
| `eurRedoThisMeasurement` | 2 | **重測這一筆**(自動重試很好用) |
| `eurCancelAllMeasurements` | 3 | 中止全部 |

### EMEResult — 單筆量測結果狀態

✅ **數值已從 `HEADACQUAlyzer` TypeLib 實測取得(2026-08-06)。** 不在 CHM 內。

| 名稱 | 值 | 判定 |
|---|---:|---|
| `emeresultUndefined` | 0 | — |
| `emeresultMeasDone` | 1 | 完成(無判定條件) |
| `emeresultMeasDoneOk` | **2** | ✅ **PASS** |
| `emeresultMeasDoneNotOk` | **3** | ❌ **FAIL** |
| `emeresultMeasError` | 4 | 錯誤 |
| `emeresultUserCanceled` | 5 | 使用者中止 |
| `emeresultMeasNotPossible` | 6 | 無法量測 |
| `emeresultIgnore` | **7** | 略過 ⚠️ **CHM 與 VB 範例都沒有** |
| `emeresultMeasDoneNotOkNotRequired` | **8** | 未通過但**非必要項** ⚠️ **CHM 沒有** |

> 🔴 **`8` 這個值特別重要。** 它代表「沒過,但這項本來就不是必檢項目」。
> 如果判定寫成 `status == 2` 才算通過,這些非必要項會被誤判成 **FAIL**,產生**假不良**。
>
> 本專案的處理方式(`acqua/constants.py`):
> ```python
> PASSING = {MEAS_DONE, MEAS_DONE_OK, IGNORE, MEAS_DONE_NOT_OK_NOT_REQUIRED}
> ```
> 另提供 `is_strict_pass()` 供只認 `emeresultMeasDoneOk` 的嚴格情境使用。

### ESingleValueCheckState — 單一數值的極限檢查結果

讀取具體數值時(`AcquaDBMask` 的 `SingleValue.Status`)會用到:

| 名稱 | 值 |
|---|---:|
| `esvcsUndefined` | 0 |
| `esvcsUnchecked` | 1 |
| `esvcsCheckedOK` | 2 |
| `esvcsCheckedNotOK` | 3 |
| `esvcsNotOkNotRequired` | 4 |

### EVariableType / EVariableState — 變數驅動模式用

| EVariableType | 值 | | EVariableState | 值 |
|---|---:|---|---|---:|
| `evtDouble` | 0 | | `evsUndefined` | 0 |
| `evtBoolean` | 1 | | `evsMeasured` | 1 |
| `evtString` | 2 | | `evsUserDefined` | 2 |
| `evtInteger` | 3 | | | |
| `evtChannelList` | 4 | | | |

### EShowDiagramMode / EShowSettingMode — 報告產生器

`esdmAll`=0 `esdmSingleRun`=1 `esdmNone`=2 ・
`essmAll`=0 `essmAllButLimits`=1 `essmOnlyLimits`=2 `essmNone`=3

---

## 4. API 完整參考(從 CHM 抽出)

### IAcquaApplication

| 成員 | 型別 | 簽章 / 說明 |
|---|---|---|
| `AppLoadFinished` | Get | `As Boolean` — ACQUA 啟動完成才 True。**建立實例後一定要用** |
| `ConnectToLastSelectedProject` | Method | `Sub` — 開啟上次 session 的專案 |
| `IsMeasuring` | Get | `As Boolean` — 量測中為 True |
| `ProjectGroups` | Get | `As IProjectgroups` |
| `ReportGenerator` | Get | `As ACQUAReportGenerator.IRepGen` |
| `SelectDatabase` | Method | `(SQLServerName, DatabaseName, UseWindowsAuthentication As Boolean, Username, Password) As Boolean` — 用 Windows 驗證時後兩個參數被忽略 |
| `SelectedDatabaseName` | Get | `As String` |
| `SelectedMeasurementObject` | Get | `As IMObject` — 未選時 NULL |
| `SelectedProject` | Get | `As IProjectSelected` — 未選時 NULL |
| `SelectedProjectLoaded` | Get | `As Boolean` — 專案完全載入前保持 False |
| `SelectedSQLServerName` | Get | `As String` |

### IAcquaApplicationEvents(事件介面)

| 事件 | 簽章 |
|---|---|
| `OnBeginMeasurements` | `(SelectedProject As IProjectSelected, MeasurementObject As IMObject, NbrOfMeasurements As Long)` |
| `OnBeginSingleMeasurement` | `(SMDTitle As String, Progress As Long, NbrOfMeasurements As Long)` |
| `OnFinishedSingleMeasurement` | `(SMDTitle As String, ResultStatus As HEADACQUAlyzer.EMEResult, Progress As Long, NbrOfMeasurements As Long, UserReaction As EUserReaction)` ← **UserReaction 是 ByRef 輸出** |
| `OnFinishedMeasurements` | `(SelectedProject, MeasurementObject, NbrOfMeasurements As Long, NbrOfMeasurementsFinished As Long, Canceled As Boolean, ResultOverview As Variant)` |
| `OnEvent` | `(Description As String, EventType As EMEEventType)` |
| `OnCallbackEvent` | `(EventDescription As String, Continue As Boolean)` ← **Continue 是 ByRef 輸出** |
| `OnProgress` | `(Description As String, ProgressCounter As Long, TotalCount As Long)` |

> 🔍 `OnFinishedMeasurements` 的 `ResultOverview` 是 **Variant**,CHM 沒說明內容結構。
> 這很可能是唯一能一次拿到整批結果總覽的地方 — **值得優先實驗,把它 dump 出來看看是什麼**。

### IProjectSelected(核心介面)

| 成員 | 簽章 / 說明 |
|---|---|
| `StartMeasurements` | ⚠️ 實際為 `Sub (UseMMDSettings, MeasurementObject, **ResultComment**)` — CHM 少寫第 3 個參數 |
| `StartSingleMeasurement` | ⚠️ 實際為 `Sub (SMDRowID, UseMMDSettings, MeasurementObject, **ResultComment**)` — CHM 少寫第 4 個參數 |
| `Close` | `Sub ()` — ⚠️ **CHM 未記載** |
| `DeleteAllResultsOfActiveMeasObj` | `Sub ()` — ⚠️ **CHM 未記載**,清空當前 DUT 的所有結果 |
| `SelectActiveMeasurementObject` | `Function (MObjectIndexOrName As Variant) As IMObject` — **索引或名稱都收** |
| `CreateReportForMO` | `Sub (MeasObjectRowID As Long, SelectionType As EReportSelectionType, ReportFileName As String, ResultIndex As Long)` |
| `FindFirstSMD` | `Function (SearchString As String) As Long` — 回傳標題**含有**該字串的第一個 SMD 的 RowID,找不到回 **-1** |
| `FindNextSMD` | `Function () As Long` — 下一個,找不到回 -1 |
| `MeasurementEngine` | `Get As HEADACQUAlyzer.IMeasurementEngine` — MFE 設定入口 |
| `MeasurementObjects` | `Get As IMObjects` |
| `Title` / `Description` / `RowID` | Get |
| `QueryProperty` / `UpdateProperty` | 見下方 |

> 💡 `FindFirstSMD` + `FindNextSMD` + `StartSingleMeasurement` 是**做「只跑指定測項」的關鍵組合**。
> 例如只想跑名稱含 "POLQA" 的 SMD,就用這三個湊出來。
>
> ⚠️ **但這兩個是「搜尋」不是「列舉」,而且只回傳 RowID、不回傳標題。**
> 要做「勾選清單」的 UI(列出全部測項含名稱),必須改走 `AcquaDBMask`:
> ```python
> subproject.GetSMDsRecursive()   # 回傳全部 SMD,含 Title / ID / SMDType
> subproject.GetNbrOfSMDsRecursive()
> ```
> 詳見 §11。

### IProject

| 成員 | 說明 |
|---|---|
| `SelectAsActive` | `Sub` — 在 ACQUA 中開啟此專案(之後要等 `SelectedProjectLoaded`) |
| `MeasurementObjects` | `Get As IMObjects` |
| `Title` / `Description` / `RowID` / `QueryProperty` / `UpdateProperty` | |

### IProjectgroup / IProjectgroups / IProjects / IMObjects(集合)

| 介面 | 成員 |
|---|---|
| `IProjectgroups` | `Count As Long`,`Item(Index As Long) As IProjectgroup` — **索引從 0 開始** |
| `IProjectgroup` | `Title`, `Description`, `CreationDate As Date`, `Projects As IProjects`, `RowID`, `QueryProperty`, `UpdateProperty` |
| `IProjects` | `Count As Long`,`Item(Idx As Long) As IProject` — **索引從 0 開始** |
| `IMObjects` | `Count As Long`,`Item(Idx As Long) As IMObject` — **索引從 0**,`AddMeasurementObject(Title, Description) As Long`(回傳新物件的 item index) |

### IMObject

`Title`, `Description`, `CreationDate As Date`, `CreatedByUser`, `CreatedOnComputer`,
`SerialNumber`, `ManufacturerName`, `ManufacturerDescription`, `RowID`, `QueryProperty`, `UpdateProperty`

> `Description` / `ManufacturerName` / `ManufacturerDescription` / `SerialNumber`
> 文件註明是「為了相容 ACQUA 2 而保留」— 新開發不要依賴,改用 `QueryProperty`。

### IAcquaBaseObject — ⭐ 被低估的萬用逃生門

所有 Project / ProjectGroup / MObject 都繼承這個:

| 成員 | 簽章 |
|---|---|
| `RowID` | `Get As Long` — 該項目在資料庫表中的 row ID |
| `QueryProperty` | `Function (PropertyName As String) As String` |
| `UpdateProperty` | `Sub (PropertyName As String, PropertyValue As String)` — **屬性不存在會自動建立** |

> 💡 `UpdateProperty` 可以任意新增自訂欄位 —— 拿來寫入 DUT 序號、韌體版本、測試批次編號、
> 治具 ID 等 metadata **非常好用**,而且會跟量測資料一起存進資料庫。
> 做測試自動化時建議一律用它標記每次測試的上下文。

### CoClass MeasurementClient / IMeasurementClient

標註 `noncreatable, hidden` / `for internal use only`,共 33 個 `OnEnterState_*` / `OnLeaveState_*` /
`OnState_*` 方法(Idle / Loops / Loop / Measurements / Measurement / RefMeasurements /
RefMeasurement / CheckingSMDs / CheckingSMD / StoreMeasurement / StoreRefMeasurement)。

**內部用,不要碰。** 但它洩漏了 ACQUA 的量測狀態機結構,debug 時當背景知識有用。

---

## 5. 範例程式碼解析

### 5.1 `.vbproj` 揭露的完整 TypeLib 清單 ⭐

CHM 只寫了 `Acqua3` 一個,但範例專案實際引用了 **12 個**:

| TypeLib | GUID | 用途 | 有無 CHM |
|---|---|---|:---:|
| **Acqua3** | `{1E189209-517B-46E7-AF7D-269A505ABD2F}` | 主控制介面 | ✅ 本 CHM |
| **HEADACQUAlyzer** | `{E7763016-A964-11D3-875C-00A024540BF1}` | MeasurementEngine、MFE4/MFE6 設定、`EMEResult` | ❌ |
| **ACQUAReportGenerator** | `{82891022-D04B-4D90-BB9A-14F0A2118211}` | 報告產生器全部選項 | ❌ |
| **AcquaDBMask** | `{CF42356C-CABD-4875-9875-EA06D1BB80D6}` | ⭐ **資料庫物件模型 — 讀結果數值靠它** | ❌ |
| HEADObjectDatabase | `{0EB1EF39-35E7-4140-BBD5-D4BAFD852B86}` | 底層物件資料庫 | ❌ |
| HEADDataset | `{E776306A-A964-11D3-875C-00A024540BF1}` | 資料集 / HDF 存取 | ❌ |
| HEADTags | `{E776306D-A964-11D3-875C-00A024540BF1}` | 標籤 | ❌ |
| HEADEventLib | `{E7763009-A964-11D3-875C-00A024540BF1}` | 事件 | ❌ |
| HEADVBTools | `{E7763015-A964-11D3-875C-00A024540BF1}` | VB 工具集 | ❌ |
| REPLib | `{C477A025-C848-11D2-812D-9D87C893D80C}` | 報告底層 | ❌ |
| Scripting | `{420B2830-E718-11CF-893D-00A0C9054228}` | MS Scripting Runtime | (MS) |
| stdole / VBA | — | VB 執行期 | (MS) |

**本機另外還註冊了這些可能有用的 ProgID**(從註冊表實測):

```
HEADACQUAlyzer.MeasurementEngine       MFE 量測引擎
ACQUAReportGenerator.RepGen            報告產生器
AcquaDBMask.Application                ⭐ 資料庫存取入口
ACQUAFormulaInterpreter.Eval           公式運算
HEADDataset.DatasetFactory             HDF 資料集
HEADSignalProcessing.SPP*              ~40 種訊號分析(Loudness/Sharpness/THD/STI/...)
HEADFileConverterExcel.HDF2Excel       HDF → Excel
HEADFileConverterMATLAB.HDF2MAT        HDF → MATLAB
HEADFileConverterWave.HDF2Wave         HDF → WAV
HEADRemoteControl.Application          硬體遠端控制
HEADSignalGenerator.*                  訊號產生
ACQUAHDFToolsLib.POLQACalc             POLQA 計算
```

> 這張表比 CHM 值錢。做結果分析、匯出 Excel、訊號後處理,全都在這裡。

### 5.2 VB6 `frmMain.frm` — 值得抄的模式

**啟動與等待(關鍵樣板)**
```vb
Set m_applicationACQUA = New Acqua3.AcquaApplication
Do
    Sleep 200
Loop Until m_applicationACQUA.AppLoadFinished
```

**切換專案後必須等載入完成**
```vb
Project.SelectAsActive
Do
    Sleep 100
Loop Until m_applicationACQUA.SelectedProjectLoaded
Set m_selectedProject = m_applicationACQUA.SelectedProject   ' 這時才拿得到 IProjectSelected
```

**MFE 設定(跨 TypeLib,CHM 沒有)**
```vb
With m_selectedProject.MeasurementEngine.Mfe4.Settings
    For i = 1 To .Count                    ' ⚠️ MFE Settings 索引從 1 開始!
        Call LVMFE4Settings.ListItems.Add(, , .Names(i))
    Next i
End With

' 套用具名設定
m_selectedProject.MeasurementEngine.Mfe4.Settings.ActiveSetting = "MySetting"
m_selectedProject.MeasurementEngine.Mfe6.Settings.ActiveSetting = "MySetting"
```
⚠️ **索引基準不一致的陷阱:**
`ProjectGroups` / `Projects` / `MeasurementObjects` 的 `Item()` **從 0 開始**,
但 `MeasurementEngine.MfeX.Settings.Names(i)` **從 1 開始**。

**自動重試 / 中止的決策點**
```vb
Private Sub m_applicationACQUA_OnFinishedSingleMeasurement( _
        ByVal SMDTitle As String, ByVal ResultStatus As HEADACQUAlyzer.EMEResult, _
        ByVal Progress As Long, ByVal NbrOfMeasurements As Long, _
        UserReaction As Acqua3.EUserReaction)      ' ← 沒有 ByVal = ByRef 輸出

    If Not (ResultStatus = emeresultMeasDoneOk Or ResultStatus = emeresultMeasDone) Then
        UserReaction = eurCancelAllMeasurements    ' 或 eurRedoThisMeasurement 做自動重試
    End If
End Sub
```
**這是整套自動化最重要的擴充點** — 自動重試、失敗即停、記錄失敗項全部在這裡實作。

**報告產生器選項**
```vb
With m_applicationACQUA.ReportGenerator
    .ShortReportOnly    = True
    .ShowMMDPath        = False
    .ShowResultIndex    = True
    .ShowResultComment  = True
    .ShowDiagramMode    = esdmAll        ' esdmAll / esdmSingleRun / esdmNone
    .ShowSettingMode    = essmAll        ' essmAll / essmAllButLimits / essmOnlyLimits / essmNone
End With
Call SetForegroundWindow(m_applicationACQUA.ReportGenerator.Handle)   ' 有 Handle 屬性
m_selectedProject.CreateReportForMO m_selectedObject.RowID, erstLastPosition, "C:\out.doc", 0
```

> ⚠️ 範例第 613 行讀的是 `.ShortReport`,但第 541 行寫的是 `.ShortReportOnly` —
> **讀寫用了不同的屬性名**。這兩個到底是不是同一個屬性,要自己驗證。

### 5.3 VB.NET `frmMain.vb` — ⚠️ 有原廠 bug

[frmMain.vb:203-208](Example%20Applications/VB.Net/Acqua3COMDemo/frmMain.vb#L203-L208):

```vb
Select Case LBReportMode.SelectedIndex
    Case 0 : SelType = Acqua3.EReportSelectionType.erstFirstPosition
    Case 0 : SelType = Acqua3.EReportSelectionType.erstLastPosition   ' ← 應為 Case 1
    Case 0 : SelType = Acqua3.EReportSelectionType.erstAllPositions   ' ← 應為 Case 2
    Case 0 : SelType = Acqua3.EReportSelectionType.erstForIndex       ' ← 應為 Case 3
End Select
```

四個 `Case` 全寫成 `0`。VB 的 `Select Case` 只會執行第一個符合的分支,所以:
- 選第一項 → 得到 `erstFirstPosition`(碰巧對)
- 選其他任何項 → **完全不進 Select,`SelType` 保持未初始化的 0** → 一律變成 `erstFirstPosition`

**不要照抄這段。** 另外 [frmMain.vb:240](Example%20Applications/VB.Net/Acqua3COMDemo/frmMain.vb#L240) 的
`For Each MO In ...` 用了未宣告的 `MO`(靠 `Option Strict Off` 才編得過)。

**結論:以 VB6 版為主要參考,VB.NET 版只當入門讀。**

---

## 6. 開發順序(建議按階段走,不要跳)

### 階段 0 — 環境準備(半天)

| 項目 | 狀態 | 說明 |
|---|---|---|
| ACQUA 6 已安裝 | ✅ 已確認 | `Acqua6.exe` v6.2.210.33798 |
| COM 已註冊 | ✅ 已確認 | ProgID `Acqua3.AcquaApplication` → LocalServer32 |
| SQL Server | ✅ 已確認 | 執行個體 `ACQUADBSERVER`,FILESTREAM 已啟用 |
| **ACQUA 資料庫** | ✅ 已建立 | `61_Demo_SMDs_Rev07`(**132 個 SMD**)、`AUTOMATION_TEST_0806`(空) |
| **Python** | ✅ **原廠已內建** | HEAD 附的 32-bit Python 3.9.13,pywin32 已裝好 |
| 專案 venv | ✅ 已建立 | `ACQUA Automation\.venv`(+ Flask 3.1.3 + pywin32 312) |
| **ACOPT18 授權** | 🔴 **未確認** | **沒有它 `Dispatch()` 會直接失敗 —— 唯一的硬性阻塞** |
| 量測硬體 | ❓ 未確認 | 已裝 HEAD device drivers |

**不用自己裝 Python。** 直接用原廠內建的建 venv(專案已經建好了):

```powershell
& "C:\Program Files (x86)\Common Files\HEAD shared\Python39\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install flask pywin32

# 確認位元數 —— 必須印出 32
.\.venv\Scripts\python.exe -c "import struct; print(struct.calcsize('P')*8)"
```

> ⚠️ 系統 PATH 上的 `python` 是 Microsoft Store 的空殼,執行不出版本號,**不能用**。

> 先把 ACQUA 手動打開、連上資料庫、手動跑通一次量測。
> **COM 自動化不會修好手動就跑不通的東西。**

### 階段 1 — ⭐ Dump 出「當前」的 API(最重要的一步,1 小時)

CHM 是 2012 年的,你裝的是 2024+ 的 ACQUA 6。**先確認實際 API 長什麼樣。**

> ✅ **這一步已經做完了。** 工具與結果都在專案裡:

```powershell
cd "ACQUA Automation"
.\.venv\Scripts\python.exe tools\dump_typelib.py                  # 全部
.\.venv\Scripts\python.exe tools\dump_typelib.py --enums-only     # 只看列舉
.\.venv\Scripts\python.exe tools\dump_typelib.py --grep SingleValue
```

這個工具用 `LoadRegTypeLib` **唯讀走訪**型別資訊:

- ✅ **不會啟動 ACQUA**(不呼叫 `CoCreateInstance`)
- ✅ 不產生 `gencache` 快取檔(不汙染 Python 安裝目錄)
- ✅ 涵蓋 `Acqua3` / `HEADACQUAlyzer` / `ACQUAReportGenerator` / `AcquaDBMask` / `HEADObjectDatabase`

取得的數值已寫進 `ACQUA Automation/acqua/constants.py`,主要成果見 §3 與 §11。

> 💡 也可以用 `makepy` 產生早期繫結 wrapper,或用 **OleView.exe** 反組譯成 IDL 交叉比對。
> 但 `makepy` 會寫入 `site-packages\win32com\gen_py\`,唯讀走訪比較乾淨。

### 階段 2 — 最小連通性驗證(1 小時)

**目標只有一個:證明 Python 能叫得動 ACQUA。** 不要一次寫太多。

```python
import pythoncom, win32com.client
pythoncom.CoInitialize()
app = win32com.client.Dispatch("Acqua3.AcquaApplication")
print("dispatch OK")
import time
while not app.AppLoadFinished:
    pythoncom.PumpWaitingMessages(); time.sleep(0.2)
print("ACQUA 已就緒")
```

跑通了才往下走。這一步會攔截掉:授權問題、位元數不符、ProgID 錯誤、DCOM 權限。

### 階段 3 — 唯讀瀏覽(半天)

連資料庫、列出 ProjectGroups / Projects / MeasurementObjects。**先不要量測。**
確認階層走得通、`SelectAsActive` + `SelectedProjectLoaded` 的等待邏輯正確。

### 階段 4 — 事件接線(1 天,最難的一步)

把 §7 的事件類別接上,**先只是印出來**。重點驗證:
- 事件真的有進來(訊息幫浦有沒有寫對)
- `ResultStatus` 的實際數值 vs 你在階段 1 抄的 `EMEResult`
- ByRef 的 `UserReaction` / `Continue` 回傳機制是否如預期
- ⭐ 把 `OnFinishedMeasurements` 的 `ResultOverview` 整個 dump 出來看看是什麼結構

### 階段 5 — 實際量測 + pass/fail 判定(2–3 天)

`StartMeasurements` 全跑,或 `FindFirstSMD` + `StartSingleMeasurement` 只跑指定項。
在 `OnFinishedSingleMeasurement` 累積結果,產出測試報告。
加入自動重試(`eurRedoThisMeasurement`)與失敗即停(`eurCancelAllMeasurements`)。

### 階段 6 — 讀取數值結果(視需求)

如果需要具體數字(不只是 OK/NOT OK):
- 先試 `ResultOverview`
- 不夠的話接 `AcquaDBMask.Application` → `MeasurementResults` / `SingleValue`
- 或用 `HEADFileConverterExcel.HDF2Excel` 把結果匯出後在外部分析

### 階段 7 — 產線化

CI 整合、無人值守、日誌、`UpdateProperty` 寫入 DUT metadata、報告歸檔。

---

## 7. Python 實作骨架

```python
"""
ACQUA 測試自動化骨架 (ACOPT18 COM Interface)
需求:32-bit Python + pywin32 + 已安裝並授權的 ACQUA
"""
import time
import pythoncom
import win32com.client

# ── 列舉常數 ─────────────────────────────────────────────
# 來源:Acqua3COM.chm(已確認)
class EUserReaction:
    NO_REACTION   = 0
    DO_NEXT       = 1
    REDO_THIS     = 2
    CANCEL_ALL    = 3

class EMEEventType:
    INFORMATION = 0
    WARNING     = 1
    ERROR       = 2

class EReportSelectionType:
    FIRST_POSITION = 0      # 注意:數值不連續
    LAST_POSITION  = 3
    ALL_POSITIONS  = 4
    FOR_INDEX      = 5

# ✅ EMEResult 屬於 HEADACQUAlyzer TypeLib,數值已從 TypeLib 實測取得
class EMEResult:
    UNDEFINED                     = 0
    MEAS_DONE                     = 1
    MEAS_DONE_OK                  = 2   # ← PASS
    MEAS_DONE_NOT_OK              = 3   # ← FAIL
    MEAS_ERROR                    = 4
    USER_CANCELED                 = 5
    MEAS_NOT_POSSIBLE             = 6
    IGNORE                        = 7   # CHM 未記載
    MEAS_DONE_NOT_OK_NOT_REQUIRED = 8   # CHM 未記載 — 沒過但非必要,不該算 FAIL

    # 只用 == MEAS_DONE_OK 判定會把非必要項誤判成 FAIL
    PASSING = {MEAS_DONE, MEAS_DONE_OK, IGNORE, MEAS_DONE_NOT_OK_NOT_REQUIRED}


# ── 事件接收器 ───────────────────────────────────────────
class AcquaEvents:
    """對應 VB 的 WithEvents。方法名必須與 IAcquaApplicationEvents 完全一致。"""

    def _init(self):
        # DispatchWithEvents 不會呼叫 __init__,自訂初始化放這裡由外部呼叫
        self.results = []
        self.cancel_requested = False
        self.retry_count = {}
        self.max_retries = 1

    # --- 進度類:純資訊 ---
    def OnProgress(self, Description, ProgressCounter, TotalCount):
        if TotalCount:
            print(f"  [{ProgressCounter}/{TotalCount}] {Description}")

    def OnEvent(self, Description, EventType):
        tag = {0: "INFO", 1: "WARN", 2: "ERROR"}.get(EventType, "?")
        print(f"  <{tag}> {Description}")

    def OnBeginMeasurements(self, SelectedProject, MeasurementObject, NbrOfMeasurements):
        print(f"=== 開始:共 {NbrOfMeasurements} 筆量測 ===")

    def OnBeginSingleMeasurement(self, SMDTitle, Progress, NbrOfMeasurements):
        print(f"[{Progress}/{NbrOfMeasurements}] 量測中:{SMDTitle}")

    # --- 決策點:ByRef 輸出以「回傳值」給回 ACQUA ---
    def OnFinishedSingleMeasurement(self, SMDTitle, ResultStatus,
                                    Progress, NbrOfMeasurements, UserReaction):
        passed = ResultStatus == EMEResult.MEAS_DONE_OK
        self.results.append({"smd": SMDTitle, "status": ResultStatus, "pass": passed})
        print(f"    → {SMDTitle}: status={ResultStatus} {'PASS' if passed else 'FAIL'}")

        if self.cancel_requested:
            return EUserReaction.CANCEL_ALL

        if not passed:
            n = self.retry_count.get(SMDTitle, 0)
            if n < self.max_retries:
                self.retry_count[SMDTitle] = n + 1
                print(f"    → 重試 {SMDTitle}({n + 1}/{self.max_retries})")
                return EUserReaction.REDO_THIS
            # 失敗即停就改成 CANCEL_ALL
        return EUserReaction.DO_NEXT

    def OnFinishedMeasurements(self, SelectedProject, MeasurementObject,
                               NbrOfMeasurements, NbrOfMeasurementsFinished,
                               Canceled, ResultOverview):
        print(f"=== 結束:{NbrOfMeasurementsFinished}/{NbrOfMeasurements}"
              f"{' (已取消)' if Canceled else ''} ===")
        # ⭐ 階段 4 務必把這個 dump 出來研究,CHM 沒說明它的結構
        print(f"    ResultOverview type={type(ResultOverview)} value={ResultOverview!r}")

    def OnCallbackEvent(self, EventDescription, Continue):
        """ACQUA 詢問使用者決策(例如「請接上治具」)。無人值守一律回 True。"""
        print(f"  [CALLBACK] {EventDescription} → 自動繼續")
        return True


# ── 工具:訊息幫浦 ───────────────────────────────────────
def pump_until(predicate, timeout=120.0, interval=0.05, what="condition"):
    """COM 事件靠 Windows 訊息迴圈送達 —— 等待時必須持續打幫浦,
    等同 VB 的 DoEvents / Sleep 迴圈。純 time.sleep() 會讓事件全部卡住。"""
    deadline = time.monotonic() + timeout
    while not predicate():
        pythoncom.PumpWaitingMessages()
        time.sleep(interval)
        if time.monotonic() > deadline:
            raise TimeoutError(f"等待逾時:{what}")


# ── 主流程 ───────────────────────────────────────────────
def main():
    pythoncom.CoInitialize()
    try:
        app = win32com.client.DispatchWithEvents("Acqua3.AcquaApplication", AcquaEvents)
        app._init()

        print("等待 ACQUA 啟動…")
        pump_until(lambda: app.AppLoadFinished, timeout=180, what="AppLoadFinished")

        if not app.SelectDatabase(r".\AcquaDBServer", "MyDatabase", True, "", ""):
            raise RuntimeError("資料庫連線失敗")
        print(f"已連線:{app.SelectedSQLServerName} / {app.SelectedDatabaseName}")

        # 找到目標專案(索引從 0 開始)
        target_pg, target_pj = "MyGroup", "MyProject"
        project = None
        for i in range(app.ProjectGroups.Count):
            pg = app.ProjectGroups.Item(i)
            if pg.Title != target_pg:
                continue
            for j in range(pg.Projects.Count):
                pj = pg.Projects.Item(j)
                if pj.Title == target_pj:
                    project = pj
                    break
        if project is None:
            raise RuntimeError(f"找不到專案 {target_pg}/{target_pj}")

        project.SelectAsActive()
        pump_until(lambda: app.SelectedProjectLoaded, timeout=180, what="SelectedProjectLoaded")
        sp = app.SelectedProject           # ← 這時才是 IProjectSelected
        print(f"已開啟專案:{sp.Title}")

        # 選 / 建立量測物件(接受索引或名稱)
        dut_name = "DUT_001"
        titles = [sp.MeasurementObjects.Item(i).Title
                  for i in range(sp.MeasurementObjects.Count)]
        if dut_name not in titles:
            sp.MeasurementObjects.AddMeasurementObject(dut_name, "自動化建立")
        mo = sp.SelectActiveMeasurementObject(dut_name)
        if mo is None:
            raise RuntimeError("選取量測物件失敗")

        # ⭐ 用 UpdateProperty 標記測試上下文(屬性不存在會自動建立)
        mo.UpdateProperty("SerialNo", "SN-2026-0001")
        mo.UpdateProperty("Firmware", "v1.2.3")
        mo.UpdateProperty("TestRun", "auto-001")

        # 開始量測(True = 使用 MMD 內建設定)
        sp.StartMeasurements(True, mo.Title)

        # ⚠️ StartMeasurements 是非同步的 —— 必須在這裡打幫浦,事件才會進來
        time.sleep(1.0)   # 給 IsMeasuring 一點時間變 True
        pump_until(lambda: not app.IsMeasuring, timeout=3600, what="量測完成")

        # 產出報告
        sp.CreateReportForMO(mo.RowID, EReportSelectionType.LAST_POSITION,
                             r"C:\reports\result.doc", 0)

        # 匯總
        ev = app                                     # 事件狀態存在包裝物件上
        total = len(ev.results)
        failed = [r for r in ev.results if not r["pass"]]
        print(f"\n總計 {total} 筆,失敗 {len(failed)} 筆")
        for r in failed:
            print(f"  FAIL: {r['smd']} (status={r['status']})")
        return 1 if failed else 0

    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    raise SystemExit(main())
```

### Python 五大陷阱

| # | 陷阱 | 說明 |
|:-:|---|---|
| 1 | **忘記 `PumpWaitingMessages()`** | COM 事件靠 Windows 訊息迴圈遞送。只用 `time.sleep()` 會讓所有事件卡死,程式看起來像當掉 |
| 2 | **位元數不符** | ACQUA 是 x86。裝 32-bit Python 最省事;`Dispatch` 失敗報 "class not registered" 通常就是這個 |
| 3 | **ByRef 輸出參數** | `UserReaction`、`Continue` 在 pywin32 是用 **return** 回傳,不是改參數。多個 out 參數時回傳 tuple。**階段 4 一定要實測驗證** |
| 4 | **`DispatchWithEvents` 不呼叫 `__init__`** | 事件類別的初始化要另外寫一個 `_init()` 手動叫,否則屬性不存在 |
| 5 | **索引基準不一致** | `ProjectGroups`/`Projects`/`MeasurementObjects` 的 `Item()` 從 **0** 開始;`MeasurementEngine.MfeX.Settings.Names(i)` 從 **1** 開始 |

額外:`CoInitialize()` 每個執行緒都要各自呼叫;COM 物件不能隨意跨執行緒傳遞
(需要 `CoMarshalInterThreadInterfaceInStream`)。建議**單執行緒跑完整套流程**,別急著多工。

---

## 8. C++ 實作要點

```cpp
// 用 #import 從 EXE 內嵌的 TypeLib 產生型別安全的包裝
// 編譯期會產出 Acqua6.tlh / Acqua6.tli —— 打開來看就是完整 API 宣告(等同 CHM 內容)
#import "C:\\Program Files (x86)\\HEAD Analyzer ACQUA\\Acqua6.exe" \
        no_namespace, named_guids

#include <atlbase.h>
#include <atlcom.h>

int main() {
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);   // ← 事件必須用 STA
    {
        IAcquaApplicationPtr app;
        HRESULT hr = app.CreateInstance(__uuidof(AcquaApplication));
        if (FAILED(hr)) return 1;

        while (!app->AppLoadFinished) PumpMessages();    // 自行實作訊息幫浦
        app->SelectDatabase(L".\\AcquaDBServer", L"MyDatabase", VARIANT_TRUE, L"", L"");
    }
    CoUninitialize();
    return 0;
}
```

**要點:**

| 項目 | 說明 |
|---|---|
| 事件接收 | `IAcquaApplicationEvents` 是 dispinterface。手寫 `IDispatch` sink + `IConnectionPoint` 很囉唆 → **用 ATL 的 `IDispEventImpl`**,省掉 90% 樣板碼 |
| 執行緒模型 | 必須 `COINIT_APARTMENTTHREADED`(STA)。用 MTA 事件不會正常送達 |
| 訊息幫浦 | 跟 Python 一樣不可省。`PeekMessage`/`TranslateMessage`/`DispatchMessage` 迴圈 |
| 位元數 | 建議編 **x86**,與 ACQUA 對齊 |
| ByRef 參數 | C++ 這邊比 Python 直觀:直接寫 `*pUserReaction = eurRedoThisMeasurement;` |
| 跨 TypeLib | `MeasurementEngine`、`ReportGenerator` 屬於別的 TypeLib,要一併 `#import` ACQUAlyzer.exe / ACQUAReportGenerator.exe |

**建議:除非有硬性效能或整合需求,先用 Python 做出可跑的版本,再決定要不要移植到 C++。**
這類自動化的瓶頸永遠在量測本身(秒級到分鐘級),不在膠水語言。

---

## 9. 快速對照表:VB → Python

| VB6 / VB.NET | Python (pywin32) |
|---|---|
| `New Acqua3.AcquaApplication` | `win32com.client.Dispatch("Acqua3.AcquaApplication")` |
| `Dim WithEvents x As ...` | `DispatchWithEvents("Acqua3.AcquaApplication", HandlerClass)` |
| `Sleep 200` + `DoEvents` | `pythoncom.PumpWaitingMessages()` + `time.sleep(0.2)` |
| `Loop Until app.AppLoadFinished` | `pump_until(lambda: app.AppLoadFinished)` |
| `Set PG = app.ProjectGroups.Item(0)` | `pg = app.ProjectGroups.Item(0)` |
| `For Each PJ In PG.Projects` | `for i in range(pg.Projects.Count): pj = pg.Projects.Item(i)` |
| `If MO Is Nothing Then` | `if mo is None:` |
| `UserReaction = eurCancelAllMeasurements`(ByRef) | `return EUserReaction.CANCEL_ALL` |
| `Continue = True`(ByRef) | `return True` |
| `On Error GoTo ErrorHandler` | `try: ... except pythoncom.com_error as e:` |
| `MsgBox Err.Description` | `print(e.excepinfo[2])` |

---

## 10. 待確認清單

### ✅ 已完成(2026-08-10)

- [x] 32-bit Python + pywin32 就緒(**原廠內建**,不用自己裝)
- [x] TypeLib 已 dump,確認 CHM 有多處過時
- [x] ⭐ 已取得 **`EMEResult` 的實際數值**(含 CHM 未記載的 7 / 8)
- [x] 已確認 **SMD 列舉解法**(`GetSMDsRecursive()`)
- [x] 已確認 **數值讀取解法**(`SingleValue.Value / .Unit / .Status`)
- [x] 已確認 **變數驅動解法**(`MeasurementEngine.UsedVariables`)
- [x] ACQUA 資料庫已建立,`61_Demo_SMDs_Rev07` 含 132 個測項
- [x] 自動化程式已完成並通過**模擬模式**驗證(兩種執行模式)

### 🔴 阻塞中

- [ ] **ACOPT18 授權已購買且生效** —— 沒有的話 `Dispatch()` 直接失敗,整套都不用談
- [ ] 各測項所需的 **ACOPT 模組授權**(6819 / 6820 / 6844 / 6857 / 6869…共 17 個模組)

### ⬜ 待實機驗證(前提:授權確認)

- [ ] ACQUA 手動操作可以正常連資料庫、跑完一次量測
- [ ] `Dispatch("Acqua3.AcquaApplication")` 成功且 `AppLoadFinished` 會變 True
- [ ] ⚠️ **demo 專案的 `rProjectGroup` 是 NULL** → COM 的 `ProjectGroups→Projects` 走訪找不找得到它
- [ ] 事件確實會進來(`OnProgress` 有印出東西)
- [ ] ByRef 的 `UserReaction` / `Continue` 回傳機制
- [ ] ⭐ **DBMask 的 `SMD.ID` 是否等於 `StartSingleMeasurement(SMDRowID)` 要的 RowID**
- [ ] `MeasurementEngine.UsedVariables` vs `ResultVariables` —— 條件執行到底讀哪一組
- [ ] `IVariables.Add()` 後設 `.Name` 是否需要 `Save()` 才生效
- [ ] `OnFinishedMeasurements` 的 `ResultOverview` 結構
- [ ] 17 個需要外部參考檔(`.dat`/`.fft`)的測項,檔案是否存在

---

## 11. ⭐ CHM 之外的三條路(2026-08-10 新增)

CHM 只涵蓋 `Acqua3` 一個 TypeLib。實際做自動化會用到的東西,有一大半不在裡面。
以下都是從 TypeLib 實測取得的。

### 11.1 AcquaDBMask —— 列舉測項與讀取數值

`Acqua3` 介面能「叫 ACQUA 動手」,但**列不出測項清單、也讀不到數值**。
這兩件事要靠 `AcquaDBMask`(ProgID `AcquaDBMask.Application`)。

⚠️ **兩套模型的名詞不一樣,這是最容易搞混的地方:**

| Acqua3 說的 | AcquaDBMask 說的 | VB6 範例 UI 上寫的 |
|---|---|---|
| `ProjectGroup` | `Project` | "project group" |
| `Project` | **`Subproject`** | **"Selected Subproject"** ←! |
| `MeasurementObject` | `LocalMeasurementObject` | "Measurement Object" |

⚠️ **連線的參數順序也相反:**

```python
Acqua3     : SelectDatabase(SQLServerName, DatabaseName, winAuth, user, pwd)
AcquaDBMask: Connect(DatabaseName, SQLServerName)          # ← 資料庫在前!
```

**資料模型(TypeLib 實測確認):**

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
                     │     .Value .Unit .Title .Status .Precision .HasValue
                     └─ Runs
```

**列舉全部 SMD(含標題)—— 這是 `FindFirstSMD` 做不到的:**

```python
sub = app.Projects.Item(i).Subprojects.Item(j)
smds = sub.GetSMDsRecursive()      # ⭐ 回傳全部 SMD
n    = sub.GetNbrOfSMDsRecursive()
for k in range(smds.Count):
    smd = smds.Item(k)
    print(smd.ID, smd.Title, smd.SMDType, smd.NumberOfMeasurementResults)
```

**讀出數值:**

```python
mr = smd.MeasurementResults.Item(-1)      # 最後一筆
sv = mr.SingleValue1
if sv.HasValue:
    print(sv.Title, sv.Value, sv.Unit, sv.Status)   # Status 見 ESingleValueCheckState
```

**程式化建立 MMD / SMD(`Acqua3` 完全沒有這個能力):**

```python
sub.MmdsAndSmds.AddMMD(title, description)
sub.MmdsAndSmds.AddSMD(title, description, smdType, smdCompleteFileName)
```

> ⚠️ `AddSMD` 後兩個參數的合法值未知。最可靠做法是先在 GUI 建一個 SMD,
> 再用 `GetSMDsRecursive()` 把它的 `SMDType` 讀出來當範本。

### 11.2 兩種執行模式

| | `selected` 逐項勾選 | `conditional` 變數驅動 |
|---|---|---|
| 誰決定跑哪些 | **你的程式** | **ACQUA** |
| COM 呼叫 | `StartSingleMeasurement` 逐項 | `StartMeasurements` 一次 |
| 篩選依據 | 你給的 SMD RowID 清單 | 專案樹的 `ConditionalExecution` 讀變數 |
| 適合 | 重跑失敗項、抽測、CI 指定子集 | 依 DUT 屬性決定完整測試計畫 |

**變數怎麼設**(`IProjectSelected.MeasurementEngine` → `HEADACQUAlyzer.IMeasurementEngine`):

```python
me = project.MeasurementEngine
vs = me.UsedVariables            # IVariables:Item/Count/Add/Delete/Exists/Save

v = vs.Add()                     # 沒有 AddNamed() —— 只能 Add() 再設 Name
v.Name  = "DUT_speakerphone_type"
v.Type  = 2                      # evtString
v.Value = "Shared"
v.State = 2                      # evsUserDefined
vs.Save()

project.StartMeasurements(True, mo.Title, "")   # ACQUA 依條件自動篩選
```

變數名稱建議沿用 HEAD 官方精靈用的那組(見 §11.4):
`DUT_speakerphone_type`、`DUT_connection_type`、`DUT_is_deskphone`、
`DUT_premium_reqs`、`DUT_pickup_range_*`、`DUT_stereo_calling`…

> ⚠️ `MeasurementEngine` 另有 `ResultVariables`。條件執行到底讀哪一組,**待實測確認**。

### 11.3 `RunScript` —— 從 COM 執行 ACQUA 內部 Python

`IMeasurementEngine` 有兩個 CHM 完全沒提的東西:

```python
me.PythonAvailable                      # bool
me.RunScript(Language, Code)            # ⭐ 在 ACQUA 內部執行腳本
me.DoMeasurementEx2(smdFile, subProjectPath, info,
                    ScriptBeforeFilename, ScriptAfterFilename)   # 量測前後掛腳本
me.CheckPreconditions()                 # 開跑前檢查硬體/校正
```

**這打通了 COM(外部)與 ACQUA 內建 Python(內部)。** 可以從外部呼叫只有
內部才拿得到的 API(例如 `HSL.save_var()`)。

`IMeasurementEngine` 其他值得知道的成員:`Mfe4`…`Mfe11`、`Frontends`、`Labcore`、
`TurnTable`、`HHP`、`Hpo`、`HardwareConfig`、`Calibrations`、`SingleValues`、`ResultFiles`。

> 💡 VB6 範例只用到 `Mfe4` / `Mfe6` —— 那是舊版。現在有到 `Mfe11`。

### 11.4 腳本型 SMD —— `SMD/` 資料夾是什麼

後來收到的 `SMD/` 資料夾裡有兩個檔案:

```
DUT & Measurement Wizard.aqs      146 B     ← SMD 定義(XML)
dut_meas_wizard.py             12.6 KB     ← 實際的 Python 程式
```

`.aqs` 內容就一行:

```xml
<AcquaScript><Language>Python</Language>
<ExternalScriptFilename>dut_meas_wizard.py</ExternalScriptFilename></AcquaScript>
```

這代表 **ACQUA 有內建 Python 腳本引擎,一個「測項」本身可以就是一支腳本**。

這支腳本是 **DUT 與量測精靈**:跳出問卷視窗詢問 DUT 屬性(免持型態、連接方式、
收音/播放距離、是否 Premium…),把答案用 `save_var()` 存成 ACQUA 變數,
再由專案樹的 `ConditionalExecution` 決定哪些 SMD 要跑。

> ⭐ **這就是 HEAD 官方版的「勾選要跑哪些測項」** —— 跟 §11.2 的 `conditional` 模式是同一件事。
>
> ⚠️ 但這支腳本**目前跑不起來** —— 它 `from HSL import ...`,而 `HSL` 模組整台機器上都找不到。
> 應該隨完整測試套件提供,**目前拿到的只是片段**。
>
> 🔍 腳本內容出現 `EMTR`、`Teams client`、`SRW`、personal/shared space speakerphone
> —— 這是 **Microsoft Teams 周邊裝置認證**的測試規範。

### 11.5 三個層級總覽

```
層級 1  ACQUA GUI                     人手動點
層級 2  COM 介面 (ACOPT18)             外部程式遙控        ← 本文件主題
層級 3  ACQUA 內建 Python 腳本          腳本住在 ACQUA 裡面  ← §11.4
```

| | COM (層級 2) | 腳本型 SMD (層級 3) |
|---|---|---|
| 程式跑在哪 | 外部行程 | ACQUA 內部 |
| 角色 | **指揮官** —— 決定跑什麼 | **士兵** —— 它本身就是一個測項 |
| 能碰到的 API | 有限的 COM 介面 | `HEAD.*` 完整內部 API |
| 適合 | 排程、批次、CI、串外部系統 | 客製量測邏輯、互動問卷、特殊計算 |

**兩者不是替代關係。** `RunScript`(§11.3)可以讓層級 2 直接呼叫層級 3。

---

## 附錄:CHM 解壓縮指令

```powershell
# 解除封鎖(從網路/OneDrive 來的檔案必做)
Unblock-File "Acqua3COM.chm"

# 解成 HTML
New-Item -ItemType Directory -Force C:\acqua_help | Out-Null
hh.exe -decompile C:\acqua_help "Acqua3COM.chm"
```

解出來的結構:
```
Acqua3.hhc / Acqua3.hhk            目錄與索引
Acqua3_coclasses\                  2 個 CoClass
Acqua3_enumerations\               3 個列舉
Acqua3_interfaces\                 12 個介面,共 ~150 個 HTML 頁
```

> ⚠️ 再次提醒:這份 CHM 是 **2012 年**的,對應 ACQUA 3。
> 你裝的是 **ACQUA 6.2.210**。當作參考文件用,**真相以 TypeLib dump 為準**。
