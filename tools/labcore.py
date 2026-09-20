# -*- coding: utf-8 -*-
"""labCORE 硬體狀態 —— 讀取與診斷。

這支取代了八支一次性的探路腳本(labcore_ws / labcore_probe /
labcore_which_setup / labcore_write_test / labcore_usb_write_test /
labcore_event_test / labcore_cp_test / labcore_autoswitch_test)。
那些是為了回答「能不能用程式控制硬體」而寫的,問題已經有答案,
留著只會讓人以為每一支都還有用。結論記在 README 的「硬體設定」一節。

背景
────
`Acqua3COM.chm` 那 137 個主題裡沒有硬體 API,但機器上另外裝了一組
**沒有文件**的 COM 程式庫 `MfeControlLib`(546 個型別),硬體在那裡:

    MfeControlLib.LabCoreControl -> MfeControl.exe（ACQUA 已經開著的那個）
      .Items(0).AudioWiring.Blocks        83 個區塊
         mic|0|      type=9   = ACQUA「labCORE選項/麥克風選項」
         usbaudio|0| type=16  = 「USB Audio Host Settings」

誰管哪一塊（實測結論,別再重測)
──────────────────────────────
    接線路由 Connections   ACQUA 自己管 —— 量測開始套用、結束還原
    麥克風供電/極化電壓     **沒人管**
    USB Audio Host 設定    **沒人管**

沒人管的那兩塊設錯不會報錯,只會讓數據靜靜地變成錯的
(實測:極化電壓關著跑完,ACQUA 照樣回報 PASS)。所以這支的重點是
**看得到現況**,好在跑之前比對。

「目前是哪一組設定」不要用接線去反推
────────────────────────────────────
本來寫過一支比對接線指紋的工具,但那只能縮到幾個候選。
服務本身就有 `/acqua/api/hardware`,底層是
`project.MeasurementEngine.HardwareConfig.Settings.ActiveSetting`,
直接給名字。要查名字用那個,不要用這支。

用法
────
    python tools/labcore.py              麥克風 + USB + 接線摘要
    python tools/labcore.py --blocks     連 83 個區塊一起列
    python tools/labcore.py --json       給程式用
"""
from __future__ import annotations

import argparse
import json
import sys

import pythoncom
import win32com.client as w

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROGID = "MfeControlLib.LabCoreControl"

SUPPLY = {-1: "Unknown", 0: "Off", 1: "± 60 V", 2: "+120 V", 3: "± 14 V"}
POLAR = {-1: "Unknown", 0: "Off", 1: "200 V", 2: "28 V"}


def _get(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:                                       # noqa: BLE001
        return default


def connect():
    """回 (device, blocks)。接的是 ACQUA 已經開著的那個 MfeControl。"""
    pythoncom.CoInitialize()
    dev = w.Dispatch(PROGID).Items(0)
    return dev, dev.AudioWiring.Blocks


def find_block(blocks, block_id):
    for i in range(blocks.Count):
        b = blocks.Items(i)
        if b.ID == block_id:
            return b
    return None


def read_mic(blocks):
    """麥克風卡:供電模式、成對的極化電壓、每通道開關。"""
    b = find_block(blocks, "mic|0|")
    if b is None:
        return None
    s = b.Settings
    n = _get(s, "ChannelCount", 0) or 0
    return {
        "supply_mode": _get(s, "SupplyVoltageMode"),
        "channel_count": n,
        "pairs": [s.ChannelPair(p).PolarizationVoltage
                  for p in range(max(0, n // 2))],
        "channels": [{"supply_on": bool(s.Channel(c).SupplyVoltageOn),
                      "polarization": s.Channel(c).PolarizationVoltage}
                     for c in range(n)],
    }


def read_usb(blocks):
    """USB Audio Host:裝置清單與播放/錄音參數。"""
    b = find_block(blocks, "usbaudio|0|")
    if b is None:
        return None
    s = b.Settings

    def side(o):
        return {"channels": _get(o, "Channels"),
                "sample_rate": _get(o, "SampleRate"),
                "format": _get(o, "Format")}

    devs = _get(s, "Devices")
    return {
        "any_device": bool(_get(s, "AnyDeviceAvailable", False)),
        "device_count": _get(devs, "Count", 0),
        "state": _get(s, "State"),
        "auto_resampling": _get(s, "AutoResampling"),
        "playback": side(_get(s, "PlaybackSettings")),
        "capture": side(_get(s, "CaptureSettings")),
    }


def read_wiring(dev):
    """目前作用中的接線,正規化成 (block,pin) 配對。"""
    conns = dev.AudioWiring.ActiveConnections
    out = []
    for i in range(conns.Count):
        c = conns.Items(i)
        try:
            p1, p2 = c.Pin1, c.Pin2
            out.append(sorted([(p1.Block.ID, p1.ID), (p2.Block.ID, p2.ID)]))
        except Exception:                                   # noqa: BLE001
            continue
    return sorted(out)


def snapshot(with_blocks=False):
    dev, blocks = connect()
    d = _get(dev, "Device")
    snap = {
        "serial": str(_get(d, "SerialNumber", "")),
        "mic": read_mic(blocks),
        "usb": read_usb(blocks),
        "wiring": read_wiring(dev),
    }
    if with_blocks:
        snap["blocks"] = [{"id": blocks.Items(i).ID,
                           "type": blocks.Items(i).BlockType,
                           "name": str(blocks.Items(i).Name)}
                          for i in range(blocks.Count)]
    return snap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks", action="store_true", help="列出全部區塊")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    snap = snapshot(args.blocks)
    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
        return 0

    print("labCORE %s\n" % snap["serial"])

    m = snap["mic"]
    if m:
        print("麥克風卡 mic|0|   （ACQUA 不會自動設這裡)")
        print("   供應電壓 %s" % SUPPLY.get(m["supply_mode"], m["supply_mode"]))
        for i, p in enumerate(m["pairs"]):
            print("   Channels %d & %d  極化電壓 %s"
                  % (i * 2 + 1, i * 2 + 2, POLAR.get(p, p)))
        for i, c in enumerate(m["channels"]):
            print("      Ch%d  供電 %-5s 極化 %s"
                  % (i + 1, "On" if c["supply_on"] else "Off",
                     POLAR.get(c["polarization"], c["polarization"])))
        print()

    u = snap["usb"]
    if u:
        print("USB Audio Host usbaudio|0|   （ACQUA 不會自動設這裡)")
        print("   裝置 %d 個（有可用裝置:%s)"
              % (u["device_count"], u["any_device"]))
        for k in ("playback", "capture"):
            s = u[k]
            print("   %-9s %s ch / %s Hz / %s"
                  % (k, s["channels"], s["sample_rate"], s["format"]))
        print()

    print("作用中的接線 %d 條   （這一塊 ACQUA 會自己切,不要手動改)"
          % len(snap["wiring"]))
    for c in snap["wiring"]:
        print("   %s" % " <-> ".join("%s %s" % p for p in c))

    if args.blocks:
        print("\n區塊 %d 個:" % len(snap["blocks"]))
        for b in snap["blocks"]:
            print("   %-14s type=%-4s %s" % (b["id"], b["type"], b["name"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
