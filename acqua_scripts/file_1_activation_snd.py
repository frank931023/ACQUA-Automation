"""
========================================================================
  activation_snd.py
  資料庫 ACQUA_auto_v2026Aug
========================================================================

⚠️ 這是從 ACQUA 資料庫解出來的**副本**,只是給你看的。
   改這裡不會影響 ACQUA。要真的改請用 ACQUA 自己的腳本編輯器 ——
   它會處理 ZIP 壓縮、FileSize、CRCValue、ChangeDate,
   少寫一個欄位 ACQUA 可能就讀不到、或靜默用舊版。

   來源:acqua.Files idFile=61719 ・ 型別 FT_SMDUsedFile ・ 最後修改 2022-08-30 10:03:07

它在做什麼
    把預錄的 .dat 複製一份,註冊成這次量測的結果檔。

兩個重點
    1) `Smd.Path` 是 ACQUA 的檔案快取目錄,腳本讀寫檔案都走這裡:
           C:\ACQUA_Files\File_Cache\<專案名>_<GUID>\

    2) **怎麼讓單一測項失敗**:
           Smd.Cancel = True
           Smd.CancelMsg = "File not found!"
       跟掛鉤用 `raise` 不一樣 —— 這裡是「這一筆失敗」,不是「整批擋下」。

    `ResultFiles.AddFile(路徑, 型別, 通道)` 把檔案掛進結果,
    之後的分析測項才看得到。

在 ACQUA 裡怎麼找到它
    資料庫   ACQUA_auto_v2026Aug
    專案     ZoomRooms_v2020Oct_v1
    測項樹   ZoomRooms_v2020Oct_v1 / COS_auto_Sentinal / Basic Test_using Mouth only / P09A Send path - Activation level _1.5m_away
             └ Send path - activation sensitivity - REC. unfiltered
               row_id 1835

    開啟上面那個專案 -> 在測項樹照路徑展開 -> 選到該測項
    -> 測項設定裡可以開啟並編輯這支腳本。

    共 6 個測項用到它。
    **改它會同時影響這些測項**,其他幾個例如:
      #4075   Send path - activation sensitivity - REC. unfiltered
      #5173   Send path - activation sensitivity - REC. unfiltered
      #6048   Send path - activation sensitivity - REC. unfiltered
      ...另外 2 個

========================================================================
  以下是**原始程式碼**,一字未改。
========================================================================
"""
import pythoncom
from HEAD import const
from pathlib import Path
from ACQUAlyzer import Smd, ResultFiles
import shutil


def main():
    input_init_file_name = "SND_activation_fives.dat"
    input_init_file_path = Path(Smd.Path) / input_init_file_name
    output_init_file_path = Path(Smd.Path) / "SND_activation_fives_unfiltered.dat"
    # if dummy file exists in file cache, make a copy of the file
    if input_init_file_path.is_file():
        shutil.copyfile(input_init_file_path, output_init_file_path)
        ResultFiles.AddFile(output_init_file_path, const.erftNamedTimeSignal, 1)
    else:
        Smd.Cancel = True
        Smd.CancelMsg = "File '{}' not found!".format(input_init_file_name)


if __name__ == "__main__":
    main()