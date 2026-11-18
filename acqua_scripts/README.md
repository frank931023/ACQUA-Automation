# ACQUA 的 Python 腳本

ACQUA 本體是 Delphi 寫的,**安裝目錄裡一個 .py 都沒有**。但它會執行
使用者寫的 Python 腳本 —— 那些才是你能改的東西。

這個資料夾放兩種東西:

- **我們寫的掛鉤**(`HOOK_*.py`)—— 要貼進 ACQUA 專案的腳本,見下一節
- **19 支從資料庫解出來的範例**,每一支都加了說明:什麼時候執行、出自哪個
  資料庫哪個專案、ACQUA 裡怎麼點進去、改了會影響幾個測項。
  **原始程式碼一字未改**,放在說明下面。這是一次性挑選的參考資料,不會自動更新

---

## 我們寫的掛鉤

| 檔案 | 貼到哪 | 做什麼 |
|---|---|---|
| `HOOK_setup_bridge.py` | 專案的 `before_each_measurement.py` | 讀這一筆的 `Setup` 標籤 -> 請本服務移動機構 -> 等到位才放行。服務連不上、名稱找不到、移動失敗都**不擋量測**,改回報到 `/api/room/not-applied` 進跑完的摘要 |
| `HOOK_diagnose_smd.py` | 同上(暫時) | 只印不做事:印出 `Smd.Title / Path / Filename / Namespace`、`Tags` 等實際的值。用來確認 `Smd.Path` 的格式 —— ACQUA 直接跑時的資料夾繼承要靠它 |

兩支都不綁任何資料庫或專案:標籤名固定是 `Setup`,擺位用名稱對應,
服務位址在檔頭的 `SERVICE`。專案原本已經有 `before_each_measurement.py` 時
(例如 SP2 的 `hook_1_...`),把擺位那段接在原本內容的**前面**。

不需要 ACQUA 就能測外部那半邊:`tools/test_hook_bridge.py`(要先起服務)。

---

## 兩種腳本,差很多

| | 型別 | 什麼時候跑 | 掛在哪 |
|---|---|---|---|
| **生命週期掛鉤** | `FT_Script` | 每一筆量測前/後、中止時、開專案時 | 專案層級,不掛測項 |
| **單一測項腳本** | `FT_SMDUsedFile` | 跑到那個測項才執行 | 掛在 SMD 上 |

掛鉤影響範圍是整個專案,測項腳本只影響掛到它的那幾個 —— 但一支腳本
常常被很多測項共用(最多的一支被 **162 個測項**用到),改之前先看清單。

---

## 檔案導覽

### 掛鉤(每筆量測都會跑)

| 檔案 | 說明 |
|---|---|
| `hook_1_before_each_measurement.py` | 量測前。**唯一能在量測開始前擋下來的地方** |
| `hook_2_after_each_measurement.py` | 量測後。示範用標籤當開關 |
| `hook_3_after_canceled_measurement.py` | 中止時的善後 |
| `hook_4_on_project_open.py` | 開專案時跑一次 |

### 最小範例(想自己寫就從這裡開始)

| 檔案 | 行數 | 說明 |
|---|---|---|
| `min_1_show_ch_name_in_legend.py` | 11 | 最短的一支 |
| `min_2_save_dtattn_result.py` | 12 | 「存結果變數」的骨架 |
| `min_3_cal_corr_level.py` | ~12 | Demo 庫的小範例 |

### 結果 → 變數(這些變數餵給條件執行)

| 檔案 | 被幾個測項用 |
|---|---|
| `var_1_store_mos_variables.py` | **162** |
| `var_2_save_echo_level.py` | 72 |
| `var_3_save_p863_delay.py` | 20 |

### 檔案操作

| 檔案 | 說明 |
|---|---|
| `file_1_activation_snd.py` | `Smd.Path`、`Smd.Cancel`、`ResultFiles.AddFile` |
| `file_2_add_clean_ref.py` | 一支服務 16 個測項的典型 |
| `file_3_rename_analyses_files.py` | 比較完整的檔案處理流程 |

### 互動 GUI(擋住無人值守的元凶)

| 檔案 | 說明 |
|---|---|
| `gui_1_dut_meas_wizard.py` | ⭐ **就是那個 DUT & Measurement Wizard** |
| `gui_2_max_vol_msg.py` | 12 行,直接叫 Windows MessageBox |
| `gui_3_select_volume_control.py` | SMDType 43 不代表一定開視窗 |

### 硬體相關

| 檔案 | 說明 |
|---|---|
| `hw_1_set_hardware_delays.py` | ⭐ **腳本可以改硬體設定** |
| `hw_2_define_hardware_options.py` | 硬體能力 → 變數 → 條件執行 |
| `hw_3_set_equipment_delays.py` | 設備延遲補償 |

`index.json` 是全部 **107 支**腳本的目錄(含沒收錄在這裡的),
有檔名、型別、所屬專案、被幾個測項用。

---

## 腳本存在哪裡

```
權威來源   SQL 資料庫  acqua.Files + acqua.BinData
                       內容是 ZIP 壓縮的(開頭 PK)

執行快取   C:\ACQUA_Files\File_Cache\<專案名>_<GUID>\
                       跑的時候解壓到這裡,881 個 .py
```

⚠️ **不要直接改快取裡的檔案。** 那是從資料庫解出來的副本,
下次同步會被覆蓋,而且改了資料庫不知道。

### 腳本怎麼連到測項

```
SMDs.rFileCollection -> FileCollectionLists.rFileCollection -> Files.idFile
SMDs.idSMDItem == TreeItems.idTreeItem    （同一個 id 空間)
```

用 `TreeItems` 的巢狀集合(`LeftNode` / `RightNode`)往上爬就是樹狀路徑 ——
每支腳本說明裡的「測項樹」那一行就是這樣算出來的。

---

## 怎麼改

**用 ACQUA 自己的腳本編輯器。** 在專案樹選到該測項,它的設定裡可以開啟。
存檔時 ACQUA 會處理 ZIP 壓縮、`FileSize`、`CRCValue`、`ChangeDate`,
並重建快取。

**不要直接寫 SQL。** 技術上做得到(`BinData` 就是個 ZIP),但要自己處理
上面那些欄位,錯一個 ACQUA 可能就讀不到、或靜默用舊版。這個專案一路以來
的原則就是不對 ACQUA 的資料庫寫入(目前 0 筆 INSERT/UPDATE/DELETE)。

---

## 腳本能用的 API

```python
from ACQUAlyzer import Smd, Tags, SubProject, MeasObject, ResultFiles, SingleValues
from HEAD import const
from HEAD.AcquaBasic import Results, Variables
from HSL import (run_universal_questionnaire_gui, save_var, get_var_value,
                 get_tag_values, AnalysisDiagram, BGNConfigurator)
```

`ACQUAlyzer` 與 `HSL` **不在檔案系統上** —— 是 ACQUA 執行腳本時注入的,
所以這些腳本只能在 ACQUA 裡跑,外面用一般 Python 執行會 ImportError。

`HEAD` 套件倒是裝在
`C:\Program Files (x86)\Common Files\HEAD shared\Python39\Lib\site-packages\HEAD\`,
但幾乎全是編譯過的 `.pyd`,沒有原始碼,也不該改(更新會被蓋掉)。

---

## 👉 延伸:讓 ACQUA 自己知道「這個測項要哪個擺位」

這個資料夾裡還有一份 **[SETUP_AUTOMATION_PLAN.md](SETUP_AUTOMATION_PLAN.md)** ——
第二次大工程的規劃與執行紀錄。

核心發現是:**ACQUA 本來就有「每個測項帶著自己的硬體需求」的機制**
(`TurningDevices`、`HHPSettingName`、以及 1858 個測項已經在用的 Tags),
而且**掛鉤已經在用 socket 控制外部硬體**(`BGNConfigurator` → `BGNRemote.py`)。

那份文件有完整的證據、實測數據(41 次切換 vs 分組後 11 次)、
依序的開發步驟,以及還沒解決的疑慮。做的時候一邊填結果。

現況(2026-11-18):從網頁跑的那條路已完成並真機驗過(含資料夾繼承與開跑前
檢查);ACQUA 直接跑的掛鉤 `HOOK_setup_bridge.py` 外部半邊驗完,等在 ACQUA
裡貼上實測。

---

## 對我們自動化的兩個機會

**1. `before_each_measurement.py` 可以補上我們缺的檢查**

我們一直說「麥克風極化電壓設錯會靜默產生廢資料」。這個掛鉤每筆量測前都跑,
而且跑在 ACQUA 內部,比 `/api/run` 更靠近現場。在那裡 `raise Exception(...)`
就能擋下這一筆 —— 現有程式碼已經示範了怎麼擋 DUT 名稱非法字元。

**2. `hw_1_set_hardware_delays.py` 證明腳本能碰硬體設定**

我們花很久才找到 `MfeControlLib` 那條路。但腳本層本來就能改硬體設定,
而且時機比我們從外面介入更準。

⚠️ `gui_1_dut_meas_wizard.py` 理論上可以改成「變數已設好就不跳視窗」,
那批 manual 測項就能無人值守。但 MS Teams 那兩個資料庫是**認證用**的
標準流程,改了可能影響認證效力 —— 動之前先確認這件事。

---

## 重新產生

```bash
.venv\Scripts\python.exe tools\export_acqua_scripts.py      # 解出全部 + 建 index.json
```

**只讀資料庫,不寫入。** 那 19 支加了說明的範例是一次性整理的,產生它們的
工具(綁死了特定資料庫與檔名)已經移除;要看別的腳本,用上面這支解出來即可。
