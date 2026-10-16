"""
========================================================================
  save_p863_delay.py
  資料庫 51_MS_Teams_Rev05_SP2
========================================================================

⚠️ 這是從 ACQUA 資料庫解出來的**副本**,只是給你看的。
   改這裡不會影響 ACQUA。要真的改請用 ACQUA 自己的腳本編輯器 ——
   它會處理 ZIP 壓縮、FileSize、CRCValue、ChangeDate,
   少寫一個欄位 ACQUA 可能就讀不到、或靜默用舊版。

   來源:acqua.Files idFile=1402 ・ 型別 FT_SMDUsedFile ・ 最後修改 2022-08-08 16:07:12

存 P.863(POLQA)量到的延遲。20 個測項共用。

跟前兩支同樣的模式,但處理的是延遲值 —— 可以對照看「同一套寫法
怎麼套用到不同的量測項目」。

在 ACQUA 裡怎麼找到它
    資料庫   51_MS_Teams_Rev05_SP2
    專案     MS Teams v5 Rev05 SP2 - Speakerphone
    測項樹   MS Teams v5 Rev05 SP2 - Speakerphone / V5_Personal Space and Shared Space Devices - Desk Phone, Speakerphone  / Primary requirements over E2E call / Speakerphone E2E call - Anechoic Room tests / P01A-P10A Send path tests - Speakerphone - Anechoic room / P01A-P02A Send path - Average MOS-LQO and latency over E2E call
             └ Super Wideband MOS (P.863) SND - female run 1
               row_id 1194

    開啟上面那個專案 -> 在測項樹照路徑展開 -> 選到該測項
    -> 測項設定裡可以開啟並編輯這支腳本。

    共 20 個測項用到它。
    **改它會同時影響這些測項**,其他幾個例如:
      #1195   Super Wideband MOS (P.863) SND - male run 1
      #1196   Super Wideband MOS (P.863) SND - female run 2
      #1197   Super Wideband MOS (P.863) SND - male run 2
      ...另外 16 個

========================================================================
  以下是**原始程式碼**,一字未改。
========================================================================
"""
# -*- coding: utf-8 -*-
from HEAD import const
from ACQUAlyzer import Smd, SingleValues
from HSL import save_var


def main():
    srvs = SingleValues.GetSingleValuesForRun(1)
    for i in range(srvs.Count):
        srv = srvs.GetItem(i)
        if srv.Title == "Avg. Delay":
            stored_result_value_str = Smd.Values(704)
            var_name_base = stored_result_value_str.replace("PMOS", "DELAY")
            var_name = f'{var_name_base}'
            save_var(var_name, srv.Value, const.evsMeasured, var_unit=srv.PhysUnit, var_description='Delay', var_comment=Smd.Title)
            break


if __name__ == "__main__":
    main()
