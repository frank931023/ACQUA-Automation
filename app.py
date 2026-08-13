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


def _cmd(name, timeout=600, **kwargs):
    """下命令並等待結果,統一轉成 JSON 回應。"""
    if worker is None or not worker.ready.is_set():
        return jsonify(ok=False, error="工作執行緒尚未就緒"), 503
    if worker.init_error:
        return jsonify(ok=False, error=f"後端初始化失敗:{worker.init_error}"), 500
    try:
        result = worker.submit(name, **kwargs).wait(timeout=timeout)
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
    """[*] 整套自動化的核心入口。兩種執行模式:

    selected    —— 逐項跑勾選的 SMD(StartSingleMeasurement)
    conditional —— 先設變數,再一次跑完整個專案(StartMeasurements),
                   由 ACQUA 依 ConditionalExecution 自動篩選
    """
    body = request.get_json(silent=True) or {}
    mode = str(body.get("mode") or config.get("run", {}).get("mode", "selected"))

    if state.running:
        return jsonify(ok=False, error="已經有一批測試在執行中"), 409

    if mode == "conditional":
        # 先寫變數(如果有給),再整批跑
        values = body.get("variables") or {}
        if values:
            try:
                worker.submit("set_variables", values=values).wait(timeout=180)
            except Exception as exc:                        # noqa: BLE001
                return jsonify(ok=False, error=f"設定變數失敗:{exc}"), 400
        state.set(run_mode="conditional")
        worker.submit("run_all")
        return jsonify(ok=True, mode="conditional", variables=len(values))

    # 續跑:直接沿用上次紀錄裡「還沒跑的」
    if body.get("resume"):
        pending = state.runlog.unfinished() if state.runlog else None
        if not pending:
            return jsonify(ok=False, error="沒有可續跑的紀錄"), 400
        row_ids = [p["row_id"] for p in pending["remaining"]]
        state.set(run_mode="selected")
        worker.submit("run_smds", row_ids=row_ids)
        return jsonify(ok=True, mode="resume", queued=len(row_ids))

    row_ids = [int(r) for r in (body.get("row_ids") or [])]
    if not row_ids:
        return jsonify(ok=False, error="沒有選擇任何測項"), 400
    state.set(run_mode="selected")
    # 不等它跑完 —— 讓 HTTP 立刻回應,進度透過 SSE 推播
    worker.submit("run_smds", row_ids=row_ids)
    return jsonify(ok=True, mode="selected", queued=len(row_ids))


@acqua_bp.route("/api/cancel", methods=["POST"])
def api_cancel():
    worker.request_cancel()
    return jsonify(ok=True)


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
