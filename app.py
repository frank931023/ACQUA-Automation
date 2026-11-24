"""ACQUA 測試自動化 —— Flask Web 介面。

啟動:
    python app.py                # 用 config.json(沒有的話用 config.example.json)
    python app.py --backend mock # 強制模擬模式

[!] Flask 執行緒與 COM 執行緒是分開的。這個檔案裡的任何程式碼
   都不可以直接碰 COM 物件 —— 一律透過 worker.submit() 下命令。
"""
import argparse
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time

from flask import (Blueprint, Flask, Response, jsonify, render_template,
                   request, send_from_directory)

from acqua.labcore import PAIR_LABELS as MIC_PAIR_LABELS
from acqua import env as env_settings
from acqua.crane import AXES, axes_manifest as crane_axes_manifest, make_crane
from acqua.context import parse_ctx, project_id_of
from acqua.prefs import Prefs
from acqua.roomsetups import RoomSetups
from acqua.runlog import RunLog
from acqua.sqlcat import raw_query
from acqua.setupcoord import SetupCoordinator, match_position
from acqua.state import SharedState
from acqua.testplans import TestPlans, source_of
from acqua.worker import make_worker

# 主控台預設是 cp950,印到非 CJK 符號會丟 UnicodeEncodeError 把程式打掛。
# 這裡強制 stdout/stderr 走 UTF-8,印不出來的字元退化成 ? 而不是例外。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
state = SharedState()
worker = None
config = {}
# 測試計畫存在本地 plans/ 資料夾,不寫回 ACQUA 資料庫
plans = TestPlans(BASE_DIR)
prefs = Prefs(BASE_DIR)
# 量測擺位存在本地 setups/ 資料夾,與測試計畫分開 —— 見 acqua/roomsetups.py
#
# 目錄可以用 --setups-dir 或 ACQUA_SETUPS_DIR 換掉。這不是為了彈性,是為了
# **不要讓測試踩到真資料**:測試伺服器跟正在用的服務如果共用同一個
# setups/,測試開場的「清乾淨」就會把使用者存的擺位一起刪掉。
room_setups = RoomSetups(os.environ.get("ACQUA_SETUPS_DIR") or BASE_DIR)
#: 天車位置橋接。真正的位址在讀完設定之後才知道,所以這裡先放 None,
#: 由 main() 建起來。import 時就連線會讓 `python -c "import app"` 也去打網路。
bridge = None

#: 最後一次收到請求的時間。閒置退出用 —— 見 _idle_watchdog。
_last_seen = [time.monotonic()]


@app.before_request
def _mark_seen():
    # 靜態檔不算 —— 瀏覽器可能只是在背景抓 favicon
    if not request.path.startswith("/soundproofroom/src/"):
        _last_seen[0] = time.monotonic()


# ACQUA 測試自動化整組掛在 /acqua 底下 —— 頁面與 API 都是。
# 好處:網址一看就知道屬於哪個子系統,以後要再加別的模組也不會打架。
acqua_bp = Blueprint("acqua", __name__, url_prefix="/acqua")


# ── 設定 ────────────────────────────────────────────
class StepRunner:
    """依序執行一串 worker 命令,並記下每一步的成敗。

    用途:把 ACQUA 帶到某個位置(換庫 → 開專案 → 選 MO → 載入測項)。
    這種流程的重點不是「成功了沒」,而是**卡在哪一步、為什麼** ——
    所以每一步都留下 {name, ok, detail},直接回給前端逐條顯示。
    """

    def __init__(self, worker, log_prefix=""):
        self._worker = worker
        self._prefix = log_prefix
        self.steps = []

    def run(self, name, command, timeout=300, **kwargs):
        """送一個 worker 命令並等它完成。回傳成功與否,不丟例外。"""
        try:
            self._worker.submit(command, **kwargs).wait(timeout=timeout)
            self.steps.append({"name": name, "ok": True})
            return True
        except Exception as exc:                            # noqa: BLE001
            self.steps.append({"name": name, "ok": False,
                               "detail": str(exc)[:200]})
            if self._prefix:
                state.log(f"{self._prefix} {name} 失敗:{exc}", "warn")
            return False

    def note(self, name, detail=""):
        """記一個不需要送命令的步驟(例如「對應測項 3/3」)。"""
        self.steps.append({"name": name, "ok": True, "detail": detail})

    def fail(self, name, detail):
        self.steps.append({"name": name, "ok": False, "detail": str(detail)[:200]})

    @property
    def done(self):
        return [s["name"] for s in self.steps if s["ok"]]

    def bail(self, **extra):
        """中途失敗時的統一回應。"""
        return jsonify(ok=False, steps=self.steps,
                       state=state.snapshot(), **extra), 400


def _cmd(_cmd_name, timeout=600, **kwargs):
    """下命令並等待結果,統一轉成 JSON 回應。

    第一個參數刻意加底線前綴 —— 指令的 kwargs 裡本來就可能有 name
    (例如切換硬體設定),同名會撞成 TypeError。
    """
    if worker is None or not worker.ready.is_set():
        return jsonify(ok=False, error="Worker thread is not ready"), 503
    if worker.init_error:
        return jsonify(ok=False, error=f"Backend initialisation failed: {worker.init_error}"), 500
    try:
        result = worker.submit(_cmd_name, **kwargs).wait(timeout=timeout)
        return jsonify(ok=True, result=result, state=state.snapshot())
    except Exception as exc:                            # noqa: BLE001
        return jsonify(ok=False, error=str(exc), state=state.snapshot()), 400


# ── 首頁 ────────────────────────────────────────────
@app.route("/")
def home():
    """入口頁 —— 四張卡,分別進到各個子系統。"""
    return render_template("home.html")


# ── ACQUA 測試自動化(全部在 /acqua 底下)──────────────
@acqua_bp.route("/")
def index():
    return render_template("index.html", config=config)


# ── 聲學測試室 3D 視覺化 ─────────────────────────────
#
# 兩種模式,路由會自動選:
#   1. 有 build 過 → 直接送 static/soundproofroom/ 底下的成品(離線可用)
#   2. 沒 build    → 送 templates/soundproofroom.html,用 importmap 從 CDN 取 three.js
#
# 不管哪種模式,原始碼都是同一份 soundproofroom/src/。
ROOM_DIR = os.path.join(BASE_DIR, "soundproofroom")
ROOM_DIST = os.path.join(BASE_DIR, "static", "soundproofroom")


def _room_is_built():
    return os.path.isfile(os.path.join(ROOM_DIST, "index.html"))


@app.route("/soundproofroom")
@app.route("/soundproofroom/")
def soundproofroom():
    if _room_is_built():
        return send_from_directory(ROOM_DIST, "index.html")
    return render_template("soundproofroom.html")


@app.route("/soundproofroom/src/<path:filename>")
def soundproofroom_src(filename):
    """免 build 模式下,直接把原始碼當靜態檔送出去。"""
    return send_from_directory(os.path.join(ROOM_DIR, "src"), filename)


@app.route("/soundproofroom/<path:filename>")
def soundproofroom_asset(filename):
    """build 過之後的 assets(js/css/map)。"""
    if _room_is_built():
        return send_from_directory(ROOM_DIST, filename)
    return ("Not built yet", 404)


# ── 量測擺位(setup)清單頁 ────────────────────────
#
# 跟 /acqua/plans 分開:那一頁排的是「要跑哪些測項」,這一頁存的是
# 「機構擺在哪裡」。同一個擺位會被好幾批測項共用,綁在一起改一次位置
# 要去改三個計畫檔。
@app.route("/setups")
def setups_page():
    return render_template("setups.html")


@app.route("/setups/<setup_id>")
def setup_detail_page(setup_id):
    d = room_setups.load(setup_id)
    if d is None:
        return render_template("setups.html", missing=setup_id), 404
    return render_template("setup_detail.html", setup_id=setup_id)


# ── 擺位與機構 ───────────────────────────────────
#
# 全部在 /api/room 底下。刻意不掛進 acqua_bp —— 這組 API 跟 ACQUA 的
# COM 工作佇列完全無關,ACQUA 的掛鉤在量測開始前就會呼叫。
#
# 這裡**沒有**給人看實機位置、手動推機構的 API。那類即時操作屬於天車
# 控制中心(MCC);本專案只負責設計擺位,並在測試執行時自動套用。
def _no_bridge():
    """bridge 是 main() 建的(位址要等 config 讀完才知道)。

    有人用 `flask run` 之類的方式跳過 main() 起服務時,每一支 /api/room/*
    都會爆 AttributeError: 'NoneType' —— 那看起來像程式壞了,其實是沒照
    app.py 的入口起。回一個講得清楚的 503,照 _cmd() 檢查 worker 的做法。
    """
    return jsonify(ok=False,
                   error="Crane bridge is not initialised - start the service "
                         "with `python app.py` (not `flask run`)"), 503


@app.route("/api/room/axes")
def api_room_axes():
    """軸清單(行程以場景單位表示)。

    3D 頁拿這個跟 spec.json 交叉比對 —— 兩邊的行程刻意各存一份(後端不能
    拿瀏覽器送來的範圍當行程上限),所以要有個地方會在不一致時示警,
    不然就變成「一份寫死的數字,沒人知道它跟另一份不一樣」。存擺位時
    超出後端行程的值會被夾回範圍內,不一致時畫面跟存檔就會對不上。
    """
    return jsonify(ok=True, axes=crane_axes_manifest())


#: 擺位協調:Setup 標籤 -> 機構動作,見 acqua/setupcoord.py。
#: 機構橋接與逾時要等 main() 讀完設定才知道,在那裡接上。
setup_coord = SetupCoordinator(state, room_setups, raw_query)


@app.route("/api/room/current")
def api_room_current():
    """[*] 機構現在停在哪一個存好的擺位上。

    為什麼需要這支
    ──────────────
    測項的 `Setup` 標籤說「我要哪個擺位」,但要知道「現在是不是已經在
    那裡了」才能決定要不要移動 —— 不然每一筆都會重跑一次移動,
    而移動要好幾分鐘。

    執行器與 ACQUA 掛鉤都用這支,見 acqua_scripts/SETUP_AUTOMATION_PLAN.md。

    怎麼判斷
    ────────
    拿目前每根軸的位置,跟每個存好的擺位逐軸比對。全部落在容差內就算命中。
    沒有命中的話回 setup=None —— 那不是錯誤,只是機構停在一個沒存過的
    位置上(例如有人手動調過)。
    """
    if bridge is None:
        return _no_bridge()

    snap = bridge.snapshot()
    axes = snap.get("axes") or {}
    matched, scored = match_position(
        {k: v["value"] for k, v in axes.items()}, room_setups.list())
    estimated = any(v.get("estimated") for v in axes.values())

    return jsonify(
        ok=True,
        setup=(matched or {}).get("name") or None,
        setup_id=(matched or {}).get("id") or None,
        # 位置是推估的時候要講出來 —— 呼叫端可能想拒絕在這種狀態下判斷
        estimated=estimated,
        kind=snap.get("kind"),
        # ⚠️ 不能寫 bool(snap["job"]) —— 作業跑完留在那裡當紀錄不會清掉,
        #    那樣寫的話第一次移動之後這支就永遠回報「移動中」。
        moving=bridge.busy(),
        closest=scored[:3],
    )


@app.route("/api/room/not-applied", methods=["POST"])
def api_room_not_applied():
    """[*] 「這一筆沒套用到指定擺位」—— 給 **ACQUA 內部的掛鉤** 回報用。

    為什麼要有這支
    ──────────────
    擺位有兩條驅動路線:

        我們主導   /api/run 逐筆送出,送之前自己把機構移好
                   -> 沒套用到就由 SetupCoordinator.before_item() 記下來
        ACQUA 主導 使用者直接在 ACQUA 按執行,繞過我們的網頁
                   -> 掛鉤 before_each_measurement.py 讀 Tags.Value("Setup"),
                      打這支叫我們移動;移不動的時候**也要留下紀錄**

    第二條路沒有這支就等於沒有防線 ⑤ —— 掛鉤只能在 ACQUA 視窗印一行字,
    而無人值守時沒有人看得到。有了這支,那幾筆一樣會出現在跑完的摘要、
    CSV 與報告旁邊的警告清單裡。

    **不排 COM 佇列** —— 掛鉤是在量測開始前呼叫的,那時工作執行緒正忙,
    排佇列會讓 ACQUA 卡在那裡等我們,等到天荒地老。
    """
    body = request.get_json(silent=True) or {}
    wanted = str(body.get("wanted") or "").strip()
    if not wanted:
        return jsonify(ok=False, error="wanted is required"), 400

    # row_id 是選填 —— 掛鉤那端只拿得到標題(ACQUA 腳本環境沒有 row id)。
    # 給了就用,沒給標 -1,這樣結果比對時至少看得出「有這麼一筆」。
    raw = body.get("row_id")
    row_id = int(raw) if str(raw or "").lstrip("-").isdigit() else -1
    count = setup_coord.note_not_applied(
        row_id, str(body.get("smd") or body.get("title") or ""),
        wanted, str(body.get("reason") or "未說明")[:120])
    return jsonify(ok=True, count=count)


@app.route("/api/room/apply", methods=["POST"])
def api_room_apply():
    """[*] 把一個存好的擺位送去實機 —— 給 **ACQUA 內部的掛鉤** 用。

    吃 {setup_name}:SMD 的 Setup 標籤存的是**名稱**,掛鉤那端沒有 id,
    硬要它自己查一次表只是多一個會壞的地方。

    整組送給機構橋接(真機時交給 MCC 決定順序與防撞,見 docs/MCC_MOTION_API.md)。
    從我們網頁開跑的那條路不經過這支,由 SetupCoordinator 直接叫 bridge。
    """
    if bridge is None:
        return _no_bridge()
    body = request.get_json(silent=True) or {}
    name = str(body.get("setup_name") or "").strip()
    if not name:
        return jsonify(ok=False, error="setup_name is required"), 400
    d = room_setups.find(name)
    if d is None:
        return jsonify(ok=False, error="找不到擺位「%s」" % name), 404
    # 整組都送,不先扣掉「看起來已經到位」的軸 —— 我們這邊的位置可能是
    # 推估的(剛開機、上次沒回報),MCC / 韌體那邊才知道真正在哪。
    # 已經在那裡的軸,韌體走 0 mm 就結束了。
    moves = sorted((k, v) for k, v in (d.get("axes") or {}).items() if k in AXES)
    if not moves:
        return jsonify(ok=False, error="擺位「%s」沒有任何認得的軸" % name), 400
    try:
        job = bridge.submit(moves, label=d.get("name") or name)
    except RuntimeError as exc:
        return jsonify(ok=False, error=str(exc), **bridge.snapshot()), 409
    state.log("套用擺位「%s」到實機(%d 根軸)" % (d.get("name") or name, len(moves)))
    return jsonify(ok=True, job=job)


# ── 擺位的增刪改查 ───────────────────────────────
@app.route("/api/room/setups", methods=["GET", "POST"])
def api_room_setups():
    if request.method == "GET":
        # 一起回存放位置。使用者會想知道「我的擺位在哪個資料夾」,而測試
        # 靠它確認自己沒有打到正在用的服務(刪錯地方一次就夠了)。
        return jsonify(ok=True, setups=room_setups.list(), dir=room_setups.dir)

    body = request.get_json(silent=True) or {}
    if not (body.get("axes") or {}):
        return jsonify(ok=False, error="沒有任何軸的位置 —— 存不出擺位"), 400
    d = room_setups.save(
        setup_id=body.get("id"),
        name=body.get("name", ""),
        description=body.get("description", ""),
        axes=body.get("axes"))
    state.log("已儲存擺位「%s」(%d 根軸)" % (d["name"], d["count"]))
    return jsonify(ok=True, setup=d, setups=room_setups.list())


@app.route("/api/room/setups/<setup_id>", methods=["GET", "POST", "DELETE"])
def api_room_setup_one(setup_id):
    if request.method == "DELETE":
        ok = room_setups.delete(setup_id)
        return jsonify(ok=ok, setups=room_setups.list())

    d = room_setups.load(setup_id)
    if d is None:
        return jsonify(ok=False, error="找不到這個擺位"), 404

    if request.method == "POST":
        # 只給了名稱/說明就不動位置 —— 改個名字不該把擺位洗掉。
        body = request.get_json(silent=True) or {}
        d = room_setups.save(
            setup_id=setup_id,
            name=body.get("name", d.get("name", "")),
            description=body.get("description", d.get("description", "")),
            axes=body.get("axes") if body.get("axes") is not None else d.get("axes"))
        return jsonify(ok=True, setup=d, setups=room_setups.list())

    # 連軸的定義一起回(行程、單位、在哪台 Pi)—— 詳細頁的輸入框要靠它
    # 做範圍提示與驗證。分兩支 API 的話畫面會先畫出一半再跳動。
    #
    # 刻意**不**讀實機位置:這一頁顯示的是存檔裡的數字,不是機構現在在哪。
    # 兩者混在同一張表上,使用者會分不清自己在改哪一個。
    axes = d.get("axes") or {}
    rows = [{**a, "target": axes[a["id"]]}
            for a in crane_axes_manifest() if a["id"] in axes]
    return jsonify(ok=True, setup=d, axes=rows)


# ── 狀態與事件串流 ───────────────────────────────────
@acqua_bp.route("/plans")
def plans_page():
    """[*] 測試計畫頁 —— 勾選幾個已建立的計畫,依序執行。

    刻意跟 /acqua 分開:那一頁是「挑測項馬上跑」,這一頁是
    「把存好的幾批排成佇列」。兩件事的節奏差很多,混在一頁會互相干擾。
    """
    return render_template("plans.html")


@acqua_bp.route("/api/status")
def api_status():
    return jsonify(state.snapshot())


@acqua_bp.route("/api/events")
def api_events():
    """[*] 非串流版的事件查詢 —— 給輪詢用。

    SSE 只是加速用的;真正保證畫面會更新的是前端每 2 秒打這支。
    這樣 SSE 斷線、被 proxy 擋掉、瀏覽器限制連線數的時候都不會瞎掉。
    """
    since = int(request.args.get("since", 0))
    evs = state.events_since(since)
    return jsonify(events=evs, seq=(evs[-1]["seq"] if evs else since))


@acqua_bp.route("/api/stream")
def api_stream():
    """Server-Sent Events —— 低延遲推播。

    [!] 曾經的 bug:原本在 generate() 裡面讀 request.args。
       產生器是「回傳 Response 之後」才被迭代的,那時 Flask 的 request context
       已經銷毀,會丟 RuntimeError: Working outside of request context,
       整條 SSE 回 500 → 前端完全收不到更新。
       修法:在 view function 裡先把值讀出來,用閉包帶進產生器。
    """
    since = int(request.args.get("since", 0))       # ← context 還在時先讀

    def generate(last):
        idle = 0
        while True:
            events = state.events_since(last)
            if events:
                last = events[-1]["seq"]
                for ev in events:
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                idle = 0
            else:
                idle += 1
                if idle >= 20:                          # 約 10 秒送一次 keepalive
                    yield ": keepalive\n\n"
                    idle = 0
            time.sleep(0.5)

    return Response(generate(since), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── 操作 ────────────────────────────────────────────
@acqua_bp.route("/api/connect", methods=["POST"])
def api_connect():
    body = request.get_json(silent=True) or {}
    db = config.get("database", {})
    return _cmd("connect", timeout=300,
                server=body.get("server") or db.get("server", ""),
                database=body.get("database") or db.get("name", ""),
                win_auth=bool(body.get("win_auth", db.get("use_windows_auth", True))),
                username=body.get("username") or db.get("username", ""),
                password=body.get("password") or db.get("password", ""))


@acqua_bp.route("/api/databases", methods=["POST"])
def api_databases():
    """列出 SQL Server 上的資料庫,讓 UI 做成下拉選單。"""
    body = request.get_json(silent=True) or {}
    return _cmd("list_databases", timeout=120,
                server=body.get("server") or config.get("database", {}).get("server", ""))


@acqua_bp.route("/api/restore", methods=["POST"])
def api_restore():
    """換庫之後把上次在這個資料庫用的專案 / 量測物件 / 測項接回來。

    換資料庫會把繫於舊上下文的東西全部作廢(見 acqua/context.py)—— 那是
    對的,但作廢不該讓使用者每次重點四遍。所以記住「這個庫上次用什麼」,
    連上就接回去。

    接回去的每一步都重新驗證:專案不在了、MO 不見了就跳過那一步並說明,
    絕不硬套 —— 記的是標題(意圖),不是 row_id。
    """
    s = state.snapshot()
    want = prefs.recall(s.get("server"), s.get("database"))
    r = StepRunner(worker, "[接回]")

    if not want.get("project"):
        return jsonify(ok=True, restored=False,
                       note="This database has not been used yet — pick a project once and it will be remembered",
                       steps=r.steps, state=state.snapshot())

    # 專案還在不在?不在就不要嘗試,直接說清楚
    groups = {g["name"]: set(g["projects"]) for g in (s.get("project_groups") or [])}
    grp, proj = want.get("group"), want["project"]
    if proj not in groups.get(grp, set()):
        hit = next((g for g, ps in groups.items() if proj in ps), None)
        if hit is None:
            return jsonify(ok=True, restored=False,
                           note=f"The last project \"{proj}\" is no longer in this database",
                           steps=r.steps, state=state.snapshot())
        grp = hit                                # 群組換了名字,專案還在

    if not r.run(f"開啟專案 {proj}", "open_project", group=grp, project=proj):
        return jsonify(ok=True, restored=False, steps=r.steps,
                       state=state.snapshot())

    if want.get("mo"):
        r.run(f"選定量測物件 {want['mo']}", "select_mo",
              timeout=120, title=want["mo"], create_if_missing=False)
    r.run("載入測項", "list_smds", timeout=180, search="")

    state.log("[接回] " + ("、".join(r.done) if r.done else "沒有可接回的項目"))
    return jsonify(ok=True, restored=bool(r.done), steps=r.steps,
                   state=state.snapshot())


@acqua_bp.route("/api/refresh-groups", methods=["POST"])
def api_refresh_groups():
    return _cmd("refresh_groups", timeout=120)


@acqua_bp.route("/api/open-project", methods=["POST"])
def api_open_project():
    body = request.get_json(silent=True) or {}
    group, project = body.get("group", ""), body.get("project", "")
    resp = _cmd("open_project", timeout=300, group=group, project=project)
    if not isinstance(resp, tuple):          # tuple = 失敗(response, status)
        s = state.snapshot()
        prefs.remember(s.get("server"), s.get("database"),
                       group=group, project=project)
    return resp


@acqua_bp.route("/api/select-mo", methods=["POST"])
def api_select_mo():
    body = request.get_json(silent=True) or {}
    target = config.get("target", {})
    title = body.get("title") or target.get("measurement_object", "")
    if not title:
        return jsonify(ok=False, error="Select a measurement object first"), 400
    # 前端給的名稱一律來自下拉選單(既有的),所以不嘗試建立 ——
    # ACQUA 的 AddMeasurementObject 實測回 -1 不動作,詳見 backend_com。
    resp = _cmd("select_mo", timeout=120, title=title, create_if_missing=False)

    # 只有選定成功才寫 metadata(_cmd 失敗時回傳的是 (response, status_code) 的 tuple)
    if isinstance(resp, tuple):
        return resp

    meta = {k: v for k, v in (config.get("metadata") or {}).items()
            if not k.startswith("_") and v}
    meta.update(body.get("metadata") or {})
    if meta:
        try:
            worker.submit("write_metadata", props=meta).wait(timeout=60)
        except Exception:                               # noqa: BLE001
            pass    # metadata 寫入失敗不該擋住主流程,錯誤已經記進日誌

    s = state.snapshot()
    prefs.remember(s.get("server"), s.get("database"), mo=title)
    return resp


@acqua_bp.route("/api/list-smds", methods=["POST"])
def api_list_smds():
    body = request.get_json(silent=True) or {}
    return _cmd("list_smds", timeout=180, search=body.get("search", ""))


@acqua_bp.route("/api/variables", methods=["GET"])
def api_variables_get():
    return _cmd("list_variables", timeout=120)


@acqua_bp.route("/api/variables", methods=["POST"])
def api_variables_set():
    """[*] 混合模式的第一步:把 DUT 屬性寫成 ACQUA 變數。

    之後 StartMeasurements 時,專案樹的 ConditionalExecution 會讀這些變數,
    自動決定哪些 SMD 要跑、哪些略過。
    """
    body = request.get_json(silent=True) or {}
    values = body.get("values") or {}
    if not values:
        return jsonify(ok=False, error="沒有提供任何變數"), 400
    return _cmd("set_variables", timeout=180, values=values)


@acqua_bp.route("/api/last-run")
def api_last_run():
    """[*] 上次有沒有跑到一半?頁面載入時會問這個。

    回傳 null 代表沒有未完成的執行。
    """
    if state.runlog is None:
        return jsonify(None)
    return jsonify(state.runlog.unfinished())


@acqua_bp.route("/api/last-run/dismiss", methods=["POST"])
def api_last_run_dismiss():
    """使用者選擇不續跑 —— 把紀錄清掉,下次不要再問。"""
    if state.runlog:
        state.runlog.clear()
    return jsonify(ok=True)


@acqua_bp.route("/api/predict", methods=["POST"])
def api_predict():
    """[*] 事前預覽:這組變數會跑哪些測項?完全不啟動量測。"""
    body = request.get_json(silent=True) or {}
    return _cmd("predict_run_set", timeout=180,
                variables=body.get("variables") or {})


@acqua_bp.route("/api/run", methods=["POST"])
def api_run():
    """[*] 唯一的執行入口:逐項送出勾選的測項。

    為什麼只有這一種
    ────────────────
    另一條路(StartMeasurements 整批)**沒辦法排除任何項目** —— ACQUA
    自己決定跑什麼,所以「DUT & Measurement Wizard」這類互動精靈一定會
    跳出來等人操作,使用者就得守在旁邊。

    逐項模式可以事前排除那些項目,才有辦法「按下開始就走人」。
    附帶好處:中止是真的能停(不送下一筆就結束了)。
    """
    body = request.get_json(silent=True) or {}

    if state.running:
        return jsonify(ok=False, error="A run is already in progress"), 409

    row_ids = [int(r) for r in (body.get("row_ids") or [])]
    if not row_ids:
        return jsonify(ok=False, error="Nothing selected"), 400

    # ⭐ 呼叫端要聲明「我是在哪個上下文挑的」,不一致就拒絕。
    #
    #    為什麼不能只靠「這些 id 存在於目前專案」:實測 2026-08-21,
    #    51_MS_Teams_Rev05_SP2 的 2443 是 Info 類測項,
    #    ACQUA_auto_v2026Aug 的 2443 是 3QUEST 分析 —— 兩邊都存在,
    #    存在性檢查完全擋不住,但跑起來是完全不同的東西。
    #    ctx 比對是唯一能抓到這種重疊的方法。
    want_ctx = body.get("ctx")
    cur_ctx = state.snapshot().get("ctx")
    if want_ctx and cur_ctx and want_ctx != cur_ctx:
        return jsonify(
            ok=False,
            error=("這批測項是在別的專案/資料庫挑的(%s),"
                   "目前是 %s。請重新載入測項再勾選。" % (want_ctx, cur_ctx))), 409

    # ⚠️ 前置條件要在這裡擋掉。
    #    worker.submit 是射後不理 —— 不先檢查的話,run_smds 就算第一行
    #    就丟「尚未選定量測物件」,這支 API 還是會回 ok,前端就永遠停在
    #    「ACQUA 準備中…」,錯誤只進 log 沒人看到。
    s = state.snapshot()
    if not s.get("open_project"):
        return jsonify(ok=False, error="No project open"), 400
    if not s.get("measurement_object"):
        return jsonify(ok=False,
                       error="No measurement object selected"), 400

    # ⭐ 歸屬驗證要同步做完再送 —— 這批 row_id 真的屬於目前這個專案嗎?
    #    跨資料庫的 idTreeItem 必然重疊,送錯不會報錯,只會安靜地跑到
    #    別的測項。詳見 acqua/context.py。
    try:
        worker.submit("check_rows", row_ids=row_ids).wait(timeout=60)
    except Exception as exc:                                # noqa: BLE001
        return jsonify(ok=False, error=str(exc)), 409

    # 這一批的名稱 —— 會變成每筆結果在 ACQUA 裡的 Description
    # (實測:同一批的每一筆都拿到同一個字串,見 backend_com.run_smds)
    comment = str(body.get("comment") or "").strip()[:250]

    state.set(blocking_window=None)
    # 擺位:讀標籤(含資料夾繼承),需要的話為了少移動而重排(不拆群組)
    snap_now = state.snapshot()
    row_ids = setup_coord.prepare(snap_now.get("ctx"), row_ids,
                                  snap_now.get("smds"),
                                  regroup=bool(body.get("group_by_setup", True)))

    cmd = worker.submit("run_smds", row_ids=row_ids, comment=comment)

    # 給它一下下,萬一一送出就失敗,直接把錯誤回給前端而不是讓它空等
    try:
        cmd.wait(timeout=1.5)
    except TimeoutError:
        pass                                                # 還在跑 = 正常
    except Exception as exc:                                # noqa: BLE001
        return jsonify(ok=False, error=str(exc)), 400

    return jsonify(ok=True, queued=len(row_ids))


@acqua_bp.route("/api/setup-check", methods=["POST"])
def api_setup_check():
    """[*] 開跑前的擺位標籤檢查(計畫書防線 ①②)。**只報告,不擋。**

    取代原本「這個計畫沒設 setup」的提醒。擺位改由 ACQUA 裡的 Setup 標籤
    決定之後,會出錯的地方變成「忘了標」和「名稱打錯」—— 這支把兩種都在
    按下執行之前講出來,打錯的還附上最接近的名稱。

    為什麼不擋:擺位是加分項。打錯一個字不該讓一整晚的批次跑不起來,
    那幾筆會照常量、記一筆警告(防線 ⑤)。要不要先回去修,讓人決定。

    走 SQL 不排 COM 佇列 —— 前一批還在跑的時候也要能檢查下一批。

    兩種問法:
        {row_ids, ctx}   單批頁:剛勾的那幾筆,在哪個專案勾的
        {plan_id}        序列頁:一個存好的計畫 —— 它可能屬於別的資料庫,
                         所以用計畫自己記的 ctx,不用目前開著的專案
    """
    body = request.get_json(silent=True) or {}
    if body.get("plan_id"):
        plan = plans.load(body["plan_id"])
        if plan is None:
            return jsonify(ok=False, error="Plan not found"), 404
        row_ids = [int(x["row_id"]) for x in (plan.get("items") or [])]
        ctx = (plan.get("source") or {}).get("ctx")
    else:
        row_ids = [int(r) for r in (body.get("row_ids") or [])
                   if str(r).lstrip("-").isdigit()]
        ctx = body.get("ctx") or state.snapshot().get("ctx")
    if not parse_ctx(ctx)[2]:
        # 舊計畫沒記 ctx —— 判斷不了是哪個專案,不要拿目前的專案硬猜
        return jsonify(ok=False, error="This plan has no project context "
                       "(legacy format)"), 400
    return jsonify(ok=True, **setup_coord.check(ctx, row_ids))


@acqua_bp.route("/api/health")
def api_health():
    """開頁前的就緒檢查。**不排進工作佇列。**

    量測跑起來時佇列是塞住的,而那正是最需要知道「服務還活著嗎」的時候。
    所以只讀已經記錄下來的狀態,不主動去碰 COM。

    三個層層遞進的訊號:
        licence_service  Sentinel LDK 在不在(dongle 拔掉時它還是在,
                         所以只是必要條件)
        acqua_process    ACQUA 開著沒
        com              **決定性的一項** —— 真的碰得到 ACQUA。
                         授權或 dongle 有問題時 COM 一定失敗。

    每一項都附「怎麼修」,因為看到這個畫面的人通常正卡住。
    """
    import subprocess
    import time as _t

    checks = []

    def add(key, ok, detail, fix=""):
        checks.append({"key": key, "ok": bool(ok), "detail": detail, "fix": fix})

    # ⚠️ `ready` 是啟動時設一次的閂鎖 —— 執行緒死了它照樣是 True。
    #    活性要看 is_alive()。
    alive_thread = bool(worker and worker.is_alive())
    ready = bool(worker and worker.ready.is_set())
    init_err = str(worker.init_error)[:160] if (worker and worker.init_error) else ""
    busy_cmd = worker.running_command() if worker else None
    add("worker", alive_thread and ready and not init_err,
        ("running: %s" % busy_cmd) if busy_cmd
        else ("idle" if (alive_thread and ready) else "thread not alive"),
        init_err or ("The worker thread died - restart the service."
                     if not alive_thread else ""))

    snap = state.snapshot()
    if snap.get("backend") != "com":
        add("acqua", True, "mock backend — ACQUA not needed")
        return jsonify(ok=all(c["ok"] for c in checks), mock=True,
                       checks=checks, state=snap)

    def probe(cmd, needle, timeout=8):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=timeout).stdout
            return needle in out
        except Exception:                                   # noqa: BLE001
            return None                                     # 查不到,不當作失敗

    svc = probe(["sc", "query", "hasplms"], "RUNNING", 6)
    add("licence_service", svc is not False,
        {True: "running", False: "not running"}.get(svc, "unknown"),
        "Start the Sentinel LDK License Manager service (hasplms)."
        if svc is False else "")

    proc = probe(["tasklist", "/FI", "IMAGENAME eq Acqua6.exe"], "Acqua6.exe")
    add("acqua_process", proc is not False,
        {True: "running", False: "not running"}.get(proc, "unknown"),
        "Start ACQUA first — this service attaches to it, it does not launch it."
        if proc is False else "")

    beat = worker.last_pump_ok if worker else 0.0
    age = (_t.monotonic() - beat) if beat else None
    err = (worker.last_pump_error if worker else "worker missing")
    # 忙著執行命令時走不到閒置迴圈,心跳當然不會更新 —— 那不是死掉。
    # 開專案可以跑 300 秒,一批量測好幾分鐘,用時間判斷一定誤報。
    alive = bool(busy_cmd) or bool(
        beat and age is not None and age < 30 and not err)
    add("com", alive,
        ("busy: %s" % busy_cmd) if busy_cmd
        else (("heartbeat %.1fs ago" % age) if age is not None else "no heartbeat"),
        (err or "Cannot reach ACQUA over COM. Check that ACQUA is open and the "
                "ACOPT18 licence dongle is plugged in.") if not alive else "")

    return jsonify(ok=all(c["ok"] for c in checks), mock=False,
                   checks=checks, state=snap)


@acqua_bp.route("/api/shutdown", methods=["POST"])
def api_shutdown():
    """把服務關掉並釋放 port。

    環境有問題時(ACQUA 沒開、dongle 沒插)最自然的動作就是收工去修,
    而不是留一個半死不活的行程佔著 port。

    有測試在跑就拒絕 —— 那是唯一不該被隨手關掉的情況。
    """
    body = request.get_json(silent=True) or {}
    if (state.running or (worker and worker.busy())) and not body.get("force"):
        return jsonify(ok=False, running=True,
                       error="A test is running - stop it first"), 409

    state.log("Shutdown requested from the web UI", "warn")

    def bye():
        import time as _tt
        _tt.sleep(0.4)          # 讓這個回應先送出去
        try:
            if worker:
                worker.stop()
                worker.join(timeout=8)
        except Exception:                                   # noqa: BLE001
            pass
        os._exit(0)

    threading.Thread(target=bye, daemon=True).start()
    return jsonify(ok=True)


@acqua_bp.route("/api/status-codes")
def api_status_codes():
    """狀態碼字典 —— 讓前端不用自己抄一份 0-8 的對應表。

    負數是我們自己標的(ACQUA 沒發結果事件時),見 acqua/constants.py。
    """
    from acqua.constants import EMEResult
    names = EMEResult.all_names()
    return jsonify(ok=True, codes=[
        {"code": c, "name": names[c],
         "ours": EMEResult.is_ours(c),
         # unknown = 「沒有回報」,不是「判定失敗」。它算在未通過那一側,
         # 但要讓 UI 能分開講,否則會被當成受測物不合格。
         "unknown": c in EMEResult.UNKNOWN,
         "passing": (not EMEResult.is_ours(c)) and c in EMEResult.PASSING}
        for c in sorted(names)])


@acqua_bp.route("/api/clear-run", methods=["POST"])
def api_clear_run():
    """清掉這個服務裡殘留的執行紀錄與狀態。

    為什麼需要:同一台機器可能有好幾個 port 各跑過一輪,或上一輪跑到一半
    行程就掛了 —— 於是 running 一直是 True,新的一批送不出去,畫面上還
    掛著別人的進度。這支就是把「我們這邊的殘留」歸零。

    ⚠️ 不會動 ACQUA 資料庫裡的量測結果 —— 那是破壞性操作,要刪請在
       ACQUA 裡自己刪。這裡只清本服務的狀態與 runs/current.json。
    """
    body = request.get_json(silent=True) or {}
    busy = bool(worker is not None and worker.busy())
    if state.running and busy and not body.get("force"):
        return jsonify(ok=False, running=True,
                       error="A run really is in progress — stop it first"), 409

    stale = state.running and not busy
    state.clear_results()
    state.set(running=False, cancel_requested=False, paused=False,
              current=None, progress=None, blocking_window=None)
    if state.runlog:
        try:
            state.runlog.finish(canceled=True)
        except Exception:                                   # noqa: BLE001
            pass
    state.log("已清除本服務的執行紀錄"
              + ("(原本卡在執行中,但工作執行緒其實是閒的)" if stale else ""), "warn")
    return jsonify(ok=True, was_stale=stale, state=state.snapshot())


@acqua_bp.route("/api/cancel", methods=["POST"])
def api_cancel():
    """[*] 中止。真的中止 —— run_smds 的迴圈不送下一筆就停了,在途的那一筆會跑完。"""
    worker.request_cancel()
    return jsonify(ok=True)


@acqua_bp.route("/api/pause", methods=["POST"])
def api_pause():
    """[*] 暫停(可恢復)。停在兩筆之間,在途的那一筆會跑完。"""
    if worker is None:
        return jsonify(ok=False, error="Worker thread is not ready"), 503
    worker.request_pause()
    return jsonify(ok=True)


@acqua_bp.route("/api/resume", methods=["POST"])
def api_resume():
    """[*] 從暫停接回去繼續跑。

    暫停 = 停掉視窗監看器,量測停在對話框前面;
    繼續 = 監看器開回來,那些對話框又會被處理,量測自然往下走。
    """
    if worker is None:
        return jsonify(ok=False, error="Worker thread is not ready"), 503
    worker.request_resume()
    return jsonify(ok=True)


@acqua_bp.route("/api/blocking", methods=["GET", "POST"])
def api_blocking():
    """[*] ACQUA 開了對話框在等人時,用這支查詢與回覆。

    GET  → 目前擋著的視窗(含訊息與按鈕文字)
    POST → {hwnd, action}  action = "close" 或 "click:<按鈕文字>"
    """
    if request.method == "GET":
        return jsonify(ok=True, blocking=state.snapshot().get("blocking_window"))
    body = request.get_json(silent=True) or {}
    hwnd, action = body.get("hwnd"), body.get("action")
    if not hwnd or not action:
        return jsonify(ok=False, error="需要 hwnd 與 action"), 400

    # ⚠️ 不能走 _cmd()/命令佇列 —— run_smds 正阻塞著工作執行緒,
    #    排進去的命令要等整批跑完才會被處理。而阻塞視窗只在量測進行中
    #    才出現,排隊等於永遠不會被回答。
    if worker is None:
        return jsonify(ok=False, error="Worker thread is not ready"), 503
    try:
        ok = worker.answer_blocking(hwnd, action)
    except Exception as exc:                                # noqa: BLE001
        return jsonify(ok=False, error=str(exc)), 400
    return jsonify(ok=bool(ok), state=state.snapshot())


@acqua_bp.route("/api/wizard-options")
def api_wizard_options():
    """[*] 精靈選項 —— 從專案樹的 ConditionalExecution 反推出來。

    ACQUA 自己的 DUT & Measurement Wizard 是 Tcl/Tk 的,內容讀不到;
    但它的選項最後都變成變數,而變數的可能值都寫在條件式裡。
    """
    return _cmd("wizard_options", timeout=180)


@acqua_bp.route("/api/plans", methods=["GET", "POST"])
def api_plans():
    """[*] 測試計畫(一批要跑的測項 + 當時的 DUT 設定)。

    GET  → 清單(最新的在前)
    POST → 新增/更新。給 id 就是更新,沒給就新增。
    """
    if request.method == "GET":
        return jsonify(ok=True, plans=plans.list())

    body = request.get_json(silent=True) or {}
    items = body.get("items") or []
    if not items:
        return jsonify(ok=False, error="No items — cannot save a plan"), 400
    s = state.snapshot()
    # source = 「這批測項是在哪裡挑的」。跨庫執行時要靠它知道切去哪,
    # 也要靠 ctx 判斷能不能直接用 row_id(見 acqua/context.py)。
    d = plans.save(
        plan_id=body.get("id"),
        title=body.get("title", ""),
        description=body.get("description", ""),
        items=items,
        variables=body.get("variables") or {},
        source=source_of(s),
        manual_excluded=body.get("manual_excluded") or [],
    )
    state.log(f"已儲存測試計畫「{d['title']}」({d['count']} 項)")
    return jsonify(ok=True, plan=d, plans=plans.list())


@acqua_bp.route("/api/plans/<plan_id>", methods=["GET", "DELETE", "POST"])
def api_plan_one(plan_id):
    if request.method == "DELETE":
        ok = plans.delete(plan_id)
        return jsonify(ok=ok, plans=plans.list())

    d = plans.load(plan_id)
    if d is None:
        return jsonify(ok=False, error="Plan not found"), 404

    if request.method == "POST":
        # 只改「描述性」欄位 —— 測項與 source 不在這裡動,
        # 那些要重新挑一次才有意義(換了專案的 row_id 不能沿用)。
        body = request.get_json(silent=True) or {}
        d = plans.save(
            plan_id=plan_id,
            title=body.get("title", d.get("title", "")),
            description=body.get("description", d.get("description", "")),
            items=d.get("items") or [],
            variables=d.get("variables") or {},
            source=d.get("source") or {},
        )
        return jsonify(ok=True, plan=d, plans=plans.list())

    return jsonify(ok=True, plan=d)


@acqua_bp.route("/api/mos")
def api_mos():
    """目前開著的專案底下有哪些量測物件(DUT)。

    走 SQL 而不是 COM:這只是填一個下拉選單,不該為它排進工作佇列 ——
    量測正在跑的時候佇列是塞住的,那時候使用者更需要看得到清單。
    """
    s = state.snapshot()
    if not (s.get("server") and s.get("database")):
        return jsonify(ok=True, mos=[], note="Not connected")

    pid = project_id_of(s.get("ctx"))
    if pid is None and not s.get("open_project"):
        return jsonify(ok=True, mos=[], note="No project open")

    from acqua.sqlcat import SqlCatalog
    cat = SqlCatalog(state)
    if not cat.connect(s["server"], s["database"]):
        return jsonify(ok=False, error="SQL connection failed"), 400
    try:
        mos = cat.list_mobjects(project_id=pid,
                                project_title=s.get("open_project"))
    except Exception as exc:                                # noqa: BLE001
        return jsonify(ok=False, error=str(exc)[:160]), 400
    return jsonify(ok=True, mos=mos, current=s.get("measurement_object") or "")


@acqua_bp.route("/api/plans/<plan_id>/mos")
def api_plan_mos(plan_id):
    """這個計畫的來源專案底下有哪些量測物件(DUT)可以選。

    走 SQL 直接查,不碰 COM —— 使用者是在「還沒切過去」的時候要選的,
    為了填一個下拉選單就把 ACQUA 切走太粗暴,而且序列可能正在跑。

    ⚠️ 不提供「輸入新名稱自動建立」:實測 AddMeasurementObject 一律回傳
       -1 且不寫任何資料(見 acqua/sqlcat.py 上方說明)。新 DUT 要在
       ACQUA 裡建。
    """
    plan = plans.load(plan_id)
    if plan is None:
        return jsonify(ok=False, error="Plan not found"), 404
    src = plan.get("source") or {}
    # 舊計畫沒記 server(那時候只存了 database)—— 退回目前連的那台。
    # 實務上只有一台 SQL Server,真正決定內容的是 database。
    server = (src.get("server") or state.snapshot().get("server")
              or config.get("database", {}).get("server", ""))
    database = src.get("database")
    if not (server and database):
        return jsonify(ok=True, mos=[], note="This plan has no source database (legacy format)")

    pid = project_id_of(src.get("ctx"))

    from acqua.sqlcat import SqlCatalog
    cat = SqlCatalog(state)
    if not cat.connect(server, database):
        return jsonify(ok=False, error=f"Cannot reach {server} / {database}"), 400
    try:
        mos = cat.list_mobjects(project_id=pid, project_title=src.get("project"))
    except Exception as exc:                                # noqa: BLE001
        return jsonify(ok=False, error=str(exc)[:160]), 400
    return jsonify(ok=True, mos=mos, default=src.get("measurement_object") or "")


@acqua_bp.route("/api/plans/<plan_id>/prepare", methods=["POST"])
def api_plan_prepare(plan_id):
    """把 ACQUA 切到這個計畫需要的位置,並算出它對應到哪些 row_id。

    為什麼要有這一步
    ────────────────
    使用者的流程是「跑一串 → 移動治具 → 再跑一串」,而這幾串可能來自
    **不同的資料庫**。所以執行序列的每一步都要先把 ACQUA 帶到對的地方:

        換資料庫 → 開專案 → 選量測物件 → 載入測項 → 對應計畫內容

    最後一步不能省:計畫存的 row_id 只在它被建立的那個專案有意義,
    跨庫的 idTreeItem 必然重疊且指到別的測項(見 acqua/context.py)。
    所以改用「路徑 + 名稱」重新對應,對不上的明白回報,不猜。

    每一步都會回報成功與否,呼叫端可以直接顯示給人看。
    """
    plan = plans.load(plan_id)
    if plan is None:
        return jsonify(ok=False, error="Plan not found"), 404
    if state.running:
        return jsonify(ok=False, error="A run is already in progress"), 409

    src = plan.get("source") or {}
    r = StepRunner(worker)

    # 這一步要把結果寫進哪個 DUT。跨庫/跨機跑同一批時,每台受測物的名稱
    # 本來就不同,所以允許呼叫端覆寫。
    body = request.get_json(silent=True) or {}
    mo_override = str(body.get("measurement_object") or "").strip()

    # ⚠️ 要比對 (server, database) 而不是只比資料庫名 ——
    #    不同機器上很可能有同名的資料庫,只比名字就會以為「不用切」,
    #    然後在錯的機器上跑完一整批。
    cfg = config.get("database", {})
    now = state.snapshot()
    db = src.get("database")
    srv = src.get("server") or cfg.get("server", "")
    if db and (srv, db) != (now.get("server"), now.get("database")):
        where = db if srv == now.get("server") else f"{srv} / {db}"
        if not r.run(f"切換到 {where}", "connect",
                     server=srv, database=db,
                     win_auth=bool(cfg.get("use_windows_auth", True)),
                     username=cfg.get("username", ""),
                     password=cfg.get("password", "")):
            return r.bail()
        r.run("讀取專案清單", "refresh_groups", timeout=120)

    proj = src.get("project")
    if proj and proj != state.snapshot().get("open_project"):
        if not r.run(f"開啟專案 {proj}", "open_project",
                     group=src.get("group") or "", project=proj):
            return r.bail()

    # 選單裡的名稱都是這個專案已經有的,所以不需要(也沒辦法)建立 ——
    # AddMeasurementObject 實測回 -1 不動作,詳見 /api/plans/<id>/mos。
    mo = mo_override or src.get("measurement_object")
    if mo and mo != state.snapshot().get("measurement_object"):
        if not r.run(f"選定量測物件 {mo}", "select_mo", timeout=120,
                     title=mo, create_if_missing=False):
            return r.bail()

    if not r.run("載入測項", "list_smds", search=""):
        return r.bail()

    # 麥克風供電。ACQUA 會自己切接線,但不碰供電 —— 接線跳到沒供電的
    # 通道上時量測照樣 PASS,數據卻是錯的。所以這一步要我們自己做,
    # 而且要在跑之前。沒指定就不動,維持現況。
    mic_pair = str(body.get("mic_power") or "").strip()
    if mic_pair:
        r.run("麥克風供電切到 %s" % MIC_PAIR_LABELS.get(mic_pair, mic_pair),
              "set_mic_power", timeout=60, pair=mic_pair)

    try:
        # 交叉驗證要用的兩個線索:
        #   指紋 —— 專案樹在存檔之後動過沒有(序號可不可信)
        #   same_ctx —— 同一個專案的話 row_id 才是權威
        rep = worker.submit(
            "resolve_items", items=plan.get("items") or [],
            expect_fingerprint=(src.get("tree_fingerprint") or ""),
            same_ctx=(bool(src.get("ctx"))
                      and src.get("ctx") == state.snapshot().get("ctx"))
        ).wait(timeout=180)
    except Exception as exc:                                # noqa: BLE001
        r.fail("對應測項", exc)
        return r.bail()

    detail = "%d / %d" % (len(rep["resolved"]), len(plan.get("items") or []))
    if rep.get("tree_changed"):
        detail += " ・ ⚠️ 專案樹已變動"
    elif rep.get("needs_review"):
        detail += " ・ %d 項要確認" % rep["needs_review"]
    r.note("對應測項", detail)
    return jsonify(ok=True, steps=r.steps, plan=plan, resolution=rep,
                   row_ids=[x["row_id"] for x in rep["resolved"]],
                   ctx=state.snapshot().get("ctx"), state=state.snapshot())


@acqua_bp.route("/api/mic-power", methods=["GET", "POST"])
def api_mic_power():
    """[*] 麥克風極化電壓走哪一組通道。

    GET  → 現況(含接線實際用到哪幾個通道,以及兩者對不對得上)
    POST → {pair: "1-2" | "3-4"}  切換

    為什麼要有這個:ACQUA 量測時會自動切**接線**,但**不碰供電**。
    接線跳到沒供電的通道上時,量測照樣回報 PASS,數據卻是錯的 ——
    實測 2026-09-21 確認過。那一塊沒有別人管,只能我們管。
    """
    if request.method == "GET":
        # ⚠️ **不排進工作佇列。** 量測跑起來佇列就塞住,走佇列的話這支會
        #    卡到量測結束(實測卡滿 20 秒逾時)—— 那會讓整個網頁看起來
        #    像當掉。改讀工作執行緒閒置時更新的快取,見 worker 的
        #    _refresh_mic_cache。量測中供電不會變,所以快取不會騙人。
        snap = state.snapshot()
        return jsonify(ok=True, result=snap.get("mic_power") or
                       {"available": False, "pair": None, "routed": []})

    body = request.get_json(silent=True) or {}
    pair = str(body.get("pair") or "").strip()
    if pair not in ("1-2", "3-4"):
        return jsonify(ok=False,
                       error="pair must be '1-2' or '3-4'"), 400
    # 量測中不給改 —— 改了會讓這一批的前後半段用不同的供電狀態,
    # 而且要排隊等到結束,等於卡住。快速擋下比默默等好。
    if state.running or (worker and worker.busy()):
        return jsonify(ok=False, running=True,
                       error="A test is running - stop it first"), 409
    return _cmd("set_mic_power", timeout=60, pair=pair)


@acqua_bp.route("/api/hardware", methods=["GET", "POST"])
def api_hardware():
    """[*] 硬體連接設定。

    GET  → 全部設定,標出目前選用的
    POST → {name}  切換

    跑之前把目前設定記進 log,事後才查得到那批數據是用什麼跑的。
    """
    if request.method == "GET":
        return _cmd("list_hardware", timeout=60)
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    if not name:
        return jsonify(ok=False, error="name is required"), 400
    return _cmd("set_hardware", timeout=60, name=name)


def _report_stage_dir() -> str:
    """報告的暫存資料夾。ACQUA 一律先產到這裡,再由使用者決定存去哪。"""
    d = os.path.join(BASE_DIR, (config.get("report") or {}).get("output_dir", "reports"))
    os.makedirs(d, exist_ok=True)
    return os.path.abspath(d)


def _suggest_report_name(snap, ext=".doc") -> str:
    """建議檔名:專案_量測物件_日期時間。檔名安全字元以外一律換成底線。"""
    parts = [snap.get("open_project") or "report",
             snap.get("measurement_object") or "",
             time.strftime("%Y%m%d_%H%M")]
    stem = "_".join(p for p in parts if p)
    # Windows 不允許的檔名字元一律換成底線(chr(92) 是反斜線,
    # 直接寫在字串裡容易在各層跳脫中被吃掉)
    bad = chr(92) + '<>:"/|?*'
    stem = "".join("_" if c in bad else c for c in stem)
    return stem[:120] + ext


@acqua_bp.route("/api/report", methods=["POST"])
def api_report():
    """產生報告到暫存資料夾,並回傳「建議檔名 + 上次存放位置」。

    產生完不直接落在最終位置 —— 因為 ACQUA 的 CreateReportForMO 要先有
    確定的路徑才能輪詢判斷寫完沒(見 backend_com.create_report)。
    所以流程是:先產到 reports/,再由前端跳出另存視窗決定去哪。
    """
    body = request.get_json(silent=True) or {}
    rep = config.get("report", {})
    stage = _report_stage_dir()
    name = body.get("filename") or f"report_{time.strftime('%Y%m%d_%H%M%S')}.doc"
    resp = _cmd("create_report", timeout=900,
                output_path=os.path.join(stage, name),
                selection_type=int(body.get("selection_type", rep.get("selection_type", 3))),
                result_index=int(body.get("result_index", 0)))
    if isinstance(resp, tuple):                 # tuple = 失敗
        return resp

    d = resp.get_json() or {}
    path = d.get("result") or ""
    snap = state.snapshot()
    return jsonify(
        ok=True, result=path, state=d.get("state"),
        size=(os.path.getsize(path) if path and os.path.exists(path) else 0),
        suggest_name=_suggest_report_name(snap, os.path.splitext(path)[1] or ".doc"),
        suggest_dir=prefs.report_dir() or stage)


@acqua_bp.route("/api/report/save", methods=["POST"])
def api_report_save():
    """把剛產生的報告另存到使用者指定的位置。

    ⚠️ 來源限定在 reports/ 底下 —— 這支 API 會把檔案寫到任意路徑,
       來源不設限就等於開放「複製本機任意檔案到任意位置」。
    """
    body = request.get_json(silent=True) or {}
    src = os.path.abspath(body.get("src") or "")
    stage = _report_stage_dir()
    if not (src.startswith(stage + os.sep) and os.path.isfile(src)):
        return jsonify(ok=False, error="Cannot find the generated report — generate it again"), 400

    directory = (body.get("directory") or "").strip()
    filename = (body.get("filename") or "").strip()
    if not directory or not filename:
        return jsonify(ok=False, error="File name and folder are required"), 400
    if os.path.basename(filename) != filename:
        return jsonify(ok=False, error="The file name cannot contain a path separator"), 400
    if not os.path.splitext(filename)[1]:
        filename += os.path.splitext(src)[1] or ".doc"

    dst = os.path.join(os.path.abspath(directory), filename)
    if os.path.exists(dst) and not body.get("overwrite"):
        return jsonify(ok=False, exists=True, path=dst,
                       error=f"\"{filename}\" already exists — overwrite?"), 409
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)      # 先複製再刪 —— 中途失敗暫存檔還在
        os.unlink(src)
    except Exception as exc:                                # noqa: BLE001
        return jsonify(ok=False, error=f"Save failed: {exc}"), 400

    prefs.set_report_dir(os.path.dirname(dst))
    state.log(f"報告已存到 {dst}")
    return jsonify(ok=True, path=dst, size=os.path.getsize(dst),
                   setup_note=_write_setup_warning_note(dst))


def _write_setup_warning_note(report_path):
    """報告旁邊補一張「擺位未套用」清單,沒有疑慮就不產生。回檔名或 None。

    ⚠️ 計畫書防線 ⑤ 要求「Word 報告同樣帶這個標記」。報告是 ACQUA 自己
       用 CreateReportForMO 產的,我們改不了它的內容 —— 唯一能做到
       「交出去看得出問題」的方式,是讓警告跟著檔案一起走。
       所以寫成同名的 .擺位警告.txt,放在報告隔壁。
    """
    rows = state.snapshot().get("setup_not_applied") or []
    if not rows:
        return None
    note = os.path.splitext(report_path)[0] + ".擺位警告.txt"
    lines = [
        "⚠️ 這份報告有 %d 筆測項沒有套用到指定的擺位。" % len(rows),
        "這些結果是在**當下的機構位置**量到的,數據可能是錯的。",
        "",
        "報告:%s" % os.path.basename(report_path),
        "產生時間:%s" % time.strftime("%Y-%m-%d %H:%M:%S"),
        "",
        "row_id\t指定擺位\t原因\t測項",
    ]
    lines += ["%s\t%s\t%s\t%s" % (w.get("row_id"), w.get("wanted", ""),
                                 w.get("reason", ""), w.get("title", ""))
              for w in rows]
    try:
        with open(note, "w", encoding="utf-8-sig") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError as exc:
        state.log("擺位警告清單寫不出來:%s" % exc, "warn")
        return None
    state.log("⚠️ 報告旁邊附了擺位警告清單:%s" % os.path.basename(note), "warn")
    return os.path.basename(note)


@acqua_bp.route("/api/report/reveal", methods=["POST"])
def api_report_reveal():
    """在檔案總管裡選取這個檔案。伺服器就跑在使用者自己的機器上。"""
    path = os.path.abspath((request.get_json(silent=True) or {}).get("path") or "")
    if not os.path.exists(path):
        return jsonify(ok=False, error="File does not exist"), 400
    try:
        subprocess.Popen(["explorer", "/select,", path])
    except Exception as exc:                                # noqa: BLE001
        return jsonify(ok=False, error=str(exc)), 400
    return jsonify(ok=True)


@acqua_bp.route("/api/values", methods=["POST"])
def api_values():
    """讀出量測的實際數值(含極限值)。走 SQL —— Acqua3 介面拿不到數字。"""
    body = request.get_json(silent=True) or {}
    return _cmd("read_results", timeout=300,
                latest_only=bool(body.get("latest_only", True)),
                smd_row_ids=body.get("row_ids"))


@acqua_bp.route("/api/results.csv")
def api_results_csv():
    snap = state.snapshot()
    buf = io.StringIO()
    w = csv.writer(buf)
    # setup_not_applied 這一欄是計畫書防線 ⑤ —— 匯出去的檔案也要看得出
    # 哪幾筆可能是在錯誤的位置量到的,不然只有網頁上看得到就等於沒警告。
    w.writerow(["timestamp", "smd_title", "row_id", "status", "result",
                "retries", "setup_not_applied"])
    for r in snap["results"]:
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"])),
                    r["title"], r["row_id"], r["status"],
                    "PASS" if r["passed"] else "FAIL", r["retries"],
                    r.get("setup_warn") or ""])
    return Response(
        "﻿" + buf.getvalue(),          # BOM,讓 Excel 正確辨識 UTF-8
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="acqua_results_{time.strftime("%Y%m%d_%H%M%S")}.csv"'})


# ── 進入點 ──────────────────────────────────────────
def _open_browser_when_ready(url, port, timeout=90):
    """等到 port 真的在聽了才開瀏覽器。

    直接開的話會撞上「還在初始化 COM」那幾秒 —— 使用者看到的是
    連線被拒絕的錯誤頁,然後要自己重新整理。
    """
    def wait():
        import socket
        import webbrowser
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            s = socket.socket()
            s.settimeout(0.5)
            ok = s.connect_ex(("127.0.0.1", port)) == 0
            s.close()
            if ok:
                webbrowser.open(url)
                return
            time.sleep(0.5)

    threading.Thread(target=wait, name="open-browser", daemon=True).start()


def _idle_watchdog(seconds, port):
    """沒人用又沒在跑,就收工把 port 讓出來。

    「沒在跑」有兩個條件都要看:
        state.running    後端自己的旗標
        worker.busy()    工作執行緒真的在執行命令嗎
    只看旗標的話,上一輪沒收乾淨留下的 True 會讓它永遠不退出。
    """
    def loop():
        while True:
            time.sleep(5)
            idle = time.monotonic() - _last_seen[0]
            if idle < seconds:
                continue
            if state.running or (worker and worker.busy()):
                continue        # 有測試在跑 —— 關頁不該讓它停
            print(f"\nIdle for {int(idle)}s with nothing running - shutting down, "
                  f"port {port} released.\nRun again when you need it.")
            try:
                if worker:
                    worker.stop()
                    worker.join(timeout=8)
            except Exception:                                # noqa: BLE001
                pass
            # werkzeug 的開發伺服器沒有乾淨的關閉入口,而該收的
            # (COM、SQL 連線)worker.stop() 已經處理過了。
            os._exit(0)

    th = threading.Thread(target=loop, name="idle-watchdog", daemon=True)
    th.start()


def main():
    global worker, config, bridge, room_setups

    app.register_blueprint(acqua_bp)

    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--backend", choices=["mock", "com"])
    ap.add_argument("--port", type=int)
    ap.add_argument("--setups-dir", metavar="DIR",
                    help="擺位存放的位置(預設是專案底下的 setups/)。"
                         "測試請務必指到別的地方,不然會刪到真的擺位")
    ap.add_argument("--idle-exit", type=int, default=None, metavar="SEC",
                    help="沒人用且沒在跑超過這麼多秒就自動退出(0 = 不退出)")
    ap.add_argument("--open", action="store_true",
                    help="伺服器起來之後自動開瀏覽器")
    args = ap.parse_args()

    if args.setups_dir:
        room_setups = RoomSetups(args.setups_dir)
        print("setups : %s" % room_setups.dir)

    config = env_settings.load_config(BASE_DIR, args.config)
    for line in (config.get("_env_overrides") or []):
        print("[.env] %s" % line)
    if args.backend:
        config["backend"] = args.backend

    print(f"config : {config.get('_loaded_from')}")
    print(f"backend: {config.get('backend')}")
    if config.get("backend") == "mock":
        print("         (mock - does not talk to a real ACQUA)")

    # 天車橋接:位址空的就用模擬位置。刻意印出來 —— 「我以為在看實機,
    # 其實是模擬的」是這類頁面最貴的誤會。
    sc = config.get("setup_controller") or {}
    crane_url = sc.get("url") or ""
    bridge = make_crane(crane_url, sc.get("token") or "")
    print("crane  : %s" % (crane_url if bridge.kind == "http"
                           else "mock (simulated positions - set "
                                "ACQUA_SETUP_CONTROLLER to drive real hardware)"))

    state.runlog = RunLog(BASE_DIR)
    pending = state.runlog.unfinished()
    if pending:
        print(f"[!] Unfinished run found: "
              f"{pending['done_count']}/{pending['total']} done, "
              f"{pending['remaining_count']} left")

    worker = make_worker(config, state)
    worker.start()

    # 擺位鉤子:每一筆測項送出前,需要的話先把機構移到位。
    # 掛在這裡而不是讓 backend 自己做 —— 機構橋接活在 Flask 這一端,
    # backend 只該管 ACQUA。等 ready 之後 worker.backend 才存在。
    setup_coord.bridge = bridge
    setup_coord.move_timeout = float(sc.get("move_timeout_sec", 900))

    def _attach_setup_hook():
        if worker.ready.wait(timeout=320) and worker.backend is not None:
            worker.backend.before_item = setup_coord.before_item

    threading.Thread(target=_attach_setup_hook, daemon=True).start()

    if not worker.ready.wait(timeout=320):
        print("[!] Worker start-up timed out - the web UI still starts so you can read the log")
    elif worker.init_error:
        print(f"[!] Backend initialisation failed: {worker.init_error}")

    web = config.get("web", {})
    port = args.port or int(web.get("port", 5000))
    host = web.get("host", "127.0.0.1")

    # 先確認 port 沒被占用 —— 開兩個 app.py 會各自建 COM 連線去搶同一個 ACQUA
    import socket
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(1.0)
    busy = probe.connect_ex(("127.0.0.1", port)) == 0
    probe.close()
    if busy:
        worker.stop()
        raise SystemExit(
            f"\n[x] Port {port} is already in use.\n"
            f"  A second copy would fight the first one over the same ACQUA.\n"
            f"  Stop the old one, or pass --port to use another port.\n"
            f"  Find it with:  Get-NetTCPConnection -LocalPort {port} -State Listen\n")

    print(f"\nOpen  http://{host}:{port}")
    print(f"   Test run    http://{host}:{port}/acqua")
    print(f"   Test room   http://{host}:{port}/soundproofroom")
    print(f"   Setup list  http://{host}:{port}/setups\n")

    if args.open:
        _open_browser_when_ready(f"http://{host}:{port}/acqua/", port)

    idle = args.idle_exit
    if idle is None:
        idle = int(os.environ.get("ACQUA_IDLE_EXIT", "0") or 0)
    if idle > 0:
        print(f"Quits by itself after {idle}s idle, unless a test is running.")
        _idle_watchdog(idle, port)

    # use_reloader=False —— 重載器會 fork 出第二個行程,COM 執行緒會被開兩份
    app.run(host=host, port=port, threaded=True, use_reloader=False, debug=False)


if __name__ == "__main__":
    sys.exit(main())
