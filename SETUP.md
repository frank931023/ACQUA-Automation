# 移植到另一台電腦

這份是「把專案 clone 到新機器並跑起來」的完整步驟。
架構本身是可移植的 —— 原始碼裡**沒有任何硬編碼路徑**,機器相關的東西全部集中在 `config.json`。

---

## 0. 新機器必須先具備

| 項目 | 為什麼 | 沒有的後果 |
|---|---|---|
| **ACQUA 6 已安裝** | 提供 COM 介面,也順便提供 Python | `Dispatch()` 找不到類別 |
| **ACOPT18 授權 + dongle 已插入** | COM 介面本身是選配授權 | `Dispatch()` 直接失敗 |
| SQL Server + ACQUA 資料庫 | 測項定義存在資料庫裡 | 沒東西可跑 |
| 每個專案**至少一個量測物件 (MO)** | 實測限制,見下方 ⚠️ | `MeasurementObjects` 丟例外 |
| 量測硬體(視測項而定) | 真正的量測需要 MFE / labCORE / 治具 | 量測失敗 |

> ⚠️ **第一個 MO 必須在 ACQUA GUI 裡手動建立。**
> 實測(2026-08-10):專案底下一個 MO 都沒有時,`IProjectSelected.MeasurementObjects`
> 會直接丟 `Index out of range` —— 連集合物件都拿不到,所以無法用 COM 建第一個。
> 之後程式才能新增第 2 個以後的。

---

## 1. 取得程式碼

```powershell
git clone <repo-url> "ACQUA Automation"
cd "ACQUA Automation"
```

---

## 2. 建立 Python 環境

**不需要自己安裝 Python。** HEAD 原廠隨 ACQUA 附了一套 32-bit Python 3.9,
位元數剛好對得上 ACQUA(x86),而且 pywin32 已經內建。

```powershell
& "C:\Program Files (x86)\Common Files\HEAD shared\Python39\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**驗證位元數 —— 必須印出 32:**

```powershell
.\.venv\Scripts\python.exe -c "import struct; print(struct.calcsize('P')*8)"
```

> ⚠️ 系統 PATH 上的 `python` 常常是 Microsoft Store 的空殼,**不能用**。
> ⚠️ 如果新機器的 HEAD Python 路徑不同,自己調整;找不到的話就去 python.org
> 裝 **32-bit** 版(一定要 32-bit,ACQUA 的 TypeLib 只註冊了 win32 分支)。

---

## 3. 建立設定檔

```powershell
copy config.example.json config.json
```

`config.json` 已在 `.gitignore` 裡(可能含資料庫密碼),**不會進版控**。

### 要改的值

| 欄位 | 說明 |
|---|---|
| `database.server` | ⚠️ **機器名會不一樣**,格式 `機器名\ACQUADBSERVER` |
| `database.name` | ACQUA 資料庫名稱 |
| `target.project_group` | 專案群組 |
| `target.project` | 專案 |
| `target.measurement_object` | 受測物名稱 |

### 不用自己猜 server 名稱

**方法 A(推薦)** —— 啟動 app 後按左欄的「**掃描**」,會列出該機器上所有 ACQUA
資料庫,含測項數與已有結果數。

**方法 B** —— 讀 ACQUA 自己記的連線紀錄:

```powershell
Get-ItemProperty "HKCU:\Software\HEAD acoustics\HEAD Analyser ACQUA\ACQUA3\MRUConnections"
```

格式是 `伺服器?資料庫?旗標?上次開的專案`。

---

## 4. ⭐ 重新 dump TypeLib(不要跳過)

```powershell
.\.venv\Scripts\python.exe tools\dump_typelib.py --enums-only
```

**為什麼必須做:** `acqua/constants.py` 裡的列舉數值(特別是 `EMEResult`)是從
**原本那台機器**的 ACQUA TypeLib 抓出來的。新機器如果 ACQUA 版本不同,數值**可能不一樣**。

重點檢查這幾個,跟 `acqua/constants.py` 比對:

```
EMEResult:
  emeresultMeasDoneOk               = 2    ← PASS
  emeresultMeasDoneNotOk            = 3    ← FAIL
  emeresultIgnore                   = 7
  emeresultMeasDoneNotOkNotRequired = 8    ← 沒過但非必要,不該算 FAIL
```

數值不同就直接改 `constants.py`。**判定錯了整份測試報告就是錯的。**

> 這個工具是**唯讀**的:用 `LoadRegTypeLib` 讀型別資訊,不會啟動 ACQUA、
> 不產生 gencache 快取檔。

---

## 5. 分段驗證

### 5.1 模擬模式(不碰 ACQUA)

```powershell
.\.venv\Scripts\python.exe app.py --backend mock
```

開 `http://127.0.0.1:5000`,把流程點一遍。這步只驗證程式本身沒問題。

### 5.2 真實模式

```powershell
.\.venv\Scripts\python.exe app.py --backend com
```

或把 `config.json` 的 `backend` 改成 `"com"`。

**建議的驗證順序:**

1. 連線 → 右上角應顯示 `機器名\ACQUADBSERVER / 資料庫名`
2. 掃描 → 確認列出的資料庫與測項數合理
3. 開啟專案 → 選受測物
4. 載入測項 → 數量應與 ACQUA GUI 專案樹一致
5. 挑一個 **`Info:` 開頭、SMDType=34** 的測項跑跑看
   (純資訊、不驅動硬體,是最安全的白老鼠)

---

## 6. 移植時容易踩的坑

| # | 坑 | 症狀 |
|:-:|---|---|
| 1 | Python 不是 32-bit | `Dispatch` 報 class not registered |
| 2 | 忘了 dump TypeLib | pass/fail 判定相反或亂跳 |
| 3 | `server` 用舊機器名 | 連線失敗 |
| 4 | 專案沒有任何 MO | `Index out of range` |
| 5 | 沒插 dongle / 沒授權 | `Dispatch()` 失敗 |
| 6 | 改了 `templates/index.html` 沒重啟 | 看不到變更(Jinja 有快取,`debug=False` 不自動重載) |
| 7 | ACOPT 模組授權不足 | 測項執行時失敗(非程式問題) |

---

## 7. 不會跟著 clone 的東西

git repo 只涵蓋 `ACQUA Automation/` 這層以下。上層這些**不在版控裡**:

| 檔案 | 要不要帶 |
|---|---|
| `../ACQUA_COM_自動化開發指南.md` | ⭐ **建議手動帶** —— COM 觀念與 API 參考 |
| `../61_Demo_SMDs_Rev07_測項清單.md` | ⭐ **建議手動帶** —— 測項清單 |
| `../Acqua3COM.chm` | 不用 —— 2012 年版已過時,而且程式不讀它 |
| `../SMD/` | 不用 —— 官方精靈,程式不讀它(同樣的東西也存在資料庫裡) |
| `../Example Applications/` | 不用 —— 原廠 VB 範例,純參考 |

**程式碼對後三者是零相依**,只有註解裡提到而已。

---

## 8. 環境變數?

**不需要任何 `.env`。** 所有設定都在 `config.json`,原因:

- 要改的東西不多(5 個值)
- Windows 驗證不需要帳密
- 設定跟著專案走比較好追

真的要用環境變數(例如 CI),可以自己在 `app.py` 的 `load_config()` 加覆寫邏輯。

---

## 附:重建環境的一鍵指令

```powershell
git clone <repo-url> "ACQUA Automation"
cd "ACQUA Automation"
& "C:\Program Files (x86)\Common Files\HEAD shared\Python39\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -c "import struct; print('bits =', struct.calcsize('P')*8)"
copy config.example.json config.json
notepad config.json
.\.venv\Scripts\python.exe tools\dump_typelib.py --enums-only
.\.venv\Scripts\python.exe app.py --backend mock
```
