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
    ├── config.js         ⭐ 所有尺寸常數都在這
    ├── builders.js       房間 / 滑軌 / 喇叭陣列 / HATS / 燈光
    ├── interaction.js    滑鼠拖曳 + slider 雙向同步
    ├── main.js           組裝與 UI 綁定
    └── style.css
```

另外兩個檔案在 Flask 那邊:

```
../templates/soundproofroom.html   免 build 模式的頁面(含 importmap)
../app.py                          /soundproofroom 路由
```

---

## 改尺寸

**只要動 `src/config.js`。** 其他程式碼都是從那裡讀,不會有寫死的數字。

```js
room:        { width: 3.41, depth: 5.20, height: 2.50 }
mainRail:    { length: 2.00, z: -1.55, y: 2.34, travel: { min: -0.85, max: 0.85 } }
bracketRail: { length: 0.80, min: 0.50, max: 0.80 }   // 可調節範圍
floorRail:   { length: 4.61, gauge: 0.54, travel: { min: -1.90, max: 1.90 } }
speakerArray:{ cols: 2, rows: 4, spacingX: 0.30, spacingY: 0.42 }
```

### 座標系

three.js 慣例,**Y 朝上**,原點在房間正中央的地板:

```
X = 房間寬度 3.41  →  主滑軌沿這個方向,喇叭左右移動
Y = 房間高度 2.50
Z = 房間深度 5.20  →  地面滑軌沿這個方向,HATS 前後移動
```

所以 `X ∈ [-1.705, +1.705]`、`Z ∈ [-2.60, +2.60]`。

---

## 操作

| 動作 | 結果 |
|---|---|
| 左鍵拖**物件** | 移動喇叭陣列(沿 X)或 HATS 平台(沿 Z) |
| 左鍵拖**空白處** | OrbitControls 旋轉視角 |
| 滾輪 | 縮放 |
| 右鍵拖曳 | 平移 |
| 側邊欄 slider | 精確定位,**跟拖曳雙向同步** |

滑鼠移到可拖曳的物件上會**高亮 + 游標變成手掌**。

### 拖曳與 slider 怎麼同步

兩邊都走同一條回呼:

```
拖曳   → interaction 內部更新 position → onChange(key, value, 'drag')   → 更新 slider
slider → interaction.setPosition()      → onChange(key, value, 'slider') → 更新數值顯示
```

因為只有一個真實來源(物件的 `position`),不會出現兩邊對不上的情況。

---

## 已知限制

- **HATS 人形是簡化的幾何體**(方塊軀幹 + 球形頭 + 耳朵位置標記),不是真實 HATS 的
  3D 模型。要換成真的模型可以在 `builders.js` 的 `buildHats()` 裡改用 `GLTFLoader`。
- 喇叭是圓柱體近似,沒有做號角、障板等細節。
- 尺寸取自現場圖面標註(3.41 / 5.20 / 2.00 / 0.80 / 4.61 / 0.54 / 0.42),
  但**滑軌在房間內的確切位置(`mainRail.z`、`floorRail` 的中心)是我推估的**,
  跟實際佈局可能有出入 —— 對照現場圖調 `config.js` 即可。
