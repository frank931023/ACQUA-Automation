# ACQUA 測試自動化

用 COM 驅動 HEAD acoustics ACQUA,把「挑測項 → 跑 → 出報告」變成網頁上的操作,
並且可以把多批測試接成一條序列連續跑,中間留給治具移動。

```
瀏覽器  ──HTTP──▶  Flask  ──佇列──▶  工作執行緒(STA)  ──COM──▶  ACQUA
                                          │
                                          └──ADO──▶  SQL Server(測項樹 / 結果 / 數值)
```

---

## 快速開始

```bash
cd "ACQUA Automation"
.venv\Scripts\python.exe app.py --backend com     # 真的接 ACQUA
.venv\Scripts\python.exe app.py --backend mock    # 不接 ACQUA,純看流程
```

開 <http://127.0.0.1:5000/>。**ACQUA 要先自己開著**——程式是附掛上去,不會幫你啟動。

> 用 `.venv` 裡的 Python。HEAD 那份 `Python39` 沒有 flask。

三個頁面:

| 網址 | 做什麼 |
|---|---|
| `/` | 入口 |
| `/acqua/` | 連線、開專案、勾測項、跑、出報告 |
| `/acqua/plans` | 把多個計畫接成序列連續跑 |

---

## 兩種用法

**① 單次執行**(`/acqua/`)
連線 → 開專案 → 選 DUT → 載入測項 → 勾 → 命名 → 執行。

**② 執行序列**(`/acqua/plans`)
把勾好的一批存成「計畫」,再把多個計畫排成序列。每一步之間會停下來調整
治具位置。**計畫可以來自不同資料庫**——執行時會自動切過去。

```
① ZoomRooms / Front_of_Room ・ 226 項
   ↓ setup:0°／1m   ・ 切換到 51_MS_Teams_Rev05_SP2
② MS Teams Speakerphone / DUT_A ・ 40 項
```

每一步可以各自指定 run 名稱、DUT、Word 檔名與位置。

---

## 設計上的幾個關鍵決定

### 逐項送,而不是整批交給 ACQUA

`StartMeasurements` 會讓 ACQUA 自己決定跑哪些,互動精靈一定會跳出來等人。
改成用 `StartSingleMeasurement` 一筆一筆送:

- 勾幾項就跑幾項
- **中止是真的能停**——排隊的是 Python 的 for 迴圈,不送下一筆就結束了
- 需人工的項目可以事前排除

### 上下文(context)貫穿全域

`ctx = server | database | idProject`。所有繫在 `row_id` 上的東西都屬於某個 ctx。

> 為什麼要這麼嚴格:不同資料庫的 `idTreeItem` 各自從小編號開始、**必然重疊**。
> 實測 `#2443` 在一個庫是 `Info: MS Teams Information`,在另一個庫是
> `H. Analy. 3QUEST TS103`。送錯不會報錯,只會安靜地跑到別的測項。

三道防線(`acqua/context.py`):

1. **作廢**——換庫/換專案時,`_reset_context()` 一次清掉所有衍生狀態
2. **ctx 比對**——前端送出時聲明「我是在哪個上下文挑的」,不符就拒絕
3. **歸屬驗證**——開跑前確認每個 `row_id` 都屬於當前專案

計畫存的是**路徑 + 名稱**而不只是 `row_id`,跨庫執行時重新對應,對不上的明白回報。

### 視窗監看器取代不存在的自動化介面

ACQUA 跑到某些測項會開視窗等人(PDF 檢視器、Tcl/Tk 精靈、Win32 對話框)。
COM 沒有介面可以回答它們——`UserReaction` 的 ByRef 回傳在 pywin32 下**送不到 ACQUA**。

所以 `acqua/winwatch.py` 直接用 Win32 API 找視窗、按按鈕,規則寫在
`config.json` 的 `blocking_windows`。處理不了的就端到網頁上讓人按。

### 讀數值走 SQL,不走 COM

`AcquaDBMask.Connect()` 一律回 False;`FindFirstSMD("")` 回 0 筆而且不給標題。
所以測項列舉、數值、極限值全部改走 ADO 直連 SQL(`acqua/sqlcat.py`)。
已驗證 `idTreeItem == SMDRowID`。

---

## 專案結構

```
app.py                 Flask:路由 + StepRunner
acqua/
  worker.py            工作執行緒:COM 只在這裡碰,外面透過命令佇列
  backend_base.py      後端介面
  backend_com.py       真的 COM 實作
  backend_mock.py      模擬實作(同一組介面)
  state.py             共享狀態 + SSE 事件
  context.py           ⭐ 上下文規則:哪些狀態屬於哪個專案
  sqlcat.py            SQL 目錄:測項樹、數值、量測物件
  winwatch.py          擋路視窗的偵測與回答
  condeval.py          ConditionalExecution 的求值
  wizard.py            從條件式反推精靈選項
  testplans.py         計畫的本地儲存(plans/*.json)
  prefs.py             每個資料庫上次用什麼(prefs.json)
  runlog.py            執行紀錄(runs/current.json)
  constants.py         TypeLib 來的列舉
templates/
  _ui.html             ⭐ 共用設計系統(三頁都 include)
  _runmini.html        右下角進度視窗(跨頁)
  index.html           測項選擇
  plans.html           執行序列
  home.html            入口
tools/
  check_context.py     上下文一致性檢查
  check_ui.py          前端與路由的機械化盤點
```

### 為什麼 COM 只在工作執行緒碰

COM 的 STA 綁執行緒。所有 COM 物件都由 `AcquaWorker` 持有,Flask 用命令佇列
跟它溝通。中止/暫停**刻意不走佇列**——`run_smds` 正在阻塞那條執行緒,
排進去就永遠輪不到。

SQL 不同:`raw_query()` 自己確保呼叫端執行緒有 COM(ADO 也是 COM),
所以像「DUT 下拉選單」這種查詢可以直接在請求執行緒做,不用排隊等量測跑完。

> 這裡踩過一個坑:一開始寫成「用完就 `CoUninitialize`」,結果拆掉 apartment
> 之後工作執行緒對 ACQUA 的 proxy 全部斷線。**初始化之後不要收。**

---

## 結果狀態碼

判定完全來自 ACQUA,我們只翻譯(`acqua/constants.py`):

| 碼 | 名稱 | 意思 | 算通過 |
|---:|---|---|:--:|
| 0 | Undefined | 未定義 | ✗ |
| 1 | Done | 量完,**沒有判定標準** | ✓ |
| 2 | OK | 判定通過 | ✓ |
| 3 | **Not OK** | 量完但**超出標準** | ✗ |
| 4 | Error | 量測過程出錯 | ✗ |
| 5 | User canceled | 被中止 | ✗ |
| 6 | Not possible | 缺前置條件 | ✗ |
| 7 | Ignored | 略過 | ✓ |
| 8 | Not OK (not required) | 沒過但非必要項 | ✓ |

負數是我們自己標的,不跟 ACQUA 的號碼空間相撞:

| 碼 | 名稱 | 意思 |
|---:|---|---|
| −1 | NoResult | 等到逾時都沒收到結果事件(**不是通過,是不知道**) |
| −2 | Busy | ACQUA 持續忙碌,這筆沒送出去 |
| −3 | Exception | 送出或等待時我們這邊丟了例外 |

網頁上按「看明細」可以按狀態碼展開,看到是哪幾個測項。

---

## run 的名稱

傳給 `StartSingleMeasurement` 的 `ResultComment`,ACQUA 存成結果的 `Description`,
也就是在 ACQUA 裡看到的 run 名稱。**整批共用一個**——ACQUA 就是這樣設計的。

開跑前會跳出視窗讓你命名,最近用過的 8 個存在瀏覽器裡。

---

## 已知限制

| 限制 | 說明 |
|---|---|
| 不能新增量測物件 | `AddMeasurementObject` 實測**一律回 −1 且不寫任何資料**。新 DUT 要在 ACQUA 裡建,網頁只列出現有的讓你選 |
| Standards 群組不能執行 | ACQUA 回「This is a standard. It cannot be modified」。要先在 ACQUA 裡複製成實際專案 |
| `UserReaction` 無效 | pywin32 的 ByRef 出參送不回 ACQUA,所以 REDO/CANCEL 那條路是死的 |
| 中斷後不能續跑 | `runs/current.json` 有記錄,但續跑邏輯還沒做 |
| setup 位置是 mock | 序列中間固定停五秒。之後接 Raspberry Pi |
| 條件式的數值比較未驗證 | `Relation` 2/3/4 的語意是推的,`condeval.py` 有標出來 |

---

## 檢查程式

沒有測試框架,但有兩支機械化盤點:

```bash
.venv\Scripts\python.exe tools\check_context.py    # 上下文一致性
.venv\Scripts\python.exe tools\check_ui.py         # 前端與路由
```

會抓什麼:

- 狀態欄位有沒有分類(新增欄位忘了決定歸屬會被叫出來)
- JS 取用的 id 是否存在、按鈕是否有人接、fetch 的路由是否存在
- worker 命令兩個 backend 是否都實作
- 切換專案的防線是否還在

> 這些檢查是被真實 bug 逼出來的。舉例:區間替換不小心刪掉 `renderBlocking()`,
> 頁面照樣載入,直到有人按下去才炸。括號平衡、語法檢查都查不出這種洞。

---

## 設定

`config.json`:

| 區塊 | 用途 |
|---|---|
| `database` | SQL Server 與預設資料庫 |
| `run` | `use_mmd_settings`、逾時、預設 `result_comment` |
| `blocking_windows` | 哪些視窗自動關、哪些要問人 |
| `manual_items` | 哪些測項需人工(標題或萬用字元) |
| `report` | 報告暫存資料夾 |

`prefs.json`(自動產生)記每個資料庫上次用的專案與 DUT,連線後會自動接回去。
