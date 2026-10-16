"""
========================================================================
  show_ch_name_in_legend.py
  資料庫 51_MS_Teams_Rev05_SP2
========================================================================

⚠️ 這是從 ACQUA 資料庫解出來的**副本**,只是給你看的。
   改這裡不會影響 ACQUA。要真的改請用 ACQUA 自己的腳本編輯器 ——
   它會處理 ZIP 壓縮、FileSize、CRCValue、ChangeDate,
   少寫一個欄位 ACQUA 可能就讀不到、或靜默用舊版。

   來源:acqua.Files idFile=4185 ・ 型別 FT_SMDUsedFile ・ 最後修改 2022-09-27 13:15:16

整批裡最短的一支(11 行)。

它在做什麼
    把分析圖的圖例改成顯示通道名稱。

    `with AnalysisDiagram() as d:` 是 HSL 提供的情境管理器,
    進去改圖、出來自動套用。要調圖表外觀都走這個。

在 ACQUA 裡怎麼找到它
    資料庫   51_MS_Teams_Rev05_SP2
    專案     MS Teams v5 Rev05 SP2 - Speakerphone
    測項樹   MS Teams v5 Rev05 SP2 - Speakerphone / V5_Personal Space and Shared Space Devices - Desk Phone, Speakerphone  / Primary requirements over E2E call / Speakerphone E2E call - Anechoic Room tests / P01A-P10A Send path tests - Speakerphone - Anechoic room / P05A-P07A Send path - Send noise and interference  / P05A-P07A Send path - send noise and interference - Personal Speakerphone
             └ Graph - noise spectrum P05A act.P06 Speech
               row_id 3705

    開啟上面那個專案 -> 在測項樹照路徑展開 -> 選到該測項
    -> 測項設定裡可以開啟並編輯這支腳本。

    共 11 個測項用到它。
    **改它會同時影響這些測項**,其他幾個例如:
      #3723   Graph - noise spectrum P05A act.P06 Speech
      #3741   Graph - noise spectrum P05A act.P06 Speech
      #3759   Graph - noise spectrum P05A act.P06 Speech
      ...另外 7 個

========================================================================
  以下是**原始程式碼**,一字未改。
========================================================================
"""
from HEAD import const
from HSL import AnalysisDiagram


def main():
    with AnalysisDiagram() as analysis_diagram:
        analysis_diagram.diag.SetGlobalLegendLayout(const.erepLegendChName)


if __name__ == "__main__":
    main()
