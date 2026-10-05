# -*- coding: utf-8 -*-
"""labCORE 硬體現況 —— 命令列檢視。

邏輯全部在 `acqua/labcore.py`,這支只負責把它印得好看。
(先前這支自己實作了一份連線與讀取,跟模組重複 —— 已經收掉。)

誰管哪一塊(實測結論,別再重測)
──────────────────────────────
    接線路由 Connections   ACQUA 自己管 —— 量測開始套用、結束還原
    麥克風供電/極化電壓     **沒人管**,設錯會靜默產生廢資料
    USB Audio Host 設定    **沒人管**

「目前載入的是哪一組設定」不要用接線去反推 —— 服務本身有
`/acqua/api/hardware`,底層是 `HardwareConfig.Settings.ActiveSetting`,
直接給名字。

用法
────
    python tools/labcore.py              麥克風 + USB + 接線摘要
    python tools/labcore.py --blocks     連 83 個區塊一起列
    python tools/labcore.py --json       給程式用
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from acqua import labcore                                   # noqa: E402


def blocks_of(dev):
    bs = dev.AudioWiring.Blocks
    return [{"id": bs.Items(i).ID,
             "type": bs.Items(i).BlockType,
             "name": str(bs.Items(i).Name)}
            for i in range(bs.Count)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks", action="store_true", help="列出全部區塊")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    import pythoncom
    pythoncom.CoInitialize()

    try:
        dev, mic = labcore.connect()
    except labcore.LabCoreUnavailable as exc:
        print("連不上 labCORE:%s" % exc)
        return 1

    state = labcore.read_state()
    usb = labcore.read_usb(dev)
    wiring = labcore.wiring(dev)

    if args.json:
        out = {"mic": state, "usb": usb, "wiring": wiring}
        if args.blocks:
            out["blocks"] = blocks_of(dev)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    print("labCORE %s\n" % dev.Device.SerialNumber)

    print("麥克風卡 mic|0|   （ACQUA 不會自動設這裡)")
    print("   供應電壓 %s" % state["supply_label"])
    for i, p in enumerate(state["pairs"]):
        print("   Channels %d & %d  極化電壓 %s"
              % (i * 2 + 1, i * 2 + 2, labcore.POL_NAMES.get(p, p)))
    print("   接線實際用到通道 %s"
          % (", ".join(map(str, state["routed"])) or "無"))
    bad = labcore.mismatch(state)
    print("   %s" % ("⚠️ " + bad if bad else "供電與接線相符"))
    print()

    if usb:
        print("USB Audio Host usbaudio|0|   （ACQUA 不會自動設這裡)")
        print("   裝置 %d 個（有可用裝置:%s)"
              % (usb["device_count"], usb["any_device"]))
        for side in ("playback", "capture"):
            s = usb[side]
            print("   %-9s %s ch / %s Hz / %s"
                  % (side, s["channels"], s["sample_rate"], s["format"]))
        print()

    print("作用中的接線 %d 條   （這一塊 ACQUA 會自己切,不要手動改)"
          % len(wiring))
    for c in wiring:
        print("   %s" % " <-> ".join("%s %s" % tuple(p) for p in c))

    if args.blocks:
        bl = blocks_of(dev)
        print("\n區塊 %d 個:" % len(bl))
        for b in bl:
            print("   %-14s type=%-4s %s" % (b["id"], b["type"], b["name"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
