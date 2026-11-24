# 系統圖

[SYSTEM_OVERVIEW.md](../../SYSTEM_OVERVIEW.md) 用到的圖。**`.mmd` 是原始檔,`.svg` 是產生出來的。**
要改圖就改 `.mmd`,再重新產生 `.svg`。不要直接改 `.svg`。

| 檔案 | 內容 |
|---|---|
| `01_context` | 全景圖:三個專案和周邊系統 |
| `02_layers` | 責任分層:每一層懂什麼、不懂什麼 |
| `03_components` | ACQUA Automation 內部元件 |
| `04_seq_web_run` | 從網頁開跑(循序圖) |
| `05_seq_hook` | 直接在 ACQUA 按開始,經過掛鉤(循序圖) |
| `06_before_item` | 每一筆量測前要不要移動的決策流程 |
| `07_seq_command` | 一個擺位走完整條路:送 MCC 作業 → MCC 驅動 Pi → 回報 |
| `08_data_model` | 資料關係:標籤 → 擺位 → 軸 → 裝置 → 韌體 |
| `09_device_state` | MCC 的裝置狀態 |
| `10_deployment` | 部署:什麼跑在哪 |
| `11_issue_homing` | 問題 1(舊版,已修):位置輪詢讓轉盤一直歸位 |
| `12_proposed_motion` | MCC 內部可以怎麼做(示意,待 MCC 設計) |
| `13_roadmap` | 接上真機的建議順序 |

## 重新產生

需要 Node.js 和本機的 Chrome(用現有的 Chrome,不另外下載 Chromium)。在這個資料夾執行:

```bash
set PUPPETEER_SKIP_DOWNLOAD=1
echo {"executablePath":"C:/Program Files/Google/Chrome/Application/chrome.exe"} > %TEMP%\pp.json
for %f in (*.mmd) do npx -y @mermaid-js/mermaid-cli@11.4.2 -q -p %TEMP%\pp.json -b white -i %f -o %~nf.svg
```

(上面是 cmd 的寫法。)

**想直接在 VS Code 預覽 `.mmd` 或 md 裡的 Mermaid**:裝「Markdown Preview Mermaid Support」擴充套件。
不裝也沒關係,SYSTEM_OVERVIEW.md 嵌的是 `.svg`,在哪裡都看得到。

畫圖時的注意事項:
- 外框不要一層包一層,又有線跨框連出去。Mermaid 會排得很亂,框也會疊在一起。
- 中文標籤要用 `["…"]` 包起來;換行用 `<br/>`。
