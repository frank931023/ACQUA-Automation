# 系統總覽:ACQUA 自動化 × 天車控制中心 × Pi 控制端

> 最後更新:2026-11-21
>
> 這份文件說明三個專案怎麼一起運作:各自負責什麼、資料怎麼流、彼此約定了什麼,
> 以及目前還有哪些問題和沒做完的部分。各專案的細節請看各自的 README。
>
> 圖的原始檔在 `docs/diagrams/*.mmd`(Mermaid),改完要重新產生 `.svg`,見 [docs/diagrams/README.md](docs/diagrams/README.md)。

| 專案 | 位置 | 一句話 |
|---|---|---|
| **ACQUA Automation** | 本資料夾 | 決定「這一筆測項要什麼擺位」,並驅動 ACQUA 量測 |
| **Motion Control Center(MCC)** | [frank931023/pc-led-controller](https://github.com/frank931023/pc-led-controller) | 管所有 Pi,把指令送到正確的 Pi,一台一次只跑一個指令 |
| **Pi 控制端** | [frank931023/pi-arduino-connection-test-0717](https://github.com/frank931023/pi-arduino-connection-test-0717) | 每台 Pi 上一份,把 HTTP 指令轉成 Serial 給 Arduino |

---

## 1. 全景圖

![全景圖](docs/diagrams/01_context.svg)

圖上沒畫的兩條次要連線:
- 人可以直接開 MCC 的網頁(`:5001`)手動操作機構。這時自動化送的指令會收到 `409`,見 §6 問題 8。
- 每台 Pi 上的 beszel-agent(選用)會主動把健康資料送到 Beszel hub。

![責任分層](docs/diagrams/02_layers.svg)

**原則:每一層只跟相鄰的那一層講話。**
- ACQUA Automation 不直接連 Pi,一律經過 MCC。MCC 已經處理好裝置鎖、逾時和狀態判斷,重寫一份只會多一個要維護的地方。
- MCC 不懂 ACQUA,也不懂「擺位」,只懂裝置和韌體指令。
- Pi 不懂「軸屬於哪個總成」,只把字串原樣轉給 Arduino。

---

## 2. 各專案負責什麼

### 2.1 ACQUA Automation(本專案)

| 負責 | 不負責 |
|---|---|
| 用 COM 驅動 ACQUA,一筆一筆送測項(`StartSingleMeasurement`) | 寫入 ACQUA 的資料庫(一律唯讀,目前 0 筆寫入) |
| 從 SQL 讀專案樹、條件執行、測項的 `Setup` 標籤 | 編輯標籤(只能在 ACQUA 介面改) |
| 依 `Setup` 標籤決定這筆要哪個擺位,沒到位就先移動 | 機構怎麼安全地走到那裡(見 §7,建議交給 MCC) |
| 擺位存檔(`setups/*.json`,房間座標) | 韌體指令的細節 |
| 開跑前把測項依擺位分組,減少移動次數 | |
| 麥克風卡極化電壓(ACQUA 不碰這塊) | |
| 自動關掉 ACQUA 的彈窗(`winwatch`) | |

主要模組:

| 模組 | 角色 |
|---|---|
| `acqua/setuptags.py` | 純資料:讀標籤、資料夾繼承(同資料夾的兄弟測項)、開跑前檢查 |
| `acqua/setupcoord.py` | `SetupCoordinator`:標籤 → 擺位 → 叫機構移動,失敗不擋量測 |
| `acqua/roomsetups.py` | 擺位存檔,**用名稱對應** |
| `acqua/crane.py` | `CraneBridge`:`MockCrane`(模擬)/ `HttpCrane`(接 MCC),以及 19 根軸的定義 `AXES` |
| `acqua/labcore.py` | 麥克風卡供電 |
| `acqua_scripts/HOOK_setup_bridge.py` | 貼進 ACQUA 的掛鉤,讓「直接在 ACQUA 按開始」也會移機構 |

![ACQUA Automation 內部元件](docs/diagrams/03_components.svg)

### 2.2 MCC(pc-led-controller)

- 裝置清單(`data/pi_config.json`):`pi_id` → host / port / 名稱 / 停車位置。
- 背景每 5 秒檢查每台 Pi 的狀態:`online` / `busy` / `no-arduino` / `offline`。**30 秒沒有任何 API 呼叫就暫停檢查。**
- **一台裝置一次只跑一個指令**,前一個沒結束就回 `409`。Pi 本身也會擋,所以從 Pi 本機網頁送的指令一樣擋得住。
- 指令逾時以 Pi 回報的值為準,自己再多等 5 秒。
- 指令表(按鈕、逾時、Home all 順序)來自每台 Pi 的 `/api/commands`。
- Beszel 健康監控(CPU、溫度、容器)和告警(webhook)。
- 用 Ansible 部署多台 Pi。

MCC 眼中一台裝置的狀態:

![裝置狀態](docs/diagrams/09_device_state.svg)

### 2.3 Pi 控制端(pi-arduino-connection-test-0717)

- 一台 Pi 接一片 Arduino。`.env` 裡的 `PI_ID`、`BOARD`(`mega` / `uno`)、序列埠、逾時,每台各自設定。
- 把指令補上換行寫進 Serial,一直讀到 `DONE` 或 `ERR` 為止。韌體穿插的心跳行(`HB,...`)在這裡就濾掉了。
- 在 `/api/status` 回報 `board`、`rig_name`、`command_timeout`、`max_command_timeout`、`app_version`。
- 也有本機網頁 `http://<Pi>:5000/`。

---

## 3. 一筆測項從開始到量測

有兩種開跑方式,都會走到同一個擺位協調。

### 3.1 從我們的網頁開跑(目前主要用這條)

![從網頁開跑](docs/diagrams/04_seq_web_run.svg)

每一筆量測前的 `before_item` 怎麼決定要不要動。紅色框代表「記成未套用,但照樣量測」:

![before_item 決策流程](docs/diagrams/06_before_item.svg)

### 3.2 直接在 ACQUA 裡按開始

![ACQUA 掛鉤](docs/diagrams/05_seq_hook.svg)

ACQUA 的掛鉤拿不到測項的 row id,也看不到其他測項的標籤,所以**資料夾繼承在這條路上還沒有支援**(見 §8)。

### 3.3 擺位資料怎麼一路換算到韌體

```
ACQUA 測項標籤          <UserDefinedProperty name="Setup">Center_1m</...>
      │ 只用名稱對應
      ▼
setups/<id>.json        { name: "Center_1m", axes: { "hats.z": 0.40, "hats.rot": 90, ... } }
      │                   房間座標:公尺(以房間中心為 0)、度
      ▼
crane.AXES["hats.z"]    Axis(pi="pi-003", ch="SZ", lo=-1.85, hi=1.85, unit="m")
      │ to_device:(0.40 − lo) × 1000 = 2250 mm
      ▼
MCC                     POST /api/pi/pi-003/command {"command": "SZM,2250", "timeout": 90}
      ▼
Pi → Arduino            "SZM,2250\n" → … "DONE"(或多一行 "Exceeded Max travel.")
```

**韌體的 0 = 機械原點 = 我們設定的 `lo`。** 換算只在 `crane.py` 做一次。

---

## 4. 介面約定

### 4.1 ACQUA Automation → MCC

| 用途 | 呼叫 | 備註 |
|---|---|---|
| 送指令 | `POST /api/pi/<id>/command` `{command, timeout}` | 回 `pi_response.arduino_result`(`DONE`/`ERR`)和 `arduino_response`(多行陣列) |
| 裝置狀態 | `GET /api/pis` | 我們快取 4 秒。讀取類 API 不需要 token |
| (尚未使用)指令表 | `GET /api/pi/<id>/commands` | 可以拿來確認某台有哪些軸、逾時多少 |
| (尚未使用)停車位置 | `PATCH /api/pi/<id>` `{park}` | |

狀態碼:`409` = 那台正在忙,`401` = 有設 `API_TOKEN` 但沒帶,`502` / `504` = 連不到 Pi 或逾時。

一個指令走完整條路:

![一個韌體指令](docs/diagrams/07_seq_command.svg)

### 4.2 MCC → Pi

`POST /api/command`、`GET /api/status`、`GET /api/commands`、`GET|POST /api/ping`。MCC 一定會明確轉發 `timeout`。

### 4.3 Pi → Arduino(韌體指令)

| 指令 | 意思 |
|---|---|
| `SXC` / `SYC` / `SZC` | 校正(量兩顆極限開關之間的行程,存進 EEPROM,只需做一次) |
| `SXH` / … | 歸位 |
| `SXP` / … | 查位置 |
| `SXM,<mm>` / … | 移動到絕對位置 |
| `RC` `RH` `RP` `RM,<deg>` | 轉盤(−180 ~ 180°) |
| `TP` `TM,<deg>` | 傾角(0 ~ 90°) |
| `?` | 回報天車名稱 |
| `L0`–`L3`、`HB,...` | 只有 LED 模擬版韌體才有 |

韌體寫的行程上限:**X / Y 1000 mm、Z 300 mm**。
**移動前必須先校正和歸位**,否則所有移動都會回 `Exceeded Max travel.`。

---

## 5. 名詞對照

![資料關係](docs/diagrams/08_data_model.svg)

| 這邊叫 | 那邊叫 | 對應方式 |
|---|---|---|
| Setup 標籤 | ACQUA 測項的 `UserDefinedProperty name="Setup"` | 字串 |
| 擺位(setup) | `setups/*.json` | 用**名稱**對到標籤。改名會讓標籤對不上 |
| 軸(axis),例如 `hats.z` | 3D 頁的 PANEL、擺位檔的鍵 | 字串,改名會讓舊擺位對不上 |
| 裝置(device / pi) | MCC 的 `pi_id` = Pi 的 `PI_ID` | 目前寫死在 `crane.AXES`(見 §6 問題 3) |
| 軸前綴 `ch` | 韌體的 `SX` / `SY` / `SZ` / `R` / `T` | 組成 `<ch>M`、`<ch>P`、`<ch>C`、`<ch>H` |
| 總成(HATS、喇叭台…) | Pi 回報的 `rig_name` | 目前沒有對應關係,可以拿來核對接線 |

---

## 6. 已知問題(接上真機前要處理)

| # | 嚴重度 | 問題 | 後果 | 建議 |
|---|---|---|---|---|
| 1 | 🔴 | 韌體的 `RP` / `TP` 查詢會**順便讓轉盤歸位**;而 `HttpCrane` 閒置時**每 2 秒查一次所有軸**,每次移動後也會查一次 | 轉盤會一直自己歸位;轉到目標角度後馬上被查,又回到 0° | 轉盤和傾角不要主動查位置,改記住最後一次下的目標。韌體修好再開放 |
| 2 | 🔴 | **行程對不上**:19 根軸有 14 根超過韌體上限。例如 `hats.z` 需要 3700 mm(Z 上限 300)、`speakers.x` 需要 1500 mm(X 上限 1000)、`hats.head` 要到 −15°(T 只有 0–90°) | 韌體回 `DONE` 加一行 `Exceeded`,機構不動 → 擺位全部記成未套用 | 確認真機的行程。韌體上限是校正量出來的,3D 頁的數字是照房間規格畫的,兩邊要對齊 |
| 3 | 🟡 | 軸接在哪台 Pi **寫死**成 `pi-001` … `pi-007`,但 MCC 範例是 `pi-01` 格式,而且接線還沒對過 | 找不到裝置,狀態顯示 `missing` | 搬到設定檔;開機時用 Pi 回報的 `rig_name` 和 `board` 核對 |
| 4 | 🟡 | `TM`(傾角)**目前不會真的驅動機構**,只會更新內部數值 | 傾角回報到位,其實沒動 → 數據錯了卻看起來正常 | 韌體修好前,`hats.head` 一律記成未套用 |
| 5 | 🟡 | 移動逾時**寫死 90 秒**,Pi 預設 130、上限 300 | 長距離移動時我們先判定失敗,機構還在動,下一個指令吃 `409` | 不帶 `timeout`,讓 MCC 用 Pi 的值;或先讀 `/api/pis` 的 `command_timeout` |
| 6 | 🟡 | 沒有帶 `API_TOKEN` | MCC 設了 token 之後所有指令都 `401` | `.env` 加 `ACQUA_SETUP_CONTROLLER_TOKEN`,送 `Authorization: Bearer` |
| 7 | 🟡 | 「校正 / 歸位」沒有對外 API。MCC 的 Home all 是**瀏覽器**依序送的,關掉頁面就斷了 | 過夜批次沒辦法在開跑前確保機構已歸位 | MCC 加 `POST /api/motion/home`(見 §7) |
| 8 | 🟡 | `409` 一律當成失敗 | 有人在 MCC 網頁手動操作時,自動化那筆會被記成未套用 | 收到 `409` 先等一下再重試幾次 |
| 9 | 🟢 | `_parse_position` 取「最後一行的最後一個數字」,韌體文件說要取**第一行** | `RP` 多一行 `Homing rotation` 時可能讀錯 | 改成取第一行 |
| 10 | 🟢 | MCC 30 秒沒有 API 呼叫就暫停狀態檢查;我們每 2 秒輪詢,等於讓它一直檢查 | 對 Arduino 多一點流量,不會壞 | 修第 1 項時一併降低頻率 |

問題 1 的過程:

![轉盤一直歸位](docs/diagrams/11_issue_homing.svg)

> 目前 `.env` 的 `ACQUA_SETUP_CONTROLLER` 是空的,所以用的是 `MockCrane`,**上面的問題都還沒對真機造成影響**。
> **在第 1、2 項修好之前,不要填這個設定。**

---

## 7. 移動順序:建議放在 MCC

目前 `HttpCrane` 是**一根一根軸依序移動**,沒有考慮碰撞,也沒有讓不同的 Pi 同時動。這段邏輯建議放在 MCC:

```
ACQUA Automation 負責                  MCC 負責
────────────────                        ────────
哪一筆測項要哪個擺位                     這個擺位怎麼安全地走到
什麼時候移動、等到位才量                 ・哪根先動(例如先升高再橫移)
沒到位 → 記警告、照常量測                ・不同 Pi 同時動,同一台依序動
                                         ・開跑前校正 / 歸位
                                         ・逾時、409、超出行程的判斷
```

理由:會不會撞、能不能同時動,都是**機構本身**的知識;MCC 本來就管著裝置清單、鎖和 Home all 順序。這樣以後換機構或韌體,只需要改 MCC。

建議的 API 形狀。形狀跟我們現在的 `CraneBridge` 一樣,所以 `SetupCoordinator` 不用改,只要換掉 `HttpCrane` 的內容:

```
POST /api/motion/jobs         {label, targets: {"pi-01": {"SXM": 200, "RM": 90}, ...}}  → {job_id}
GET  /api/motion/jobs/<id>    → {state: running|done|error|aborted, steps: [...], error}
POST /api/motion/jobs/<id>/abort
POST /api/motion/home         開跑前校正 / 歸位(伺服器端執行,不靠瀏覽器)
```

改完之後的流程:

![建議的移動作業](docs/diagrams/12_proposed_motion.svg)

要一起決定的:**單位換算放哪一邊。** 擺位檔存的是房間座標(公尺),目前在 `crane.py` 換成公釐。
換算只能在一個地方做。如果移到 MCC,`targets` 就改傳房間座標,`AXES` 也跟著搬過去。

---

## 8. 尚未完成

接上真機的建議順序(紅色是一定要先做的):

![路線圖](docs/diagrams/13_roadmap.svg)

### 硬體串接
- [ ] §6 的第 1、2 項(🔴)
- [ ] 軸 ↔ Pi 對應表搬到設定檔,並照現場接線核對
- [ ] 真機韌體上線。目前 Arduino 燒的是 **LED 模擬版**,機構還沒接上
- [ ] MCC 的移動作業 API 和歸位 API(§7)
- [ ] 碰撞規則和移動順序(還沒設計)
- [ ] 先用 LED 模擬台跑 `tools/test_hook_bridge.py` 和一批真的測項,再上真機

### ACQUA 這一側
- [ ] `HOOK_setup_bridge.py` 還沒貼進 ACQUA 實測(外部那半邊已經用模擬服務驗過)
- [ ] 掛鉤這條路的資料夾繼承:要等 `HOOK_diagnose_smd.py` 印出 `Smd.Path` 的實際格式
- [ ] 掛鉤會不會擋住 ACQUA 的量測流程(預計用 `SELFTEST_SLEEP` 10 → 60 → 180 秒測)
- [ ] 條件執行的數值條件(例如 `Lvl_CodedUS_MAX >= 70`):目前開跑前只能標成「沒把握」。要改成**跑到那一筆才用實際變數值判斷**,而且分組排序不能把「產生值的測項」排到後面
- [ ] AUTO_RUN 精靈的跳過條件(讓需要人工的精靈在無人值守時不跳出來)
- [ ] 認證專案(SP2 / SP3)加標籤:**要先取得同意**

### 長期穩定運行
- [ ] 登入 Windows 時自動在背景啟動(`tools/install_task.ps1` 要改成不開視窗、當掉自動重啟、等 ACQUA 開好才開始),**目前還沒安裝**
- [ ] Docker Desktop 設成登入時自動啟動(MCC 容器已設 `restart: unless-stopped`)

---

## 9. 執行環境與部署

![部署](docs/diagrams/10_deployment.svg)

| 元件 | 跑在哪 | Port | 為什麼 |
|---|---|---|---|
| ACQUA 6 | Windows 桌面 | — | 需要 dongle、桌面視窗 |
| ACQUA Automation | Windows **原生**(`.venv`,`run stay`) | 5000 | 要用 COM 連桌面上的 ACQUA,也要點掉桌面彈窗。Docker 或 Windows 服務都碰不到使用者的桌面 |
| MCC + Beszel hub | PC 上的 Docker | 5001 / 8090 | 不碰桌面,適合放 Docker |
| Pi 控制端 | 每台 Pi 的 Docker | 5000 | 映像檔在 ghcr,用 Ansible 部署 |

**注意 port:我們的服務和每台 Pi 都用 5000**,一個在 PC、一個在 Pi,所以不衝突。但不要把 Pi 控制端也跑在這台 PC 上。

啟動順序:Docker Desktop(MCC 會自動起來)→ ACQUA → `run stay`。MCC 沒開也不影響量測,擺位會記成未套用。

---

## 10. 小細節與坑

- **超出行程不算錯誤**:韌體仍以 `DONE` 收尾,只多一行 `Exceeded Max travel.`。三邊都要掃這一行(MCC 網頁、我們的 `HttpCrane` 都有掃)。
- **擺位用名稱對應**:在網頁上改擺位名稱,ACQUA 裡的標籤就對不上了。改名前先用 `tools/setup_inventory.py` 看有哪些測項在用。
- **找不到擺位或移動失敗都不會擋量測**,只會記進跑完的摘要。這是刻意的:過夜跑不能因為機構卡住就整批停下。代價是要記得看摘要。
- **到位判斷的容許誤差**:線性軸 1 cm、角度 1°(`setupcoord.POSITION_TOLERANCE`)。
- **後端有自己的一份行程表**:不採用前端送來的範圍,避免瀏覽器改個數字就把機構送去撞牆。和 3D 頁不一致時,UI 會示警。
- **MCC 只能跑 1 個 worker**:狀態快取和指令鎖都在記憶體裡,多開 worker 會各自上鎖。
- **MCC 的指令紀錄只存在瀏覽器分頁裡**,重新整理就沒了。要追查移動紀錄,看我們這邊的 log。
- **MCC 的 `API_TOKEN` 只是共用密碼**,沒有 HTTPS;Pi 的 API 完全沒有驗證。只能在受信任的區網使用。
- **指令必須單行**:中間夾換行會變成兩個指令,但 Pi 只等一個 `DONE`,之後的回應全部錯位。
- **麥克風供電只在從網頁開跑時切換**。直接在 ACQUA 按開始,沿用卡上的現況。
- **同一個 row id 在不同資料庫是不同的測項**。所以每次開跑都要帶 `ctx`(server | database | idProject),對不上就拒絕。
