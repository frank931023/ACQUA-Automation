"""
========================================================================
  3quest_add_clean_ref.py
  資料庫 51_MS_Teams_Rev05_SP2
========================================================================

⚠️ 這是從 ACQUA 資料庫解出來的**副本**,只是給你看的。
   改這裡不會影響 ACQUA。要真的改請用 ACQUA 自己的腳本編輯器 ——
   它會處理 ZIP 壓縮、FileSize、CRCValue、ChangeDate,
   少寫一個欄位 ACQUA 可能就讀不到、或靜默用舊版。

   來源:acqua.Files idFile=3515 ・ 型別 FT_SMDUsedFile ・ 最後修改 2022-08-08 08:56:16

準備 3QUEST 分析需要的乾淨參考訊號。16 個測項共用。

為什麼挑這支
    典型的「一支腳本服務很多測項」。改它之前要先知道會影響多少 ——
    下面的清單就是算這個的。

    同名檔案在 Handset / Headset / Speakerphone 各有獨立副本,
    改其中一份不影響其他。

在 ACQUA 裡怎麼找到它
    資料庫   51_MS_Teams_Rev05_SP2
    專案     MS Teams v5 Rev05 SP2 - Headset
    測項樹   MS Teams v5 Rev05 SP2 - Headset / MS Teams Rev.05 SP2 - Headset Devices / Primary Requirements over E2E call / Headset E2E call - Reverberant Room tests / P01R-P02R Send path tests - Send quality in the presence of ambient noise / Record 3QUEST - HAE-BGN
             └ O. Record 3QUEST TS103 - HAE-BGN - noBGN
               row_id 3071

    開啟上面那個專案 -> 在測項樹照路徑展開 -> 選到該測項
    -> 測項設定裡可以開啟並編輯這支腳本。

    共 16 個測項用到它。
    **改它會同時影響這些測項**,其他幾個例如:
      #3072   G. Record 3QUEST TS103 - HAE-BGN - Mensa
      #3073   H. Record 3QUEST TS103 - HAE-BGN - CallCenter
      #3074   I. Record 3QUEST TS103 - HAE-BGN - VoiceDistr
      ...另外 12 個

========================================================================
  以下是**原始程式碼**,一字未改。
========================================================================
"""
# -*- coding: utf-8 -*-
from HEAD import const
from pathlib import Path
from ACQUAlyzer import Smd, SubProject
from HSL import append_channels, rename_channels


def main():
    stored_time_file_path = Path(SubProject.Path) / Path(Smd.Values(770)).name
    source_file = Path(SubProject.Path) / Path(Smd.SourceFilename).name

    append_channels(file_path_base_sig=stored_time_file_path,
                    file_path_append_sig=source_file,
                    file_path_output_sig=stored_time_file_path,
                    appended_channels=[1])

    new_channel_names = {1: 'Proc', 2: 'Unproc', 3: 'Ref'}
    rename_channels(file_path_input=stored_time_file_path, channel_names=new_channel_names)


if __name__ == "__main__":
    main()
