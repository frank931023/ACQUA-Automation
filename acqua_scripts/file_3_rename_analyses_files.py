"""
========================================================================
  rename_analyses_files_channels.py
  資料庫 51_MS_Teams_Rev05_SP2
========================================================================

⚠️ 這是從 ACQUA 資料庫解出來的**副本**,只是給你看的。
   改這裡不會影響 ACQUA。要真的改請用 ACQUA 自己的腳本編輯器 ——
   它會處理 ZIP 壓縮、FileSize、CRCValue、ChangeDate,
   少寫一個欄位 ACQUA 可能就讀不到、或靜默用舊版。

   來源:acqua.Files idFile=1470 ・ 型別 FT_SMDUsedFile ・ 最後修改 2022-11-17 10:04:39

把分析產生的檔案與通道重新命名。11 個測項共用。

比前面幾支長(約 80 行),示範了比較完整的檔案處理流程 ——
想看「正式一點的腳本長什麼樣」就看這支。

在 ACQUA 裡怎麼找到它
    資料庫   51_MS_Teams_Rev05_SP2
    專案     MS Teams v5 Rev05 SP2 - Speakerphone
    測項樹   MS Teams v5 Rev05 SP2 - Speakerphone / V5_Personal Space and Shared Space Devices - Desk Phone, Speakerphone  / Primary requirements over E2E call / Speakerphone E2E call - Anechoic Room tests / P01A-P10A Send path tests - Speakerphone - Anechoic room / P05A-P07A Send path - Send noise and interference  / P05A-P07A Send path - send noise and interference - Personal Speakerphone
             └ Graph - noise spectrum P05A act.P06 Speech
               row_id 1264

    開啟上面那個專案 -> 在測項樹照路徑展開 -> 選到該測項
    -> 測項設定裡可以開啟並編輯這支腳本。

    共 11 個測項用到它。
    **改它會同時影響這些測項**,其他幾個例如:
      #1282   Graph - noise spectrum P05A act.P06 Speech
      #1300   Graph - noise spectrum P05A act.P06 Speech
      #1318   Graph - noise spectrum P05A act.P06 Speech
      ...另外 7 個

========================================================================
  以下是**原始程式碼**,一字未改。
========================================================================
"""
from HEAD import Dispatch, const
from pathlib import Path
from ACQUAlyzer import Smd, ResultFiles
from HSL import save_var


def rename_channel(file_path, channel_nr, new_name=None, new_abbr=None, backup_orig_name_to_var=None, backup_orig_abbr_to_var=None):
    if new_name or new_abbr:
        dataset_factory = Dispatch("HEADDataset.DatasetFactory")
        outfile = dataset_factory.Open(file_path, 3)[0]
        if new_name:
            if backup_orig_name_to_var:
                old_name = outfile.Channels(channel_nr).Name
                save_var(backup_orig_name_to_var, old_name, const.evsUserDefined, var_description='temporary variable', var_comment=Smd.Title)
            outfile.Channels(channel_nr).Name = new_name
        if new_abbr:
            if backup_orig_abbr_to_var:
                old_abbr = outfile.Channels(channel_nr).Abbreviation
                save_var(backup_orig_abbr_to_var, old_abbr, const.evsUserDefined, var_description='temporary variable', var_comment=Smd.Title)
            outfile.Channels(channel_nr).Abbreviation = new_abbr


def main():
    for i in range(30):
        if Path(Smd.Values(62+i)).name not in [".fft", ".hdf"]:
            file_name = Path(Smd.Values(62+i)).name
            file_path = Path(Smd.Path) / file_name
            file_stem = str(file_path.stem)
            backup_old_name_to_var = None
            backup_old_abbr_to_var = None
            if file_stem.startswith("snd_stab"):
                new_ch_name = f"SND Freq. resp. position {i+1}"
                new_ch_abbr = f"SND Pos{i+1}"
                if i == 0:
                    backup_old_name_to_var = "BAK_old_snd_ch_name"
                    backup_old_abbr_to_var = "BAK_old_snd_ch_abbr"
            elif file_stem.startswith("rcv_stab"):
                new_ch_name = f"RCV Freq. resp. position {i+1}"
                new_ch_abbr = f"RCV Pos{i+1}"
                if i == 0:
                    backup_old_name_to_var = "BAK_old_rcv_ch_name"
                    backup_old_abbr_to_var = "BAK_old_rcv_ch_abbr"
            elif file_stem.startswith("speech"):
                name_base = file_stem.replace("_", " ")
                new_ch_name = f"{name_base} dBSPL"
                new_ch_abbr = f"{name_base[:2]} {name_base[-2:]}"
            elif file_stem.startswith("noise"):
                name_base = file_stem.replace("_", " ")
                new_ch_name = f"{name_base} dBSPL"
                new_ch_abbr = f"{name_base[:3]} {name_base[-2:]}"
            else:
                name_base = file_stem.replace("_", " ")
                new_ch_name = f"{name_base}"
                new_ch_abbr = None

            rename_channel(file_path, 1, new_ch_name, new_ch_abbr, backup_orig_name_to_var=backup_old_name_to_var, backup_orig_abbr_to_var=backup_old_abbr_to_var)
            ResultFiles.AddFile(file_path, const.erftNamedAnalysis, 0)


if __name__ == "__main__":
    main()
