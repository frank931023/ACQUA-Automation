"""
========================================================================
  set_hardware_config_delay_values_for_positional_double_talk.py
  資料庫 51_MS_Teams_Rev05_SP2
========================================================================

⚠️ 這是從 ACQUA 資料庫解出來的**副本**,只是給你看的。
   改這裡不會影響 ACQUA。要真的改請用 ACQUA 自己的腳本編輯器 ——
   它會處理 ZIP 壓縮、FileSize、CRCValue、ChangeDate,
   少寫一個欄位 ACQUA 可能就讀不到、或靜默用舊版。

   來源:acqua.Files idFile=5175 ・ 型別 FT_SMDUsedFile ・ 最後修改 2022-08-29 14:10:24

⭐ **腳本可以改硬體設定。**

它在做什麼
    為了定位雙講(positional double talk)量測,設定硬體設定裡的延遲值。

為什麼值得注意
    我們之前查「硬體能不能程式控制」查了很久,結論是走 MfeControlLib。
    但這支證明:**ACQUA 的腳本層本來就能碰硬體設定** ——
    而且它跑在量測流程裡,時機比我們從外面介入更準。

    如果將來要自動設麥克風供電,這裡可能是比 /api/mic-power 更好的位置。

在 ACQUA 裡怎麼找到它
    資料庫   51_MS_Teams_Rev05_SP2
    專案     MS Teams v5 Rev05 SP2 - Speakerphone
    測項樹   MS Teams v5 Rev05 SP2 - Speakerphone / V5_Personal Space and Shared Space Devices - Desk Phone, Speakerphone  / Optional module - Positional audio for EMTR / Positional audio for EMTR - Device direct connection / OpS05R-ECC - Echo path: Echo during altern. SND-RCV - Far end dynamic pan L->R - reverberant room
             └ Recording for ECC - Stereo - FE not active
               row_id 4647

    開啟上面那個專案 -> 在測項樹照路徑展開 -> 選到該測項
    -> 測項設定裡可以開啟並編輯這支腳本。

    共 4 個測項用到它。
    **改它會同時影響這些測項**,其他幾個例如:
      #4648   Recording for ECC - Stereo - FE active and panning
      #4688   Recording for ECC - Stereo - FE not active
      #4689   Recording for ECC - Stereo - FE active and panning

========================================================================
  以下是**原始程式碼**,一字未改。
========================================================================
"""
from win32com.client import CastTo
from HEAD import const
from HSL import LabCore, get_tag_values, get_var_value


def set_delay_values():
    lc = LabCore()

    # get tags
    use_case, bandwidth = get_tag_values("UseCase", "Bandwidth")

    # get delay variable from measurement object
    delay_value = get_var_value(f"D_RCV_{use_case}{bandwidth}")

    # get first and second delay block
    first_delay_block_settings = lc.selected_labcore.AudioWiring.Blocks.BlockByID("delay|0|").Settings
    second_delay_block_settings = lc.selected_labcore.AudioWiring.Blocks.BlockByID("delay|1|").Settings
    first_delay_block = CastTo(first_delay_block_settings, "ILabCoreAudioBlockSettingsDelays")
    second_delay_block = CastTo(second_delay_block_settings, "ILabCoreAudioBlockSettingsDelays")

    # activate first delay line of each block
    first_delay_block.Line(0).Active = True
    second_delay_block.Line(0).Active = True

    # set delay values of first line of each delay block
    first_delay_block.Line(0).Delay = delay_value/1000
    second_delay_block.Line(0).Delay = delay_value/1000

    first_delay_block.Mode = const.eBlockSPModeActive
    second_delay_block.Mode = const.eBlockSPModeActive


if __name__ == "__main__":
    set_delay_values()
