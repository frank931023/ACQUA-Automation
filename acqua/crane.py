# -*- coding: utf-8 -*-
"""天車位置橋接 —— 3D 場景的邏輯軸 ←→ Raspberry Pi 的韌體指令。

這一層存在的理由
────────────────
3D 頁面講的是「HATS 的 MRP 高度是 1.20 公尺」,韌體講的是「SYM,450」。
中間差了三件事:單位(公尺/公釐)、原點(場景以房間中心為 0,韌體以行程
起點為 0)、以及「哪一根軸在哪一台 Pi 上」。

把這三件事塞在路由裡,以後改接線就要翻整個 app.py。所以集中在 AXES 這
一張表:**改接線只改這張表**,其他程式碼一行都不用動。

兩種後端,介面完全一樣
──────────────────────
    MockCrane   沒有硬體時用。位置是模擬的,會隨時間慢慢跑。
    HttpCrane   真的去打天車控制中心(port 5001)的 REST API。

由 .env 的 ACQUA_SETUP_CONTROLLER 決定用哪個 —— 沒設就是 Mock。前端、API、3D 動畫完全
不知道差別,因為**「移動中的位置怎麼算」是在基底類別裡算的,兩個後端共用**
(見 _run_job)。這不是為了讓 mock 好寫,是因為真機也非得這樣做:

    ⚠️ 機構在動的時候讀不到位置。
       Pi 是序列埠單線程,移動指令會一直佔著埠直到 Arduino 回 DONE ——
       這期間送位置查詢只會排在後面。所以「動的時候」的位置一律是
       **由起點、終點、標稱速度推算出來的估計值**(estimated=True),
       等指令回來才用真實查詢校正回去。

    也就是說 mock 跟真機的差別只有一個方法:_start_move()。
    其他的(估計、進度、中止、狀態機)全部是同一份程式在跑。

⚠️ 中止(stop)的真實語意
────────────────────────
韌體沒有中止指令。所以 stop 只能做到「不要再送後面那幾軸」——
**已經送出去的那一段機構會自己走完**。UI 上要照這個講,不能寫成
「緊急停止」讓人誤會按了就會停。真的要停只能斷電。
"""
from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ══════════════════════════════════════════════════════════
#  軸對應表
# ══════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Axis:
    """一根可動的自由度。

    id      場景側的邏輯代號(與 soundproofroom/src/axes.js 一致,也是
            setup 檔裡的鍵 —— 改名字會讓存好的 setup 對不上,別改)
    pi      這根軸接在哪一台 Raspberry Pi 上
    ch      韌體的軸前綴。'SX'/'SY'/'SZ' 是滑台,'R' 轉盤,'T' 傾角。
            指令由前綴組出來:移動 <ch>M,<值> ・ 查詢 <ch>P ・
            校正 <ch>C ・ 歸位 <ch>H
    lo/hi   場景座標的行程兩端。**韌體的 0 對應 lo**(見 to_device)
    unit    'm' 線性軸(公尺,對韌體換成公釐)/ 'deg' 旋轉軸(直接給度數)
    speed   標稱速度,場景單位 / 秒。只用來估計移動中的位置與預估時間,
            不會送給韌體
    """
    id: str
    pi: str
    ch: str
    lo: float
    hi: float
    label: str
    unit: str = "m"
    speed: float = 0.07

    # ── 單位與原點換算 ──────────────────────────────
    def to_device(self, scene: float) -> int:
        """場景座標 → 韌體數值。

        線性軸:韌體的行程是「從機械原點算起的公釐數」,不會有負的;
        場景的 X 是以房間中心為 0、兩邊各一半。所以要先減掉 lo 再乘 1000。
        旋轉軸沒有這個問題,度數直接過。
        """
        if self.unit == "deg":
            return int(round(scene))
        return int(round((scene - self.lo) * 1000.0))

    def to_scene(self, device: float) -> float:
        if self.unit == "deg":
            return float(device)
        return self.lo + float(device) / 1000.0

    def clamp(self, scene: float) -> float:
        return min(self.hi, max(self.lo, float(scene)))

    # ── 指令字串 ────────────────────────────────────
    def cmd_move(self, scene: float) -> str:
        return f"{self.ch}M,{self.to_device(scene)}"

    def cmd_query(self) -> str:
        # ⚠️ [待確認] 位置查詢的助憶碼。PC 端 README 只寫「查詢位置」按鈕
        #    存在,沒列字串。照 <ch>C/<ch>H/<ch>M 的規律推成 <ch>P。
        #    對不上的話韌體會回 ERR,程式會退回用估計值(不會壞掉,只是
        #    位置標成 estimated),換成正確的字串就好。
        return f"{self.ch}P"

    def travel_seconds(self, a: float, b: float) -> float:
        return abs(b - a) / max(self.speed, 1e-6)


#: 一台 Pi = 一組天車 = 一個可動總成。行程數字與 soundproofroom/src/spec.js
#: 同源 —— 但**刻意各存一份**:後端絕對不能拿前端送來的範圍當行程上限,
#: 不然瀏覽器改個數字就能把機構送去撞牆。兩邊不一致時由 /api/room/axes
#: 交叉比對並在 UI 上示警(見 live.js 的 limit mismatch)。
#:
#: ⚠️ [待確認] pi_id 與哪個總成配對,要照現場接線對一次。
AXES = {
    # ── 喇叭陣列台車(落地,pi-001)──
    "speakers.x":    Axis("speakers.x",    "pi-001", "SX", -0.75, 0.75, "喇叭陣列 — 橫移 X"),
    "speakers.lift": Axis("speakers.lift", "pi-001", "SY",  0.80, 1.80, "喇叭陣列 — 中心高度"),

    # ── 大螢幕(pi-002)──
    "screen.z":    Axis("screen.z",    "pi-002", "SZ", 1.20, 2.35, "大螢幕 — 前後 Z"),
    "screen.lift": Axis("screen.lift", "pi-002", "SY", 0.70, 1.90, "大螢幕 — 中心高度"),

    # ── HATS 平台(雙層軌 + 轉盤 + 頭部傾角,pi-003)──
    "hats.z":    Axis("hats.z",    "pi-003", "SZ", -1.85, 1.85, "HATS — 縱向 Z(下層軌)"),
    "hats.x":    Axis("hats.x",    "pi-003", "SX", -0.55, 0.55, "HATS — 橫向 X(上層軌)"),
    "hats.mrp":  Axis("hats.mrp",  "pi-003", "SY",  0.75, 1.50, "HATS — MRP 高度"),
    "hats.rot":  Axis("hats.rot",  "pi-003", "R", -180.0, 180.0, "HATS — 轉盤角度",
                      unit="deg", speed=12.0),
    "hats.head": Axis("hats.head", "pi-003", "T",  -15.0, 35.0, "HATS — 頭部前傾角",
                      unit="deg", speed=6.0),

    # ── 前方 DUT 升降台(pi-004)──
    "tableFront.z":    Axis("tableFront.z",    "pi-004", "SZ", 0.55, 2.00, "前方 DUT 台 — 前後 Z"),
    "tableFront.lift": Axis("tableFront.lift", "pi-004", "SY", 0.40, 2.30, "前方 DUT 台 — 高度"),

    # ── 後方 Dixie 升降台(pi-005)──
    "tableBack.z":    Axis("tableBack.z",    "pi-005", "SZ", -2.00, -0.55, "後方 Dixie 台 — 前後 Z"),
    "tableBack.lift": Axis("tableBack.lift", "pi-005", "SY",  0.40,  2.30, "後方 Dixie 台 — 高度"),

    # ── 天花板麥克風吊架 ×2(各一台,pi-006 / pi-007)──
    "micRig1.x": Axis("micRig1.x", "pi-006", "SX", -1.10, 1.10, "麥克風吊架 1 — 橫向 X"),
    "micRig1.z": Axis("micRig1.z", "pi-006", "SZ", -1.30, 1.70, "麥克風吊架 1 — 縱向 Z"),
    "micRig1.h": Axis("micRig1.h", "pi-006", "SY",  0.70, 1.50, "麥克風吊架 1 — 高度 Y"),
    "micRig2.x": Axis("micRig2.x", "pi-007", "SX", -1.10, 1.10, "麥克風吊架 2 — 橫向 X"),
    "micRig2.z": Axis("micRig2.z", "pi-007", "SZ", -1.30, 1.70, "麥克風吊架 2 — 縱向 Z"),
    "micRig2.h": Axis("micRig2.h", "pi-007", "SY",  0.70, 1.50, "麥克風吊架 2 — 高度 Y"),
}

#: 開機時的「假設位置」。真機第一次查詢成功就會被蓋掉;mock 則一直用這組
#: 當起點。用 spec.js 的 default 而不是行程中點 —— 這樣 mock 一開就跟
#: 設定模式看到的畫面一樣,不會一進即時模式所有東西都跳一次。
HOME = {
    "speakers.x": 0.0, "speakers.lift": 1.30,
    "screen.z": 2.05, "screen.lift": 1.25,
    "hats.z": -0.30, "hats.x": 0.0, "hats.mrp": 1.20, "hats.rot": 0.0, "hats.head": 0.0,
    "tableFront.z": 1.35, "tableFront.lift": 0.90,
    "tableBack.z": -0.95, "tableBack.lift": 1.20,
    "micRig1.x": -0.35, "micRig1.z": 0.55, "micRig1.h": 0.95,
    "micRig2.x": 0.40, "micRig2.z": -0.35, "micRig2.h": 1.25,
}

DEVICES = sorted({a.pi for a in AXES.values()})


def axes_manifest() -> list:
    """給前端交叉比對用的軸清單(行程以場景單位表示)。"""
    return [{"id": a.id, "pi": a.pi, "ch": a.ch, "label": a.label,
             "unit": a.unit, "min": a.lo, "max": a.hi, "speed": a.speed}
            for a in AXES.values()]


# ══════════════════════════════════════════════════════════
#  移動作業(job)—— 一次只有一個
# ══════════════════════════════════════════════════════════
#
# 「手動移動一根軸」與「把一整個 setup 套到實機」是同一件事的兩種大小:
# 一串 (軸, 目標) 依序執行。做成同一個模型的好處是進度顯示、中止、
# 「正在動,別再下指令」這些狀態只要寫一次。
#
# 為什麼是**依序**而不是所有軸一起跑:機構之間會互相干涉(HATS 平台跟
# 升降台的行程是重疊的)。一次只動一根,任何時刻都只有一個東西在動,
# 撞到什麼也看得出來是誰。


class _Handle:
    """一個「已經送出去的移動」。done() 問完成了沒,error() 問失敗原因。

    抽出來的理由:mock 是「睡一段時間」,真機是「等 HTTP 回來」,
    但上層的等待邏輯要一模一樣(見 CraneBridge._drive)。
    """

    def __init__(self, fn):
        self._err = None
        self._done = threading.Event()
        self._t = threading.Thread(target=self._run, args=(fn,), daemon=True)
        self._t.start()

    def _run(self, fn):
        try:
            fn()
        except Exception as exc:                            # noqa: BLE001
            self._err = str(exc)[:300]
        finally:
            self._done.set()

    def done(self) -> bool:
        return self._done.is_set()

    def error(self):
        return self._err


class CraneBridge:
    """位置橋接的基底 —— 狀態機、位置估計、進度都在這裡。

    子類只要實作三件事:
        _send_move(axis, target)    阻塞著把移動指令做完
        _query(axis)                讀一根軸的真實位置(讀不到回 None)
        device_status()             每台 Pi 的連線狀態
    """

    #: 沒有作業在跑時,多久去問一次真實位置
    poll_interval = 2.0

    def __init__(self):
        self._lock = threading.RLock()
        self._pos = dict(HOME)               # 目前位置(場景單位)
        self._est = {k: True for k in HOME}  # 這個值是估計的還是真的量到的
        self._job = None
        self._abort = threading.Event()
        self._stop_poll = threading.Event()
        threading.Thread(target=self._poll_loop, daemon=True,
                         name="crane-poll").start()

    # ── 子類要實作 ──────────────────────────────────
    def _send_move(self, axis: Axis, target: float):
        raise NotImplementedError

    def _query(self, axis: Axis):
        return None

    def device_status(self) -> dict:
        return {pi: {"status": "unknown"} for pi in DEVICES}

    @property
    def kind(self) -> str:
        return "unknown"

    # ── 對外:讀位置 ────────────────────────────────
    def snapshot(self) -> dict:
        """目前所有軸的位置 + 作業狀態。前端即時模式每秒拿這個。"""
        with self._lock:
            axes = {k: {"value": round(self._pos.get(k, AXES[k].lo), 4),
                        "estimated": bool(self._est.get(k, True))}
                    for k in AXES}
            job = self._job_view()
        return {"kind": self.kind, "axes": axes, "job": job,
                "devices": self.device_status()}

    def _job_view(self):
        if not self._job:
            return None
        job = dict(self._job)
        job["steps"] = [dict(s) for s in self._job["steps"]]
        return job

    # ── 對外:下移動作業 ────────────────────────────
    def submit(self, moves, label="") -> dict:
        """moves = [(axis_id, target), ...],依序執行。

        目標值在這裡就夾到行程內 —— 不信任呼叫端,瀏覽器改個數字不該能
        把機構送去撞牆。已經有作業在跑時丟 RuntimeError。
        """
        steps = []
        for axis_id, target in moves:
            ax = AXES.get(axis_id)
            if ax is None:
                raise KeyError("未知的軸:" + str(axis_id))
            t = ax.clamp(float(target))
            with self._lock:
                start = self._pos.get(axis_id, ax.lo)
            steps.append({"axis": axis_id, "label": ax.label, "pi": ax.pi,
                          "unit": ax.unit, "from": round(start, 4),
                          "to": round(t, 4), "state": "pending",
                          "command": ax.cmd_move(t),
                          "seconds": round(ax.travel_seconds(start, t), 1)})
        if not steps:
            raise ValueError("沒有要移動的軸")

        with self._lock:
            if self._job and self._job["state"] in ("running", "aborting"):
                raise RuntimeError("已經有移動在進行中")
            self._abort.clear()
            self._job = {
                "id": "%x" % int(time.time() * 1000),
                "label": label or steps[0]["label"],
                "state": "running", "index": 0, "steps": steps,
                "started": time.time(), "finished": None, "error": None,
                "eta": round(sum(s["seconds"] for s in steps), 1),
            }
            job_id = self._job["id"]
            view = self._job_view()

        threading.Thread(target=self._run_job, args=(job_id,), daemon=True,
                         name="crane-job").start()
        return view

    def abort(self) -> dict:
        """停掉作業。

        ⚠️ 只擋得住「還沒送出去」的那幾軸 —— 正在走的那一段機構會走完,
           因為韌體沒有中止指令。UI 必須照這個講,不能寫成「緊急停止」。
        """
        self._abort.set()
        with self._lock:
            if self._job and self._job["state"] == "running":
                self._job["state"] = "aborting"
        return self.snapshot()

    def busy(self) -> bool:
        with self._lock:
            return bool(self._job and self._job["state"] in ("running", "aborting"))

    # ── 作業執行 ────────────────────────────────────
    def _run_job(self, job_id):
        try:
            while True:
                with self._lock:
                    job = self._job
                    if not job or job["id"] != job_id:
                        return
                    idx = job["index"]
                    if idx >= len(job["steps"]):
                        break
                    if self._abort.is_set():
                        for s in job["steps"][idx:]:
                            s["state"] = "skipped"
                        job["state"] = "aborted"
                        job["finished"] = time.time()
                        return
                    step = job["steps"][idx]
                    step["state"] = "moving"
                    step["began"] = time.time()
                    frm, to = step["from"], step["to"]

                self._drive(AXES[step["axis"]], frm, to)

                with self._lock:
                    job = self._job
                    if not job or job["id"] != job_id:
                        return
                    job["steps"][idx]["state"] = "done"
                    job["index"] = idx + 1

            with self._lock:
                if self._job and self._job["id"] == job_id:
                    self._job["state"] = "done"
                    self._job["finished"] = time.time()
        except Exception as exc:                            # noqa: BLE001
            with self._lock:
                if self._job and self._job["id"] == job_id:
                    self._job["state"] = "error"
                    self._job["error"] = str(exc)[:300]
                    self._job["finished"] = time.time()

    def _drive(self, ax: Axis, start: float, target: float):
        """送出一根軸的移動,期間用估計值餵位置,結束後用真實查詢校正。

        這是 mock 與真機唯一共用、也最重要的一段。移動中的位置一律是
        「起點 → 終點,照標稱速度線性內插」—— 因為序列埠被移動指令佔著,
        那期間真的問不到(見檔頭)。所以:

            移動中  estimated = True   位置是算出來的
            停下來  estimated = False  位置是問出來的(問不到就維持 True)

        3D 畫面吃的就是這個位置流,所以「慢慢移動過去」在 mock 與真機
        看起來一樣 —— 不是動畫特效,是真的在追報回來的位置。
        """
        handle = _Handle(lambda: self._send_move(ax, target))
        total = max(ax.travel_seconds(start, target), 0.001)
        t0 = time.time()

        while not handle.done():
            frac = min(1.0, (time.time() - t0) / total)
            with self._lock:
                self._pos[ax.id] = start + (target - start) * frac
                self._est[ax.id] = True
            time.sleep(0.08)

        err = handle.error()
        if err:
            raise RuntimeError(ax.label + ":" + err)

        # 指令回來了,序列埠空出來,這才問得到真實位置
        try:
            real = self._query(ax)
        except Exception:                                   # noqa: BLE001
            real = None
        with self._lock:
            if real is None:
                self._pos[ax.id] = target        # 問不到就相信目標值
                self._est[ax.id] = True
            else:
                self._pos[ax.id] = ax.clamp(real)
                self._est[ax.id] = False

    # ── 閒置時的背景刷新 ────────────────────────────
    def _poll_loop(self):
        """作業沒在跑的時候,慢慢把真實位置補回來。

        為什麼要背景執行緒而不是在 API 裡現問:真機有 7 台 Pi,逐台問
        就是 7 次 HTTP 來回。前端每秒刷一次的話請求會越積越多(控制中心
        README 記過同一個坑)。這裡用固定節奏刷快取,API 只讀快取。
        """
        while not self._stop_poll.wait(self.poll_interval):
            if self.busy():
                continue
            for ax in list(AXES.values()):
                if self.busy() or self._stop_poll.is_set():
                    break
                try:
                    real = self._query(ax)
                except Exception:                           # noqa: BLE001
                    real = None
                if real is None:
                    continue
                with self._lock:
                    self._pos[ax.id] = ax.clamp(real)
                    self._est[ax.id] = False

    def close(self):
        self._stop_poll.set()
        self._abort.set()


# ══════════════════════════════════════════════════════════
#  後端 A:模擬(沒有硬體時)
# ══════════════════════════════════════════════════════════

class MockCrane(CraneBridge):
    """沒接硬體時用的後端。

    跟真機的差別**只有 _send_move 一個方法** —— 它不送 HTTP,只是睡掉
    機構該花的時間。位置怎麼變、進度怎麼算、中止怎麼處理,全部走基底類別
    那一份。所以等真機接上來,即時模式的行為不會忽然變成另一個樣子。

    _query 刻意回 None(= 讀不到真實位置)。這樣開發時看到的就是真機
    「移動中讀不到」的那個狀態,estimated 的標記會一直亮著 —— 如果哪天
    前端把 estimated 當成不存在,在 mock 就會先被抓到,而不是上線才發現。
    """

    #: 模擬時把時間壓縮幾倍。1 = 照標稱速度(看起來最像真的)
    time_scale = 1.0

    @property
    def kind(self) -> str:
        return "mock"

    def _send_move(self, axis: Axis, target: float):
        with self._lock:
            start = self._pos.get(axis.id, axis.lo)
        time.sleep(axis.travel_seconds(start, target) / max(self.time_scale, 0.01))

    def device_status(self) -> dict:
        return {pi: {"status": "online", "note": "模擬"} for pi in DEVICES}


# ══════════════════════════════════════════════════════════
#  後端 B:真的打天車控制中心
# ══════════════════════════════════════════════════════════

class HttpCrane(CraneBridge):
    """透過天車控制中心(預設 http://127.0.0.1:5001)驅動實機。

    只用控制中心的兩支 API,不直接碰 Pi:
        POST /api/pi/<id>/command   送指令
        GET  /api/pis               所有裝置的三態狀態

    刻意不繞過控制中心自己連 Pi —— 那邊已經處理好並行檢測、timeout 緩衝、
    三態判定(綠燈的門檻是 Arduino 真的回話)。重寫一份只會多一個要維護的
    真相來源。
    """

    def __init__(self, base_url: str, timeout_move: int = 90):
        self.base = base_url.rstrip("/")
        self.timeout_move = int(timeout_move)
        self._dev = {}
        self._dev_at = 0.0
        super().__init__()

    @property
    def kind(self) -> str:
        return "http"

    # ── 低階:HTTP ──────────────────────────────────
    #
    # 用 stdlib 的 urllib 而不是 requests:整個專案只有這裡要發 HTTP,
    # 為兩支呼叫多釘一個套件不值得(理由同 acqua/env.py 不用 python-dotenv)。
    @staticmethod
    def _http(url: str, timeout: float, payload=None):
        """回 (status_code, 解析好的 JSON)。4xx/5xx 不丟例外 —— 控制中心會在
        錯誤回應的 body 裡講原因(SERIAL_DISCONNECTED 之類),那比狀態碼
        有用得多,不能因為 HTTPError 就把它丟掉。"""
        req = Request(url, method="GET" if payload is None else "POST")
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            req.add_header("Content-Type", "application/json")
        try:
            with urlopen(req, data=data, timeout=timeout) as r:
                return r.status, json.loads((r.read() or b"{}").decode("utf-8"))
        except HTTPError as exc:
            raw = exc.read() or b"{}"
            try:
                return exc.code, json.loads(raw.decode("utf-8"))
            except ValueError:
                return exc.code, {}
        except URLError as exc:
            raise RuntimeError("連不到控制中心:%s" % (exc.reason,)) from exc
        except socket.timeout as exc:
            raise RuntimeError("控制中心逾時") from exc

    def _command(self, pi: str, command: str, timeout: int):
        code, body = self._http(
            "%s/api/pi/%s/command" % (self.base, pi),
            # +8 秒緩衝:讓控制中心先自己判定逾時、回傳看得懂的原因,
            # 而不是我們這邊先斷線,把有原因的錯誤變成連線失敗。
            timeout + 8,
            {"command": command, "timeout": timeout})
        if code >= 400 or body.get("status") != "success":
            raise RuntimeError(body.get("error") or ("HTTP %d" % code))
        return body.get("pi_response") or {}

    def _send_move(self, axis: Axis, target: float):
        resp = self._command(axis.pi, axis.cmd_move(target), self.timeout_move)
        lines = resp.get("arduino_response") or []
        if resp.get("arduino_result") == "ERR":
            raise RuntimeError("韌體不認得 " + axis.cmd_move(target))
        # 超出行程時韌體仍以 DONE 收尾,只是中間多一行 —— 不掃就會以為動了。
        for ln in lines:
            if "Exceeded Max travel" in str(ln):
                raise RuntimeError("超出行程(該軸可能還沒校正)")

    def _query(self, axis: Axis):
        """讀真實位置。讀不到回 None,讓基底類別退回估計值。

        ⚠️ 位置查詢的助憶碼還沒對過(見 Axis.cmd_query)。對不上時韌體回
           ERR,這裡就回 None —— 系統照樣能用,只是位置一直標成「估計」。
           這是刻意的:寧願顯示「這個數字是推算的」,也不要編一個看起來
           很確定的位置出來。
        """
        try:
            resp = self._command(axis.pi, axis.cmd_query(), 10)
        except Exception:                                   # noqa: BLE001
            return None
        if resp.get("arduino_result") != "DONE":
            return None
        return self._parse_position(axis, resp.get("arduino_response") or [])

    @staticmethod
    def _parse_position(axis: Axis, lines):
        """從 Arduino 回的訊息行裡撈出一個數字。

        韌體回什麼格式還沒定,所以取「最後一行裡的最後一個數字」——
        不管它是 "pos: 412" 還是 "412" 都撈得到。格式定了就把這裡收緊,
        現在寬鬆是刻意的:寧願讀到就用,讀不到就老實標成估計值。
        """
        for ln in reversed([str(x) for x in lines]):
            nums = re.findall(r"-?\d+(?:\.\d+)?", ln)
            if nums:
                return axis.to_scene(float(nums[-1]))
        return None

    # ── 裝置狀態 ────────────────────────────────────
    def device_status(self) -> dict:
        """控制中心的三態狀態。快取 4 秒 —— 它那支 API 本身就會並行檢測
        所有裝置,每次前端刷新都打一次太重。"""
        now = time.time()
        if now - self._dev_at < 4.0 and self._dev:
            return self._dev
        out = {pi: {"status": "offline"} for pi in DEVICES}
        try:
            _, body = self._http(self.base + "/api/pis", 8)
            pis = (body or {}).get("pis") or {}
            for pi in DEVICES:
                info = pis.get(pi)
                out[pi] = ({"status": info.get("status", "offline"),
                            "name": info.get("name", "")} if info
                           else {"status": "missing",
                                 "note": "控制中心裡沒有這台裝置"})
        except Exception as exc:                            # noqa: BLE001
            for pi in DEVICES:
                out[pi] = {"status": "offline", "note": str(exc)[:120]}
        self._dev, self._dev_at = out, now
        return out


# ══════════════════════════════════════════════════════════
#  選後端
# ══════════════════════════════════════════════════════════

def make_crane(base_url: str = None) -> CraneBridge:
    """位址有設就打真機,沒設就用模擬。

    位址從 config 的 setup_controller.url 來(由 .env 的
    ACQUA_SETUP_CONTROLLER 覆寫)—— 沿用專案裡已經有的那個鉤子,
    那一欄本來就是為「移動治具的控制器」留的,現在它有實作了。

    預設是模擬,而不是「試著連、連不到再退回」—— 連不到的時候要吵,
    不要安靜地變成假的。要接真機就明確設環境變數。
    """
    if base_url is None:
        base_url = os.environ.get("ACQUA_SETUP_CONTROLLER", "")
    url = (base_url or "").strip()
    if not url:
        return MockCrane()
    return HttpCrane(url)
