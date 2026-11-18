# -*- coding: utf-8 -*-
"""⚠️ 診斷用掛鉤 —— 要貼進 ACQUA 的,不是匯出副本。**只印資訊,不改任何東西。**

貼到 AUTOMATION_TEST_0806 / test1 的專案層級 before_each_measurement.py,
從 ACQUA 直接跑一筆,然後把 ACQUA 視窗印出來的那幾行抄給我(或截圖)。
驗完就刪掉,換成 HOOK_setup_bridge.py。

要回答的問題
────────────
資料夾不能加標籤,所以「沒標就往上找」要改成由我們的服務用 SQL 判斷。
掛鉤得告訴服務「我在哪個資料夾」。型別庫(ACQUALyzerScripting.tlb)顯示
ISmd **沒有 row id**,但有 Path —— 要看它實際回什麼格式,才能跟 SQL 算出來
的路徑對上。

已經查過的:
  - (路徑 + 標題)會重複,約一成的測項撞名 -> 不能拿來認「哪一筆」
  - 資料夾路徑在兩個主力庫都不重複          -> 拿來認「哪個資料夾」夠用
"""
from ACQUAlyzer import Smd, Tags, SubProject, MeasObject


def show(label, getter):
    try:
        print("[diag] %-16s = %r" % (label, getter()))
    except Exception as exc:                                # noqa: BLE001
        print("[diag] %-16s ✗ %s" % (label, exc))


print("[diag] ========== 這一筆 ==========")
show("Smd.Title", lambda: Smd.Title)
show("Smd.Path", lambda: Smd.Path)                  # ← 最重要的一行
show("Smd.SMDType", lambda: Smd.SMDType)
show("Smd.Filename", lambda: Smd.Filename)
show("Smd.Namespace", lambda: Smd.Namespace)
show("Smd.ResultComment", lambda: Smd.ResultComment)
show("SubProject.Title", lambda: SubProject.Title)
show("SubProject.Path", lambda: SubProject.Path)
show("MeasObject.Title", lambda: MeasObject.Title)

print("[diag] ========== 標籤 ==========")
show("Tags.Exists", lambda: Tags.Exists("Setup"))
show("Tags.Value", lambda: Tags.Value("Setup"))
show("Tags 全部", lambda: [n for n in dir(Tags) if not n.startswith("_")])
show("Smd 全部", lambda: [n for n in dir(Smd) if not n.startswith("_")])
