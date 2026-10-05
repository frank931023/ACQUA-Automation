# -*- coding: utf-8 -*-
"""labCORE 麥克風供電 —— 讀取與切換。

為什麼需要這個模組
──────────────────
一組 labCORE 硬體設定包含三塊,**ACQUA 只自動處理第一塊**:

    Connections        接線路由         ACQUA 量測開始套用、結束還原
    MicCardSettings    供電/極化電壓     沒人管  ← 這個模組負責
    usbaudio 區塊      USB 音訊參數      沒人管

實測過的危險情況(2026-09-21):載入 `Teams_chamber_v5` 之後,
ACQUA 把麥克風訊號路由到**通道 4**,但通道 3&4 的極化電壓是 Off ——
訊號接到一個沒有供電的通道上。而那樣跑完,ACQUA 回報 **PASS**。
設錯不會有錯誤訊息,只會讓數據靜靜地變成錯的。

極化電壓是**成對**的(畫面上就是 Channels 1 & 2 一個勾、3 & 4 一個勾),
所以切換的單位是「對」,不是單一通道。

走哪條路
────────
不是 `Acqua3`,是另一組**沒有文件**的 COM 程式庫 `MfeControlLib`
(546 個型別,`Acqua3COM.chm` 完全沒提)。SQL 這條路不存在 ——
ACQUA 的資料庫裡沒有任何硬體設定欄位,硬體狀態在 labCORE 那台機器上。

    MfeControlLib.LabCoreControl -> MfeControl.exe
      .Items(0).AudioWiring.Blocks -> mic|0|.Settings
         .SupplyVoltageMode                     ±60V 等
         .ChannelPair(n).PolarizationVoltage    0=Off 1=200V 2=28V
         .BeginUpdate() / .EndUpdate()          批次套用

`Dispatch` 接到的是 **ACQUA 已經開著的那個 MfeControl 行程**,不是另開
一個搶硬體 —— 實測連線前後 PID 不變。而且實測確認 ACQUA 載入硬體設定
時**不會覆蓋**這裡設的電壓,兩邊管的是不同東西。
"""
from __future__ import annotations

PROGID = "MfeControlLib.LabCoreControl"

#: ELabCorePolarizationVoltage
POL_OFF, POL_200V, POL_28V = 0, 1, 2

#: ELabCoreSupplyVoltage
SUPPLY_NAMES = {-1: "Unknown", 0: "Off", 1: "±60 V", 2: "+120 V", 3: "±14 V"}
POL_NAMES = {-1: "Unknown", 0: "Off", 1: "200 V", 2: "28 V"}

#: 前端用的代號 -> 要通電的那一對(0 = Channels 1&2,1 = Channels 3&4)
PAIRS = {"1-2": 0, "3-4": 1}
PAIR_LABELS = {"1-2": "Channels 1 & 2", "3-4": "Channels 3 & 4"}
DEFAULT_PAIR = "1-2"


class LabCoreUnavailable(RuntimeError):
    """連不上 labCORE。呼叫端自己決定要不要當成致命錯誤。"""


def connect():
    """回 (device, 麥克風卡的設定物件)。

    ⚠️ 要在已經 CoInitialize 過的執行緒上呼叫（工作執行緒就是)。
    """
    try:
        import win32com.client as w
    except ImportError as exc:                              # noqa: BLE001
        raise LabCoreUnavailable("沒有 pywin32:%s" % exc)

    try:
        ctrl = w.Dispatch(PROGID)
        if int(ctrl.Count) < 1:
            raise LabCoreUnavailable("找不到 labCORE 裝置")
        dev = ctrl.Items(0)
        blocks = dev.AudioWiring.Blocks
        for i in range(blocks.Count):
            b = blocks.Items(i)
            if b.ID == "mic|0|":
                return dev, b.Settings
        raise LabCoreUnavailable("這台 labCORE 沒有 mic|0| 區塊")
    except LabCoreUnavailable:
        raise
    except Exception as exc:                                # noqa: BLE001
        raise LabCoreUnavailable(str(exc))


def routed_mic_channels(dev) -> list:
    """目前有哪幾個麥克風通道的訊號被接出去(1 起算)。

    這是「該開哪一對」的依據 —— 接線由 ACQUA 決定,我們跟著它走。
    """
    out = set()
    conns = dev.AudioWiring.ActiveConnections
    for i in range(conns.Count):
        c = conns.Items(i)
        try:
            for pin in (c.Pin1, c.Pin2):
                if pin.Block.ID == "mic|0|" and str(pin.ID).startswith("out|"):
                    out.add(int(str(pin.ID).split("|")[1]) + 1)
        except Exception:                                   # noqa: BLE001
            continue
    return sorted(out)


def wiring(dev) -> list:
    """目前作用中的接線,每條是 [[區塊, 接腳], [區塊, 接腳]]。

    只用來「看」和「比對」—— 這一塊 ACQUA 自己會切,不要寫。
    """
    out = []
    conns = dev.AudioWiring.ActiveConnections
    for i in range(conns.Count):
        c = conns.Items(i)
        try:
            p1, p2 = c.Pin1, c.Pin2
            out.append(sorted([[p1.Block.ID, p1.ID], [p2.Block.ID, p2.ID]]))
        except Exception:                                   # noqa: BLE001
            continue
    return sorted(out)


def read_usb(dev) -> dict:
    """USB Audio Host 區塊的現況。沒有這個區塊就回 None。

    跟麥克風供電一樣:ACQUA 不碰這裡。目前只讀不寫 —— 要寫的時候
    介面都在(Devices / ActiveDevice / Playback|CaptureSettings)。
    """
    blocks = dev.AudioWiring.Blocks
    settings = None
    for i in range(blocks.Count):
        if blocks.Items(i).ID == "usbaudio|0|":
            settings = blocks.Items(i).Settings
            break
    if settings is None:
        return None

    def side(o):
        return {"channels": o.Channels, "sample_rate": o.SampleRate,
                "format": o.Format}

    return {
        "any_device": bool(settings.AnyDeviceAvailable),
        "device_count": settings.Devices.Count,
        "state": settings.State,
        "auto_resampling": settings.AutoResampling,
        "playback": side(settings.PlaybackSettings),
        "capture": side(settings.CaptureSettings),
    }


def read_state() -> dict:
    """目前的供電狀態。不會丟例外 —— 連不上就回 available=False。"""
    try:
        dev, mic = connect()
    except LabCoreUnavailable as exc:
        return {"available": False, "error": str(exc)[:160],
                "pair": None, "pairs": [], "routed": []}

    pairs = [mic.ChannelPair(p).PolarizationVoltage for p in (0, 1)]
    # 「現在是哪一對」= 唯一通電的那一對。兩對都開或都關就沒有單一答案。
    on = [i for i, v in enumerate(pairs) if v == POL_200V]
    pair = None
    if len(on) == 1:
        pair = "1-2" if on[0] == 0 else "3-4"

    return {
        "available": True,
        "pair": pair,
        "pairs": pairs,
        "pair_labels": [POL_NAMES.get(v, v) for v in pairs],
        "supply_mode": mic.SupplyVoltageMode,
        "supply_label": SUPPLY_NAMES.get(mic.SupplyVoltageMode, "?"),
        "routed": routed_mic_channels(dev),
    }


def set_pair(pair: str) -> dict:
    """把 200V 切到指定的那一對,另一對關掉。

    用 BeginUpdate/EndUpdate 包起來,兩對一起套用 —— 不然中間會短暫
    出現「兩對都開」或「兩對都關」的狀態。
    """
    key = str(pair or DEFAULT_PAIR).strip()
    if key not in PAIRS:
        raise ValueError("不認得的通道組:%r（可用:%s)"
                         % (pair, "、".join(PAIRS)))

    dev, mic = connect()
    want = PAIRS[key]

    # 先問硬體支不支援 200V,不要硬塞。這張卡實測不支援 28V。
    try:
        if not bool(mic.CanPolarizationVoltage(POL_200V)):
            raise LabCoreUnavailable("這張麥克風卡不支援 200V 極化電壓")
    except LabCoreUnavailable:
        raise
    except Exception:                                       # noqa: BLE001
        pass            # 問不到就照設,下面會讀回來驗證

    mic.BeginUpdate()
    try:
        for p in (0, 1):
            mic.ChannelPair(p).PolarizationVoltage = (
                POL_200V if p == want else POL_OFF)
    finally:
        mic.EndUpdate()

    # 讀回來驗證 —— 寫進去沒生效是不會報錯的
    after = [mic.ChannelPair(p).PolarizationVoltage for p in (0, 1)]
    ok = after[want] == POL_200V and after[1 - want] == POL_OFF
    state = read_state()
    state["requested"] = key
    state["applied"] = bool(ok)
    return state


def mismatch(state: dict) -> str:
    """接線用到的通道有沒有供電?有問題回一句說明,沒事回空字串。

    這是整個模組存在的理由:訊號接到沒供電的通道上,量測會回報 PASS
    但數據是錯的。
    """
    if not state.get("available"):
        return ""
    routed = state.get("routed") or []
    if not routed:
        return ""
    pairs = state.get("pairs") or []
    bad = [ch for ch in routed
           if len(pairs) > (0 if ch <= 2 else 1)
           and pairs[0 if ch <= 2 else 1] != POL_200V]
    if not bad:
        return ""
    return ("訊號接在麥克風通道 %s,但那一組的極化電壓是關的 —— "
            "量測會通過但數據是錯的"
            % "、".join(str(c) for c in bad))
