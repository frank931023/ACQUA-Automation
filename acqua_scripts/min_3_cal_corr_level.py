"""
========================================================================
  cal_corr_level.py
  資料庫 61_Demo_SMDs_Rev07
========================================================================

⚠️ 這是從 ACQUA 資料庫解出來的**副本**,只是給你看的。
   改這裡不會影響 ACQUA。要真的改請用 ACQUA 自己的腳本編輯器 ——
   它會處理 ZIP 壓縮、FileSize、CRCValue、ChangeDate,
   少寫一個欄位 ACQUA 可能就讀不到、或靜默用舊版。

   來源:acqua.Files idFile=128 ・ 型別 FT_SMDUsedFile ・ 最後修改 2017-09-28 11:20:51

校正修正值。Demo 資料庫裡的小範例,跟量測流程無關,適合拿來試手。

在 ACQUA 裡怎麼找到它
    資料庫   61_Demo_SMDs_Rev07
    專案     ACQUA Demo SMDs Rev.07
    測項樹   ACQUA Demo SMDs Rev.07 / ACQUA Demo SMDs Rev.07 / Special SMD Types - ACOPTs / 6866 - 3QUEST-SWB/FB / TS 103 281 (Model A) / English
             └ Prep. 3QUEST SWB/FB HA Eng (6819 - SLVM P.56 required)
               row_id 114

    開啟上面那個專案 -> 在測項樹照路徑展開 -> 選到該測項
    -> 測項設定裡可以開啟並編輯這支腳本。

    共 5 個測項用到它。
    **改它會同時影響這些測項**,其他幾個例如:
      #117    Prep. 3QUEST SWB/FB HA Ger (6819 - SLVM P.56 required)
      #120    Prep. 3QUEST SWB/FB HA Chn (6819 - SLVM P.56 required)
      #177    Prep. 3QUEST (6819 SLVM P.56) - Air-Borne
      ...另外 1 個

========================================================================
  以下是**原始程式碼**,一字未改。
========================================================================
"""
from HEAD.AcquaBasic import Variables

def main():

    speVar = Variables.GetVar("LVL_3QUEST")
    speLvl = speVar[0]
    corr_3quest = 73 - speLvl                                           # Calculate offset to default listening level acc. to TS 103 281
    Variables.SaveToVar("CORR_3QUEST", corr_3quest, 1, PhUnit = "dB")

main()
