# -*- coding: utf-8 -*-
"""實測:USB Audio Host 區塊的設定寫不寫得動。

背景
────
第二張截圖那個「USB Audio Host Settings」對應的是 usbaudio|0| 區塊
(type=16)。先前只讀過,沒寫過。

現在 MeetUp 2 沒插在 labCORE 的 USB host 埠上,所以
Devices.Count = 0、AnyDeviceAvailable = False ——
**裝置選擇測不了**。但其他成員可以測,而且這正好回答一個實際問題:
沒有裝置在線時,這些設定是可寫的,還是會被擋?

這件事對自動化很重要:如果沒裝置就不能預先設定,那流程就得是
「先插上 -> 才能設定」;如果可以先設,就能在裝置接上之前先準備好。

測法
────
每一項都:讀現值 -> 寫一個不同的值 -> 讀回確認 -> 還原 -> 再讀回確認。
還原一律放在 finally。
"""
from __future__ import annotations

import sys
import time

import pythoncom
import win32com.client as w

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def usb_settings():
    c = w.Dispatch("MfeControlLib.LabCoreControl")
    dev = c.Items(0)
    bs = dev.AudioWiring.Blocks
    for i in range(bs.Count):
        b = bs.Items(i)
        if b.ID == "usbaudio|0|":
            return dev, b.Settings
    raise RuntimeError("找不到 usbaudio|0|")


def try_write(owner, prop, newval, label, use_update=None):
    """讀 -> 寫不同值 -> 讀回 -> 還原 -> 讀回。回 (結果字串, 是否還原成功)。"""
    try:
        before = getattr(owner, prop)
    except Exception as exc:                                # noqa: BLE001
        return "讀不到:%s" % str(exc)[-60:], True

    if before == newval:
        return "略過(現值就等於要測的值 %r)" % (newval,), True

    changed = False
    try:
        if use_update:
            use_update.BeginUpdate()
        setattr(owner, prop, newval)
        if use_update:
            use_update.EndUpdate()
        changed = True
        time.sleep(0.4)
        mid = getattr(owner, prop)
        took = (mid == newval)
        result = "%r -> 寫 %r -> 讀回 %r   %s" % (
            before, newval, mid, "生效" if took else "沒生效(被忽略)")
    except Exception as exc:                                # noqa: BLE001
        msg = str(exc)
        return "%r -> 寫 %r 被拒:%s" % (before, newval, msg[-90:]), True
    finally:
        if changed:
            try:
                if use_update:
                    use_update.BeginUpdate()
                setattr(owner, prop, before)
                if use_update:
                    use_update.EndUpdate()
                time.sleep(0.3)
            except Exception as exc:                        # noqa: BLE001
                return ("%s   !! 還原失敗:%s" % (label, exc)), False

    ok = (getattr(owner, prop) == before)
    return result + ("   還原OK" if ok else "   !! 還原後不一致"), ok


def main():
    pythoncom.CoInitialize()
    dev, usb = usb_settings()
    print("labCORE %s ・ 區塊 usbaudio|0|" % dev.Device.SerialNumber)
    print("  AnyDeviceAvailable = %s   Devices.Count = %s   State = %s"
          % (usb.AnyDeviceAvailable, usb.Devices.Count, usb.State))
    print("  （沒有 USB 裝置在線 —— 裝置選擇這一項測不了）\n")

    allok = True

    print("── 區塊層級 ──")
    r, ok = try_write(usb, "AutoResampling", not usb.AutoResampling,
                      "AutoResampling", use_update=usb)
    allok &= ok
    print("  %-18s %s" % ("AutoResampling", r))

    for side in ("PlaybackSettings", "CaptureSettings"):
        o = getattr(usb, side)
        print("\n── %s ──" % side)
        for prop, newval in (("SampleRate", 44100),
                             ("Channels", 2),
                             ("Format", "S24_LE")):
            r, ok = try_write(o, prop, newval, "%s.%s" % (side, prop),
                              use_update=usb)
            allok &= ok
            print("  %-12s %s" % (prop, r))

    print("\n全部還原成功:%s" % ("是" if allok else "否 —— 請檢查"))
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
