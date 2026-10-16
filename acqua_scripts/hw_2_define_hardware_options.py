"""
========================================================================
  define_hardware_options.py
  資料庫 51_MS_Teams_Rev05_SP2
========================================================================

⚠️ 這是從 ACQUA 資料庫解出來的**副本**,只是給你看的。
   改這裡不會影響 ACQUA。要真的改請用 ACQUA 自己的腳本編輯器 ——
   它會處理 ZIP 壓縮、FileSize、CRCValue、ChangeDate,
   少寫一個欄位 ACQUA 可能就讀不到、或靜默用舊版。

   來源:acqua.Files idFile=1336 ・ 型別 FT_SMDUsedFile ・ 最後修改 2022-08-25 12:31:10

問使用者有哪些硬體可用(轉盤 HRT I、旋轉反射板 HRR I),存成變數。

    這些變數再透過條件執行決定「沒有轉盤就跳過需要轉盤的測項」。

    是「硬體能力 -> 變數 -> 條件執行 -> 要跑哪些測項」這條鏈的起點,
    跟我們在 acqua/condeval.py 處理的那套條件式是同一件事的兩端。

在 ACQUA 裡怎麼找到它
    資料庫   51_MS_Teams_Rev05_SP2
    專案     MS Teams v5 Rev05 SP2 - Speakerphone
    測項樹   MS Teams v5 Rev05 SP2 - Speakerphone / V5_Personal Space and Shared Space Devices - Desk Phone, Speakerphone  / Information and preparation
             └ Hardware options
               row_id 1152

    開啟上面那個專案 -> 在測項樹照路徑展開 -> 選到該測項
    -> 測項設定裡可以開啟並編輯這支腳本。

    共 1 個測項用到它。

========================================================================
  以下是**原始程式碼**,一字未改。
========================================================================
"""
from HSL import run_universal_questionnaire_gui


def main():

    # define frames
    query_hardware_options = {'Frame Title': 'Enable database support for hardware options',
                              'VarNamePerCheckBox': ['HRT_available', 'HRR_available'],
                              'Options': ['HRT I - Turntable', 'HRR I - Rotating reflector (variable acoustic echo path)'],
                              'Tooltips': ['Select if HRT I turntable is available. If selected, corresponding SMDs will be enabled.',
                                           'Select if HRR I rotating reflector is available. If selected, corresponding SMDs will be enabled.'],
                              'CheckBoxesFlag': True,
                              'Orientation': 'V',
                              'Position': [0, 0]}

    run_universal_questionnaire_gui(query_hardware_options)


if __name__ == "__main__":
    main()
