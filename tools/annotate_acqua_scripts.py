# -*- coding: utf-8 -*-
"""挑 18 支代表性的 ACQUA 腳本,加上說明與導覽路徑。

為什麼不是全部倒出來
────────────────────
整個 SQL 裡有 107 支相異的 Python 腳本(含各專案的副本共 369 份)。
全部倒出來只是一堆沒有脈絡的檔案 —— 看不出哪支重要、什麼時候會跑、
在 ACQUA 裡要怎麼找到它。

這支挑 18 支涵蓋各種用法的,每一支前面加說明:它什麼時候執行、
在哪個資料庫哪個專案、ACQUA 裡怎麼點進去、改了會影響幾個測項。
**原始程式碼一字不動**,放在說明下面。

先跑 export_acqua_scripts.py 產生 index.json,再跑這支。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.join(ROOT, "acqua_scripts")
INDEX = os.path.join(BASE, "index.full.json")   # 完整版,含每個專案的副本

SP2 = "51_MS_Teams_Rev05_SP2"
AUTO = "ACQUA_auto_v2026Aug"
DEMO = "61_Demo_SMDs_Rev07"

#: (資料庫, 原檔名, 輸出檔名, 說明)
PICKS = [
    # ── 生命週期掛鉤:不掛在任何測項上,自動執行 ──────────
    (SP2, "before_each_measurement.py", "hook_1_before_each_measurement.py", """
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
"""),
    (SP2, "after_each_measurement.py", "hook_2_after_each_measurement.py", """
每一筆量測**結束後**自動執行。

它在做什麼
    把錄到的訊號匯出成 .wav。

值得學的手法:用標籤當開關
        if Tags.Exists('Export to .wav'):
            ...
    要讓某些測項有特殊行為,在 ACQUA 裡給它加標籤,掛鉤讀標籤決定做什麼
    —— 不用改程式碼就能逐項控制。
"""),
    (SP2, "after_canceled_measurement.py", "hook_3_after_canceled_measurement.py", """
量測**被中止**時執行(不是正常結束)。

它在做什麼
    善後:把背景噪音(BGN)播放停掉。沒有這支的話,中止之後喇叭會繼續放。

    這三支掛鉤裡最容易被忽略、又最該有的一支。
"""),
    (SP2, "OnProjectOpen.py", "hook_4_on_project_open.py", """
**開啟專案時**執行一次。

它在做什麼
    專案載入後的初始化。注意它跑在「開專案」這個動作裡 ——
    我們的 /api/open-project 會觸發它,所以開專案比想像中慢是正常的。
"""),

    # ── 最小範例:想自己寫一支就從這裡開始 ────────────────
    (SP2, "show_ch_name_in_legend.py", "min_1_show_ch_name_in_legend.py", """
整批裡最短的一支(11 行)。

它在做什麼
    把分析圖的圖例改成顯示通道名稱。

    `with AnalysisDiagram() as d:` 是 HSL 提供的情境管理器,
    進去改圖、出來自動套用。要調圖表外觀都走這個。
"""),
    (AUTO, "save_dtattn_result.py", "min_2_save_dtattn_result.py", """
最精簡的「存結果變數」骨架(12 行)。自己寫一支的話從這個開始。

四個步驟
    讀標籤 -> 取這個測項的結果 -> 挑出要的那一項 -> 存成變數

    `Variables.evsMeasured` 是變數狀態常數(「量到的」,相對於推算或預設)。
"""),
    (DEMO, "cal_corr_level.py", "min_3_cal_corr_level.py", """
校正修正值。Demo 資料庫裡的小範例,跟量測流程無關,適合拿來試手。
"""),

    # ── 結果 → 變數:這些變數餵給條件執行 ────────────────
    (AUTO, "3quest_store_mos_variables.py", "var_1_store_mos_variables.py", """
**這個資料庫裡被用最多次的腳本:162 個測項共用。**

它在做什麼
    把 3QUEST 分析算出的 MOS 分數存成變數。

一支腳本怎麼服務 162 個測項
        BGNScenario = Tags.Value("BGNScenario")
        Position = Tags.Value("Position")
    靠標籤產生不同的變數名稱 —— 掛在不同測項上就存成不同的變數。
    這是整個專案「少量腳本服務大量測項」的核心手法。

    存出來的變數就是我們網頁上看到的那些,也是條件執行
    (ConditionalExecution)決定要不要跳過某些測項的依據。
"""),
    (SP2, "equest_save_echo_level.py", "var_2_save_echo_level.py", """
**SP2 裡被用最多次的腳本:72 個測項共用。**

它在做什麼
    從結果裡挑出「Echo Level」存成變數。

兩個新東西
    `SingleValues.GetSingleValuesForRun(1)` —— 取某一輪的單值結果
    `Smd.Values(704)` —— 讀測項自己的設定欄位(704 是欄位編號)。
    這種數字編號在 ACQUA 文件裡查得到,程式裡看不出意思,要小心。
"""),
    (SP2, "save_p863_delay.py", "var_3_save_p863_delay.py", """
存 P.863(POLQA)量到的延遲。20 個測項共用。

跟前兩支同樣的模式,但處理的是延遲值 —— 可以對照看「同一套寫法
怎麼套用到不同的量測項目」。
"""),

    # ── 檔案操作 ────────────────────────────────────────
    (AUTO, "activation_snd.py", "file_1_activation_snd.py", """
它在做什麼
    把預錄的 .dat 複製一份,註冊成這次量測的結果檔。

兩個重點
    1) `Smd.Path` 是 ACQUA 的檔案快取目錄,腳本讀寫檔案都走這裡:
           C:\\ACQUA_Files\\File_Cache\\<專案名>_<GUID>\\

    2) **怎麼讓單一測項失敗**:
           Smd.Cancel = True
           Smd.CancelMsg = "File not found!"
       跟掛鉤用 `raise` 不一樣 —— 這裡是「這一筆失敗」,不是「整批擋下」。

    `ResultFiles.AddFile(路徑, 型別, 通道)` 把檔案掛進結果,
    之後的分析測項才看得到。
"""),
    (SP2, "3quest_add_clean_ref.py", "file_2_add_clean_ref.py", """
準備 3QUEST 分析需要的乾淨參考訊號。16 個測項共用。

為什麼挑這支
    典型的「一支腳本服務很多測項」。改它之前要先知道會影響多少 ——
    下面的清單就是算這個的。

    同名檔案在 Handset / Headset / Speakerphone 各有獨立副本,
    改其中一份不影響其他。
"""),
    (SP2, "rename_analyses_files_channels.py", "file_3_rename_analyses_files.py", """
把分析產生的檔案與通道重新命名。11 個測項共用。

比前面幾支長(約 80 行),示範了比較完整的檔案處理流程 ——
想看「正式一點的腳本長什麼樣」就看這支。
"""),

    # ── 互動 GUI:這些就是擋住無人值守的元凶 ──────────────
    (SP2, "dut_meas_wizard.py", "gui_1_dut_meas_wizard.py", """
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
"""),
    (SP2, "max_vol_msg.py", "gui_2_max_vol_msg.py", """
最小的互動範例(12 行),但後果一樣嚴重。

        import ctypes
        msg = ctypes.windll.user32.MessageBoxW
        msg(0, "Set the volume control of the DUT-PC to:\\n100 %", ...)

    直接叫 Windows 的 MessageBox。沒人按確定就卡在那裡。

    這解釋了我們為什麼需要「擋路視窗偵測」(acqua/winwatch.py)——
    這種視窗不是 ACQUA 自己開的,是腳本開的,所以只能從視窗層級抓。
"""),
    (SP2, "select_automatic_or_manual_volume_control.py",
     "gui_3_select_volume_control.py", """
另一支互動測項:問要用自動還是手動音量控制。

    這支的 SMDType 是 43(腳本型),跟 dut_meas_wizard 一樣。
    但我們的分類器實測發現 —— **43 不代表一定會開視窗**,
    所以不能只靠型別判斷,還要比對標題清單。
    (見 acqua/backend_base.py 的 _classifier)
"""),

    # ── 硬體相關:跟我們研究的 labCORE 那一塊有關 ──────────
    (SP2, "set_hardware_config_delay_values_for_positional_double_talk.py",
     "hw_1_set_hardware_delays.py", """
⭐ **腳本可以改硬體設定。**

它在做什麼
    為了定位雙講(positional double talk)量測,設定硬體設定裡的延遲值。

為什麼值得注意
    我們之前查「硬體能不能程式控制」查了很久,結論是走 MfeControlLib。
    但這支證明:**ACQUA 的腳本層本來就能碰硬體設定** ——
    而且它跑在量測流程裡,時機比我們從外面介入更準。

    如果將來要自動設麥克風供電,這裡可能是比 /api/mic-power 更好的位置。
"""),
    (SP2, "define_hardware_options.py", "hw_2_define_hardware_options.py", """
問使用者有哪些硬體可用(轉盤 HRT I、旋轉反射板 HRR I),存成變數。

    這些變數再透過條件執行決定「沒有轉盤就跳過需要轉盤的測項」。

    是「硬體能力 -> 變數 -> 條件執行 -> 要跑哪些測項」這條鏈的起點,
    跟我們在 acqua/condeval.py 處理的那套條件式是同一件事的兩端。
"""),
    (SP2, "set_measurement_equipment_delays.py", "hw_3_set_equipment_delays.py", """
設定量測設備的延遲補償值。

    跟 hw_1 類似但更完整,示範腳本怎麼讀寫硬體設定的各項參數。
"""),
]


def main():
    index = json.load(io.open(INDEX, encoding="utf-8"))

    # 同一個 (db, filename) 有多份(各專案一份)—— 取被最多測項用的
    best = {}
    for it in index:
        key = (it["database"], it["filename"])
        cur = best.get(key)
        if cur is None or len(it["used_by"]) > len(cur["used_by"]):
            best[key] = it

    staged = {}
    for db, fname, outname, note in PICKS:
        it = best.get((db, fname))
        if it is None:
            print("   !! 找不到 %s / %s" % (db, fname))
            continue
        # newline="" —— 不要讓 Python 把 CRLF 轉成 LF,
        # 不然寫出去的「原始程式碼」就跟資料庫裡的不是同一份了。
        src = io.open(os.path.join(BASE, it["saved_as"]),
                      encoding="utf-8", newline="").read()
        staged[outname] = (it, db, fname, note, src)

    # 原始傾印的資料夾收掉 —— 369 個沒有脈絡的檔案留著只是雜訊。
    # ⚠️ 要重試:這個專案放在 OneDrive 上,同步程序會短暫抓著資料夾,
    #    第一次 rmtree 常常丟 PermissionError。
    for name in os.listdir(BASE):
        p = os.path.join(BASE, name)
        if not os.path.isdir(p) or name.startswith("_"):
            continue
        for _ in range(6):
            try:
                shutil.rmtree(p)
                break
            except PermissionError:
                time.sleep(0.6)
        else:
            print("   !! 刪不掉 %s(OneDrive 鎖住了,手動刪即可)" % name)
    os.makedirs(BASE, exist_ok=True)

    for outname, (it, db, fname, note, src) in sorted(staged.items()):
        users = it["used_by"]
        if users:
            u = users[0]
            where = ["", "在 ACQUA 裡怎麼找到它",
                     "    資料庫   %s" % db,
                     "    專案     %s" % it["project"],
                     "    測項樹   %s" % (" / ".join(u["path"]) or "(樹根)"),
                     "             └ %s" % u["title"],
                     "               row_id %s" % u["row_id"],
                     "",
                     "    開啟上面那個專案 -> 在測項樹照路徑展開 -> 選到該測項",
                     "    -> 測項設定裡可以開啟並編輯這支腳本。",
                     "",
                     "    共 %d 個測項用到它。" % len(users)]
            if len(users) > 1:
                where.append("    **改它會同時影響這些測項**,其他幾個例如:")
                for x in users[1:4]:
                    where.append("      #%-6s %s" % (x["row_id"], x["title"]))
                if len(users) > 4:
                    where.append("      ...另外 %d 個" % (len(users) - 4))
        else:
            where = ["", "在 ACQUA 裡怎麼找到它",
                     "    資料庫   %s" % db,
                     "    專案     %s" % it["project"],
                     "",
                     "    這是**專案層級的掛鉤**,不掛在任何測項上,測項樹裡找不到。",
                     "    開啟上面那個專案 -> 專案層級的設定 / 腳本那一區,",
                     "    before / after / canceled / OnProjectOpen 都在那裡。",
                     "",
                     "    執行時的副本在:",
                     "      C:\\ACQUA_Files\\File_Cache\\%s_<GUID>\\%s" % (db, fname)]

        header = ['"""', "=" * 72, "  %s" % fname,
                  "  資料庫 %s" % db, "=" * 72, "",
                  "⚠️ 這是從 ACQUA 資料庫解出來的**副本**,只是給你看的。",
                  "   改這裡不會影響 ACQUA。要真的改請用 ACQUA 自己的腳本編輯器 ——",
                  "   它會處理 ZIP 壓縮、FileSize、CRCValue、ChangeDate,",
                  "   少寫一個欄位 ACQUA 可能就讀不到、或靜默用舊版。",
                  "",
                  "   來源:acqua.Files idFile=%s ・ 型別 %s ・ 最後修改 %s"
                  % (it["id_file"], it["file_type"], it["changed"]), ""]
        header += note.strip("\n").split("\n")
        header += where
        # 結尾不要補空字串 —— 下面 join 完會自己接一個 eol,
        # 補了就會多一個空行,原始碼前面就不是乾淨地接著收尾引號。
        header += ["", "=" * 72, "  以下是**原始程式碼**,一字未改。",
                   "=" * 72, '"""']

        # 換行用原始碼自己的 —— 資料庫裡存的是 CRLF。說明區塊跟著它走,
        # 一個檔案裡不要混兩種換行,而且這樣原始碼才真的一字未改。
        eol = "\r\n" if "\r\n" in src else "\n"
        io.open(os.path.join(BASE, outname), "w", encoding="utf-8",
                newline="").write(eol.join(header) + eol + src)
        print("   %-42s <- %s" % (outname, db))

    print("\n%d 支 -> %s" % (len(staged), BASE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
