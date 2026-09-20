# -*- coding: utf-8 -*-
"""決定性實驗:ACQUA 跑測項時,會不會自己載入 MMD 宣告的硬體設定?

為什麼這題最重要
────────────────
SQL 的 MMDSettings 型別 14(Hardware_Configuration_Setting)記錄了
每個 MMD 需要哪一組 labCORE 接線設定。如果 ACQUA 執行時**自己會套用**,
那自動化這邊一行控制都不該寫 —— 寫了只會跟 ACQUA 搶,
而且是「兩邊各自以為自己贏了」的那種搶法。

反過來,如果 ACQUA 不套用,那跨資料庫序列就**必須**自己切,
因為同一個專案裡 4 組設定是交錯的。

實驗設計
────────
挑一個 MMD 宣告 COS_auto_3QUEST_240626_USB 的測項。
目前硬體載入的是 BK+GRAS 那組 —— 跟目標組只有 1 條接線相同,
目標組宣告 15 條。所以只要真的切了,差異大到不可能看錯。

分三階段,由輕到重,每一階段都先看結果再決定要不要往下:

    A 基準          現在的接線
    B 開專案+選MO   只是開啟,不跑任何東西
    C 跑一個測項    真的執行

接線用背景執行緒持續輪詢,所以「切換發生在執行中途然後又切回去」
這種情況也抓得到 —— 只看前後兩張快照會漏掉。

注意
────
階段 C 會真的跑一次量測,在 ACQUA 裡留下一筆結果。
測項選「Analy.」(純分析)還是「Record」(會放音收音)由參數決定。
"""
from __future__ import annotations

import argparse
import sys
import threading
import time

import pythoncom
import win32com.client as w

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SERVER = r"AUTOMATION_ACQU\ACQUADBSERVER"
DATABASE = "ACQUA_auto_v2026Aug"
PROJECT = "ZoomRooms_v2020Oct_v1"
GROUP = "(Unsorted Projects)"

samples = []          # (時間, 接線集合)
stop_poll = threading.Event()


def wiring_of(dev):
    conns = dev.AudioWiring.ActiveConnections
    out = set()
    for i in range(conns.Count):
        cn = conns.Items(i)
        try:
            p1, p2 = cn.Pin1, cn.Pin2
            out.add(frozenset(((p1.Block.ID, p1.ID), (p2.Block.ID, p2.ID))))
        except Exception:                                   # noqa: BLE001
            continue
    return out


def poller():
    """自己的執行緒要自己 CoInitialize,而且要自己拿一份 COM 代理。"""
    pythoncom.CoInitialize()
    c = w.Dispatch("MfeControlLib.LabCoreControl")
    dev = c.Items(0)
    t0 = time.time()
    while not stop_poll.is_set():
        try:
            samples.append((time.time() - t0, wiring_of(dev)))
        except Exception:                                   # noqa: BLE001
            pass
        time.sleep(1.0)


def summarise(base, label):
    """把輪詢結果壓成「有沒有變過」。"""
    distinct = []
    for t, s in samples:
        if not distinct or distinct[-1][1] != s:
            distinct.append((t, s))
    print("\n── %s ──" % label)
    print("   取樣 %d 次,出現 %d 種不同的接線狀態"
          % (len(samples), len(distinct)))
    for t, s in distinct:
        same = len(s & base)
        print("      t=%5.1fs  %d 條接線（與基準相同 %d 條,新增 %d,消失 %d）"
              % (t, len(s), same, len(s - base), len(base - s)))
    changed = len(distinct) > 1 or (distinct and distinct[0][1] != base)
    print("   => 接線%s" % ("**有變過**" if changed else "完全沒變"))
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smd", type=int, default=5328,
                    help="要跑的 SMD RowID（預設 5328 = 純分析測項)")
    ap.add_argument("--stage", default="AB", help="要跑哪幾階段,例如 AB 或 ABC")
    args = ap.parse_args()

    pythoncom.CoInitialize()
    lc = w.Dispatch("MfeControlLib.LabCoreControl")
    dev = lc.Items(0)

    # ── A 基準 ───────────────────────────────────
    base = wiring_of(dev)
    print("階段 A —— 基準")
    print("   目前作用中的接線:%d 條" % len(base))
    for cn in sorted(tuple(sorted(x)) for x in base):
        print("      %s" % " <-> ".join("%s %s" % p for p in cn))

    # ⚠️ 這裡必須用 Dispatch,不能用 GetActiveObject。
    #    ACQUA **不會**把自己登記進 ROT（實測等了 160 秒都等不到),
    #    它是用 CoRegisterClassObject 註冊類別工廠。
    #    但 Acqua3.AcquaApplication 的 LocalServer32 就是 Acqua6.exe,
    #    所以 ACQUA 沒開的時候 Dispatch 會**自己啟動一個**,
    #    而且引用歸零它就跟著結束 —— 要先確認 GUI 已經開好再連。
    acqua = w.Dispatch("Acqua3.AcquaApplication")
    for _ in range(60):
        pythoncom.PumpWaitingMessages()
        if acqua.AppLoadFinished:
            break
        time.sleep(1)

    # ACQUA 重啟之後不會自動接資料庫,這時候碰 ProjectGroups 會丟
    # 「Missing Connection or ConnectionString」。要自己接上。
    if not acqua.SelectedDatabaseName:
        print("\n   尚未連資料庫,連上 %s / %s ..." % (SERVER, DATABASE))
        # ⚠️ SelectDatabase 有 5 個參數:server, database, win_auth,
        #    username, password。只傳前兩個的話 ACQUA 會彈出
        #    「ACQUA SQL Server Login」對話框等人輸入,而那是 modal ——
        #    整個 COM 呼叫就卡在那裡不回來。
        acqua.SelectDatabase(SERVER, DATABASE, True, "", "")
        for _ in range(120):
            pythoncom.PumpWaitingMessages()
            if acqua.SelectedDatabaseName:
                break
            time.sleep(0.5)
    print("\n   ACQUA 資料庫 = %s / %s"
          % (acqua.SelectedSQLServerName, acqua.SelectedDatabaseName))

    # ── B 開專案 ─────────────────────────────────
    if "B" in args.stage:
        samples.clear()
        stop_poll.clear()
        th = threading.Thread(target=poller, daemon=True)
        th.start()
        print("\n階段 B —— 開專案 + 選量測物件（不跑任何東西)")
        try:
            grp = None
            for i in range(acqua.ProjectGroups.Count):
                g = acqua.ProjectGroups.Item(i)
                if str(g.Title).strip() == GROUP:
                    grp = g
                    break
            proj = None
            for i in range(grp.Projects.Count):
                p = grp.Projects.Item(i)
                if str(p.Title).strip() == PROJECT:
                    proj = p
                    break
            print("   選 %s ..." % PROJECT)
            proj.SelectAsActive()
            for _ in range(120):
                pythoncom.PumpWaitingMessages()
                if str(acqua.SelectedProject.Title).strip() == PROJECT:
                    break
                time.sleep(0.5)
            print("   已開啟:%s" % acqua.SelectedProject.Title)
            sel = acqua.SelectedProject
            mos = sel.MeasurementObjects
            print("   量測物件 %d 個" % mos.Count)
            if mos.Count:
                sel.SelectActiveMeasurementObject(mos.Item(0).RowID)
                print("   選了:%s" % mos.Item(0).Title)
            for _ in range(8):
                pythoncom.PumpWaitingMessages()
                time.sleep(0.5)
        finally:
            time.sleep(2)
            stop_poll.set()
            th.join(timeout=4)
        summarise(base, "階段 B 結果")
        base = wiring_of(dev)

    # ── C 跑測項 ─────────────────────────────────
    if "C" in args.stage:
        samples.clear()
        stop_poll.clear()
        th = threading.Thread(target=poller, daemon=True)
        th.start()
        print("\n階段 C —— 執行 SMD #%d" % args.smd)
        try:
            sel = acqua.SelectedProject
            mos = sel.MeasurementObjects
            mo = mos.Item(0)
            print("   StartSingleMeasurement(%d, True, mo, 'hw-autoswitch-test')"
                  % args.smd)
            sel.StartSingleMeasurement(args.smd, True, mo,
                                       "hw-autoswitch-test")
            t0 = time.time()
            while time.time() - t0 < 180:
                pythoncom.PumpWaitingMessages()
                if not acqua.IsMeasuring:
                    break
                time.sleep(0.5)
            print("   量測結束（耗時 %.1fs,IsMeasuring=%s)"
                  % (time.time() - t0, acqua.IsMeasuring))
        except Exception as exc:                            # noqa: BLE001
            print("   執行時出錯:%s" % str(exc)[-200:])
        finally:
            time.sleep(2)
            stop_poll.set()
            th.join(timeout=4)
        summarise(base, "階段 C 結果")

    return 0


if __name__ == "__main__":
    sys.exit(main())
