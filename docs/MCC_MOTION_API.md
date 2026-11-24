# MCC 移動作業 API(給 pc-led-controller 實作)

> 狀態:**ACQUA Automation 這邊已經照這份實作完成**(`acqua/crane.py` 的 `HttpCrane`),
> MCC 那邊還沒有。MCC 照這份加上兩支 API 就能接起來。
> 測試用的假 MCC:`tools/fake_mcc.py`,行為就是這份規格。
>
> 最後更新:2026-11-24

---

## 一句話

ACQUA Automation 跑測試時,換擺位會把 **「擺位名稱 + 每台 Pi 的目標位置」** 一次送給 MCC,
**怎麼走(順序、哪些同時動、防撞、逾時、重試)由 MCC 決定**,走完回報結果。

```
ACQUA Automation                         MCC
────────────────                         ───
哪一筆測項要哪個擺位         ──POST──▶  收到 {label, targets}
房間座標 → 韌體數值(換算在這邊)        決定順序 / 並行 / 防撞
每秒問一次進度               ──GET───▶  逐台送 SXM / SZM / RM …
等到 done 才開始量測         ◀─────────  回報 done / error + 最後位置
```

為什麼名稱和目標一起送、不是只送名稱:只送名稱的話 MCC 得自己存一份擺位,
兩邊就要同步,遲早對不上。擺位的唯一來源是 ACQUA Automation 的 `setups/*.json`,
名稱只是給 MCC 顯示、記錄用。

---

## 1. 送出作業

```
POST /api/motion/jobs
Content-Type: application/json
Authorization: Bearer <API_TOKEN>        ← MCC 有設 API_TOKEN 才帶
```

```json
{
  "label": "location2",
  "targets": {
    "pi-03": { "SZM": 3350, "SXM": 1100, "SYM": 450, "RM": 0, "TM": 0 },
    "pi-04": { "SZM": 650,  "SYM": 500 }
  }
}
```

| 欄位 | 說明 |
|---|---|
| `label` | 擺位名稱。只用來顯示與記錄,MCC 不需要認得它 |
| `targets` | `{裝置 ID: {指令: 數值}}`。裝置 ID = MCC 裝置清單的 `pi_id` |
| 指令鍵 | 韌體的**絕對移動**指令名稱:`SXM` `SYM` `SZM` `RM` `TM`。**跟 MCC 既有的停車位置 `park` 是同一種格式** |
| 數值 | 韌體單位的整數:滑台是**公釐**(從機械原點算起)、轉盤與傾角是**度** |

**一個作業 = 一個擺位的全部軸**,包括看起來已經在那裡的軸(ACQUA Automation 這邊的位置
可能是推估的,韌體才知道真正在哪;已經到位的軸走 0 mm 就結束)。

MCC 實際送給 Pi 的就是 `"<指令>,<數值>"`,例如 `SZM,3350`。

### 回應

**成功(作業已排入,還沒走完)** —— `202` 或 `200`:

```json
{ "status": "success", "job_id": "j-1a2b3c" }
```

**拒絕** —— 作業不成立,一根軸都不要動:

| 狀態碼 | 什麼時候 | body |
|---|---|---|
| `400` | body 格式錯、裝置 ID 不存在、不認得的指令鍵、數值不是數字 | `{"status":"error","error":"pi-09: no such device"}` |
| `401` | 有設 `API_TOKEN` 但沒帶或帶錯 | 同上格式 |
| `409` | 已經有一個移動作業在跑,或某台裝置正忙(例如有人在網頁手動操作) | 同上格式 |
| `503` | 某台裝置 offline / no-arduino | 同上格式 |

ACQUA Automation 收到拒絕時:那一筆測項記成「擺位未套用」(附上 `error` 的文字),
**照常量測**,不重試。所以 `error` 請寫人看得懂的原因。

---

## 2. 查進度

```
GET /api/motion/jobs/<job_id>
Authorization: Bearer <API_TOKEN>        ← 同上
```

```json
{
  "status": "success",
  "job": {
    "job_id": "j-1a2b3c",
    "label": "location2",
    "state": "done",
    "error": null,
    "positions": {
      "pi-03": { "SZM": 3350, "SXM": 1100, "SYM": 450, "RM": 0, "TM": 0 },
      "pi-04": { "SZM": 650,  "SYM": 500 }
    }
  }
}
```

| 欄位 | 說明 |
|---|---|
| `state` | `queued` / `running` / `done` / `error` / `aborted` |
| `error` | `error` / `aborted` 時寫原因,其他時候 `null` |
| `positions` | **選填。** 作業結束時每根軸實際在哪,格式同 `targets`。有給的話 ACQUA Automation 會用它判斷「到位了沒」;沒給就假設到了目標 |

找不到這個 `job_id`(例如 MCC 重啟過)回 `404`,ACQUA Automation 會當成失敗。

### `done` 的條件(請嚴格遵守)

**每一個**送出去的指令都回了 `DONE`,**而且**回應裡沒有 `Exceeded Max travel.` 這一行。

韌體超出行程時仍然以 `DONE` 收尾,只多一行 `Exceeded Max travel.`,機構其實沒動。
這種情況必須回 `state: "error"`,`error` 寫是哪台哪根軸,例如
`"pi-03 SZM,3350: Exceeded Max travel (not calibrated / homed?)"`。
否則 ACQUA Automation 會以為到位了,在錯的位置上量測,數據錯了卻看起來一切正常。

韌體回 `ERR`、逾時、Pi 斷線,同樣是 `error`。

---

## 3. 輪詢與逾時

- ACQUA Automation 每 **1 秒**查一次進度,直到 `done` / `error` / `aborted`。
- 總共最多等 `move_timeout_sec`(預設 **900 秒**,在 ACQUA Automation 的 `config.json`)。
  超過就記成「移動逾時」、照常量測。所以 MCC 自己的逾時請**短於** 900 秒,才能回報明確原因。
- 查詢暫時連不上不算失敗(機構可能還在走),會繼續查到總逾時為止。
- 同一時間只會有一個作業:ACQUA Automation 在前一個作業結束前不會送下一個。

---

## 4. 建議 MCC 一起處理的事

這些 ACQUA Automation **目前不會呼叫**,但是機構安全需要,建議 MCC 在作業內部處理:

| 項目 | 為什麼 |
|---|---|
| **順序與防撞** | 例如先把 Z 升高再橫移、HATS 平台與升降台的行程重疊。這是機構的知識,只有 MCC 知道 |
| **不同 Pi 同時動** | 同一台 Pi 的指令只能依序;不同 Pi 可以並行,換擺位會快很多 |
| **沒校正 / 沒歸位** | 韌體要求先 `C` 再 `H` 才能移動,否則一律 `Exceeded`。可以在作業開始前檢查,或提供 `POST /api/motion/home` 讓批次開跑前先歸位(之後 ACQUA Automation 可以接) |
| **逾時用每台 Pi 回報的 `command_timeout`** | MCC 原本就這樣做,作業內沿用即可 |
| **不要在作業中查 `RP` / `TP`** | 韌體已知行為:這兩個查詢會順便觸發轉盤歸位 |
| **`TM`(傾角)目前不會真的動** | 韌體已知行為。修好之前,含 `TM` 的作業建議回報警告 |

---

## 5. 數值怎麼來的(供核對)

ACQUA Automation 的擺位存房間座標(公尺,以房間中心為 0)。送出前在 `acqua/crane.py` 換算:

```
滑台:韌體公釐 = (場景值 − 該軸行程下限 lo) × 1000
轉盤 / 傾角:度數直接送
```

例:`hats.z` 行程 −1.85 ~ 1.85 m,擺位值 1.50 m → `(1.50 − (−1.85)) × 1000 = 3350` → `"SZM": 3350`。

每根軸接在哪台 Pi、用哪個指令前綴,在 `acqua/crane.py` 的 `AXES`。
⚠️ 目前寫的是 `pi-001` ~ `pi-007`,要跟 MCC 裝置清單的 `pi_id` 對齊;
行程也還沒跟真機校正值對過(見 `SYSTEM_OVERVIEW.md` §6)。

---

## 6. 不用真的 MCC 就能測

```powershell
# 終端機 1:起一個照這份規格回應的假 MCC
.venv\Scripts\python.exe tools\fake_mcc.py --port 5001

# .env
ACQUA_SETUP_CONTROLLER=http://127.0.0.1:5001

# 終端機 2:照常起服務、跑測試
.\run stay
```

自動測試:`.venv\Scripts\python.exe tools\test_mcc_jobs.py`(自己起假 MCC,不用服務、不用 ACQUA)。
