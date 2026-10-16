"""
========================================================================
  after_canceled_measurement.py
  資料庫 51_MS_Teams_Rev05_SP2
========================================================================

⚠️ 這是從 ACQUA 資料庫解出來的**副本**,只是給你看的。
   改這裡不會影響 ACQUA。要真的改請用 ACQUA 自己的腳本編輯器 ——
   它會處理 ZIP 壓縮、FileSize、CRCValue、ChangeDate,
   少寫一個欄位 ACQUA 可能就讀不到、或靜默用舊版。

   來源:acqua.Files idFile=1306 ・ 型別 FT_Script ・ 最後修改 2022-12-08 16:10:31

量測**被中止**時執行(不是正常結束)。

它在做什麼
    善後:把背景噪音(BGN)播放停掉。沒有這支的話,中止之後喇叭會繼續放。

    這三支掛鉤裡最容易被忽略、又最該有的一支。

在 ACQUA 裡怎麼找到它
    資料庫   51_MS_Teams_Rev05_SP2
    專案     MS Teams v5 Rev05 SP2 - Speakerphone

    這是**專案層級的掛鉤**,不掛在任何測項上,測項樹裡找不到。
    開啟上面那個專案 -> 專案層級的設定 / 腳本那一區,
    before / after / canceled / OnProjectOpen 都在那裡。

    執行時的副本在:
      C:\ACQUA_Files\File_Cache\51_MS_Teams_Rev05_SP2_<GUID>\after_canceled_measurement.py

========================================================================
  以下是**原始程式碼**,一字未改。
========================================================================
"""
from HEAD import const
from win32com.client import CastTo
from HSL import BGNConfigurator, get_var_value, get_tag_values, LabCore
from ACQUAlyzer import Tags


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
    # restore HW configuration for AES-BT connection
    if Tags.Exists("UseCase"):
        usecase = get_tag_values("UseCase")
        if usecase == 'E2E':
            connection_type_var_name = 'DUT_connection_type'
            connection_type = get_var_value(var_name=connection_type_var_name, var_type=str,
                                            add_error_sentence="Please execute script SMD 'DUT & Measurement Wizard'!")
            if connection_type == 'Bluetooth':
                core_bt_type_var_name = 'DUT_labcore_bt_type'
                corebt_type = get_var_value(var_name=core_bt_type_var_name, var_type=str,
                                            add_error_sentence="Please execute script SMD 'DUT & Measurement Wizard'!")
                if corebt_type not in ['coreBT', 'coreBT2']:
                    raise Exception(f"Variable '{core_bt_type_var_name}' must be 'coreBT' or 'coreBT2', but is "
                                    f"'{corebt_type}' instead! Please execute script SMD 'DUT & Measurement "
                                    f"Wizard'.")
                delete_connection_gains_aes_bt(corebt_type)

    # stop 3Pass playback
    if Tags.Exists("BGN_Markname"):
        bgn_control = get_var_value('BGNControl')
        if bgn_control == 'Automatic':
            BGNConfigurator().stop_bgn()


if __name__ == "__main__":
    main()
