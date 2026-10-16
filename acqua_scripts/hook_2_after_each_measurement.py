"""
========================================================================
  after_each_measurement.py
  資料庫 51_MS_Teams_Rev05_SP2
========================================================================

⚠️ 這是從 ACQUA 資料庫解出來的**副本**,只是給你看的。
   改這裡不會影響 ACQUA。要真的改請用 ACQUA 自己的腳本編輯器 ——
   它會處理 ZIP 壓縮、FileSize、CRCValue、ChangeDate,
   少寫一個欄位 ACQUA 可能就讀不到、或靜默用舊版。

   來源:acqua.Files idFile=444 ・ 型別 FT_Script ・ 最後修改 2022-11-03 10:53:22

每一筆量測**結束後**自動執行。

它在做什麼
    把錄到的訊號匯出成 .wav。

值得學的手法:用標籤當開關
        if Tags.Exists('Export to .wav'):
            ...
    要讓某些測項有特殊行為,在 ACQUA 裡給它加標籤,掛鉤讀標籤決定做什麼
    —— 不用改程式碼就能逐項控制。

在 ACQUA 裡怎麼找到它
    資料庫   51_MS_Teams_Rev05_SP2
    專案     MS Teams v5 Rev05 SP2 - Headset

    這是**專案層級的掛鉤**,不掛在任何測項上,測項樹裡找不到。
    開啟上面那個專案 -> 專案層級的設定 / 腳本那一區,
    before / after / canceled / OnProjectOpen 都在那裡。

    執行時的副本在:
      C:\ACQUA_Files\File_Cache\51_MS_Teams_Rev05_SP2_<GUID>\after_each_measurement.py

========================================================================
  以下是**原始程式碼**,一字未改。
========================================================================
"""
import pythoncom
from HEAD import const
from HEAD.HdfIO.Convert import HDF2Wave32Bit, HDF2Wave
from win32com.client import CastTo
from pathlib import Path
from ACQUAlyzer import Smd, Tags, SubProject, MeasObject
from HSL import BGNConfigurator, get_var_value, get_tag_values, LabCore, \
                get_absolute_min_vol_step_usb_driver, get_absolute_max_vol_step_usb_driver, \
                get_absolute_min_vol_step_bt, get_absolute_max_vol_step_bt


def auto_export_wav_file():
    """User defined control for .wav export per SMD: If SMD tag 'Export to .wav' exists, .wav export is enabled for SMD,
    otherwise export is disabled"""
    smd_tag_export_to_wav = 'Export to .wav'
    if Tags.Exists(smd_tag_export_to_wav):  # SMD tag 'Export to .wav' exists, .wav file export is enabled for SMD
        stored_time_signal_file_path, destination_directory_path, allow_wav_export_file_overwrite, export_wav_channels = _check_reqs_for_wav_export_return_source_and_destination_paths(smd_tag_export_to_wav)
        _save_wav_file(stored_time_signal_file_path, destination_directory_path, allow_wav_export_file_overwrite, export_wav_channels)


def _check_reqs_for_wav_export_return_source_and_destination_paths(tag_export_wav):
    """Check if requirements for .wav file export are fulfilled"""
    # 1. Measurement object title must be valid (i.e. forbid /\:*?"<>| characters)
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
    stored_time_signal_stem = stored_time_signal_file_path.stem  # build dummy export file to get the resulting de facto destination directory path
    test_destination_file_path = Path(destination_folder) / f"{meas_obj_title}_{stored_time_signal_stem}_XX.wav"
    destination_directory_path = test_destination_file_path.parent
    try:
        destination_directory_path_is_dir = destination_directory_path.is_dir()
    except PermissionError as e:
        raise PermissionError(f"Destination folder cannot be accessed! Export of .wav file is not possible!\n{e}")
    else:
        if not destination_directory_path_is_dir:
            raise Exception(f"Destination folder '{destination_directory_path}' is not a valid directory! Export of .wav file is not possible!")
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


def _save_wav_file(stored_time_signal_file_path, destination_directory_path, allow_wav_export_file_overwrite, export_wav_channels):
    direction = get_tag_values("Direction").upper()
    snd_user_def_scaling_peak_range = 1.57223
    stored_time_signal_stem = stored_time_signal_file_path.stem

    if export_wav_channels == 'Channel 1':
        if '3quest' in stored_time_signal_stem:
            destination_file_name = f'{MeasObject.Title}_{stored_time_signal_stem}_Proc.wav'
        elif 'double_talk' in stored_time_signal_stem:
            destination_file_name = f'{MeasObject.Title}_{stored_time_signal_stem}_ST.wav'
        else:
            destination_file_name = f'{MeasObject.Title}_{stored_time_signal_stem}_Ch1.wav'
        destination_file_path = destination_directory_path / Path(destination_file_name)

        if not allow_wav_export_file_overwrite:
            # check if file already exist in destination path, and if yes add incrementing index
            destination_file_path_stem_base = destination_file_path.stem
            i = 0
            while destination_file_path.exists():
                i += 1
                new_destination_file_name = f'{destination_file_path_stem_base}_{i}.wav'
                destination_file_path = destination_directory_path / Path(new_destination_file_name)

        channel_to_export = '1'  # channel 1
        if direction in ["SND", "ECHO"]:
            HDF2Wave(stored_time_signal_file_path, destination_file_path, ExportChannelList=channel_to_export, IEEE_FLOAT_Format=False, Resolution24Bit=False, ScalingMode=const.eh2wscmUser, PeakRange=snd_user_def_scaling_peak_range)
        elif direction in ["RCV", "SIDE"]:
            HDF2Wave32Bit(stored_time_signal_file_path, destination_file_path, ExportChannelList=channel_to_export)
        print(f'\nPath of exported .wav file: {destination_file_path}')

    elif export_wav_channels == 'Channel 2':
        if '3quest' in stored_time_signal_stem:
            destination_file_name = f'{MeasObject.Title}_{stored_time_signal_stem}_Unproc.wav'
        elif 'double_talk' in stored_time_signal_stem:
            destination_file_name = f'{MeasObject.Title}_{stored_time_signal_stem}_DT.wav'
        else:
            destination_file_name = f'{MeasObject.Title}_{stored_time_signal_stem}_Ch2.wav'
        destination_file_path = destination_directory_path / Path(destination_file_name)

        if not allow_wav_export_file_overwrite:
            # check if file already exist in destination path, and if yes add incrementing index
            destination_file_path_stem_base = destination_file_path.stem
            i = 0
            while destination_file_path.exists():
                i += 1
                new_destination_file_name = f'{destination_file_path_stem_base}_{i}.wav'
                destination_file_path = destination_directory_path / Path(new_destination_file_name)

        channel_to_export = '2'  # channel 2
        if direction in ["SND", "ECHO"]:
            HDF2Wave(stored_time_signal_file_path, destination_file_path, ExportChannelList=channel_to_export, IEEE_FLOAT_Format=False, Resolution24Bit=False, ScalingMode=const.eh2wscmUser, PeakRange=snd_user_def_scaling_peak_range)
        elif direction in ["RCV", "SIDE"]:
            HDF2Wave32Bit(stored_time_signal_file_path, destination_file_path, ExportChannelList=channel_to_export)
        print(f'\nPath of exported .wav file: {destination_file_path}')

    elif export_wav_channels == 'Both channels':
        # export 1 stereo wav file
        destination_file_name = f'{MeasObject.Title}_{stored_time_signal_stem}.wav'
        destination_file_path = destination_directory_path / Path(destination_file_name)

        if not allow_wav_export_file_overwrite:
            # check if file already exist in destination path, and if yes add incrementing index
            destination_file_path_stem_base = destination_file_path.stem
            i = 0
            while destination_file_path.exists():
                i += 1
                new_destination_file_name = f'{destination_file_path_stem_base}_{i}.wav'
                destination_file_path = destination_directory_path / Path(new_destination_file_name)

        channel_to_export = '1, 2'
        if direction in ["SND", "ECHO"]:
            HDF2Wave(stored_time_signal_file_path, destination_file_path, ExportChannelList=channel_to_export, IEEE_FLOAT_Format=False, Resolution24Bit=False, ScalingMode=const.eh2wscmUser, PeakRange=snd_user_def_scaling_peak_range)
        elif direction in ["RCV", "SIDE"]:
            HDF2Wave32Bit(stored_time_signal_file_path, destination_file_path, ExportChannelList=channel_to_export)
        print(f'\nPath of exported .wav file: {destination_file_path}')

    elif export_wav_channels == 'Channel 1, Channel 2':
        # export 2 separate mono .wav files
        if '3quest' in stored_time_signal_stem:
            destination_file_name_1 = f'{MeasObject.Title}_{stored_time_signal_stem}_Proc.wav'
            destination_file_name_2 = f'{MeasObject.Title}_{stored_time_signal_stem}_Unproc.wav'
        elif 'double_talk' in stored_time_signal_stem:
            destination_file_name_1 = f'{MeasObject.Title}_{stored_time_signal_stem}_ST.wav'
            destination_file_name_2 = f'{MeasObject.Title}_{stored_time_signal_stem}_DT.wav'
        else:
            destination_file_name_1 = f'{MeasObject.Title}_{stored_time_signal_stem}_Ch1.wav'
            destination_file_name_2 = f'{MeasObject.Title}_{stored_time_signal_stem}_Ch2.wav'

        destination_file_path_1 = destination_directory_path / Path(destination_file_name_1)
        if not allow_wav_export_file_overwrite:
            # check if file already exist in destination path, and if yes add incrementing index
            destination_file_1_path_stem_base = destination_file_path_1.stem
            i = 0
            while destination_file_path_1.exists():
                i += 1
                new_destination_file_name = f'{destination_file_1_path_stem_base}_{i}.wav'
                destination_file_path_1 = destination_directory_path / Path(new_destination_file_name)
        channel_to_export = '1'  # channel 1
        if direction in ["SND", "ECHO"]:
            HDF2Wave(stored_time_signal_file_path, destination_file_path_1, ExportChannelList=channel_to_export, IEEE_FLOAT_Format=False, Resolution24Bit=False, ScalingMode=const.eh2wscmUser, PeakRange=snd_user_def_scaling_peak_range)
        elif direction in ["RCV", "SIDE"]:
            HDF2Wave32Bit(stored_time_signal_file_path, destination_file_path_1, ExportChannelList=channel_to_export)
        print(f'\nPath of exported .wav file 1: {destination_file_path_1}')

        destination_file_path_2 = destination_directory_path / Path(destination_file_name_2)
        if not allow_wav_export_file_overwrite:
            # check if file already exist in destination path, and if yes add incrementing index
            destination_file_2_path_stem_base = destination_file_path_2.stem
            i = 0
            while destination_file_path_2.exists():
                i += 1
                new_destination_file_name = f'{destination_file_2_path_stem_base}_{i}.wav'
                destination_file_path_2 = destination_directory_path / Path(new_destination_file_name)
        channel_to_export = '2'  # channel 2
        if direction in ["SND", "ECHO"]:
            HDF2Wave(stored_time_signal_file_path, destination_file_path_2, ExportChannelList=channel_to_export, IEEE_FLOAT_Format=False, Resolution24Bit=False, ScalingMode=const.eh2wscmUser, PeakRange=snd_user_def_scaling_peak_range)
        elif direction in ["RCV", "SIDE"]:
            HDF2Wave32Bit(stored_time_signal_file_path, destination_file_path_2, ExportChannelList=channel_to_export)
        print(f'\nPath of exported .wav file 2: {destination_file_path_2}')
    else:  # export_wav_channels value has been checked, so this should never happen
        pass


def delete_connection_gains_aes_bt(corebt_type):
    lc_audio_wiring = LabCore().selected_labcore.AudioWiring
    if corebt_type == 'coreBT2':
        selected_bt_block = lc_audio_wiring.Blocks.FirstBlockByType(const.eBlockTypeBluetooth2)
    else:
        selected_bt_block = lc_audio_wiring.Blocks.FirstBlockByType(const.eBlockTypeBluetooth)
    bt_block_active_connections = lc_audio_wiring.ActiveConnectionsOfBlock(selected_bt_block)
    for conn_idx in range(bt_block_active_connections.Count):
        if bt_block_active_connections.Items(conn_idx).Pin1.Block.Name == selected_bt_block.Name and bt_block_active_connections.Items(conn_idx).Pin2.Block.Name.startswith('AES'):
            CastTo(bt_block_active_connections.Items(conn_idx), "ILabCoreAudioConnection").GaindB = 0
        elif bt_block_active_connections.Items(conn_idx).Pin2.Block.Name == selected_bt_block.Name and bt_block_active_connections.Items(conn_idx).Pin1.Block.Name.startswith('AES'):
            CastTo(bt_block_active_connections.Items(conn_idx), "ILabCoreAudioConnection").GaindB = 0
        else:
            pass


def main():
    smd_mode = Smd.Values(768)  # 0:Do measurement/none,  1:Analyse existing file
    smd_type = Smd.SMDType
    smd_type_black_list = ["Analysis file operations", "Calculate Single Value", "MLS", "Play file"]
    if smd_mode == 0 and smd_type not in smd_type_black_list:

        # restore HW configuration for AES-BT connection
        usecase = get_tag_values('UseCase')
        if usecase == 'E2E':
            connection_type_var_name = 'DUT_connection_type'
            connection_type = get_var_value(var_name=connection_type_var_name, var_type=str, add_error_sentence="Please execute script SMD 'DUT & Measurement Wizard'!")
            if connection_type == 'Bluetooth':
                core_bt_type_var_name = 'DUT_labcore_bt_type'
                corebt_type = get_var_value(var_name=core_bt_type_var_name, var_type=str, add_error_sentence="Please execute script SMD 'DUT & Measurement Wizard'!")
                if corebt_type not in ['coreBT', 'coreBT2']:
                    raise Exception(f"Variable '{core_bt_type_var_name}' must be 'coreBT' or 'coreBT2', but is "
                                    f"'{corebt_type}' instead! Please execute script SMD 'DUT & Measurement "
                                    f"Wizard'.")
                delete_connection_gains_aes_bt(corebt_type)

        # Stop BGN playback
        if Tags.Exists('BGN_Markname'):
            bgn_control = get_var_value('BGNControl')
            if bgn_control == 'Automatic':
                BGNConfigurator().stop_bgn()

        # Document used playback vol ctrl for device direct connection
        usecase = get_tag_values('UseCase')
        volume_tag_name = 'Volume'
        if usecase == 'DI' and Tags.Exists(volume_tag_name):
            vol_ctrl_var_name = 'VOL_control'
            volume_control = get_var_value(vol_ctrl_var_name, add_error_sentence="Please execute script SMD 'Select automatic/manual volume control'!")
            if volume_control == 'Automatic':
                # read required values from SMD tags and m.o. variables
                volume_tag_value = get_tag_values(volume_tag_name)
                connection_type_var_name = 'DUT_connection_type'
                connection_type = get_var_value(var_name=connection_type_var_name, var_type=str, add_error_sentence="Please execute script SMD 'DUT & Measurement Wizard'!")
                # set volume for USB or USB dongle DUT
                if connection_type in ['USB', 'USB dongle']:
                    if volume_tag_value == 'MIN':
                        Smd.ResultComment = f'@ MIN (0%)'
                    elif volume_tag_value == 'MAX':
                        Smd.ResultComment = f'@ MAX (100%)'
                    elif volume_tag_value == 'NOM':
                        usb_playback_controller_idx = get_var_value(var_name='VOL_usb_playback_controller_idx', add_error_sentence="Please execute script SMD 'Select automatic/manual volume control'!")
                        min_vol_step_usb_driver = get_absolute_min_vol_step_usb_driver(usb_playback_controller_idx)
                        max_vol_step_usb_driver = get_absolute_max_vol_step_usb_driver(usb_playback_controller_idx)
                        total_vol_step_range = max_vol_step_usb_driver - min_vol_step_usb_driver
                        nom_vol_step = get_var_value(f'VOL_nom_step_{connection_type}_{usecase}', var_type=int, add_error_sentence="Please execute script SMD 'Select nominal DUT playback volume'!")
                        # convert step to manually configurable percentile
                        nom_vol_percent = round(100 * (nom_vol_step / total_vol_step_range))
                        Smd.ResultComment = f'@ NOM ({nom_vol_percent}%)'
                    else:
                        raise Exception(f"Value of SMD Tag '{volume_tag_name}' must be either 'MIN', 'MAX' or 'NOM', "
                                        f"but is '{volume_tag_value}' instead! Check SMD tag!")

                elif connection_type == 'Bluetooth':
                    core_bt_type_var_name = 'DUT_labcore_bt_type'
                    corebt_type = get_var_value(var_name=core_bt_type_var_name, var_type=str, add_error_sentence="Please execute script SMD 'DUT & Measurement Wizard'!")
                    if corebt_type not in ['coreBT', 'coreBT2']:
                        raise Exception(f"Variable '{core_bt_type_var_name}' must be 'coreBT' or 'coreBT2', but is "
                                        f"'{corebt_type}' instead! Please execute script SMD 'DUT & Measurement "
                                        f"Wizard'.")
                    if corebt_type == 'coreBT':
                        max_vol_step_bt = get_absolute_max_vol_step_bt(force_corebt=True)
                    else:
                        max_vol_step_bt = get_absolute_max_vol_step_bt()
                    min_vol_step_bt = get_absolute_min_vol_step_bt()

                    if volume_tag_value == 'MIN':
                        Smd.ResultComment = f'@ MIN {min_vol_step_bt}/{max_vol_step_bt} (0%)'
                    elif volume_tag_value == 'MAX':
                        Smd.ResultComment = f'@ MAX {max_vol_step_bt}/{max_vol_step_bt} (100%)'
                    elif volume_tag_value == 'NOM':

                        total_vol_step_range = max_vol_step_bt - min_vol_step_bt
                        nom_vol_step = get_var_value(f'VOL_nom_step_{connection_type}_{usecase}', var_type=int, add_error_sentence="Please execute script SMD 'Select nominal DUT playback volume'!")
                        nom_vol_percent = round(100 * (nom_vol_step / total_vol_step_range))
                        Smd.ResultComment = f'@ NOM {nom_vol_step}/{max_vol_step_bt} ({nom_vol_percent}%)'
                    else:
                        raise Exception(f"Value of SMD Tag '{volume_tag_name}' must be either 'MIN', 'MAX' or 'NOM', "
                                        f"but is '{volume_tag_value}' instead! Check SMD tag!")
                else:
                    raise Exception(f"Variable '{connection_type_var_name}' must be 'USB', 'USB dongle' or 'Bluetooth',"
                                    f" but is '{connection_type}' instead! Please execute script SMD 'DUT & Measurement"
                                    f" Wizard'!")
            else:
                if volume_control != 'Manual':
                    raise Exception(f"Measurement object variable '{vol_ctrl_var_name}' must be either 'Automatic or "
                                    f"'Manual', but is '{volume_control}' instead! Please execute script SMD 'Select "
                                    f"automatic/manual volume control'.")

        # Trigger .wav file export of recorded time signal
        meas_obj_title = MeasObject.Title
        smd_title = Smd.Title
        if meas_obj_title == '':
            # if SMD is executed in 'Test mode', M.O. title returns an empty string. In case of test mode, file export
            # will be skipped silently, print message in ACQUAlyzer results window.
            print(f"\nSMD '{smd_title}' was executed in test mode, export of .wav file has been skipped!")
        else:
            wav_export_var_name = 'WAV_export'
            wav_export = get_var_value(wav_export_var_name, var_type=bool, add_error_sentence="Please execute script SMD 'Automatic export of recordings in .wav format' in order to enable/disable the export of recordings! This step is mandatory!")
            if wav_export:
                auto_export_wav_file()


if __name__ == "__main__":
    main()
