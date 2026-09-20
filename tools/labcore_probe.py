# -*- coding: utf-8 -*-
"""labCORE 硬體設定 —— 讀取現況(唯讀)。

這支在回答什麼
──────────────
「麥克風供電/極化電壓能不能用程式切換?」

`Acqua3COM.chm` 那 137 個主題裡沒有任何硬體 API,所以一開始的結論是不行。
但註冊表裡有一整組**沒有文件**的 COM 類別,型別庫(546 個型別)裡有:

    ILabCoreAudioBlockSettingsMicrophoneIn
        SupplyVoltageMode                   get/put   <- 供應電壓下拉
        ChannelPair(n) / Channel(n)
        BeginUpdate() / EndUpdate()                   <- 批次套用
    ILabCoreAudioBlockSettingsMicrophoneInChannelPair
        PolarizationVoltage                 get/put   <- 200V 勾選
    ILabCoreAudioBlockSettingsMicrophoneInChannel
        SupplyVoltageOn                     get/put

    ELabCoreSupplyVoltage        Off=0  PlusMinus60V=1  Plus120V=2  PlusMinus14V=3
    ELabCorePolarizationVoltage  Off=0  200V=1          28V=2

這支把上面那條路實際走一遍,把**目前**的值讀出來跟 ACQUA 畫面對照。
讀得到而且對得上 = 這條路通。

為什麼只讀
──────────
寫進去會**真的改變量測硬體的通道供電**。設錯不會有錯誤訊息,
只會讓之後的量測數據靜靜地變成錯的 —— 那是最難查的一種錯。
所以寫入要另外明確授權,不放在這支裡。

為什麼優先附著而不是新建
────────────────────────
MfeControl.exe 是 LocalServer32,而 ACQUA 已經開著一個、正連著 labCORE。
再 CoCreateInstance 一個新的可能會跟 ACQUA 搶同一台硬體。
所以先試 GetActiveObject 掛到現有那個,失敗才退回 Dispatch。
"""
from __future__ import annotations

import sys

import pythoncom
import win32com.client as w

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROGID = "MfeControlLib.LabCoreControl"

SUPPLY = {-1: "Unknown", 0: "Off", 1: "± 60 V", 2: "+120 V", 3: "± 14 V"}
POLAR = {-1: "Unknown", 0: "Off", 1: "200 V", 2: "28 V"}


def attach():
    """先掛現有的,不行才新建。回 (物件, 用哪種方式)。"""
    try:
        return w.GetActiveObject(PROGID), "附著到執行中的 MfeControl"
    except pythoncom.com_error:
        return w.Dispatch(PROGID), "新建實例（ROT 裡沒有現成的）"


def get(obj, name, *args):
    """讀屬性,讀不到就回錯誤字串而不是炸掉 —— 這是探路用的。"""
    try:
        v = getattr(obj, name)
        return v(*args) if args and callable(v) else v
    except Exception as exc:                                # noqa: BLE001
        return "<%s>" % str(exc).split(",")[-1].strip(" )'\"")[:50]


def walk_mic(settings, label):
    """把一個麥克風輸入區塊的供電設定印出來。"""
    print("   %s" % label)
    mode = get(settings, "SupplyVoltageMode")
    print("      供應電壓 SupplyVoltageMode = %s  -> %s"
          % (mode, SUPPLY.get(mode, "?")))

    n = get(settings, "ChannelCount")
    print("      通道數 ChannelCount = %s" % n)

    if isinstance(n, int):
        # 成對的極化電壓 —— 對應畫面上的 Channels 1&2 / 3&4
        for pair in range(max(1, n // 2)):
            try:
                cp = settings.ChannelPair(pair)
                pv = get(cp, "PolarizationVoltage")
                print("      ChannelPair(%d).PolarizationVoltage = %s  -> %s"
                      % (pair, pv, POLAR.get(pv, "?")))
            except Exception as exc:                        # noqa: BLE001
                print("      ChannelPair(%d) 讀不到:%s" % (pair, str(exc)[:60]))
        # 每通道的供電開關
        for ch in range(n):
            try:
                c = settings.Channel(ch)
                print("      Channel(%d)  SupplyVoltageOn=%-6s "
                      "PolarizationVoltage=%s"
                      % (ch, get(c, "SupplyVoltageOn"),
                         POLAR.get(get(c, "PolarizationVoltage"), "?")))
            except Exception as exc:                        # noqa: BLE001
                print("      Channel(%d) 讀不到:%s" % (ch, str(exc)[:60]))


def main():
    pythoncom.CoInitialize()
    try:
        ctrl, how = attach()
    except pythoncom.com_error as exc:
        print("連不上 %s:%s" % (PROGID, exc))
        return 1
    print("%s（%s）\n" % (PROGID, how))

    count = get(ctrl, "Count")
    print("找到 %s 台 labCORE  (InitialSearchCompleted=%s)\n"
          % (count, get(ctrl, "InitialSearchCompleted")))
    if not isinstance(count, int) or count == 0:
        print("沒有裝置 —— 可能 ACQUA 佔著,或搜尋還沒完成")
        return 1

    for i in range(count):
        dev = ctrl.Items(i)
        print("── labCORE #%d ──" % i)
        for p in ("Availability",):
            print("   %s = %s" % (p, get(dev, p)))

        d = get(dev, "Device")
        if not isinstance(d, str):
            for p in ("Name", "SerialNumber", "FirmwareVersion", "Connected"):
                print("   Device.%s = %s" % (p, get(d, p)))

        # 區塊掛在 AudioWiring 底下,不是 AudioSystem —— AudioSystem 管的是
        # 取樣率/時脈那一層。
        audio = get(dev, "AudioWiring")
        if isinstance(audio, str):
            print("   AudioWiring 讀不到:%s" % audio)
            continue

        blocks = get(audio, "Blocks")
        nb = get(blocks, "Count")
        print("   AudioSystem.Blocks.Count = %s" % nb)
        if not isinstance(nb, int):
            continue

        for b in range(nb):
            blk = blocks.Items(b)
            bid = get(blk, "ID")
            name = get(blk, "Name")
            btype = get(blk, "BlockType")
            st = get(blk, "Settings")
            has_mic = not isinstance(st, str) and not isinstance(
                get(st, "SupplyVoltageMode"), str)
            mark = "  <-- 麥克風輸入" if has_mic else ""
            print("   [%2d] ID=%-14s type=%-5s %s%s"
                  % (b, bid, btype, name, mark))
            if has_mic:
                walk_mic(st, "設定:")
    return 0


if __name__ == "__main__":
    sys.exit(main())
