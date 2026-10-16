"""
========================================================================
  equest_save_echo_level.py
  資料庫 51_MS_Teams_Rev05_SP2
========================================================================

⚠️ 這是從 ACQUA 資料庫解出來的**副本**,只是給你看的。
   改這裡不會影響 ACQUA。要真的改請用 ACQUA 自己的腳本編輯器 ——
   它會處理 ZIP 壓縮、FileSize、CRCValue、ChangeDate,
   少寫一個欄位 ACQUA 可能就讀不到、或靜默用舊版。

   來源:acqua.Files idFile=1790 ・ 型別 FT_SMDUsedFile ・ 最後修改 2022-07-18 12:25:28

**SP2 裡被用最多次的腳本:72 個測項共用。**

它在做什麼
    從結果裡挑出「Echo Level」存成變數。

兩個新東西
    `SingleValues.GetSingleValuesForRun(1)` —— 取某一輪的單值結果
    `Smd.Values(704)` —— 讀測項自己的設定欄位(704 是欄位編號)。
    這種數字編號在 ACQUA 文件裡查得到,程式裡看不出意思,要小心。

在 ACQUA 裡怎麼找到它
    資料庫   51_MS_Teams_Rev05_SP2
    專案     MS Teams v5 Rev05 SP2 - Speakerphone
    測項樹   MS Teams v5 Rev05 SP2 - Speakerphone / V5_Personal Space and Shared Space Devices - Desk Phone, Speakerphone  / Primary requirements over E2E call / Speakerphone E2E call - Anechoic Room tests / P20A-P26A Echo path tests - Speakerphone - Anechoic room / P20A-P23A Echo path tests - Speakerphone - Anechoic room - Nominal volume / P21A Echo Path - EQUEST WB MOS - nominal  volume
             └ Echo path - P21A  EQUEST nomvol  (male)  1/6
               row_id 1517

    開啟上面那個專案 -> 在測項樹照路徑展開 -> 選到該測項
    -> 測項設定裡可以開啟並編輯這支腳本。

    共 72 個測項用到它。
    **改它會同時影響這些測項**,其他幾個例如:
      #1518   Echo path - P21A  EQUEST nomvol (female) 2/6
      #1519   Echo path - P21A  EQUEST nomvol  (male) 3/6
      #1520   Echo path - P21A  EQUEST nomvol  (male) 4/6
      ...另外 68 個

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
        if srv.Title == "Echo Level":
            stored_result_value_str = Smd.Values(704)
            var_name_base = stored_result_value_str.replace("EMOS", "ELEV")
            var_name = f'{var_name_base}'
            save_var(var_name, srv.Value, const.evsMeasured, var_unit=srv.PhysUnit, var_description='Level', var_comment=Smd.Title)


if __name__ == "__main__":
    main()
