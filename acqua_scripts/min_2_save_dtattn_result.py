"""
========================================================================
  save_dtattn_result.py
  資料庫 ACQUA_auto_v2026Aug
========================================================================

⚠️ 這是從 ACQUA 資料庫解出來的**副本**,只是給你看的。
   改這裡不會影響 ACQUA。要真的改請用 ACQUA 自己的腳本編輯器 ——
   它會處理 ZIP 壓縮、FileSize、CRCValue、ChangeDate,
   少寫一個欄位 ACQUA 可能就讀不到、或靜默用舊版。

   來源:acqua.Files idFile=31485 ・ 型別 FT_SMDUsedFile ・ 最後修改 2019-10-21 15:28:20

最精簡的「存結果變數」骨架(12 行)。自己寫一支的話從這個開始。

四個步驟
    讀標籤 -> 取這個測項的結果 -> 挑出要的那一項 -> 存成變數

    `Variables.evsMeasured` 是變數狀態常數(「量到的」,相對於推算或預設)。

在 ACQUA 裡怎麼找到它
    資料庫   ACQUA_auto_v2026Aug
    專案     ZoomRooms_v2020Oct_v1
    測項樹   ZoomRooms_v2020Oct_v1 / COS_auto_Sentinal / Basic Test_using Mouth only / Acoustics echo tests_max_auto / 4.4.11 Echo path - ECC with max output level - reverberant_SC 
             └ V3test Echo path - Send signal attn. during DT - RRSeq1
               row_id 1787

    開啟上面那個專案 -> 在測項樹照路徑展開 -> 選到該測項
    -> 測項設定裡可以開啟並編輯這支腳本。

    共 12 個測項用到它。
    **改它會同時影響這些測項**,其他幾個例如:
      #1788   V3test Echo path - Send signal attn. during DT - RRSeq2
      #4063   V3test Echo path - Send signal attn. during DT - RRSeq1
      #4064   V3test Echo path - Send signal attn. during DT - RRSeq2
      ...另外 8 個

========================================================================
  以下是**原始程式碼**,一字未改。
========================================================================
"""
from ACQUAlyzer import Smd, Tags
from HEAD.AcquaBasic import Results, Variables

Segment = Tags.Value("Segment")
Level = Tags.Value("Level")

sv = Results.SmdResultValues()
for val in sv.GetValues():
   if val.Title == "Attenuation during double talk":
      varName = val.Title.replace("Attenuation during double talk","DTatt")  +  "_" + Level +  "_" + Segment
      Variables.SaveToVar(varName, val.Value, Variables.evsMeasured)
