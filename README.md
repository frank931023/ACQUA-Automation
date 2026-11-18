# ACQUA 測試自動化

用 COM 驅動 HEAD acoustics ACQUA,把「挑測項 → 跑 → 出報告」變成網頁上的操作,
並且可以把多批測試接成一條序列連續跑。機構擺位由 ACQUA 裡每個測項的 `Setup`
標籤決定,跑到哪一筆就移到哪 —— 目標是**過夜、無人值守**的批次。

適用任何 ACQUA 資料庫與專案:專案由 `ctx` 決定,擺位由名稱決定,
程式碼裡沒有綁定任何資料庫、專案或測項編號。

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

五個頁面:

| 網址 | 做什麼 |
|---|---|
| `/` | 入口 |
| `/acqua/` | 連線、開專案、勾測項、跑、出報告 |
| `/acqua/plans` | 把多個計畫接成序列連續跑 |
| `/soundproofroom` | 測試室 3D。**即時模式**看實機位置並確認後移動、**設定模式**離線排擺位 |
| `/setups` | 擺位清單。點進去可以逐軸改數字、套用到實機 |

---

## 三種用法

**① 單次執行**(`/acqua/`)
連線 → 開專案 → 選 DUT → 載入測項 → 勾 → 命名 → 執行。

**② 執行序列**(`/acqua/plans`)
把勾好的一批存成「計畫」,再把多個計畫排成序列連續跑。**計畫可以來自不同
資料庫**——執行時會自動切過去。每一步的說明行會先講出這一步的擺位標籤狀況:

```
① 專案 A / 某資料夾 ・ 226 項
   ↓ setup: near-field · 2 problem(s) ・ switch to 另一個資料庫
② 專案 B / DUT_A ・ 40 項
```

每一步可以各自指定 run 名稱、DUT、Word 檔名與位置。

**③ 直接在 ACQUA 裡跑**
照平常在 ACQUA 按執行。專案的 `before_each_measurement.py` 貼上
`acqua_scripts/HOOK_setup_bridge.py` 之後,每一筆量測前掛鉤會讀 `Setup` 標籤、
請本服務移動機構、等到位再放行。服務要開著,但網頁可以不開。

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
  crane.py             ⭐ 天車橋接:3D 邏輯軸 ←→ Pi 韌體指令(mock / http 兩種後端)
  roomsetups.py        擺位的本地儲存(setups/*.json)
  setuptags.py         ⭐ Setup 標籤:讀取、資料夾繼承、開跑前檢查、照擺位分組(純資料)
  setupcoord.py        ⭐ 擺位協調:標籤 -> 機構動作、等到位、沒套用到的記下來
  labcore.py           ⭐ labCORE 麥克風供電:ACQUA 不管這塊,只能我們管
  prefs.py             每個資料庫上次用什麼(prefs.json)
  runlog.py            執行紀錄(runs/current.json)
  constants.py         TypeLib 來的列舉
templates/
  _ui.html             ⭐ 共用設計系統 + armConfirm() 二次確認 helper
  _runmini.html        右下角進度視窗(跨頁)
  _leaveguard.html     離站提醒(兩頁共用,頁面只給 window.__isBusy)
  _nav.html            側邊欄 + 抽屜(含「清除殘留」)
  _gate.html           開頁前的就緒檢查
  index.html           測項選擇
  plans.html           執行序列
  home.html            入口
  soundproofroom.html  3D 頁(免 build 模式)
  setups.html          擺位清單
  setup_detail.html    單一擺位:逐軸編輯 + 套用到實機
tools/
  check_context.py     上下文一致性檢查
  check_ui.py          前端與路由的機械化盤點
  test_nonblocking.py  ⭐ 量測進行中 UI 還能不能用(會真的跑一次量測)
  test_setupflow.py    ⭐ 擺位流程的端對端:真的協調器 + 模擬後端,只把機構換成假的
  test_hook_bridge.py  ⭐ ACQUA 掛鉤的外部半邊(把 Tags 換成假的跑真掛鉤)
  setup_inventory.py   任一專案 / 計畫的 Setup 標籤盤點與轉折點建議(只讀)
  export_acqua_scripts.py  把資料庫裡的 ACQUA Python 腳本解出來(只讀)
  test_resolve.py      跨庫測項對應
  test_selfheal.py     專案樹變動後的自我校正
  labcore.py           讀 labCORE 硬體現況(麥克風 / USB / 接線)
  dump_typelib.py      倒出 COM 型別庫
  preflight.py         啟動前自檢
  survey.py            跨資料庫的假設盤點
acqua_scripts/
  HOOK_setup_bridge.py ⭐ 貼進 ACQUA 的掛鉤:讀 Setup 標籤 -> 請服務移動 -> 等到位
  HOOK_diagnose_smd.py 只印不做事的診斷掛鉤(看 ACQUA 腳本環境裡拿得到什麼)
  SETUP_AUTOMATION_PLAN.md  擺位自動化的計畫書與進度
  其他 *.py            從資料庫匯出、加了說明的 ACQUA 腳本範例(見該資料夾 README)
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

### 讓機構動之前一定先問

3D 頁的即時模式裡,拉桿**不會**直接驅動機構 —— 放手後跳確認框,按確定才
下指令。理由不是「多一道保險比較好」,而是:

- 機構有物理行程,而且一動就是真的在動。手滑碰到拉桿讓天車跑起來太貴。
- 在按下確定之前,**畫面上不會有任何東西動**。如果拉桿一動 3D 就跟著動,
  使用者會以為東西已經移過去了 —— 那個錯覺比「沒動」危險得多。
- 韌體**沒有中止指令**。送出去就只能等它走完。既然事後救不回來,唯一的
  機會就是事前問清楚:哪一根軸、從哪到哪、走幾毫米、大概幾秒、哪一台 Pi。

同一個理由讓「套用整組擺位」是**一根軸一根軸依序**走的:機構的行程互相
重疊,同時動撞到了也看不出是誰撞的。

細節見 `acqua/crane.py` 的檔頭與 `soundproofroom/README.md`。

### 擺位對不上時,不擋,但警告要活到最後

擺位**只由 ACQUA 裡每個測項的 `Setup` 標籤決定**(「编辑标签」那個欄位)。
網頁上的計畫不再帶擺位 —— 兩個來源會打架,而且原本計畫上那段移動是假的。

ACQUA 不能對資料夾加標籤,所以沒標的測項會**看同一個資料夾裡其他測項**:
只有一種擺位就跟著用;有兩種以上就不猜、記一筆;都沒有就再往上一層。
實際效果是每個資料夾標一筆就夠。規則細節見 `acqua/setuptags.py` 檔頭。

**開跑前會先檢查**(單批頁在「為這一批命名」視窗裡,序列頁在每一步的說明行):
幾筆有擺位、幾筆沒有、哪些名稱打錯(附最接近的建議)、哪些判斷不出來。
只警告,不擋。

開跑時照擺位重排順序以少移動幾次 —— 但**不拆散 MMD 群組**,裡面常常是
「錄音 → 分析」,拆開分析會找不到結果。而且重排只在**真的比較少切換**的
時候才採用:約 6% 的群組本身混了兩個擺位,硬排反而會多切幾次。

名稱找不到對應的擺位時,規則是**不移動機構、記一筆、繼續測**。
這是刻意的 —— 打錯一個字不該讓一整晚的批次停擺。但代價是那幾筆會在
當下的位置量到,數據可能是錯的,所以警告必須活到最後:

| 在哪裡看得到 | 形式 |
|---|---|
| 執行畫面 / 右下角小視窗 | 橘色警告框,帶最近一筆是哪個 |
| 跑完的統計區 | 「⚠️ N items did not get their required setup」+ 看明細 |
| 執行紀錄 | 獨立一區,**不併進 PASS / FAIL** —— 一筆可以同時 PASS 又可疑 |
| 每一筆結果 | `results[].setup_warn`,也進 `runs/current.json` |
| CSV 匯出 | `setup_not_applied` 欄位 |
| Word 報告 | 報告是 ACQUA 產的、改不了,所以另存時在隔壁寫一份
            `<報告名>.擺位警告.txt` |
| 瀏覽器通知 | 「3 pass / 0 fail — ⚠️ 2 without the required setup」 |

理由很直接:無人值守時沒有人看得到執行當下那一行。
**一個沒人看到的警告等於沒有警告。**

規則與實作進度見 `acqua_scripts/SETUP_AUTOMATION_PLAN.md`。程式分兩層:
`acqua/setuptags.py` 只管標籤(讀、繼承、檢查,純資料、好測),
`acqua/setupcoord.py` 拿結果去動機構。`app.py` 只負責接線。

盤點任一專案的標籤狀況(跟執行時同一套規則):

```bash
.venv\Scripts\python.exe tools\setup_inventory.py --project "專案標題" [--db 資料庫] [--suggest]
.venv\Scripts\python.exe tools\setup_inventory.py --project-id 6 --db 資料庫   # 有同名專案時
.venv\Scripts\python.exe tools\setup_inventory.py --plan <計畫 id>
```

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
| 機構預設是 mock | `.env` 沒設 `ACQUA_SETUP_CONTROLLER` 時位置是模擬的(`crane.py`)。設了就走 `HttpCrane` 打天車控制中心,但還沒接過真的 Raspberry Pi |
| 從 ACQUA 直接跑沒有資料夾繼承 | 掛鉤只看得到自己的標籤;要等 `Smd.Path` 的格式驗證(`acqua_scripts/HOOK_diagnose_smd.py`) |
| 條件式的數值比較未驗證 | `Relation` 2/3/4 的語意是推的,`condeval.py` 有標出來 |
| 中止擋不住在途的那一筆 | 中止是「不送下一筆」。只剩一筆在跑時按下去會等它跑完 |
| 供電不符只會記錄不會擋 | `labcore.mismatch()` 算得出來,但還沒接進 `/api/run` 的前置檢查 |

---

## 硬體設定:誰管哪一塊

一組 labCORE 硬體設定包含三塊,**ACQUA 只自動處理第一塊**(2026-09~10 實測):

| | 誰負責 | 說明 |
|---|---|---|
| `Connections` 接線路由 | **ACQUA 自己** | 量測開始時載入該 MMD 宣告的那組,結束後還原 |
| `MicCardSettings` 供電 / 極化電壓 | **我們** | ACQUA 完全不碰 |
| `usbaudio` USB 音訊參數 | **我們** | ACQUA 完全不碰 |

哪一組設定由 SQL 的 `MMDSettings`(型別 14 = `Hardware_Configuration_Setting`)
決定,**ACQUA 執行時會自己套用,自動化不需要插手** —— 插手反而會被它還原。

但供電那塊沒人管,而且**設錯不會報錯**:實測把 Ch1&2 的極化電壓關掉再跑,
ACQUA 照樣回報 `PASS`,資料卻是廢的。更危險的是載入 `Teams_chamber_v5` 這類
用通道 4 的設定時,ACQUA 會把訊號路由過去,但供電還留在 Ch1&2。

所以序列的每一步都可以指定供電走哪一組通道(預設 Channels 1 & 2),
`prepare` 會在「載入測項」之後、開跑之前套用。

> 怎麼測出來的:用 `Record` 類測項(不能用 `Analy.` 類 —— 分析不碰音訊硬體,
> 會得到假陰性),0.4 秒取樣一次接線與供電,看量測前後的變化。

---

## 非阻塞:按下執行就可以走人

量測跑在伺服器的工作執行緒,瀏覽器只是看板。換頁、關頁、縮小都不影響它。

但這個承諾很容易破:**工作執行緒是單執行緒**,所有 COM 命令排同一個佇列。
量測一跑起來佇列就塞住,任何「要排進佇列才能回答」的唯讀 API 都會卡到量測結束,
整個網頁看起來就像當掉。

所以路由分兩類:

```
不排佇列(量測中必須照常回應)   status / health / plans / mic-power 的 GET
                                blocking / status-codes / last-run / 所有頁面
要排佇列(量測中本來就該擋下)   run / open-project / list-smds / 寫入類
```

`tools/test_nonblocking.py` 會在**真的有量測在跑**的狀態下把兩類都打一遍並量時間。
曾經抓到 `/api/mic-power` 卡滿 20 秒(當時走了佇列),改讀快取後是 0.03 秒。

### 二次確認

嚴重且不可逆的動作用兩段式確認(按一下變紅並改字,幾秒沒有第二下就放下),
而不是 `confirm()` —— 後者會擋住整個分頁,而這些按鈕常出現在量測正在跑的時候:

| 動作 | 確認方式 |
|---|---|
| 中止執行 / 中止序列 | 兩段式(`armConfirm`,在 `_ui.html`) |
| 停止服務(就緒視窗) | 兩段式 |
| 刪除計畫 | 要把計畫名稱完整打一次 |
| 清除殘留紀錄 | `confirm()`,強制清除再問一次 |
| 離開站台(執行中) | 瀏覽器原生提醒,站內換頁不攔 |

---

## 檢查程式

沒有測試框架,每支都是可以直接跑的腳本,回傳碼 0 = 通過:

```bash
# 不需要 ACQUA、資料庫或服務
.venv\Scripts\python.exe tools\check_context.py    # 上下文一致性
.venv\Scripts\python.exe tools\check_ui.py         # 前端與路由的機械化盤點
.venv\Scripts\python.exe tools\test_setupflow.py   # 擺位流程(真的協調器 + 模擬後端)

# 要先起服務(mock 或 com 都可以)
.venv\Scripts\python.exe tools\test_hook_bridge.py # ACQUA 掛鉤的外部半邊

# 要接真的 ACQUA,而且已經開好一個專案
.venv\Scripts\python.exe tools\test_nonblocking.py # 量測中 UI 還能不能用
.venv\Scripts\python.exe tools\test_resolve.py     # 跨庫測項對應
.venv\Scripts\python.exe tools\test_selfheal.py    # 專案樹變動後的自我校正
```

會抓什麼:

- 狀態欄位有沒有分類(新增欄位忘了決定歸屬會被叫出來)
- JS 取用的 id 是否存在、按鈕是否有人接、fetch 的路由是否存在
- worker 命令兩個 backend 是否都實作
- 切換專案的防線是否還在
- 擺位:有標就移、資料夾繼承、名稱找不到照常量、已在位置不白跑、機構出錯分開記,
  而且警告活到最後(結果、摘要、runlog、跑完的訊息)—— `test_setupflow` 用真的程式碼跑,
  不是另寫一份規則來比對

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
