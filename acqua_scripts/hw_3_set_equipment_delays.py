"""
========================================================================
  set_measurement_equipment_delays.py
  資料庫 51_MS_Teams_Rev05_SP2
========================================================================

⚠️ 這是從 ACQUA 資料庫解出來的**副本**,只是給你看的。
   改這裡不會影響 ACQUA。要真的改請用 ACQUA 自己的腳本編輯器 ——
   它會處理 ZIP 壓縮、FileSize、CRCValue、ChangeDate,
   少寫一個欄位 ACQUA 可能就讀不到、或靜默用舊版。

   來源:acqua.Files idFile=3187 ・ 型別 FT_SMDUsedFile ・ 最後修改 2022-08-08 10:07:07

設定量測設備的延遲補償值。

    跟 hw_1 類似但更完整,示範腳本怎麼讀寫硬體設定的各項參數。

在 ACQUA 裡怎麼找到它
    資料庫   51_MS_Teams_Rev05_SP2
    專案     MS Teams v5 Rev05 SP2 - Headset
    測項樹   MS Teams v5 Rev05 SP2 - Headset / MS Teams Rev.05 SP2 - Headset Devices / Information and preparation
             └ Load equipment delay values
               row_id 2811

    開啟上面那個專案 -> 在測項樹照路徑展開 -> 選到該測項
    -> 測項設定裡可以開啟並編輯這支腳本。

    共 1 個測項用到它。

========================================================================
  以下是**原始程式碼**,一字未改。
========================================================================
"""
# -*- coding: utf-8 -*-
from HEAD import const
from HSL import save_delays_based_on_setup, save_multiple_delays, get_var_value, save_var, delete_vars


def main():
    # get connection type
    connection_type_var_name = 'DUT_connection_type'
    connection_type = get_var_value(var_name=connection_type_var_name, var_type=str,
                                    add_error_sentence="Please execute script SMD 'DUT & Measurement Wizard'!")
    # Additional delay variables for reference interface, values relevant in case of coreBT2 (delta coreBT2 - coreBT1),
    # initialized with 0 ms and stored as such in all other cases
    delay_snd_add_ref_eq_var_name = 'D_SND_ADD_EQ'
    delay_snd_add_ref_eq_value = 0
    delay_rcv_add_ref_eq_var_name = 'D_RCV_ADD_EQ'
    delay_rcv_add_ref_eq_value = 0
    delay_echo_add_ref_eq_var_name = 'D_ECHO_ADD_EQ'
    delay_echo_add_ref_eq_value = 0

    if connection_type in ['USB', 'USB dongle']:
        interface = 'USB'
    elif connection_type == 'Bluetooth':
        core_bt_type_var_name = 'DUT_labcore_bt_type'
        corebt_type = get_var_value(var_name=core_bt_type_var_name, var_type=str,
                                    add_error_sentence="Please execute script SMD 'DUT & Measurement Wizard'!")
        if corebt_type == 'coreBT2':
            interface = "BT2"
            save_delays_based_on_setup(frontend='labCORE', interface=interface, create_report=False)
            additional_corebt1_delays = [('labCORE', 'D_DEC_BT1_WB'), ('labCORE', 'D_ENC_BT1_WB')]
            save_multiple_delays(additional_corebt1_delays, create_report=False)

            delay_snd_add_ref_eq_value = get_var_value('D_DEC_BT_WB') - get_var_value('D_DEC_BT1_WB')  # Delta DEC BT2-BT1
            delay_rcv_add_ref_eq_value = get_var_value('D_ENC_BT_WB') - get_var_value('D_ENC_BT1_WB')  # Delta ENC BT2-BT1
            delay_echo_add_ref_eq_value = delay_snd_add_ref_eq_value + delay_rcv_add_ref_eq_value  # Delta RTD BT2-BT1
            delete_vars('D_DEC_BT1_WB', 'D_ENC_BT1_WB')
        elif corebt_type == 'coreBT':
            interface = "BT"
        else:
            raise Exception(f"Value of variable '{core_bt_type_var_name}' must be either 'coreBT' or 'coreBT2', but is '{corebt_type}' instead!")
    else:
        raise Exception(f"Value of variable '{connection_type_var_name}' must be either 'USB', 'USB dongle' or 'Bluetooth', but is '{connection_type}' instead.")

    all_delay_variables = ['D_SR_REA', 'D_RAN_DA', 'D_RAN_AD',
                           'D_SND_USB', 'D_RCV_USB',
                           'D_DEC_BT_NB', 'D_DEC_BT_WB', 'D_ENC_BT_NB', 'D_ENC_BT_WB',
                           'D_SND_ADD_EQ', 'D_RCV_ADD_EQ', 'D_ECHO_ADD_EQ']
    delete_vars(*all_delay_variables)
    save_delays_based_on_setup(frontend='labCORE', interface=interface)
    save_var(delay_snd_add_ref_eq_var_name, delay_snd_add_ref_eq_value, const.evsMeasured, var_unit='ms')
    save_var(delay_rcv_add_ref_eq_var_name, delay_rcv_add_ref_eq_value, const.evsMeasured, var_unit='ms')
    save_var(delay_echo_add_ref_eq_var_name, delay_echo_add_ref_eq_value, const.evsMeasured, var_unit='ms')


if __name__ == '__main__':
    main()
