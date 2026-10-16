"""
========================================================================
  dut_meas_wizard.py
  資料庫 51_MS_Teams_Rev05_SP2
========================================================================

⚠️ 這是從 ACQUA 資料庫解出來的**副本**,只是給你看的。
   改這裡不會影響 ACQUA。要真的改請用 ACQUA 自己的腳本編輯器 ——
   它會處理 ZIP 壓縮、FileSize、CRCValue、ChangeDate,
   少寫一個欄位 ACQUA 可能就讀不到、或靜默用舊版。

   來源:acqua.Files idFile=4046 ・ 型別 FT_SMDUsedFile ・ 最後修改 2023-11-21 10:25:28

⭐ **這就是擋住我們自動化的那個「DUT & Measurement Wizard」。**

它在做什麼
    跳出一個問卷視窗,問這次要測哪些項目(個人空間 / 共享空間 /
    收音距離 / premium 需求 ...),把答案存成變數。

    那些變數再透過條件執行決定專案樹裡哪些測項要跑、哪些跳過。

為什麼它會卡住自動化
    `run_universal_questionnaire_gui(...)` 會開一個視窗等人點,
    沒人點就一直等。我們的逐項執行模式之所以要事先排除這類測項,
    原因就在這裡。

理論上可以怎麼繞過
    變數如果已經設好了,這支其實不需要跑。但它是 HEAD 原廠標準專案的
    一部分,而 MS Teams 這兩個是**認證用**的流程 ——
    改了可能影響認證效力。要動之前先確認這件事。

在 ACQUA 裡怎麼找到它
    資料庫   51_MS_Teams_Rev05_SP2
    專案     MS Teams v5 Rev05 SP2 - Speakerphone
    測項樹   MS Teams v5 Rev05 SP2 - Speakerphone / V5_Personal Space and Shared Space Devices - Desk Phone, Speakerphone  / Information and preparation
             └ DUT & Measurement Wizard
               row_id 3591

    開啟上面那個專案 -> 在測項樹照路徑展開 -> 選到該測項
    -> 測項設定裡可以開啟並編輯這支腳本。

    共 1 個測項用到它。

========================================================================
  以下是**原始程式碼**,一字未改。
========================================================================
"""
# -*- coding: utf-8 -*-

from HEAD import const
from ACQUAlyzer import Smd
from HSL import run_universal_questionnaire_gui, save_var, delete_vars, both_corebt_versions_available, corebt_available, corebt2_available


def main():
    query_dut_speakerphone_type = {'Frame Title': 'Measurements to be performed',
                                   'VarName': 'DUT_speakerphone_type',
                                   'Options': ['Measurements for personal space speakerphone', 'Measurements for shared space speakerphone', 'Measurements for both types'],
                                   'Tooltips': ['e.g. desk phones, soundbars etc.',
                                                'e.g. table mounted speakerphones, flexible setup speakerphones etc.',
                                                'e.g. hybrid speakerphones'],
                                   'Values': ['Personal', 'Shared', 'Both'],
                                   'Position': [0, 0]}

    query_misc_dut_parameters = {'Frame Title': 'Miscellaneous DUT properties',
                                 'VarNamePerCheckBox': ['DUT_is_deskphone', 'DUT_has_cooling_fan'],
                                 'Options': ['DUT is a personal desk phone', 'DUT has a cooling fan'],
                                 'GrayOutSingleRadioButtonOrCheckBox': {'DUT is a personal desk phone': {'Measurements to be performed': 'Measurements for shared space speakerphone'}},
                                 'CheckBoxesFlag': True,
                                 'Position': [0, 1]}

    query_dut_pickup_range = {'Frame Title': 'Shared space speakerphone - Pickup range',
                              'VarNamePerCheckBox': ['DUT_pickup_range_1.5m', 'DUT_pickup_range_2.3m', 'DUT_pickup_range_3.5m', 'DUT_pickup_range_4.5m'],
                              'Options': ['1.5 m', '2.3 m', '3.5 m', '4.5 m'],
                              'GrayOutWholeFrame': {'Measurements to be performed': ['Measurements for personal space speakerphone']},
                              'CheckBoxesFlag': True,
                              'Position': [1, 0]}

    query_dut_speaker_range = {'Frame Title': 'Shared space speakerphone - Speaker range',
                               'VarNamePerCheckBox': ['DUT_speaker_range_1.5m', 'DUT_speaker_range_2.3m',
                                                      'DUT_speaker_range_3.5m', 'DUT_speaker_range_4.5m',
                                                      'DUT_speaker_range_7.5m'],
                               'Options': ['1.5 m', '2.3 m', '3.5 m', '4.5 m', '7.5 m'],
                               'GrayOutWholeFrame': {'Measurements to be performed': ['Measurements for personal space speakerphone']},
                               'CheckBoxesFlag': True,
                               'Position': [1, 1]}

    query_project_tree_options = {'Frame Title': 'Project tree options',
                                   'Options': ['Optional module: Positional audio for enhanced meeting room', 'Optional module: Stereo calling', 'Premium requirements', 'Informative Measurements: DUT ultrasound render capability'],
                                   'VarNamePerCheckBox': ['DUT_positional_audio_for_emtr', 'DUT_stereo_calling', 'DUT_premium_reqs', 'DUT_ultrasound_capability'],
                                   'Tooltips': ['Select if positional audio for EMTR certification is desired. Additional measurements for positional audio for EMTR use case will be enabled.',
                                                'Select if stereo calling certification is desired. Additional measurements for stereo calling will be enabled.',
                                                'Select to enable SMDs that check conformity against premium requirements',
                                                'Select to enable informative measurements that check ultrasound render capability of the DUT'],
                                   'Position': [3, 0, 2],
                                   'CheckBoxesFlag': True,
                                   'GrayOutSingleRadioButtonOrCheckBox': {'Optional module: Positional audio for enhanced meeting room': {'Measurements to be performed': 'Measurements for personal space speakerphone', 'DUT connection': ['SRW via dedicated USB dongle', 'Bluetooth (native)', 'Android']},
                                                                          'Informative Measurements: DUT ultrasound render capability': {'Measurements to be performed': 'Measurements for personal space speakerphone'},
                                                                          'Optional module: Stereo calling': {'Measurements to be performed': 'Measurements for shared space speakerphone', 'DUT connection': ['SRW via dedicated USB dongle', 'Bluetooth (native)', 'Android']}}}

    if both_corebt_versions_available():
        query_dut_connection_type = {'Frame Title': 'DUT connection',
                                     'VarName': 'DUT_connection_type',
                                     'Options': ['USB', 'SRW via dedicated USB dongle', 'Bluetooth (native)', 'Android'],
                                     'Tooltips': ['Select for DUT connected to the host audio device via USB',
                                                  'Select for DUT connected to the host audio device with help of a dedicated USB dongle which is delivered with the DUT.',
                                                  'Select for DUT connected to the host audio device via direct Bluetooth connection.',
                                                  'Select for Android DUT with Teams client inside and Teams call established between DUT and REF PC.'],
                                     'Values': ['USB', 'USB dongle', 'Bluetooth', 'Android'],
                                     'Position': [2, 0]}

        query_labcore_bt_type = {'Frame Title': 'labCORE Bluetooth module for DUT connection',
                                 'VarName': 'DUT_labcore_bt_type',
                                 'Options': ['coreBT2  ("Bluetooth V2")', 'coreBT/coreBT-EXT  ("Bluetooth Audio")'],
                                 'Tooltips': ['Select if coreBT2 (i.e. "Bluetooth V2" block) shall be used as reference audio gateway for the Bluetooth (native) connection with the DUT.',
                                              'Select if coreBT/coreBT-EXT (i.e. "Bluetooth Audio" block) shall be used as reference audio gateway for the Bluetooth (native) connection with the DUT.'],
                                 'Values': ['coreBT2', 'coreBT'],
                                 'GrayOutWholeFrame': {'DUT connection': ['SRW via dedicated USB dongle', 'USB', 'Android']},
                                 'Position': [2, 1]}

        choice_dict = run_universal_questionnaire_gui(query_dut_speakerphone_type,
                                                      query_misc_dut_parameters,
                                                      query_dut_pickup_range,
                                                      query_dut_speaker_range,
                                                      query_dut_connection_type,
                                                      query_labcore_bt_type,
                                                      query_project_tree_options)
        if choice_dict:
            if choice_dict['DUT_connection_type'] != 'Bluetooth':
                delete_vars('DUT_labcore_bt_type')
        # initialize/enable active connection warnings
        save_var("DUT_disable_warning_no_active_bt_connections", False, const.evsUserDefined, var_comment=Smd.Title)
        save_var("DUT_disable_warning_wrong_active_bt_connections", False, const.evsUserDefined, var_comment=Smd.Title)
        save_var("DUT_disable_warning_extra_active_bt_connections", False, const.evsUserDefined, var_comment=Smd.Title)

    else:
        query_dut_connection_type = {'Frame Title': 'DUT connection',
                                     'VarName': 'DUT_connection_type',
                                     'Options': ['USB', 'SRW via dedicated USB dongle', 'Bluetooth (native)', 'Android'],
                                     'Tooltips': ['Select for DUT connected to the host audio device via USB',
                                                  'Select for DUT connected to the host audio device with help of a dedicated USB dongle which is delivered with the DUT.',
                                                  'Select for DUT connected to the host audio device via direct Bluetooth connection.',
                                                  'Select for Android DUT with Teams client inside and Teams call established between DUT and REF PC.'],
                                     'Values': ['USB', 'USB dongle', 'Bluetooth', 'Android'],
                                     'Position': [2, 0, 2]}
        if corebt2_available():
            choice_dict = run_universal_questionnaire_gui(query_dut_speakerphone_type,
                                                          query_misc_dut_parameters,
                                                          query_dut_pickup_range,
                                                          query_dut_speaker_range,
                                                          query_dut_connection_type,
                                                          query_project_tree_options)
            if choice_dict:
                if choice_dict['DUT_connection_type'] == 'Bluetooth':
                    save_var('DUT_labcore_bt_type', 'coreBT2', const.evsMeasured, var_comment=Smd.Title)
                else:
                    delete_vars('DUT_labcore_bt_type')
        elif corebt_available():
            choice_dict = run_universal_questionnaire_gui(query_dut_speakerphone_type,
                                                          query_misc_dut_parameters,
                                                          query_dut_pickup_range,
                                                          query_dut_speaker_range,
                                                          query_dut_connection_type,
                                                          query_project_tree_options)
            if choice_dict:
                if choice_dict['DUT_connection_type'] == 'Bluetooth':
                    save_var('DUT_labcore_bt_type', 'coreBT', const.evsMeasured, var_comment=Smd.Title)
                else:
                    delete_vars('DUT_labcore_bt_type')
        else:
            query_dut_connection_type = {'Frame Title': 'DUT connection',
                                         'VarName': 'DUT_connection_type',
                                         'Options': ['USB', 'SRW via dedicated USB dongle', 'Bluetooth (native)', 'Android'],
                                         'Tooltips': ['Select for DUT connected to the host audio device via USB',
                                                      'Select for DUT connected to the host audio device with help of a dedicated USB dongle which is delivered with the DUT.',
                                                      'Bluetooth module (coreBT2 or coreBT/coreBT-EXT) is not available on the connected labCORE frontend.',
                                                      'Select for Android DUT with Teams client inside and Teams call established between DUT and REF PC.'],
                                         'Values': ['USB', 'USB dongle', 'Bluetooth', 'Android'],
                                         'GrayOutSingleRadioButtonOrCheckBox': {'Bluetooth (native)': {'Measurements to be performed': ['Measurements for personal space speakerphone', 'Measurements for shared space speakerphone', 'Measurements for both types']}},
                                         'Position': [2, 0, 2]}
            choice_dict = run_universal_questionnaire_gui(query_dut_speakerphone_type,
                                                          query_misc_dut_parameters,
                                                          query_dut_pickup_range,
                                                          query_dut_speaker_range,
                                                          query_dut_connection_type,
                                                          query_project_tree_options)
            if choice_dict:
                delete_vars('DUT_labcore_bt_type')


if __name__ == "__main__":
    main()
