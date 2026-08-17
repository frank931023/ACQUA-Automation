# 聲學測試室 3D 視覺化

three.js + Vite。掛在 Flask 的 **`/soundproofroom`** 路徑下。

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
    ├── spec.js       ⭐ 規格尺寸 —— 要改尺寸只動這個
    ├── look.js          顏色 / 材質 / 燈光 / 相機
    ├── config.js        把上面兩份合併成 CONFIG(本身沒有任何數字)
    ├── builders.js      房間 / 滑軌 / 喇叭 / HATS / 桌台 / 吊架 / 螢幕 / 燈光
    ├── interaction.js   滑鼠拖曳 + slider 雙向同步
    ├── main.js          組裝與 UI 綁定
    └── style.css
```

另外兩個檔案在 Flask 那邊:

```
../templates/soundproofroom.html   免 build 模式的頁面(含 importmap)
../app.py                          /soundproofroom 路由
```

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

**只改 `src/spec.js`。**

```
spec.js   ⭐ 規格尺寸   房間、行程、設備尺寸、預設高度
look.js      外觀       顏色、材質、燈光、相機
   └─────────┬─────────┘
        config.js       合併成 CONFIG,本身一個數字都沒有
             ↓
   builders.js / main.js
```

分兩份的理由:規格數字要拿去對現場、會被人問「這 0.42 哪來的」,所以得能單獨
攤開來看。顏色不會。混在一起的話,改尺寸時要在一堆 `0x9aa3ad` 中間找 `0.42`。

`spec.js` 裡每個數字都標了來源:

| 標記 | 意思 |
|---|---|
| `[規格]` | 設備原廠規格書 / 測試規範明確寫的 |
| `[圖面]` | 現場圖面標註的 |
| `[推估]` | ⚠️ 圖面沒標、依比例抓的,對照現場要調 |
| `[構造]` | 模型結構件(底座、滑車、托座),照片目測 |

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
| 側邊欄 slider | 精確定位,**與拖曳雙向同步** |

側邊欄是**依 config 動態生成**的 —— 物件多了之後,靜態 HTML 很容易漏掉控制項。

拖曳支援單軸與雙軸(`axes: { x, z }`),HATS 與麥克風吊架的 X 軸會套用到
**子層滑塊**而不是整組,層級關係跟實體機構一致。

---

## 已知限制

- **HATS 是簡化幾何**(方塊軀幹 + 球頭 + 耳/嘴標記),尺寸依 B&K 4128 規格但
  不是原廠 3D 模型。要換真模型在 `buildHats()` 改用 `GLTFLoader`。
- ⚠️ **標「推估」的位置**:滑軌在房間內的確切座標、橫移軌長度、螢幕尺寸與
  擺放。圖面只標了長度沒標中心座標,對照現場調 `spec.js` 即可。
- 前/後桌台我對應到規格的 **DUT / Dixie 兩台升降台**(0.80×0.80 的尺寸與位置吻合)。
