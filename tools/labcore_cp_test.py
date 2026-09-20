# -*- coding: utf-8 -*-
"""實測:從 COM 改設定時,通知事件到底有沒有發出來。

為什麼要繞到連接點這一層
────────────────────────
win32com 的 WithEvents 需要物件有 coclass 才能推斷事件介面。
但真正會發「設定變了」的兩個介面掛在裸 dispatch 物件上:

    ILabCoreEvents         來源是 ILabCore（裝置）      OnDeviceParameterChanged
    ILabCoreWiringEvents   來源是 ILabCoreAudioWiring   OnBlockSettingsChanged

它們都沒有 coclass,所以 WithEvents 一律回「does not support events」。
先前那次測試就是掛錯在 LabCoreControl 上 —— 它的事件介面是
ILabCoreControlEvents,只有 USB 接上/拔掉兩個事件,跟設定無關,
所以「沒收到事件」是掛錯地方,不是真的沒發。

這支改用底層做法:
    QueryInterface(IConnectionPointContainer)
      -> FindConnectionPoint(IID)
        -> Advise(sink)

sink 用 EventHandlerPolicy 包裝,靠 _dispid_to_func_ 把 Invoke 的
dispid 對到 Python 方法 —— 事件來源是用 dispid 呼叫的,不是用名字。

這在回答什麼
────────────
如果通知路徑是通的,ACQUA 開著的畫面就會收到同一個通知而重畫,
不會出現「畫面顯示 Off、實際是 200V」的狀態不一致。
"""
from __future__ import annotations

import sys
import time

import pythoncom
import pywintypes
import win32com.client as w
import win32com.server.policy
import win32com.server.util

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

IID_LABCORE_EVENTS = pywintypes.IID("{9972D4B5-63A6-4D48-8246-389C3A214E86}")
IID_WIRING_EVENTS = pywintypes.IID("{EF473E9B-B58D-479C-808E-7AB4588350F0}")

POL = {0: "Off", 1: "200 V", 2: "28 V"}
fired = []


class _SinkBase:
    """事件接收器共用的骨架。

    `_dispid_to_func_` 是關鍵:事件來源是用 dispid 呼叫 Invoke 的,
    不是用方法名字,所以一定要自己把對應表給出來。
    """

    _public_methods_ = []

    def _log(self, name, *a):
        fired.append(name)

    def __getattr__(self, name):
        if name.startswith("On"):
            return lambda *a: self._log(name, *a)
        raise AttributeError(name)


def make_sink(dispids, iid):
    """依 dispid 表生出一個接收器類別,包裝成 COM 物件。"""
    ns = {"_dispid_to_func_": dict(dispids),
          "_public_methods_": [v for v in dispids.values()]}
    for did, fname in dispids.items():
        ns[fname] = (lambda n: (lambda self, *a: self._log(n)))(fname)
    cls = type("Sink_%s" % iid.hex[:6] if hasattr(iid, "hex") else "Sink",
               (_SinkBase,), ns)
    return win32com.server.util.wrap(
        cls(), usePolicy=win32com.server.policy.EventHandlerPolicy)


LABCORE_IDS = {201: "OnDeviceConnected", 202: "OnDeviceDisconnected",
               203: "OnDeviceParameterChanged",
               204: "OnAudioPlaybackParameterChanged", 205: "OnStateChanged",
               215: "OnAudioBlockSettingsChangedDeprecated"}
WIRING_IDS = {201: "OnBlockChanged", 202: "OnBlockSettingsChanged",
              203: "OnConnectionChanged"}


def advise(obj, iid, dispids, label):
    """把接收器掛到物件的連接點上。回 (cp, cookie) 或 None。"""
    try:
        cpc = obj._oleobj_.QueryInterface(
            pythoncom.IID_IConnectionPointContainer)
        cp = cpc.FindConnectionPoint(iid)
        cookie = cp.Advise(make_sink(dispids, iid))
        print("   掛上 %s（cookie=%s）" % (label, cookie))
        return cp, cookie
    except Exception as exc:                                # noqa: BLE001
        print("   掛 %s 失敗:%s" % (label, str(exc)[-80:]))
        return None


def pump(seconds):
    end = time.time() + seconds
    while time.time() < end:
        pythoncom.PumpWaitingMessages()
        time.sleep(0.05)


def main():
    pythoncom.CoInitialize()
    ctrl = w.Dispatch("MfeControlLib.LabCoreControl")
    dev = ctrl.Items(0)
    wiring = dev.AudioWiring
    bs = wiring.Blocks
    mic = None
    for i in range(bs.Count):
        b = bs.Items(i)
        if b.ID == "mic|0|":
            mic = b.Settings
            break

    print("掛事件接收器:")
    h1 = advise(dev, IID_LABCORE_EVENTS, LABCORE_IDS, "ILabCoreEvents（裝置）")
    h2 = advise(wiring, IID_WIRING_EVENTS, WIRING_IDS,
                "ILabCoreWiringEvents（接線）")
    if not (h1 or h2):
        print("兩個都掛不上,無法判定")
        return 1

    cur = mic.ChannelPair(1).PolarizationVoltage
    new = 1 if cur == 0 else 0
    print("\n把 ChannelPair(1) 從 %s 改成 %s" % (POL.get(cur), POL.get(new)))

    fired.clear()
    changed = False
    try:
        mic.BeginUpdate()
        mic.ChannelPair(1).PolarizationVoltage = new
        mic.EndUpdate()
        changed = True
        pump(4.0)
        print("讀回:%s" % POL.get(mic.ChannelPair(1).PolarizationVoltage))
        from collections import Counter
        if fired:
            print("\n收到事件:")
            for k, v in Counter(fired).items():
                print("   %-42s x%d" % (k, v))
        else:
            print("\n收到事件:(無)")
    finally:
        if changed:
            fired.clear()
            mic.BeginUpdate()
            mic.ChannelPair(1).PolarizationVoltage = cur
            mic.EndUpdate()
            pump(2.0)
            print("\n已還原:ChannelPair(1) = %s   還原時也收到 %d 個事件"
                  % (POL.get(mic.ChannelPair(1).PolarizationVoltage),
                     len(fired)))
        for h in (h1, h2):
            if h:
                try:
                    h[0].Unadvise(h[1])
                except Exception:                           # noqa: BLE001
                    pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
