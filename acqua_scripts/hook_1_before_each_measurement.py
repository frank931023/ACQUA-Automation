"""
========================================================================
  before_each_measurement.py
  資料庫 51_MS_Teams_Rev05_SP2
========================================================================

⚠️ 這是從 ACQUA 資料庫解出來的**副本**,只是給你看的。
   改這裡不會影響 ACQUA。要真的改請用 ACQUA 自己的腳本編輯器 ——
   它會處理 ZIP 壓縮、FileSize、CRCValue、ChangeDate,
   少寫一個欄位 ACQUA 可能就讀不到、或靜默用舊版。

   來源:acqua.Files idFile=2718 ・ 型別 FT_Script ・ 最後修改 2022-11-02 15:54:21

每一筆量測**開始前**自動執行。不掛在任何測項上。

它在做什麼
    量測前的前置檢查。重點在它用 `raise Exception(...)` 來**擋下這一筆**
    —— 丟出例外,ACQUA 就不開始量測,並把訊息顯示給操作者。

    現在檢查兩件事:DUT 名稱有沒有包含 Windows 不允許的檔名字元、
    該測項的「Store time signal」有沒有開。

為什麼這支對我們的自動化特別重要
    這是**唯一能在量測真正開始前擋下來的地方**,而且跑在 ACQUA 內部,
    比我們的 /api/run 更靠近現場。

    我們一直缺的那道檢查(麥克風極化電壓設錯會靜默產生廢資料)
    就可以放這裡 —— 現有程式碼已經示範了怎麼擋。

在 ACQUA 裡怎麼找到它
    資料庫   51_MS_Teams_Rev05_SP2
    專案     MS Teams v5 Rev05 SP2 - Handset

    這是**專案層級的掛鉤**,不掛在任何測項上,測項樹裡找不到。
    開啟上面那個專案 -> 專案層級的設定 / 腳本那一區,
    before / after / canceled / OnProjectOpen 都在那裡。

    執行時的副本在:
      C:\ACQUA_Files\File_Cache\51_MS_Teams_Rev05_SP2_<GUID>\before_each_measurement.py

========================================================================
  以下是**原始程式碼**,一字未改。
========================================================================
"""
from pathlib import Path
from HSL import get_tag_values, get_var_value, set_d_script, BGNConfigurator
from ACQUAlyzer import Tags, Smd, SubProject, MeasObject


def precheck_reqs_for_wav_export(tag_export_wav):
    """Check in advance if requirements for .wav file export are fulfilled"""
    # 1. Measurement object title must be valid (i.e. forbid \/:*?"<>| characters)
    list_of_forbidden_characters = '\\/:*?\"<>|'
    meas_obj_title = MeasObject.Title
    smd_title = Smd.Title
    for forbidden_char in list_of_forbidden_characters:
        if forbidden_char in meas_obj_title:
            raise Exception(f"Invalid Measurement Object name '{meas_obj_title}', caused by the use of at least one forbidden character. Rename the measurement object by avoiding the use of forbidden characters:\n{' '.join(list_of_forbidden_characters)}")
    # 2. SMD store time signal must be enabled. The stored signal name is used as part of the exported file's title,
    # therefore the name shall not contain any of the forbidden characters \/:*?"<>|.
    if Path(Smd.Values(770)).name == '.dat':
        raise Exception(f"SMD option 'Store time signal' is disabled for SMD '{smd_title}'!\n\nThe 'Store time signal' "
                        f"option must be enabled in the SMD's special features for successful export of .wav file.\n\n"
                        f"NOTE: If .wav export of recording is not desired, the SMD tag '{tag_export_wav}' should be "
                        f"removed from the SMD to disable the .wav export functionality.")
    stored_time_signal_file_path = Path(SubProject.Path) / Path(Smd.Values(770)).name
    stored_time_signal_file_name = stored_time_signal_file_path.name
    for forbidden_char in list_of_forbidden_characters:
        if forbidden_char in stored_time_signal_file_path.name:
            raise Exception(f"Invalid stored time file name '{stored_time_signal_file_name}', caused by the use of at least one forbidden character. Rename the stored time file in the SMD's special features by avoiding the use of forbidden characters:\n{' '.join(list_of_forbidden_characters)}")
    # 3. Destination folder (m.o. variable) must exist, and destination directory must be a valid/accessible path
    destination_folder = get_var_value('WAV_export_folder_path', var_type=str, add_error_sentence="Please execute script SMD 'Automatic export of recordings in .wav format' to define a destination folder!")
    stored_time_signal_stem = stored_time_signal_file_path.stem
    dummy_destination_file_path = Path(destination_folder) / f"{meas_obj_title}_{stored_time_signal_stem}_XX.wav"  # build dummy export file path to get the resulting de facto destination directory path
    destination_directory_path = dummy_destination_file_path.parent
    try:
        destination_directory_path_is_dir = destination_directory_path.is_dir()
    except PermissionError as e:
        raise PermissionError(f"Destination folder cannot be accessed! Export of .wav file will not be possible!\n{e}")
    else:
        if not destination_directory_path_is_dir:
            raise Exception(f"Destination folder '{destination_directory_path}' is not a valid directory! Export of .wav file will not be possible!")
    # 4. Overwrite flag must exist (m.o. variable)
    wav_export_file_overwrite_var_name = 'WAV_export_file_overwrite'
    allow_wav_export_file_overwrite = get_var_value(wav_export_file_overwrite_var_name, var_type=bool, add_error_sentence="Please execute script SMD 'Automatic export of recordings in .wav format' in order to define all necessary variables! This step is mandatory!")
    # 5. SMD tag 'Export to .wav' must have a valid value for successful export
    export_wav_channels = get_tag_values(tag_export_wav)
    valid_tag_values = ['Channel 1', 'Channel 2', 'Both channels', 'Channel 1, Channel 2']
    if export_wav_channels not in valid_tag_values:
        raise ValueError(f"SMD tag '{tag_export_wav}' exists but its value is not appropriate!\n\nIf .wav export of "
                         f"recording is desired, the SMD tag '{tag_export_wav}' must be set to one of the valid values "
                         f"('Channel 1', 'Channel 2', 'Channel 1, Channel 2', or 'Both channels').\n\nOtherwise, if "
                         f".wav export of recording is not desired, the SMD tag '{tag_export_wav}' should be removed "
                         f"from the SMD to disable the .wav export functionality.")
    return stored_time_signal_file_path, destination_directory_path, allow_wav_export_file_overwrite, export_wav_channels


def main():
    smd_mode = Smd.Values(768)  # 0:Do measurement/none,  1:Analyse existing file
    smd_type = Smd.SMDType
    smd_type_black_list = ["Analysis file operations", "Calculate Single Value", "MLS", "Play file"]
    if smd_mode == 0 and smd_type not in smd_type_black_list:

        # Pre-check requirements for .wav file export of recorded time signal, in order to throw exceptions BEFORE meas.
        meas_obj_title = MeasObject.Title
        smd_title = Smd.Title
        if meas_obj_title == '':
            # if SMD is executed in 'Test mode', M.O. title returns an empty string. In case of test mode, file export
            # will be skipped silently, print message in ACQUAlyzer results window.
            print(f"\nSMD '{smd_title}' will be executed in test mode, export of .wav file will be skipped!")
        else:
            wav_export_var_name = 'WAV_export'
            wav_export = get_var_value(wav_export_var_name, var_type=bool, add_error_sentence="Please execute script SMD 'Automatic export of recordings in .wav format' in order to enable/disable the export of recordings! This step is mandatory!")
            if wav_export:
                smd_tag_export_to_wav = 'Export to .wav'
                if Tags.Exists(smd_tag_export_to_wav):  # SMD tag 'Export to .wav' exists, .wav file export is enabled for SMD
                    precheck_reqs_for_wav_export(smd_tag_export_to_wav)

        # set D_SCRIPT
        set_d_script(tagname_usecase="UseCase", tagname_bandwidth="Bandwidth", tagname_direction="Direction")

        # configure BGN
        if Tags.Exists("BGN_Markname"):
            bgn_control = get_var_value(var_name='BGNControl', var_type=str,
                                        add_error_sentence="Please execute script SMD 'BGN Wizard'!")
            if bgn_control == 'Automatic':
                bgn_markname = get_tag_values("BGN_Markname")
                bgn_loops = 0
                if Tags.Exists("BGN_Loops"):
                    bgn_loops = get_tag_values("BGN_Loops")
                bgn_gain = 0
                if Tags.Exists("BGN_Gain"):
                    bgn_gain = get_tag_values("BGN_Gain")
                bgn_config = BGNConfigurator()
                bgn_config.set_up_bgn(bgn_scenario=bgn_markname, loops=bgn_loops, gain=bgn_gain)
                bgn_config.start_bgn(trigger=True)


if __name__ == "__main__":
    main()
