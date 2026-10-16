"""
========================================================================
  max_vol_msg.py
  資料庫 51_MS_Teams_Rev05_SP2
========================================================================

⚠️ 這是從 ACQUA 資料庫解出來的**副本**,只是給你看的。
   改這裡不會影響 ACQUA。要真的改請用 ACQUA 自己的腳本編輯器 ——
   它會處理 ZIP 壓縮、FileSize、CRCValue、ChangeDate,
   少寫一個欄位 ACQUA 可能就讀不到、或靜默用舊版。

   來源:acqua.Files idFile=5403 ・ 型別 FT_SMDUsedFile ・ 最後修改 2023-04-24 15:33:50

最小的互動範例(12 行),但後果一樣嚴重。

        import ctypes
        msg = ctypes.windll.user32.MessageBoxW
        msg(0, "Set the volume control of the DUT-PC to:\n100 %", ...)

    直接叫 Windows 的 MessageBox。沒人按確定就卡在那裡。

    這解釋了我們為什麼需要「擋路視窗偵測」(acqua/winwatch.py)——
    這種視窗不是 ACQUA 自己開的,是腳本開的,所以只能從視窗層級抓。

在 ACQUA 裡怎麼找到它
    資料庫   51_MS_Teams_Rev05_SP2
    專案     MS Teams v5 Rev05 SP2 - Speakerphone
    測項樹   MS Teams v5 Rev05 SP2 - Speakerphone / V5_Personal Space and Shared Space Devices - Desk Phone, Speakerphone  / DUT ultrasound render capability for shared space device (Informative)
             └ Render ultrasound level - MaxVol - Rec. & Delay Comp.
               row_id 4863

    開啟上面那個專案 -> 在測項樹照路徑展開 -> 選到該測項
    -> 測項設定裡可以開啟並編輯這支腳本。

    共 1 個測項用到它。

========================================================================
  以下是**原始程式碼**,一字未改。
========================================================================
"""
import ctypes
msg = ctypes.windll.user32.MessageBoxW


def main():

    msg(0,"Set the volume control of the DUT-PC to:\n100 %", "Next Volume Setting",0)


if __name__ == "__main__":
    main()
