"""ACQUA 測試自動化 —— Flask Web 介面。

啟動:
    python app.py                # 用 config.json(沒有的話用 config.example.json)
    python app.py --backend mock # 強制模擬模式

⚠️ Flask 執行緒與 COM 執行緒是分開的。這個檔案裡的任何程式碼
   都不可以直接碰 COM 物件 —— 一律透過 worker.submit() 下命令。
"""
import argparse
import csv
import io
import json
import os
import sys
import time

from flask import Flask, Response, jsonify, render_template, request

from acqua.state import SharedState
from acqua.worker import make_worker

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
state = SharedState()
worker = None
config = {}


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


# ── 頁面 ────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", config=config)


# ── 狀態與事件串流 ───────────────────────────────────
@app.route("/api/status")
def api_status():
    return jsonify(state.snapshot())


@app.route("/api/stream")
def api_stream():
    """Server-Sent Events —— 把工作執行緒的日誌與狀態即時推到瀏覽器。"""
    def generate():
        last = int(request.args.get("since", 0))
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

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── 操作 ────────────────────────────────────────────
@app.route("/api/connect", methods=["POST"])
def api_connect():
    body = request.get_json(silent=True) or {}
    db = config.get("database", {})
    return _cmd("connect", timeout=300,
                server=body.get("server") or db.get("server", ""),
                database=body.get("database") or db.get("name", ""),
                win_auth=bool(body.get("win_auth", db.get("use_windows_auth", True))),
                username=body.get("username") or db.get("username", ""),
                password=body.get("password") or db.get("password", ""))


@app.route("/api/databases", methods=["POST"])
def api_databases():
    """列出 SQL Server 上的資料庫,讓 UI 做成下拉選單。"""
    body = request.get_json(silent=True) or {}
    return _cmd("list_databases", timeout=120,
                server=body.get("server") or config.get("database", {}).get("server", ""))


@app.route("/api/refresh-groups", methods=["POST"])
def api_refresh_groups():
    return _cmd("refresh_groups", timeout=120)


@app.route("/api/open-project", methods=["POST"])
def api_open_project():
    body = request.get_json(silent=True) or {}
    return _cmd("open_project", timeout=300,
                group=body.get("group", ""), project=body.get("project", ""))


@app.route("/api/select-mo", methods=["POST"])
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


@app.route("/api/list-smds", methods=["POST"])
def api_list_smds():
    body = request.get_json(silent=True) or {}
    return _cmd("list_smds", timeout=180, search=body.get("search", ""))


@app.route("/api/variables", methods=["GET"])
def api_variables_get():
    return _cmd("list_variables", timeout=120)


@app.route("/api/variables", methods=["POST"])
def api_variables_set():
    """⭐ 混合模式的第一步:把 DUT 屬性寫成 ACQUA 變數。

    之後 StartMeasurements 時,專案樹的 ConditionalExecution 會讀這些變數,
    自動決定哪些 SMD 要跑、哪些略過。
    """
    body = request.get_json(silent=True) or {}
    values = body.get("values") or {}
    if not values:
        return jsonify(ok=False, error="沒有提供任何變數"), 400
    return _cmd("set_variables", timeout=180, values=values)


@app.route("/api/predict", methods=["POST"])
def api_predict():
    """⭐ 事前預覽:這組變數會跑哪些測項?完全不啟動量測。"""
    body = request.get_json(silent=True) or {}
    return _cmd("predict_run_set", timeout=180,
                variables=body.get("variables") or {})


@app.route("/api/run", methods=["POST"])
def api_run():
    """⭐ 整套自動化的核心入口。兩種執行模式:

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

    row_ids = [int(r) for r in (body.get("row_ids") or [])]
    if not row_ids:
        return jsonify(ok=False, error="沒有選擇任何測項"), 400
    state.set(run_mode="selected")
    # 不等它跑完 —— 讓 HTTP 立刻回應,進度透過 SSE 推播
    worker.submit("run_smds", row_ids=row_ids)
    return jsonify(ok=True, mode="selected", queued=len(row_ids))


@app.route("/api/cancel", methods=["POST"])
def api_cancel():
    worker.request_cancel()
    return jsonify(ok=True)


@app.route("/api/report", methods=["POST"])
def api_report():
    body = request.get_json(silent=True) or {}
    rep = config.get("report", {})
    out_dir = os.path.join(BASE_DIR, rep.get("output_dir", "reports"))
    os.makedirs(out_dir, exist_ok=True)
    name = body.get("filename") or f"report_{time.strftime('%Y%m%d_%H%M%S')}.doc"
    return _cmd("create_report", timeout=600,
                output_path=os.path.join(out_dir, name),
                selection_type=int(body.get("selection_type", rep.get("selection_type", 3))))


@app.route("/api/values", methods=["POST"])
def api_values():
    """讀出量測的實際數值(含極限值)。走 SQL —— Acqua3 介面拿不到數字。"""
    body = request.get_json(silent=True) or {}
    return _cmd("read_results", timeout=300,
                latest_only=bool(body.get("latest_only", True)),
                smd_row_ids=body.get("row_ids"))


@app.route("/api/results.csv")
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

    worker = make_worker(config, state)
    worker.start()
    if not worker.ready.wait(timeout=320):
        print("⚠️ 工作執行緒初始化逾時,Web 介面仍會啟動以便查看日誌")
    elif worker.init_error:
        print(f"⚠️ 後端初始化失敗:{worker.init_error}")

    web = config.get("web", {})
    port = args.port or int(web.get("port", 5000))
    host = web.get("host", "127.0.0.1")
    print(f"\n開啟瀏覽器:http://{host}:{port}\n")

    # use_reloader=False —— 重載器會 fork 出第二個行程,COM 執行緒會被開兩份
    app.run(host=host, port=port, threaded=True, use_reloader=False, debug=False)


if __name__ == "__main__":
    sys.exit(main())
