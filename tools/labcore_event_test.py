# -*- coding: utf-8 -*-
"""實測:從 COM 改硬體設定之後,ACQUA 會不會知道。

要回答的
────────
如果自動化偷偷改了極化電壓,而 ACQUA 還以為是舊值,那就會出現
「畫面顯示 Off、實際上是 200V」這種最難查的狀態不一致。

三個層次分開驗,因為它們證明的東西不一樣:

  1. 同一個 MfeControl 嗎
     ACQUA 啟動的 MfeControl.exe 是 LocalServer32。如果我們的 Dispatch
     接到的是**同一個行程**,那就沒有兩份狀態可以不同步 —— 這是最強的保證。

  2. 事件會不會發
     ILabCoreEvents.OnDeviceParameterChanged / OnAudioBlockSettingsChanged
     是 ACQUA 用來重畫畫面的機制。事件真的發出來,代表通知路徑是通的。

  3. ACQUA 自己的設定檔會不會跟著變
     ACQUAlyzer5.XML 裡的 <MicCardSettings> 是 ACQUA 的持久化狀態。

注意
────
會真的改值(Ch3&4 的極化電壓 Off <-> 200V),結束一定還原,放在 finally。
"""
from __future__ import annotations

import io
import os
import re
import sys
import time

import pythoncom
import win32com.client as w

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

XML = r"C:\ProgramData\HEAD acoustics\ACQUA\ACQUAlyzer5.XML"
POL = {0: "Off", 1: "200 V", 2: "28 V"}

fired = []


class LabCoreEvents:
    """事件接收器。每個回呼只記下來,不做事 —— 這是觀測用的。"""

    def OnDeviceParameterChanged(self, *a):
        fired.append("OnDeviceParameterChanged")

    def OnAudioBlockSettingsChanged(self, *a):
        fired.append("OnAudioBlockSettingsChanged")

    def OnAudioBlockSettingsChangedDeprecated(self, *a):
        fired.append("OnAudioBlockSettingsChangedDeprecated")

    def OnStateChanged(self, *a):
        fired.append("OnStateChanged")

    def OnDeviceConnected(self, *a):
        fired.append("OnDeviceConnected")

    def OnDeviceDisconnected(self, *a):
        fired.append("OnDeviceDisconnected")


def xml_miccard():
    """把 ACQUA 設定檔裡的 MicCardSettings 區塊抓出來。"""
    if not os.path.exists(XML):
        return None, None
    t = io.open(XML, encoding="utf-8", errors="replace").read()
    m = re.search(r"<MicCardSettings.*?</MicCardSettings>", t, re.S)
    return (m.group(0) if m else None), os.path.getmtime(XML)


def pump(seconds):
    """讓 COM 事件有機會送進來 —— 沒有訊息幫浦就收不到回呼。"""
    end = time.time() + seconds
    while time.time() < end:
        pythoncom.PumpWaitingMessages()
        time.sleep(0.05)


def main():
    pythoncom.CoInitialize()

    # ── 1. 是不是同一個 MfeControl ───────────────
    import subprocess
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process MfeControl).Id -join ','"],
        capture_output=True, text=True).stdout.strip()
    print("測試 1 —— 是不是同一個 MfeControl 行程")
    print("   連線前 MfeControl PID: %s" % (out or "(沒有)"))

    ctrl = w.Dispatch("MfeControlLib.LabCoreControl")
    out2 = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process MfeControl).Id -join ','"],
        capture_output=True, text=True).stdout.strip()
    print("   連線後 MfeControl PID: %s" % (out2 or "(沒有)"))
    same = (out == out2 and out != "")
    print("   -> %s\n" % ("同一個行程,沒有第二份狀態" if same
                          else "PID 有變,可能另外起了一個 —— 要留意"))

    dev = ctrl.Items(0)
    bs = dev.AudioWiring.Blocks
    mic = None
    for i in range(bs.Count):
        b = bs.Items(i)
        if b.ID == "mic|0|":
            mic = b.Settings
            break

    # ── 2. 事件會不會發 ──────────────────────────
    print("測試 2 —— 改值時事件會不會發出來")
    sink = None
    for target, label in ((dev, "device"), (ctrl, "control")):
        try:
            sink = w.WithEvents(target, LabCoreEvents)
            print("   事件接收器掛在 %s 上" % label)
            break
        except Exception as exc:                            # noqa: BLE001
            print("   掛在 %s 上失敗:%s" % (label, str(exc)[-70:]))
    if sink is None:
        print("   -> 掛不上,這一項無法判定")

    before_xml, before_mt = xml_miccard()
    cur = mic.ChannelPair(1).PolarizationVoltage
    new = 1 if cur == 0 else 0
    print("   把 ChannelPair(1) 從 %s 改成 %s" % (POL.get(cur), POL.get(new)))

    fired.clear()
    changed = False
    try:
        mic.BeginUpdate()
        mic.ChannelPair(1).PolarizationVoltage = new
        mic.EndUpdate()
        changed = True
        pump(3.0)
        print("   讀回:%s" % POL.get(mic.ChannelPair(1).PolarizationVoltage))
        if fired:
            from collections import Counter
            print("   收到事件:%s"
                  % ", ".join("%s x%d" % (k, v)
                              for k, v in Counter(fired).items()))
        else:
            print("   收到事件:(無)")

        # ── 3. ACQUA 的設定檔有沒有跟著變 ──────
        print("\n測試 3 —— ACQUA 的 ACQUAlyzer5.XML 有沒有跟著變")
        pump(2.0)
        after_xml, after_mt = xml_miccard()
        if before_xml is None:
            print("   讀不到設定檔")
        else:
            print("   檔案時間有變:%s" % (before_mt != after_mt))
            print("   MicCardSettings 內容有變:%s" % (before_xml != after_xml))
            v = re.search(r"<VoltageOnCh3_4>([^<]*)", after_xml or "")
            print("   檔案裡的 VoltageOnCh3_4 = %s" % (v.group(1) if v else "?"))
            print("   （ACQUA 通常在關閉或存檔時才寫這個檔，"
                  "所以沒變不代表 ACQUA 內部不知道）")
    finally:
        if changed:
            mic.BeginUpdate()
            mic.ChannelPair(1).PolarizationVoltage = cur
            mic.EndUpdate()
            pump(1.0)
            print("\n已還原:ChannelPair(1) = %s"
                  % POL.get(mic.ChannelPair(1).PolarizationVoltage))
    return 0


if __name__ == "__main__":
    sys.exit(main())
