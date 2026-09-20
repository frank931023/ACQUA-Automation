# -*- coding: utf-8 -*-
"""實測:用 COM 把麥克風極化電壓改成**不同的值**,確認硬體真的跟著動。

在測什麼
────────
前一支 labcore_probe.py 證明了讀得到,也證明 put 存取子可以呼叫 ——
但那次是刻意寫回**相同的值**,所以沒有證明「改成不同值會真的生效」。
這支補上那一刀。

    讀現值 -> 改成不同值 -> 讀回確認有變 -> 還原 -> 讀回確認還原成功

安全設計
────────
・目標鎖定 ChannelPair(1)(= 畫面上的 Channels 3 & 4),它現在是 Off。
  Ch1&2 正在用,不碰。
・先用 CanPolarizationVoltage() 問硬體支援哪些值,不硬塞。
・**還原寫在 finally 裡**:中途炸掉、Ctrl+C 都會還原。這是整支最重要的一行。
・全程每一步都讀回來印出來,不假設寫入有生效。

為什麼敢動這兩個通道
────────────────────
這台的 7 支麥克風在 WorkplaceSettingsV3.sdb 裡全部是 Polarization=1,
也就是都需要 200V —— 對它們來說「開」才是正常狀態,不是異常狀態。
而且 12 組硬體接線設定裡只有 Teams_chamber_v5 用到 Ch4,
它沒有被任何資料庫的 MMD 引用。
"""
from __future__ import annotations

import sys
import time

import pythoncom
import win32com.client as w

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

POL = {-1: "Unknown", 0: "Off", 1: "200 V", 2: "28 V"}
TARGET_PAIR = 1                      # 畫面上的 Channels 3 & 4


def mic_settings():
    c = w.Dispatch("MfeControlLib.LabCoreControl")
    dev = c.Items(0)
    blocks = dev.AudioWiring.Blocks
    for i in range(blocks.Count):
        b = blocks.Items(i)
        if b.ID == "mic|0|":
            return dev, b.Settings
    raise RuntimeError("找不到 mic|0| 區塊")


def read(mic):
    return {p: mic.ChannelPair(p).PolarizationVoltage for p in (0, 1)}


def show(tag, st):
    print("  %-10s pair0(Ch1&2)=%-8s pair1(Ch3&4)=%s"
          % (tag, POL.get(st[0], st[0]), POL.get(st[1], st[1])))


def main():
    pythoncom.CoInitialize()
    dev, mic = mic_settings()
    print("labCORE 序號 %s ・ 區塊 mic|0|\n" % dev.Device.SerialNumber)

    # ── 硬體支援哪些值 ────────────────────────────
    print("硬體支援的極化電壓:")
    supported = []
    for val, name in POL.items():
        if val < 0:
            continue
        try:
            ok = bool(mic.CanPolarizationVoltage(val))
        except Exception as exc:                            # noqa: BLE001
            ok = "?(%s)" % str(exc)[:40]
        print("   %-8s -> %s" % (name, ok))
        if ok is True:
            supported.append(val)
    print()

    before = read(mic)
    show("現在", before)

    # 挑一個跟現值不同、而且硬體支援的
    cur = before[TARGET_PAIR]
    cand = [v for v in supported if v != cur]
    if not cand:
        print("\n沒有可用的不同值可測 —— 硬體只支援目前這一個")
        return 1
    # 有 28V 就用 28V,比 200V 溫和,但同樣能證明「改得動」
    new = 2 if 2 in cand else cand[0]
    print("\n要把 pair%d 從 %s 改成 %s\n" % (TARGET_PAIR, POL[cur], POL[new]))

    changed = False
    try:
        mic.BeginUpdate()
        mic.ChannelPair(TARGET_PAIR).PolarizationVoltage = new
        mic.EndUpdate()
        changed = True
        time.sleep(0.6)                  # 給硬體一點時間套用
        mid = read(mic)
        show("改之後", mid)

        took = mid[TARGET_PAIR] == new
        print("\n  改成不同值有生效:%s" % ("是" if took else "否 —— 讀回來還是舊值"))
        if mid[0] != before[0]:
            print("  !! 注意:pair0 也跟著變了(%s -> %s)"
                  % (POL.get(before[0]), POL.get(mid[0])))
    finally:
        # 不管上面發生什麼,一定還原。這是整支最重要的一段。
        if changed:
            try:
                mic.BeginUpdate()
                mic.ChannelPair(TARGET_PAIR).PolarizationVoltage = cur
                mic.EndUpdate()
                time.sleep(0.6)
            except Exception as exc:                        # noqa: BLE001
                print("\n!! 還原失敗,請手動確認 ACQUA 的 labCORE 選項:%s" % exc)
                raise

    after = read(mic)
    print()
    show("還原後", after)
    print("\n  跟一開始完全一致:%s" % ("是" if after == before else "否 !!"))
    return 0 if after == before else 1


if __name__ == "__main__":
    sys.exit(main())
