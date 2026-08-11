# `61_Demo_SMDs_Rev07` 測項完整清單

> HEAD acoustics 官方示範測項庫 Rev.07
> 資料庫檔案位於 `C:\ACQUA_DB\`,由 SQL Server 執行個體 `ACQUADBSERVER` 掛載
> 本文件由直接查詢資料庫產生,2026-08-06

---

## 為什麼 `C:\ACQUA_DB` 打不開

那個資料夾裡只有 3 個檔案,而且**都不是給人開的**:

| 檔案 | 是什麼 | 能不能直接開 |
|---|---|:---:|
| `61_Demo_SMDs_Rev07.mdf` | SQL Server **主資料檔**(10 MB) | ❌ 二進位,且被 SQL Server 鎖住 |
| `61_Demo_SMDs_Rev07_log.ldf` | 交易紀錄檔(2.8 MB) | ❌ 同上 |
| `61_Demo_SMDs_Rev07.fs` | FILESTREAM 資料夾(存音訊等二進位) | ❌ 目錄,內容由 SQL Server 管理 |

這三個檔案是**資料庫本體**,不是文件。要看內容只有兩條路:

1. 用 ACQUA 開啟這個資料庫(正常做法)
2. 用 SQL 查詢(本文件的做法)

> ⚠️ **不要手動搬移、複製或刪除這三個檔案。** SQL Server 正在使用它們,
> 直接動檔案會讓資料庫損毀。要搬家請用 SQL Server 的 detach/attach 或備份還原。

---

## 資料庫概況

| 項目 | 值 |
|---|---|
| 專案群組 | Standards |
| 專案 | ACQUA Demo SMDs Rev.07 |
| 量測物件 (DUT) | New Measurement Object |
| **MMD(測試群組)** | **61** |
| **SMD(實際測項)** | **132** |
| 已執行的量測結果 | 0(純參考庫) |
| 資料庫結構版本 | 1.5 |

⚠️ **這是「參考庫」不是工作專案** —— 132 個測項都只有定義,沒有任何量測結果。
正確用法是把需要的測項**複製到你自己的專案**再跑。

---

## 依 ACOPT 授權模組分類

MMD 名稱開頭的 4 位數字是 **HEAD 的 ACOPT 選配編號** —— 代表這組測項需要哪個授權才能跑。

| ACOPT 編號 | 模組 | 底下測項數 |
|---|---|---:|
| 6819 | SLVM P.56 | 1 |
| 6820 | TOSQA | 5 |
| 6822 | DTMF | 1 |
| 6836 | PESQ | 2 |
| 6839 | Relative Approach | 1 |
| 6844 | 3QUEST | 10 |
| 6852 | Psychoacoustics | 5 |
| 6853 | Roomacoustics | 3 |
| 6854 | Speech Transmission Index | 3 |
| 6855 | G.160 | 5 |
| 6856 | EQUEST | 9 |
| 6857 | P.863 - POLQA | 15 |
| 6859 | Speech-based Double Talk | 11 |
| 6865 | Speech Intelligibility Index | 1 |
| 6866 | 3QUEST-SWB/FB | 6 |
| 6867 | MDAQS | 4 |
| 6869 | Listening Effort | 16 |

> 沒有編號的 MMD 是分類用的資料夾,或屬於 ACQUA 基本功能。

---

## 測項型別對照表

`SMDType` 是 ACQUA 內部的數字代碼,**沒有公開的名稱對照**。
下表是我從測項名稱實證推斷出來的。

| 代碼 | 中文 | 英文 | 數量 |
|---:|---|---|---:|
| 1 | 頻率響應 / 傳輸函數 | Frequency response, transfer function | 4 |
| 7 | 位準錄音 / 開迴路錄音 | Level recording, open-loop recording | 3 |
| 12 | 整體延遲 | Overall delay | 6 |
| 17 | SNRI 前置量測 | SNRI preparation | 1 |
| 19 | 主動語音位準 P.56 | Active speech level (ITU-T P.56) | 6 |
| 22 | 回音位準 vs 時間 | Echo level vs. time | 1 |
| 28 | DTMF 訊號 | DTMF signalling | 1 |
| 34 | 資訊項(不量測) | Info only — no measurement | 4 |
| 35 | 硬體前置動作 | Hardware preparation (HRR drive etc.) | 2 |
| 38 | 時脈飄移補償 | Clock drift compensation | 1 |
| 39 | 語音品質 TOSQA / PESQ / POLQA | Speech quality (TOSQA/PESQ/POLQA) | 22 |
| 40 | Relative Approach 3D | Relative Approach 3D | 1 |
| 41 | 延遲計算 / 連線設定 | Delay calculation, connection setup | 6 |
| 43 | 設定檔建立 / 藍牙配對 | Profile creation, BT pairing | 4 |
| 44 | 3QUEST 噪音下語音品質 | 3QUEST (speech quality in noise) | 15 |
| 45 | 心理聲學(粗糙度/尖銳度/響度) | Psychoacoustics | 5 |
| 46 | 語音傳輸指數 STI | Speech Transmission Index | 3 |
| 47 | 室內聲學(脈衝響應/殘響) | Room acoustics | 3 |
| 48 | SNR 改善量 | SNR improvement | 3 |
| 49 | 雙向通話 Double Talk | Double talk | 7 |
| 50 | EQUEST | EQUEST | 5 |
| 51 | 轉盤極座標圖 | Turntable polar plot | 1 |
| 52 | 語音清晰度指數 SII | Speech Intelligibility Index | 1 |
| 54 | 聆聽費力度評估 | Listening Effort Assessment | 16 |
| 55 | 失真 (Farina) | Distortion (Farina) | 3 |
| 56 | P.700 響度 | P.700 loudness | 5 |
| 57 | MDAQS 多維音質評分 | MDAQS | 3 |

---

## 完整測項樹

縮排代表階層。`▸` = MMD(測試群組),`•` = SMD(可執行的測項)。
每個 SMD 後面標的是型別代碼。

```
▸ ACQUA Demo SMDs Rev.07
  ▸ ACQUA Demo SMDs Rev.07
    ▸ Preparation: Delay Measurements
      • Overall Delay in Sending Direction   [12:整體延遲]
      • Overall Delay in Receiving Direction   [12:整體延遲]
      • Calculation of Echo Delay   [41:延遲計算 / 連線設定]
      • Calculation of DT Sync. Delay   [41:延遲計算 / 連線設定]
    ▸ Special SMD Types - ACOPTs
      ▸ 6819 - SLVM P.56
        • Active Speech Level acc. to ITU-T P.56   [19:主動語音位準 P.56]
      ▸ 6820 - TOSQA
        • TOSQA, List. Speech Quality (TMOS) RCV, HANB   [39:語音品質 TOSQA / PESQ / POLQA]
        • TOSQA, Speech Quality (TMOS) SND, HANB   [39:語音品質 TOSQA / PESQ / POLQA]
        • TOSQA, List. Speech Quality (TMOS) RCV, HAWB   [39:語音品質 TOSQA / PESQ / POLQA]
        • TOSQA, Speech Quality (TMOS) SND, HAWB   [39:語音品質 TOSQA / PESQ / POLQA]
        • TOSQA, Speech Quality (TMOS) SND, HANB   [39:語音品質 TOSQA / PESQ / POLQA]
      ▸ 6822 - DTMF
        • DTMF signalling all parameters   [28:DTMF 訊號]
      ▸ 6836 - PESQ
        • PESQ - One Way Speech Quality in RCV, NB   [39:語音品質 TOSQA / PESQ / POLQA]
        • PESQ - One Way Speech Quality in SND, NB   [39:語音品質 TOSQA / PESQ / POLQA]
      ▸ 6839 - Relative Approach
        • Relative Approach 3D, SND   [40:Relative Approach 3D]
      ▸ 6844 - 3QUEST
        ▸ EG 202 396-3 v1.3.1 (Old)
          • 3QUEST Narrowband, English (lead. pause 22s), Handset   [44:3QUEST 噪音下語音品質]
          • 3QUEST Narrowband, English (lead. pause 30s), Handset   [44:3QUEST 噪音下語音品質]
          • 3QUEST Wideband, English (lead. pause 22s), Handset   [44:3QUEST 噪音下語音品質]
          • 3QUEST Wideband, French (lead. pause 22s), Handset   [44:3QUEST 噪音下語音品質]
          • 3QUEST Wideband, English (lead. pause 30s), Handset   [44:3QUEST 噪音下語音品質]
          • 3QUEST Wideband, French (lead. pause 30s), Handset   [44:3QUEST 噪音下語音品質]
        ▸ TS 103 106 (New)
          • 3QUEST Narrowband - TS 103 106, Handset   [44:3QUEST 噪音下語音品質]
          • 3QUEST Wideband - TS 103 106, Handset   [44:3QUEST 噪音下語音品質]
        ▸ EG 202 396-3 v1.4.1 (New)
          • 3QUEST Narrowband - EG 202 396-3 v1.4.1, Handset   [44:3QUEST 噪音下語音品質]
          • 3QUEST Wideband -  EG 202 396-3 v1.4.1, Handset   [44:3QUEST 噪音下語音品質]
      ▸ 6852 - Psychoacoustics
        • Roughness vs. Time   [45:心理聲學(粗糙度/尖銳度/響度)]
        • Sharpness vs. Time   [45:心理聲學(粗糙度/尖銳度/響度)]
        • Spec. Loudness vs. Time   [45:心理聲學(粗糙度/尖銳度/響度)]
        • Spec. Roughness vs. Time   [45:心理聲學(粗糙度/尖銳度/響度)]
        • Loudness vs. Time   [45:心理聲學(粗糙度/尖銳度/響度)]
      ▸ 6853 - Roomacoustics
        • Cumulative Spectral Decay 3rd Octave   [47:室內聲學(脈衝響應/殘響)]
        • Impulse Response   [47:室內聲學(脈衝響應/殘響)]
        • Reverberation vs. Frequency 3rd Octave   [47:室內聲學(脈衝響應/殘響)]
      ▸ 6854 - Speech Transmission Index
        • Speech Transmission Index - RASTI, Modulation Index 2D   [46:語音傳輸指數 STI]
        • Speech Transmission Index - STIPA (male), MTF 2D   [46:語音傳輸指數 STI]
        • Speech Transmission Index - STITEL, MTF 3D   [46:語音傳輸指數 STI]
      ▸ 6855 - G.160
        ▸ Method A - DUT Transfer Function
          • Transfer Function for SNRI Calculations   [1:頻率響應 / 傳輸函數]
          • SNR Improvement - Acoustical measurement   [48:SNR 改善量]
        ▸ Method B - Turn NR on/off
          • Preparation measurement for SNRI   [17:SNRI 前置量測]
          • SNR Improvement - Acoustical measurement   [48:SNR 改善量]
        ▸ Electric-2-Electric
          • SNR improvement - Electrical measurement   [48:SNR 改善量]
      ▸ 6856 - EQUEST
        ▸ Preparation: Delay Measurements
          • Overall Delay in Sending Direction   [12:整體延遲]
          • Overall Delay in Receiving Direction   [12:整體延遲]
          • Set Connection Delay   [41:延遲計算 / 連線設定]
          • Calculation of EQUEST Echo Delay   [41:延遲計算 / 連線設定]
        ▸ Classic
          • EQUEST - NB Mixed Classic (Sequenced Time Range)   [50:EQUEST]
          • EQUEST - WB Mixed Classic (Sequenced Time Range)   [50:EQUEST]
        ▸ TS 103 802
          • EQUEST - NB Mixed TS103802 (Sequenced Time Range)   [50:EQUEST]
          • EQUEST - WB Mixed TS103802 (Sequenced Time Range)   [50:EQUEST]
          • EQUEST - SWB Mixed TS103802 (Sequenced Time Range)   [50:EQUEST]
      ▸ 6857 - P.863 - POLQA
        ▸ Version 1.1
          • P.863 AC RCV Handset or Headset NB   [39:語音品質 TOSQA / PESQ / POLQA]
          • P.863 AC RCV Handset or Headset WB   [39:語音品質 TOSQA / PESQ / POLQA]
          • P.863 AC RCV Handset or Headset SWB   [39:語音品質 TOSQA / PESQ / POLQA]
          • P.863 AC SND Handset or Headset NB   [39:語音品質 TOSQA / PESQ / POLQA]
          • P.863 AC SND Handset or Headset SWB or WB   [39:語音品質 TOSQA / PESQ / POLQA]
        ▸ Version 2.4
          • P.863 AC RCV Handset or Headset NB   [39:語音品質 TOSQA / PESQ / POLQA]
          • P.863 AC RCV Handset or Headset WB   [39:語音品質 TOSQA / PESQ / POLQA]
          • P.863 AC RCV Handset or Headset SWB   [39:語音品質 TOSQA / PESQ / POLQA]
          • P.863 AC SND Handset or Headset NB   [39:語音品質 TOSQA / PESQ / POLQA]
          • P.863 AC SND Handset or Headset SWB or WB   [39:語音品質 TOSQA / PESQ / POLQA]
        ▸ Version 3.0
          • P.863 AC RCV Handset or Headset NB   [39:語音品質 TOSQA / PESQ / POLQA]
          • P.863 AC RCV Handset or Headset WB   [39:語音品質 TOSQA / PESQ / POLQA]
          • P.863 AC RCV Handset or Headset SWB   [39:語音品質 TOSQA / PESQ / POLQA]
          • P.863 AC SND Handset or Headset NB   [39:語音品質 TOSQA / PESQ / POLQA]
          • P.863 AC SND Handset or Headset SWB or WB   [39:語音品質 TOSQA / PESQ / POLQA]
      ▸ 6859 - Speech-based Double Talk
        ▸ Preparation: Delay Measurements
          • Overall Delay in Sending Direction   [12:整體延遲]
          • Overall Delay in Receiving Direction   [12:整體延遲]
          • Calculation of Echo Delay   [41:延遲計算 / 連線設定]
          • Calculation of DT Sync. Delay   [41:延遲計算 / 連線設定]
        ▸ Speech Based Double Talk (acc. to 3GPP TS 26.132)
          • Speech Based Double Talk, SND - Record   [49:雙向通話 Double Talk]
          • Speech Based Double Talk, SND - Analysis 1   [49:雙向通話 Double Talk]
          • Speech Based Double Talk, SND - Analysis 2   [49:雙向通話 Double Talk]
        ▸ Automated Double Talk Analysis - Real Speech (ITU-T P.502)
          • Automated Double Talk Real Speech, SND - Record   [49:雙向通話 Double Talk]
          • Automated Double Talk Real Speech, SND - Analysis 1   [49:雙向通話 Double Talk]
          • Automated Double Talk Real Speech, SND - Analysis 2   [49:雙向通話 Double Talk]
        ▸ Automated Double Talk Analysis (ITU-T P.502), CSS
          • Automated Double Talk, SND  - CSS -   [49:雙向通話 Double Talk]
      ▸ 6865 - Speech Intelligibility Index
        • Speech Intelligibility Index, Speakerphone   [52:語音清晰度指數 SII]
      ▸ 6866 - 3QUEST-SWB/FB
        ▸ TS 103 281 (Model A)
          ▸ English
            • Prep. 3QUEST SWB/FB HA Eng (6819 - SLVM P.56 required)   [19:主動語音位準 P.56]
            • 3QUEST Super-wideband/Fullband - TS 103 281-A, HA Eng   [44:3QUEST 噪音下語音品質]
          ▸ German
            • Prep. 3QUEST SWB/FB HA Ger (6819 - SLVM P.56 required)   [19:主動語音位準 P.56]
            • 3QUEST Super-wideband/Fullband - TS 103 281-A, HA Ger   [44:3QUEST 噪音下語音品質]
          ▸ Chinese
            • Prep. 3QUEST SWB/FB HA Chn (6819 - SLVM P.56 required)   [19:主動語音位準 P.56]
            • 3QUEST Super-wideband/Fullband - TS 103 281-A, HA Chn   [44:3QUEST 噪音下語音品質]
      ▸ 6869 - Listening Effort
        ▸ P.501 Speech Signals
          • Listening Effort Assessment, RCV, NB   [54:聆聽費力度評估]
          • Listening Effort Assessment, RCV, WB   [54:聆聽費力度評估]
          • Listening Effort Assessment, RCV, SWB   [54:聆聽費力度評估]
          • Listening Effort Assessment, SND, FB   [54:聆聽費力度評估]
        ▸ TS 103281 Speech Signals
          ▸ English
            • Listening Effort Assessment RCV, NB, TS103681 Eng   [54:聆聽費力度評估]
            • Listening Effort Assessment RCV, WB, TS103681 Eng   [54:聆聽費力度評估]
            • Listening Effort Assessment RCV, SB, TS103681 Eng   [54:聆聽費力度評估]
            • Listening Effort Assessment SND, FB, TS103681 Eng   [54:聆聽費力度評估]
          ▸ German
            • Listening Effort Assessment RCV, NB, TS103681 Ger   [54:聆聽費力度評估]
            • Listening Effort Assessment RCV, WB, TS103681 Ger   [54:聆聽費力度評估]
            • Listening Effort Assessment RCV, SB, TS103681 Ger   [54:聆聽費力度評估]
            • Listening Effort Assessment SND, FB, TS103681 Ger   [54:聆聽費力度評估]
          ▸ Chinese
            • Listening Effort Assessment RCV, NB, TS103681 Chn   [54:聆聽費力度評估]
            • Listening Effort Assessment RCV, WB, TS103681 Chn   [54:聆聽費力度評估]
            • Listening Effort Assessment RCV, SB, TS103681 Chn   [54:聆聽費力度評估]
            • Listening Effort Assessment SND, FB, TS103681 Chn   [54:聆聽費力度評估]
      ▸ 6867 - MDAQS
        • MDAQS - Multi-Dimenstional Audio Quality Score   [57:MDAQS 多維音質評分]
        • MDAQS - Headset Application (DF Avg.)   [57:MDAQS 多維音質評分]
        • MDAQS - Open Loop Triggered Recording   [7:位準錄音 / 開迴路錄音]
        • MDAQS - Open Loop Analysis   [57:MDAQS 多維音質評分]
    ▸ Basic SMD Types Showcase
      ▸ P.700 Loudness Speech
        • P.700 Loudness Speech Sequences RCV binaural (FF)   [56:P.700 響度]
        • P.700 Loudness Speech Sequences RCV binaural (DF Avg.)   [56:P.700 響度]
        • P.700 Loudness Speech SND   [56:P.700 響度]
      ▸ Farina Distortion
        • Distortion (Farina) - Harmonic distortion [dB]   [55:失真 (Farina)]
        • Distortion (Farina) - Harmonic distortion [%]   [55:失真 (Farina)]
        • Distortion (Farina) - Harmonic frequency responses   [55:失真 (Farina)]
      ▸ Multichannel Analysis
        • Level recording, 6 channels, RCV   [7:位準錄音 / 開迴路錄音]
        • Freq. Resp. analysis, 6 channels, RCV   [1:頻率響應 / 傳輸函數]
        • Average Freq. Resp. channel 1,3,5, RCV   [1:頻率響應 / 傳輸函數]
        • Average Freq. Resp. channel 2,4,6, RCV   [1:頻率響應 / 傳輸函數]
    ▸ Hardware Modules Showcase
      ▸ Rotating Reflector - HRR I
        • Info: HEAD acoustics Rotating Reflector (HRR I)   [34:資訊項(不量測)]
        • Preparation: Reference Drive of HRR   [35:硬體前置動作]
        • Preparation: Drive HRR to 0° Position   [35:硬體前置動作]
        • Echo Level vs. Time with Time Varying Echo Path   [22:回音位準 vs 時間]
      ▸ Turntable - HRT I
        • Info: HEAD acoustics Remote-controlled Turntable (HRT I)   [34:資訊項(不量測)]
        • Turntable Level in SND at 60° Rotation   [7:位準錄音 / 開迴路錄音]
        • Turntable Freq. Resp. polar plot RCV 30° steps   [51:轉盤極座標圖]
      ▸ Structure-Borne Transmission - ViBRIDGE
        • Info: Mirror Channel in Measurement Settings   [34:資訊項(不量測)]
        ▸ Air-Borne
          • Sending Loudness P.700 - Air-Borne   [56:P.700 響度]
          • Prep. 3QUEST (6819 SLVM P.56) - Air-Borne   [19:主動語音位準 P.56]
          • 3QUEST (6866 TS 103 281) - Air-Borne   [44:3QUEST 噪音下語音品質]
        ▸ Air- & Structure-Borne
          • Sending Loudness P.700 - Air- & Structure-Borne   [56:P.700 響度]
          • Prep. 3QUEST (6819 SLVM P.56) - Air- & Structure-Borne   [19:主動語音位準 P.56]
          • 3QUEST (6866 TS 103 281) - Air- & Structure-Borne   [44:3QUEST 噪音下語音品質]
    ▸ Scripting
      ▸ Network Impairment TCN Profile Creation
        • TCNProfileCreation   [43:設定檔建立 / 藍牙配對]
        • TxtProfileCreation   [43:設定檔建立 / 藍牙配對]
      ▸ Bluetooth Volume Control Check
        • Volume Control   [34:資訊項(不量測)]
        • Setup Bluetooth Connection for Volume Control (HHPIV)   [43:設定檔建立 / 藍牙配對]
        • Setup Bluetooth Connection for Volume Control (BT2)   [43:設定檔建立 / 藍牙配對]
      ▸ Clock drift compensation
        • Compensation of Clock Drift SND (labCORE)   [38:時脈飄移補償]
▸ Recycle Bin
```

---

## ⚠️ 需要參考檔案的測項

132 個測項中有 **17 個需要外部參考檔案**才能執行,
而這個庫裡**沒有任何測項會產生參考資料**(CreatesRef = 0)。

也就是說,這些參考檔案必須**本來就存在於系統上**(隨 ACQUA 或測試套件安裝),
不是靠先跑別的測項生出來的。

| 測項 | 需要的參考檔 |
|---|---|
| P.863 AC RCV Handset or Headset NB | `sp2s_be4x2_swb_sr182.dat` |
| P.863 AC RCV Handset or Headset WB | `sp2s_be4x2_swb_sr182.dat` |
| P.863 AC RCV Handset or Headset SWB | `sp2s_be4x2_swb_sr182.dat` |
| P.863 AC SND Handset or Headset NB | `sp2s_be4x2_fb_sr147.dat` |
| P.863 AC SND Handset or Headset SWB or WB | `sp2s_be4x2_fb_sr147.dat` |
| P.863 AC RCV Handset or Headset NB | `sp2s_be4x2_swb_sr182.dat` |
| P.863 AC RCV Handset or Headset WB | `sp2s_be4x2_swb_sr182.dat` |
| P.863 AC SND Handset or Headset NB | `sp2s_be4x2_fb_sr147.dat` |
| P.863 AC SND Handset or Headset SWB or WB | `sp2s_be4x2_fb_sr147.dat` |
| P.863 AC RCV Handset or Headset NB | `sp2s_be4x2_swb_sr182.dat` |
| P.863 AC RCV Handset or Headset WB | `sp2s_be4x2_swb_sr182.dat` |
| P.863 AC SND Handset or Headset NB | `sp2s_be4x2_fb_sr147.dat` |
| P.863 AC SND Handset or Headset SWB or WB | `sp2s_be4x2_fb_sr147.dat` |
| Freq. Resp. analysis, 6 channels, RCV | `sp2s_sb_ref.fft` |
| Average Freq. Resp. channel 1,3,5, RCV | `sp2s_sb_ref.fft` |
| Average Freq. Resp. channel 2,4,6, RCV | `sp2s_sb_ref.fft` |
| Turntable Freq. Resp. polar plot RCV 30° steps | `spst_m1_f1.fft` |

> ⭐ **這對自動化很重要**:做「勾選 n 項執行」時,若使用者勾了上面這些測項,
> 但系統上找不到對應的 `.dat` / `.fft` 參考檔,量測會失敗。
> 建議程式在開跑前先檢查這些檔案是否存在,而不是跑到一半才報錯。

> 📌 `sp2s_*` 是 HEAD 的標準語音樣本檔,`*.fft` 是頻率響應參考曲線。
> 這些通常隨 ACQUA 或對應的 ACOPT 模組一起安裝。
