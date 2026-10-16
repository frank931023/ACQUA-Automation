"""
========================================================================
  select_automatic_or_manual_volume_control.py
  資料庫 51_MS_Teams_Rev05_SP2
========================================================================

⚠️ 這是從 ACQUA 資料庫解出來的**副本**,只是給你看的。
   改這裡不會影響 ACQUA。要真的改請用 ACQUA 自己的腳本編輯器 ——
   它會處理 ZIP 壓縮、FileSize、CRCValue、ChangeDate,
   少寫一個欄位 ACQUA 可能就讀不到、或靜默用舊版。

   來源:acqua.Files idFile=913 ・ 型別 FT_SMDUsedFile ・ 最後修改 2024-01-25 11:40:09

另一支互動測項:問要用自動還是手動音量控制。

    這支的 SMDType 是 43(腳本型),跟 dut_meas_wizard 一樣。
    但我們的分類器實測發現 —— **43 不代表一定會開視窗**,
    所以不能只靠型別判斷,還要比對標題清單。
    (見 acqua/backend_base.py 的 _classifier)

在 ACQUA 裡怎麼找到它
    資料庫   51_MS_Teams_Rev05_SP2
    專案     MS Teams v5 Rev05 SP2 - Headset
    測項樹   MS Teams v5 Rev05 SP2 - Headset / MS Teams Rev.05 SP2 - Headset Devices / Primary Requirements for Device Direct connection / Headset Device Direct connection - Anechoic room / Preparation - set up levels
             └ Select automatic/manual volume control
               row_id 734

    開啟上面那個專案 -> 在測項樹照路徑展開 -> 選到該測項
    -> 測項設定裡可以開啟並編輯這支腳本。

    共 1 個測項用到它。

========================================================================
  以下是**原始程式碼**,一字未改。
========================================================================
"""
from HEAD import const
from HSL import run_universal_questionnaire_gui, get_rcv_volume_control_idx, get_var_value, save_var, delete_vars


def main():
    vol_ctrl_var_name = 'VOL_control'
    connection_type = get_var_value(var_name='DUT_connection_type', var_type=str,
                                    add_error_sentence="Please execute script SMD 'DUT & Measurement Wizard'!")
    if connection_type in ['USB', 'USB dongle']:
        rcv_volume_control_idx = get_rcv_volume_control_idx()
    elif connection_type == 'Bluetooth':
        rcv_volume_control_idx = None
    else:
        raise Exception(f"Variable 'DUT_connection_type' must be 'USB', 'USB dongle' or 'Bluetooth', but is '{connection_type}' instead! Please execute script SMD 'DUT & Measurement Wizard'")

    # define frames
    query_vol_control = {'Frame Title': 'DUT volume control',
                         'Options': [f'Automatic volume control (selected DUT connection: {connection_type})      ', 'Manual volume control'],
                         'VarName': vol_ctrl_var_name,
                         'Values': ['Automatic', 'Manual'],
                         'Tooltips': [f'Volume level of DUT (connected via {connection_type}) is set automatically before each measurement through SMD tags.',
                                      f'Volume level of DUT (connected via {connection_type}) must be set manually before each measurement by the user.'],
                         'Orientation': 'V'}
    # run gui
    choice_dict = run_universal_questionnaire_gui(query_vol_control)

    if choice_dict:  # gui was not cancelled by user
        # get and save usb_playback_controller_idx if automatic volume control is selected and if connection type is
        # USB or USB dongle, or delete usb_playback_controller_idx in all other cases
        vol_ctrl = choice_dict[vol_ctrl_var_name]
        if vol_ctrl == 'Automatic':
            if rcv_volume_control_idx is not None:
                save_var('VOL_usb_playback_controller_idx', rcv_volume_control_idx, const.evsUserDefined)
            else:
                delete_vars('VOL_usb_playback_controller_idx')
        elif vol_ctrl == 'Manual':
            delete_vars('VOL_usb_playback_controller_idx')
        else:
            raise Exception(f"Variable '{vol_ctrl_var_name}' must be either 'Automatic' or 'Manual', but is '{vol_ctrl}' instead!")


if __name__ == "__main__":
    main()
