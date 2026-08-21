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
import sys
import time

from flask import (Blueprint, Flask, Response, jsonify, render_template,
                   request, send_from_directory)

from acqua.runlog import RunLog
from acqua.state import SharedState
from acqua.testplans import TestPlans
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

# ACQUA 測試自動化整組掛在 /acqua 底下 —— 頁面與 API 都是。
# 好處:網址一看就知道屬於哪個子系統,以後要再加別的模組也不會打架。
acqua_bp = Blueprint("acqua", __name__, url_prefix="/acqua")


# ── 設定 ────────────────────────────────────────────
def load_config(path=None):
    for candidate in filter(None, [path,
                                   os.path.join(BASE_DIR, "config.json"),
                                   os.path.join(BASE_DIR, "config.example.json")]):
        if os.path.exists(candidate):
            with open(candidate, encoding="utf-8") as fh:
                cfg = json.load(fh)
            cfg["_loaded_from"] = os.path.basename(candidate)
            return cfg
    raise SystemExit("找不到 config.json 或 config.example.json")


def _cmd(_cmd_name, timeout=600, **kwargs):
    """下命令並等待結果,統一轉成 JSON 回應。

    第一個參數刻意加底線前綴 —— 指令的 kwargs 裡本來就可能有 name
    (例如切換硬體設定),同名會撞成 TypeError。
    """
    if worker is None or not worker.ready.is_set():
        return jsonify(ok=False, error="工作執行緒尚未就緒"), 503
    if worker.init_error:
        return jsonify(ok=False, error=f"後端初始化失敗:{worker.init_error}"), 500
    try:
        result = worker.submit(_cmd_name, **kwargs).wait(timeout=timeout)
        return jsonify(ok=True, result=result, state=state.snapshot())
    except Exception as exc:                            # noqa: BLE001
        return jsonify(ok=False, error=str(exc), state=state.snapshot()), 400


# ── 首頁 ────────────────────────────────────────────
@app.route("/")
def home():
    """入口頁 —— 只放兩個按鈕,分別進到兩個子系統。"""
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


@acqua_bp.route("/api/refresh-groups", methods=["POST"])
def api_refresh_groups():
    return _cmd("refresh_groups", timeout=120)


@acqua_bp.route("/api/open-project", methods=["POST"])
def api_open_project():
    body = request.get_json(silent=True) or {}
    return _cmd("open_project", timeout=300,
                group=body.get("group", ""), project=body.get("project", ""))


@acqua_bp.route("/api/select-mo", methods=["POST"])
def api_select_mo():
    body = request.get_json(silent=True) or {}
    target = config.get("target", {})
    title = body.get("title") or target.get("measurement_object", "DUT_001")
    resp = _cmd("select_mo", timeout=120, title=title,
                create_if_missing=bool(target.get("create_mo_if_missing", True)))

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
        return jsonify(ok=False, error="已經有一批測試在執行中"), 409

    row_ids = [int(r) for r in (body.get("row_ids") or [])]
    if not row_ids:
        return jsonify(ok=False, error="沒有勾選任何測項"), 400

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
        return jsonify(ok=False, error="還沒開啟專案 —— 請先完成上面的「開啟專案」"), 400
    if not s.get("measurement_object"):
        return jsonify(ok=False,
                       error="還沒選定量測物件 —— 請先按「選定 / 建立」"), 400

    # ⭐ 歸屬驗證要同步做完再送 —— 這批 row_id 真的屬於目前這個專案嗎?
    #    跨資料庫的 idTreeItem 必然重疊,送錯不會報錯,只會安靜地跑到
    #    別的測項。詳見 acqua/context.py。
    try:
        worker.submit("check_rows", row_ids=row_ids).wait(timeout=60)
    except Exception as exc:                                # noqa: BLE001
        return jsonify(ok=False, error=str(exc)), 409

    state.set(run_mode="selected", blocking_window=None)
    cmd = worker.submit("run_smds", row_ids=row_ids)

    # 給它一下下,萬一一送出就失敗,直接把錯誤回給前端而不是讓它空等
    try:
        cmd.wait(timeout=1.5)
    except TimeoutError:
        pass                                                # 還在跑 = 正常
    except Exception as exc:                                # noqa: BLE001
        return jsonify(ok=False, error=str(exc)), 400

    return jsonify(ok=True, queued=len(row_ids))


@acqua_bp.route("/api/cancel", methods=["POST"])
def api_cancel():
    """[*] 中止。

    逐項模式  ✅ 真的中止 —— Python 迴圈不送下一筆就停了
    整批模式  ⚠️ 做不到 —— ACQUA 自己排隊而且不理會 UserReaction,
              這裡只能停掉視窗監看器,讓它停在下一個對話框
    """
    worker.request_cancel()
    per_item = state.snapshot().get("run_mode") == "selected"
    return jsonify(ok=True, per_item=per_item,
                   note=("目前這筆跑完就停" if per_item else
                         "整批模式只能停在下一個對話框;完全中止請到 ACQUA 視窗操作"))


@acqua_bp.route("/api/pause", methods=["POST"])
def api_pause():
    """[*] 暫停(可恢復)。逐項模式停在兩筆之間;整批模式停止關對話框。"""
    if worker is None:
        return jsonify(ok=False, error="工作執行緒尚未就緒"), 503
    worker.request_pause()
    return jsonify(ok=True)


@acqua_bp.route("/api/resume", methods=["POST"])
def api_resume():
    """[*] 從暫停接回去繼續跑。

    暫停 = 停掉視窗監看器,量測停在對話框前面;
    繼續 = 監看器開回來,那些對話框又會被處理,量測自然往下走。
    """
    if worker is None:
        return jsonify(ok=False, error="工作執行緒尚未就緒"), 503
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
        return jsonify(ok=False, error="工作執行緒尚未就緒"), 503
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
        return jsonify(ok=False, error="沒有任何測項,不能存成計畫"), 400
    s = state.snapshot()
    d = plans.save(
        plan_id=body.get("id"),
        title=body.get("title", ""),
        description=body.get("description", ""),
        items=items,
        variables=body.get("variables") or {},
        database=s.get("database"),
        project=s.get("open_project"),
        # 計畫存的是裸 row_id —— 沒有這個就無法判斷它屬於哪個專案。
        # 拿去別的專案跑會安靜地跑到別的測項(見 acqua/context.py)。
        ctx=s.get("ctx"),
        measurement_object=s.get("measurement_object"),
        hardware_setting=s.get("hardware_active"),
        manual_excluded=body.get("manual_excluded") or [],
    )
    state.log(f"已儲存測試計畫「{d['title']}」({d['count']} 項)")
    return jsonify(ok=True, plan=d, plans=plans.list())


@acqua_bp.route("/api/plans/<plan_id>", methods=["GET", "DELETE"])
def api_plan_one(plan_id):
    if request.method == "DELETE":
        ok = plans.delete(plan_id)
        return jsonify(ok=ok, plans=plans.list())
    d = plans.load(plan_id)
    if d is None:
        return jsonify(ok=False, error="找不到這個計畫"), 404
    return jsonify(ok=True, plan=d)


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
        return jsonify(ok=False, error="需要 name"), 400
    return _cmd("set_hardware", timeout=60, name=name)


@acqua_bp.route("/api/report", methods=["POST"])
def api_report():
    body = request.get_json(silent=True) or {}
    rep = config.get("report", {})
    out_dir = os.path.join(BASE_DIR, rep.get("output_dir", "reports"))
    os.makedirs(out_dir, exist_ok=True)
    name = body.get("filename") or f"report_{time.strftime('%Y%m%d_%H%M%S')}.doc"
    return _cmd("create_report", timeout=900,
                output_path=os.path.join(out_dir, name),
                selection_type=int(body.get("selection_type", rep.get("selection_type", 3))),
                result_index=int(body.get("result_index", 0)))


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
    w.writerow(["timestamp", "smd_title", "row_id", "status", "result", "retries"])
    for r in snap["results"]:
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"])),
                    r["title"], r["row_id"], r["status"],
                    "PASS" if r["passed"] else "FAIL", r["retries"]])
    return Response(
        "﻿" + buf.getvalue(),          # BOM,讓 Excel 正確辨識 UTF-8
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="acqua_results_{time.strftime("%Y%m%d_%H%M%S")}.csv"'})


# ── 進入點 ──────────────────────────────────────────
def main():
    global worker, config

    app.register_blueprint(acqua_bp)

    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--backend", choices=["mock", "com"])
    ap.add_argument("--port", type=int)
    args = ap.parse_args()

    config = load_config(args.config)
    if args.backend:
        config["backend"] = args.backend

    print(f"設定檔:{config.get('_loaded_from')}")
    print(f"後端  :{config.get('backend')}")
    if config.get("backend") == "mock":
        print("       (模擬模式 —— 不會連接真實的 ACQUA)")

    state.runlog = RunLog(BASE_DIR)
    pending = state.runlog.unfinished()
    if pending:
        print(f"[!] 偵測到上次有未完成的執行:"
              f"{pending['done_count']}/{pending['total']} 已完成,"
              f"剩 {pending['remaining_count']} 項")

    worker = make_worker(config, state)
    worker.start()
    if not worker.ready.wait(timeout=320):
        print("[!] 工作執行緒初始化逾時,Web 介面仍會啟動以便查看日誌")
    elif worker.init_error:
        print(f"[!] 後端初始化失敗:{worker.init_error}")

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
            f"\n[x] port {port} 已經有程式在用了。\n"
            f"  多開一個會讓兩個行程搶同一個 ACQUA,狀態會亂掉。\n"
            f"  請先關掉舊的,或用 --port 換一個埠號。\n"
            f"  找出是誰:  Get-NetTCPConnection -LocalPort {port} -State Listen\n")

    print(f"\n開啟瀏覽器:http://{host}:{port}")
    print(f"   ACQUA 測試自動化   http://{host}:{port}/acqua")
    print(f"   聲學測試室 3D      http://{host}:{port}/soundproofroom\n")

    # use_reloader=False —— 重載器會 fork 出第二個行程,COM 執行緒會被開兩份
    app.run(host=host, port=port, threaded=True, use_reloader=False, debug=False)


if __name__ == "__main__":
    sys.exit(main())
