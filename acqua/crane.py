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
    MockCrane   沒有硬體時用。在本機一根一根模擬,位置會隨時間慢慢跑。
    HttpCrane   把「擺位名稱 + 每台 Pi 的目標」整組交給天車控制中心(MCC),
                由 MCC 決定順序、並行與防撞,我們等它回報完成。
                約定見 docs/MCC_MOTION_API.md。

由 .env 的 ACQUA_SETUP_CONTROLLER 決定用哪個 —— 沒設就是 Mock。呼叫端
(SetupCoordinator、/api/room/*)只用 submit / busy / snapshot,不知道差別。

不主動查位置:韌體的 RP / TP 查詢會順便讓轉盤歸位,而且機構在動的時候
序列埠被佔著也問不到。位置以作業結束時 MCC 回報的為準。

這裡**沒有**給人手動推機構、看即時位置的功能 —— 那屬於天車控制中心。
本專案只在測試執行時,依測項的 Setup 標籤把存好的擺位送過去。
"""
from __future__ import annotations

import json
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

    id      場景側的邏輯代號(與 soundproofroom/src/main.js 的 PANEL 一致,也是
            setup 檔裡的鍵 —— 改名字會讓存好的 setup 對不上,別改)
    pi      這根軸接在哪一台 Raspberry Pi 上
    ch      韌體的軸前綴。'SX'/'SY'/'SZ' 是滑台,'R' 轉盤,'T' 傾角。
            指令由前綴組出來:移動 <ch>M,<值> ・ 查詢 <ch>P ・
            校正 <ch>C ・ 歸位 <ch>H。送給 MCC 的目標用 <ch>M 當鍵
    lo/hi   場景座標的行程兩端。**韌體的 0 對應 lo**(見 to_device)
    unit    'm' 線性軸(公尺,對韌體換成公釐)/ 'deg' 旋轉軸(直接給度數)
    speed   標稱速度,場景單位 / 秒。只用來估計預估時間與模擬,不會送給韌體
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

    def travel_seconds(self, a: float, b: float) -> float:
        return abs(b - a) / max(self.speed, 1e-6)


#: 一台 Pi = 一組天車 = 一個可動總成。行程數字與 soundproofroom/src/spec.json
#: 同源 —— 但**刻意各存一份**:後端絕對不能拿前端送來的範圍當行程上限,
#: 不然瀏覽器改個數字就能把機構送去撞牆。兩邊不一致時由 /api/room/axes
#: 交叉比對並在 3D 頁上示警(見 main.js 的 checkLimits)。
#:
#: ⚠️ [待確認] pi_id 與哪個總成配對,要照現場接線對一次。
AXES = {
    # ── 喇叭陣列台車(落地,pi-001)──
    "speakers.x":    Axis("speakers.x",    "pi-001", "SX", -0.75, 0.75, "Speaker array - traverse X"),
    "speakers.lift": Axis("speakers.lift", "pi-001", "SY",  0.80, 1.80, "Speaker array - centre height"),

    # ── 大螢幕(pi-002)──
    "screen.z":    Axis("screen.z",    "pi-002", "SZ", 1.20, 2.35, "Large screen - depth Z"),
    "screen.lift": Axis("screen.lift", "pi-002", "SY", 0.70, 1.90, "Large screen - centre height"),

    # ── HATS 平台(雙層軌 + 轉盤 + 頭部傾角,pi-003)──
    "hats.z":    Axis("hats.z",    "pi-003", "SZ", -1.85, 1.85, "HATS - depth Z (lower rail)"),
    "hats.x":    Axis("hats.x",    "pi-003", "SX", -0.55, 0.55, "HATS - lateral X (upper rail)"),
    "hats.mrp":  Axis("hats.mrp",  "pi-003", "SY",  0.75, 1.50, "HATS - MRP height"),
    "hats.rot":  Axis("hats.rot",  "pi-003", "R", -180.0, 180.0, "HATS - turntable angle",
                      unit="deg", speed=12.0),
    "hats.head": Axis("hats.head", "pi-003", "T",  -15.0, 35.0, "HATS - head pitch",
                      unit="deg", speed=6.0),

    # ── 前方 DUT 升降台(pi-004)──
    "tableFront.z":    Axis("tableFront.z",    "pi-004", "SZ", 0.55, 2.00, "Front DUT table - depth Z"),
    "tableFront.lift": Axis("tableFront.lift", "pi-004", "SY", 0.40, 2.30, "Front DUT table - height"),

    # ── 後方 Dixie 升降台(pi-005)──
    "tableBack.z":    Axis("tableBack.z",    "pi-005", "SZ", -2.00, -0.55, "Rear Dixie table - depth Z"),
    "tableBack.lift": Axis("tableBack.lift", "pi-005", "SY",  0.40,  2.30, "Rear Dixie table - height"),

    # ── 天花板麥克風吊架 ×2(各一台,pi-006 / pi-007)──
    "micRig1.x": Axis("micRig1.x", "pi-006", "SX", -1.10, 1.10, "Mic rig 1 - lateral X"),
    "micRig1.z": Axis("micRig1.z", "pi-006", "SZ", -1.30, 1.70, "Mic rig 1 - depth Z"),
    "micRig1.h": Axis("micRig1.h", "pi-006", "SY",  0.70, 1.50, "Mic rig 1 - height Y"),
    "micRig2.x": Axis("micRig2.x", "pi-007", "SX", -1.10, 1.10, "Mic rig 2 - lateral X"),
    "micRig2.z": Axis("micRig2.z", "pi-007", "SZ", -1.30, 1.70, "Mic rig 2 - depth Z"),
    "micRig2.h": Axis("micRig2.h", "pi-007", "SY",  0.70, 1.50, "Mic rig 2 - height Y"),
}

#: 開機時的「假設位置」(標成推估)。第一次作業完成後就換成 MCC 回報的位置。用 spec.json 的 default 而不是行程中點 —— 跟 3D 頁一打開的畫面一致。
HOME = {
    "speakers.x": 0.0, "speakers.lift": 1.30,
    "screen.z": 2.05, "screen.lift": 1.25,
    "hats.z": -0.30, "hats.x": 0.0, "hats.mrp": 1.20, "hats.rot": 0.0, "hats.head": 0.0,
    "tableFront.z": 1.35, "tableFront.lift": 0.90,
    "tableBack.z": -0.95, "tableBack.lift": 1.20,
    "micRig1.x": -0.35, "micRig1.z": 0.55, "micRig1.h": 0.95,
    "micRig2.x": 0.40, "micRig2.z": -0.35, "micRig2.h": 1.25,
}

def axes_manifest() -> list:
    """軸清單(行程以場景單位表示)。3D 頁拿來跟 spec.json 交叉比對,
    擺位詳細頁拿來做範圍提示。"""
    return [{"id": a.id, "pi": a.pi, "ch": a.ch, "label": a.label,
             "unit": a.unit, "min": a.lo, "max": a.hi, "speed": a.speed}
            for a in AXES.values()]


# ══════════════════════════════════════════════════════════
#  移動作業(job)—— 一次只有一個
# ══════════════════════════════════════════════════════════
#
# 「把一個擺位套到實機」= 一個作業:名稱 + 每根軸的目標。呼叫端
# (SetupCoordinator、/api/room/apply)只用三個方法:
#
#     submit(moves, label)   送出。label 就是擺位名稱
#     busy()                 還在動嗎
#     snapshot()             每根軸的位置 + 作業狀態
#
# 誰負責「怎麼走」:
#     MockCrane   自己在本機一根一根模擬(沒有硬體時)
#     HttpCrane   整組交給天車控制中心(MCC),**順序、並行、防撞由 MCC 決定**,
#                 我們只送名稱與目標、等它回報完成。約定見 docs/MCC_MOTION_API.md


def targets_by_device(moves) -> dict:
    """[(axis_id, 場景值), ...] → {pi: {"<ch>M": 韌體值}}。

    鍵用韌體的移動指令名稱(SXM / SZM / RM …),跟 MCC 既有的停車位置
    (PATCH /api/pi/<id> 的 park)同一種格式。單位換算只在這裡做一次:
    MCC 只看得到韌體數值,不需要知道房間座標。
    """
    out = {}
    for axis_id, value in moves:
        ax = AXES[axis_id]
        out.setdefault(ax.pi, {})[ax.ch + "M"] = ax.to_device(value)
    return out


class CraneBridge:
    """位置橋接的基底:位置表、作業狀態、輸入檢查。

    子類實作:
        _start(job)    把作業送出去(失敗就丟例外,作業不會被記下來)
        _refresh()     需要的話更新作業狀態(預設不做事)
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._pos = dict(HOME)               # 目前位置(場景單位)
        self._est = {k: True for k in HOME}  # True = 推估的,False = 有人回報過
        self._job = None

    @property
    def kind(self) -> str:
        return "unknown"

    # ── 子類要實作 ──────────────────────────────────
    def _start(self, job: dict):
        raise NotImplementedError

    def _refresh(self):
        pass

    # ── 對外 ────────────────────────────────────────
    def snapshot(self) -> dict:
        """目前所有軸的位置 + 作業狀態。SetupCoordinator 與 /api/room/current 用。"""
        self._refresh()
        with self._lock:
            axes = {k: {"value": round(self._pos.get(k, AXES[k].lo), 4),
                        "estimated": bool(self._est.get(k, True))}
                    for k in AXES}
            job = self._job_view()
        return {"kind": self.kind, "axes": axes, "job": job}

    def busy(self) -> bool:
        self._refresh()
        with self._lock:
            return bool(self._job and self._job["state"] == "running")

    def submit(self, moves, label="") -> dict:
        """moves = [(axis_id, target), ...]。label = 擺位名稱。

        目標值在這裡就夾到行程內 —— 不信任呼叫端。已經有作業在跑、
        或送不出去時丟 RuntimeError,作業不會被記下來。
        """
        steps = []
        for axis_id, target in moves:
            ax = AXES.get(axis_id)
            if ax is None:
                raise KeyError("Unknown axis: " + str(axis_id))
            t = ax.clamp(float(target))
            with self._lock:
                start = self._pos.get(axis_id, ax.lo)
            steps.append({"axis": axis_id, "label": ax.label, "pi": ax.pi,
                          "unit": ax.unit, "from": round(start, 4),
                          "to": round(t, 4), "state": "pending",
                          "command": ax.cmd_move(t),
                          "seconds": round(ax.travel_seconds(start, t), 1)})
        if not steps:
            raise ValueError("No axes to move")

        with self._lock:
            if self._job and self._job["state"] == "running":
                raise RuntimeError("A move is already in progress")
        job = {
            "id": "%x" % int(time.time() * 1000),
            "label": label or steps[0]["label"],
            "state": "running", "index": 0, "steps": steps,
            "started": time.time(), "finished": None, "error": None,
            "eta": round(sum(s["seconds"] for s in steps), 1),
        }
        self._start(job)                     # 送不出去就在這裡丟例外
        with self._lock:
            self._job = job
            return self._job_view()

    def close(self):
        pass

    # ── 內部 ────────────────────────────────────────
    def _job_view(self):
        if not self._job:
            return None
        job = dict(self._job)
        job["steps"] = [dict(s) for s in self._job["steps"]]
        return job

    def _finish(self, job, state, error=None):
        with self._lock:
            job["state"] = state
            job["error"] = error
            job["finished"] = time.time()


# ══════════════════════════════════════════════════════════
#  後端 A:模擬(沒有硬體時)
# ══════════════════════════════════════════════════════════

class MockCrane(CraneBridge):
    """沒接硬體時用。一根一根照標稱速度「走」過去,位置一律標成推估。

    走的過程中位置照起點 → 終點線性內插,所以 /api/room/current 與
    擺位協調看到的行為(要等、會動、到了才算)跟真機一樣。
    """

    #: 模擬時把時間壓縮幾倍。1 = 照標稱速度
    time_scale = 1.0

    def __init__(self):
        super().__init__()
        self._closing = threading.Event()

    @property
    def kind(self) -> str:
        return "mock"

    def _start(self, job):
        threading.Thread(target=self._run, args=(job,), daemon=True,
                         name="crane-mock").start()

    def _run(self, job):
        for i, step in enumerate(job["steps"]):
            if self._closing.is_set():
                for s in job["steps"][i:]:
                    s["state"] = "skipped"
                self._finish(job, "aborted")
                return
            with self._lock:
                job["index"], step["state"] = i, "moving"
            total = max(step["seconds"] / max(self.time_scale, 0.01), 0.001)
            t0 = time.time()
            while True:
                frac = min(1.0, (time.time() - t0) / total)
                with self._lock:
                    self._pos[step["axis"]] = step["from"] + (step["to"] - step["from"]) * frac
                if frac >= 1.0 or self._closing.is_set():
                    break
                time.sleep(0.08)
            with self._lock:
                step["state"] = "done"
                job["index"] = i + 1
        self._finish(job, "done")

    def close(self):
        self._closing.set()


# ══════════════════════════════════════════════════════════
#  後端 B:天車控制中心(MCC)
# ══════════════════════════════════════════════════════════

class HttpCrane(CraneBridge):
    """把整個擺位交給天車控制中心,等它回報完成。約定見 docs/MCC_MOTION_API.md。

        POST /api/motion/jobs        {label, targets}  → job_id
        GET  /api/motion/jobs/<id>   → state / error / positions

    哪根軸先動、哪些 Pi 同時動、怎麼防撞、逾時與 409 都由 MCC 處理 ——
    那是機構的知識,MCC 本來就管著裝置清單與指令鎖。

    **不主動查位置**:韌體的 RP / TP 查詢會順便讓轉盤歸位。位置以 MCC 在作業
    結束時回報的 positions 為準;沒回報就當作到了目標(標成推估)。
    """

    #: 作業進行中,多久問一次 MCC
    poll_seconds = 1.0

    def __init__(self, base_url: str, token: str = ""):
        super().__init__()
        self.base = base_url.rstrip("/")
        self.token = (token or "").strip()
        self._remote_id = None
        self._polled_at = 0.0

    @property
    def kind(self) -> str:
        return "http"

    # ── HTTP ────────────────────────────────────────
    #
    # 用 stdlib 的 urllib 而不是 requests:整個專案只有這裡要發 HTTP,
    # 為兩支呼叫多釘一個套件不值得(理由同 acqua/env.py 不用 python-dotenv)。
    def _call(self, method: str, path: str, payload=None, timeout: float = 10):
        """回 (status_code, 解析好的 JSON)。4xx/5xx 不丟例外 —— MCC 會在
        錯誤回應的 body 裡講原因,那比狀態碼有用得多。連不上才丟例外。"""
        req = Request(self.base + path, method=method)
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
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
            raise RuntimeError("Cannot reach the controller: %s" % (exc.reason,)) from exc
        except socket.timeout as exc:
            raise RuntimeError("Controller timed out") from exc

    # ── 送出 / 追蹤 ─────────────────────────────────
    def _start(self, job):
        moves = [(s["axis"], s["to"]) for s in job["steps"]]
        code, body = self._call("POST", "/api/motion/jobs",
                                {"label": job["label"],
                                 "targets": targets_by_device(moves)})
        job_id = (body or {}).get("job_id")
        if code >= 400 or not job_id:
            raise RuntimeError("Controller refused the move (HTTP %d): %s"
                               % (code, (body or {}).get("error") or "no job_id"))
        with self._lock:
            self._remote_id = str(job_id)
            self._polled_at = 0.0
        job["remote_id"] = str(job_id)

    def _refresh(self):
        with self._lock:
            job, rid = self._job, self._remote_id
            if not job or job["state"] != "running" or not rid:
                return
            if time.time() - self._polled_at < self.poll_seconds:
                return
            self._polled_at = time.time()
        try:
            code, body = self._call("GET", "/api/motion/jobs/" + rid)
        except RuntimeError as exc:
            # 暫時連不上不算失敗 —— 機構可能還在走。擺位協調有自己的總逾時。
            with self._lock:
                job["poll_error"] = str(exc)[:120]
            return
        if code == 404:
            self._finish(job, "error", "The controller no longer knows job %s" % rid)
            return
        remote = (body or {}).get("job") or {}
        state = str(remote.get("state") or "")
        with self._lock:
            job.pop("poll_error", None)
            job["remote_state"] = state
        if state == "done":
            self._apply_positions(job, remote.get("positions"))
            self._finish(job, "done")
        elif state in ("error", "aborted"):
            self._finish(job, state, str(remote.get("error") or state)[:300])

    def _apply_positions(self, job, reported):
        """作業完成:有回報就用回報的位置,沒有就相信目標(標成推估)。"""
        reported = reported if isinstance(reported, dict) else {}
        with self._lock:
            for step in job["steps"]:
                ax = AXES[step["axis"]]
                value = (reported.get(ax.pi) or {}).get(ax.ch + "M")
                if isinstance(value, (int, float)):
                    self._pos[ax.id] = ax.clamp(ax.to_scene(value))
                    self._est[ax.id] = False
                else:
                    self._pos[ax.id] = step["to"]
                    self._est[ax.id] = True
                step["state"] = "done"
            job["index"] = len(job["steps"])


# ══════════════════════════════════════════════════════════
#  選後端
# ══════════════════════════════════════════════════════════

def make_crane(base_url: str = "", token: str = "") -> CraneBridge:
    """位址有設就交給 MCC,沒設就用模擬。

    位址從 config 的 setup_controller.url 來(由 .env 的 ACQUA_SETUP_CONTROLLER
    覆寫),token 從 setup_controller.token(ACQUA_SETUP_CONTROLLER_TOKEN)。

    預設是模擬,而不是「試著連、連不到再退回」—— 連不到的時候要吵,
    不要安靜地變成假的。要接真機就明確設定位址。
    """
    url = (base_url or "").strip()
    if not url:
        return MockCrane()
    return HttpCrane(url, token)
