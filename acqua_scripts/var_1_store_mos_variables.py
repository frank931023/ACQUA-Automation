"""
========================================================================
  3quest_store_mos_variables.py
  資料庫 ACQUA_auto_v2026Aug
========================================================================

⚠️ 這是從 ACQUA 資料庫解出來的**副本**,只是給你看的。
   改這裡不會影響 ACQUA。要真的改請用 ACQUA 自己的腳本編輯器 ——
   它會處理 ZIP 壓縮、FileSize、CRCValue、ChangeDate,
   少寫一個欄位 ACQUA 可能就讀不到、或靜默用舊版。

   來源:acqua.Files idFile=230 ・ 型別 FT_SMDUsedFile ・ 最後修改 2020-07-17 11:48:48

**這個資料庫裡被用最多次的腳本:162 個測項共用。**

它在做什麼
    把 3QUEST 分析算出的 MOS 分數存成變數。

一支腳本怎麼服務 162 個測項
        BGNScenario = Tags.Value("BGNScenario")
        Position = Tags.Value("Position")
    靠標籤產生不同的變數名稱 —— 掛在不同測項上就存成不同的變數。
    這是整個專案「少量腳本服務大量測項」的核心手法。

    存出來的變數就是我們網頁上看到的那些,也是條件執行
    (ConditionalExecution)決定要不要跳過某些測項的依據。

在 ACQUA 裡怎麼找到它
    資料庫   ACQUA_auto_v2026Aug
    專案     ZoomRooms_v2020Oct_v1
    測項樹   ZoomRooms_v2020Oct_v1 / COS_auto_Sentinal / Basic Test_using Mouth only / 4.4.2 - 4.4.3 Send path - alternating talkers- Normal speec
             └ Calc 4.4.2 - Send path - alternating talker1-1 - pos1
               row_id 1542

    開啟上面那個專案 -> 在測項樹照路徑展開 -> 選到該測項
    -> 測項設定裡可以開啟並編輯這支腳本。

    共 162 個測項用到它。
    **改它會同時影響這些測項**,其他幾個例如:
      #1545   Calc 4.4.2 - Send path - alternating talker2-2 - pos1
      #1990   O. Analy. 3QUEST TS103 - noBGN
      #1991   G. Analy. 3QUEST TS103 - Mensa
      ...另外 158 個

========================================================================
  以下是**原始程式碼**,一字未改。
========================================================================
"""
from ACQUAlyzer import Smd, Tags
from HEAD.AcquaBasic import Results, Variables

BGNScenario = Tags.Value("BGNScenario")
Position = Tags.Value("Position")

sv = Results.SmdResultValues()
for val in sv.GetValues():
   if val.Title == "G-MOS (Average)" or val.Title == "S-MOS (Average)" or val.Title == "N-MOS (Average)":
      varName = val.Title.replace("-","_").replace(" (Average)","") + "_TS_" + BGNScenario + "_" + Position
      Variables.SaveToVar(varName, val.Value, val.State)


