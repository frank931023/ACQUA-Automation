# 聲學測試室 3D 視覺化

three.js + Vite。掛在 Flask 的 **`/soundproofroom`** 路徑下。

**這一頁只做一件事:設計擺位(setup)並存起來。** 拉桿與拖曳只改 3D,
不會碰到任何機構。存好的擺位,在測試執行時由 `acqua/setupcoord.py`
依測項的 `Setup` 標籤自動套用。

看實機位置、手動推機構這類即時操作**不在這個專案**,屬於天車控制中心
(MCC,[pc-led-controller](https://github.com/frank931023/pc-led-controller))。
三個專案怎麼配合見 [../SYSTEM_OVERVIEW.md](../SYSTEM_OVERVIEW.md)。

---

## 兩種執行方式

### A. 免安裝(現在就能看)

Flask 起來就有:

```powershell
cd ..
.\.venv\Scripts\python.exe app.py
```

開 <http://127.0.0.1:5000/soundproofroom>

這個模式用瀏覽器原生的 **importmap** 從 unpkg CDN 取 three.js,
**不需要 Node、不需要 npm install**。原始碼直接由 Flask 當靜態檔送出。

> ⚠️ 需要連得到網路。離線環境請用下面的 B。

### B. Vite(開發 / 離線)

```powershell
cd soundproofroom
npm install
npm run dev      # 開發伺服器 http://localhost:5173,有 HMR
npm run build    # 打包 → ../static/soundproofroom/
```

**build 完之後 Flask 的 `/soundproofroom` 會自動改用打包好的檔案**(路由會偵測
`static/soundproofroom/index.html` 存不存在),不用改任何設定,也不再需要網路。

---

## 檔案結構

```
soundproofroom/
├── package.json
├── vite.config.js        base='/soundproofroom/' ・ 輸出到 ../static/soundproofroom
├── index.html            Vite 的進入點
└── src/
    ├── spec.json       ⭐ 規格尺寸 —— 要改尺寸只動這個
    ├── look.js          顏色 / 材質 / 燈光 / 相機
    ├── config.js        把上面兩份合併成 CONFIG(本身沒有任何數字)
    ├── builders.js      房間 / 滑軌 / 喇叭 / HATS / 桌台 / 吊架 / 螢幕 / 燈光
    ├── interaction.js   滑鼠拖曳 + slider 雙向同步
    ├── setups.js        擺位的存 / 載(刪除與逐軸編輯在 /setups 頁)
    ├── ui.js            表單框、格式化、提示條
    ├── main.js          組裝、側欄、行程對照、UI 綁定
    └── style.css
```

Flask 那邊:

```
../templates/soundproofroom.html   免 build 模式的頁面(含 importmap)
../templates/setups.html           擺位清單
../templates/setup_detail.html     單一擺位的細節
../acqua/crane.py                  天車橋接(邏輯軸 ←→ 韌體指令),測試執行時用
../acqua/roomsetups.py             擺位的本地儲存
../app.py                          路由與 /api/room/* API
```

---

## 擺位做好之後怎麼被用到

```
3D 頁設計 → 存成 setups/<id>.json(名稱 + 19 根軸的值)
                │
ACQUA 測項的 Setup 標籤寫這個名稱
                │
測試執行時 SetupCoordinator 用名稱找到它 → crane.py → MCC → Pi → 馬達
```

這一頁本身**不會**驅動機構,也沒有「套用到實機」的按鈕。要讓某個擺位生效,
就是在 ACQUA 裡把測項的 `Setup` 標籤寫成這個名稱。

---

## 擺位(setup)

一個擺位 = 「這一次量測,房間裡每個東西站在哪裡」。存成 `setups/<id>.json`:

```json
{
  "id": "20260915-143052-a3f1",
  "name": "近場 0.5 m ・ HATS 前傾 17°",
  "description": "MS Teams Rev05 用",
  "axes": { "hats.mrp": 1.2, "hats.head": 17.0, "screen.z": 2.05, "...": 0 }
}
```

存放位置預設是專案底下的 `setups/`,可以用 `--setups-dir` 或 `ACQUA_SETUPS_DIR`
換掉。**跑測試一定要指到別的目錄** —— 測試開場會把所有擺位刪光,跟正在用的
服務共用同一個資料夾的話,存好的擺位就沒了(這不是假設,已經發生過一次)。
`GET /api/room/setups` 會回傳目前用的是哪個目錄。

> ⚠️ **`setups/` 有進版控**,跟 `plans/` 一樣 —— 擺位是對過現場才調出來的
> 數字,不是執行期的暫存檔,刪掉重建不回來。存了新擺位記得一起 commit:
> `git add setups/ && git commit -m "setup: ..."`

舊檔可能還有 `source` 欄位(以前分「3D 畫的 / 實機讀回來的」)。現在擺位只有
3D 頁這一個來源,程式不再讀它,下次更新那個擺位時會順手拿掉。

跟 `plans/` 的測試計畫**刻意分開存**,計畫也不再帶擺位:

| | 存什麼 |
|---|---|
| 測試計畫 | 要跑哪些測項(ACQUA 那一側) |
| 擺位 | 機構擺在哪裡(天車那一側) |
| 誰要哪個擺位 | ACQUA 裡每個測項的 `Setup` 標籤,**用名稱**引用擺位 |

⚠️ 因為標籤是用名稱對應,**把擺位改名等於讓所有標了舊名的測項找不到它**
(不會移動、照常量、記進跑完的警告)。改名之後到 ACQUA 用「在标签值中搜索
和替代」把舊名一次換掉,再用開跑前的標籤檢查或 `tools/setup_inventory.py` 確認。

### ⭐ 軸代號是跨三處的契約

`axes` 的鍵在三個地方是**同一組字串**:

```
soundproofroom/src/main.js   PANEL 裡每個控制項的 id
acqua/crane.py               AXES(對應到哪台 Pi 的哪根軸)
setups/*.json                存好的擺位的鍵
```

因為同名,**存好的擺位可以原封不動送去驅動機構,中間不需要任何對應表**。
這是整個設計裡最關鍵的一個決定。代價是:**改那些 id 會讓存好的擺位對不上**,
要改就得寫搬移。

### 行程為什麼各存一份

`spec.json` 有行程、`acqua/crane.py` 也有。這是刻意重複的 ——
後端絕對不能拿瀏覽器送來的範圍當行程上限,不然改一個數字就能把機構送去
撞牆。但重複不能是靜悄悄的:3D 頁一打開就會去 `/api/room/axes` 對一次,
不一致就在側欄最上面跳紅字。存檔時超出後端行程的值會被夾回範圍內,
所以兩邊不一致時,畫面上擺的跟存進去的會不一樣。

---

## 頁面與 API

| 網址 | 做什麼 |
|---|---|
| `/soundproofroom` | 3D 頁 |
| `/soundproofroom?setup=<id>` | 打開並載入那個擺位(之後按儲存就是更新它) |
| `/setups` | 擺位清單(一排直的,一頁十個) |
| `/setups/<id>` | 單一擺位:左邊軸名、右邊數字,可以直接改再存 |

| API | 做什麼 |
|---|---|
| `GET /api/room/axes` | 軸清單與行程,用來跟 `spec.json` 交叉比對 |
| `GET|POST /api/room/setups` | 清單 / 新增 |
| `GET|POST|DELETE /api/room/setups/<id>` | 詳細(存檔的值 + 軸定義) / 更新 / 刪除 |

`/api/room/current`、`/api/room/apply`(依名稱)、`/api/room/not-applied` 也在
`/api/room` 底下,但那是給 ACQUA 掛鉤在**測試執行時**用的,不是這一頁。

---

## 跟機構有關、但不在這一頁的事

軸接在哪台 Pi、行程跟韌體對不對得上、位置查詢會讓轉盤歸位等問題,
都整理在 [../SYSTEM_OVERVIEW.md](../SYSTEM_OVERVIEW.md) §6。

---

## 場景內容

| 物件 | 可動 | 規格來源 |
|---|---|---|
| 喇叭陣列 2×4 | 沿主滑軌 X ・支架下降 0.50~0.80 m | 圖面 |
| **大螢幕** | 前後 Z ・高度 0.70~1.90 m | 推估(約 55 吋) |
| **HATS** B&K 4128 | **雙層軌:縱向 Z + 橫向 X** ・MRP 高度 ・轉盤 ・**頭部前傾連續可調** | 原廠規格 |
| **桌台 × 2** | **前後 Z** ・升降(DUT 0.90 / Dixie 1.20,最高 2.30) | 規格 |
| **麥克風吊架 × 2** | X / Y / Z 三軸 ・高度 0.70~1.50 m | 規格 |

### 實際規格(已套用)

```
房間          3.41(W) × 5.20(L) × 2.35(H) m
HATS 軀幹     410(W) × 460(H) × 183(D) mm ・總高 695 mm ・脖子 Ø112 mm
HATS 立架     標稱 1.20 m ・0.75 ~ 1.50 m ・托座到 MRP 22.5 cm
DUT 升降台    測試 0.90 m ・最高 2.30 m
Dixie 升降台  測試 1.20 m ・最高 2.30 m
天花板麥克風  測試 0.95 / 1.25 m ・0.70 ~ 1.50 m
```

---

## 改尺寸

**只改 `src/spec.json`**,存檔後重新整理 3D 頁就生效,不用改程式、不用重啟服務。
(用 Vite build 過的話,`spec.json` 會被包進成品,改完要再 `npm run build` 一次。)

```
spec.json   ⭐ 規格尺寸   房間、行程、設備尺寸、預設高度(純資料)
look.js      外觀         顏色、材質、燈光、相機
   └─────────┬─────────┘
        config.js       合併成 CONFIG,本身一個數字都沒有
             ↓
   builders.js / main.js
```

分兩份的理由:規格數字要拿去對現場、會被人問「這 0.42 哪來的」,所以得能單獨
攤開來看。顏色不會。混在一起的話,改尺寸時要在一堆 `0x9aa3ad` 中間找 `0.42`。

JSON 不能寫註解,所以每一區的數字出處寫在那一區的 `_src` 欄位;以 `_` 開頭的
欄位只是說明,程式載入時會濾掉(`config.js` 的 `stripNotes`)。出處分四種:

| 標記 | 意思 |
|---|---|
| 規格 | 設備原廠規格書 / 測試規範明確寫的 |
| 圖面 | 現場圖面標註的 |
| 推估 | ⚠️ 圖面沒標、依比例抓的,對照現場要調 |
| 構造 | 模型結構件(底座、滑車、托座),照片目測 |

改數字時要注意:

- **JSON 很嚴格**:最後一個欄位後面不能有逗號、字串要用雙引號。改壞了 3D 頁會整頁
  空白,瀏覽器主控台會說哪一行錯。
- `tables.items[].key`、`micRig.items[].key` 是軸代號的一部分(`tableFront.z` …),
  **不要改**,改了存好的擺位會對不上。
- 拉桿範圍(`travel`、`lift`、`headAngle`)改了之後,要跟 `acqua/crane.py` 的 `AXES`
  對一下;不一致時 3D 頁側欄最上面會跳紅字。

### 陣列驅動

重複性的物件是陣列驅動的:

```js
tables: { items: [ {key,label,lift,travelZ}, ... ] }
micRig: { items: [ {key,label,travelX,travelZ,heightDefault}, ... ] }
```

**在陣列裡多加一筆,3D 物件與側邊欄控制項都會自動生出來** —— 不用改
builders 也不用改 HTML。

### 座標系

three.js 慣例,Y 朝上,原點在房間正中央地板:

```
X = 寬 3.41   Y = 高 2.35   Z = 深 5.20
喇叭陣列在 -Z 端,大螢幕在 +Z 端(兩者相對)
```

### builders.js 裡還有數字嗎

有 94 個,但**都不是尺寸**:材質的 roughness / metalness、避免 z-fighting 的
0.002 位移、`Math.max(0.05, ...)` 這種防止幾何翻面的保護值,以及會自己跟著
spec 縮放的相對比例(例如「端塊是滑軌的 2.2 倍粗」)。

拉出來的是 **27 處絕對尺寸**:HMS II.3 托座 0.20×0.05×0.16、桌子底盤 0.46、
螢幕底座 0.62×0.42、吊車 0.16×0.08×0.13、耳部麥克風 Ø0.024、脖子長度 0.07⋯
這些以前寫死在 builders.js,改 config 改不到。

---

## 操作

| 動作 | 結果 |
|---|---|
| 左鍵拖**物件** | 移動該物件(各自限制在自己的行程內) |
| 左鍵拖**空白處** | 旋轉視角 |
| 滾輪 / 右鍵拖曳 | 縮放 / 平移 |
| 側邊欄 slider | 精確定位,與拖曳雙向同步 |

側邊欄是**依 config 動態生成**的 —— 物件多了之後,靜態 HTML 很容易漏掉控制項。

拖曳支援單軸與雙軸(`axes: { x, z }`),HATS 與麥克風吊架的 X 軸會套用到
**子層滑塊**而不是整組,層級關係跟實體機構一致。

---

## 已知限制

- **HATS 是簡化幾何**(方塊軀幹 + 球頭 + 耳/嘴標記),尺寸依 B&K 4128 規格但
  不是原廠 3D 模型。要換真模型在 `buildHats()` 改用 `GLTFLoader`。
- ⚠️ **標「推估」的位置**:滑軌在房間內的確切座標、橫移軌長度、螢幕尺寸與
  擺放。圖面只標了長度沒標中心座標,對照現場調 `spec.json` 即可。
- 前/後桌台我對應到規格的 **DUT / Dixie 兩台升降台**(0.80×0.80 的尺寸與位置吻合)。
