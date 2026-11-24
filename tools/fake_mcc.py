# -*- coding: utf-8 -*-
"""假的天車控制中心(MCC)—— 照 docs/MCC_MOTION_API.md 回應,不碰任何硬體。

用途
────
    MCC 還沒實作移動作業 API 之前,用它把 ACQUA Automation 這邊整條路跑通;
    tools/test_mcc_jobs.py 也用它(在同一個行程裡起一個)。

用法
────
    python tools/fake_mcc.py                     預設 port 5001,每個作業 3 秒走完
    python tools/fake_mcc.py --port 5099 --seconds 1 --token abc
    python tools/fake_mcc.py --fail "pi-003 SZM,3350: Exceeded Max travel"

    然後 .env 填 ACQUA_SETUP_CONTROLLER=http://127.0.0.1:5001

只用標準函式庫,跟服務本身沒有相依。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MOVE_KEYS = {"SXM", "SYM", "SZM", "RM", "TM"}
_DEVICE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")


class FakeMCC:
    """行為可調的假 MCC。測試直接改屬性:

        seconds      作業從送出到 done 要幾秒
        token        有值就要求 Authorization: Bearer <token>
        devices      None = 任何裝置 ID 都收;給 set 就只收這些
        refuse       (狀態碼, 訊息):下一個作業直接拒絕(用一次就清掉)
        fail_with    作業最後以 error 結束,error = 這個字串
        report_positions   done 時要不要回報 positions
        received     收到的每一個 POST body(檢查送了什麼用)
    """

    def __init__(self, port=0, seconds=3.0, token="", devices=None):
        self.seconds = float(seconds)
        self.token = token or ""
        self.devices = devices
        self.refuse = None
        self.fail_with = None
        self.report_positions = True
        self.received = []
        self.jobs = {}
        self._lock = threading.Lock()
        self._seq = 0
        self.server = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.port = self.server.server_address[1]

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.port

    # ── 作業 ────────────────────────────────────────
    def _state_of(self, job):
        """依經過時間算出狀態 —— 不用背景執行緒,查的時候才算。"""
        if job["state"] in ("done", "error", "aborted"):
            return job
        if time.time() - job["created"] >= job["seconds"]:
            if job["fail_with"]:
                job.update(state="error", error=job["fail_with"])
            else:
                job.update(state="done")
                if job["report_positions"]:
                    job["positions"] = job["targets"]
        else:
            job["state"] = "running"
        return job

    def _running(self):
        return any(self._state_of(j)["state"] in ("queued", "running")
                   for j in self.jobs.values())

    def _create(self, body):
        if self.refuse:
            code, msg = self.refuse
            self.refuse = None
            return code, {"status": "error", "error": msg}
        targets = body.get("targets")
        if not isinstance(targets, dict) or not targets:
            return 400, {"status": "error", "error": "targets must be a non-empty object"}
        for dev, cmds in targets.items():
            if not _DEVICE.match(str(dev)):
                return 400, {"status": "error", "error": "%s: bad device id" % dev}
            if self.devices is not None and dev not in self.devices:
                return 400, {"status": "error", "error": "%s: no such device" % dev}
            if not isinstance(cmds, dict) or not cmds:
                return 400, {"status": "error", "error": "%s: no commands" % dev}
            for k, v in cmds.items():
                if k not in MOVE_KEYS:
                    return 400, {"status": "error", "error": "%s: unknown command %s" % (dev, k)}
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    return 400, {"status": "error", "error": "%s %s: not a number" % (dev, k)}
        with self._lock:
            if self._running():
                return 409, {"status": "error", "error": "another motion job is running"}
            self._seq += 1
            jid = "j-%d" % self._seq
            self.jobs[jid] = {"job_id": jid, "label": str(body.get("label") or ""),
                              "state": "queued", "error": None, "targets": targets,
                              "created": time.time(), "seconds": self.seconds,
                              "fail_with": self.fail_with,
                              "report_positions": self.report_positions}
        return 202, {"status": "success", "job_id": jid}

    def _get(self, jid):
        with self._lock:
            job = self.jobs.get(jid)
            if job is None:
                return 404, {"status": "error", "error": "no such job"}
            job = self._state_of(job)
            view = {k: job[k] for k in ("job_id", "label", "state", "error")}
            if "positions" in job:
                view["positions"] = job["positions"]
        return 200, {"status": "success", "job": view}

    # ── HTTP ────────────────────────────────────────
    def _handler(self):
        mcc = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):     # 安靜一點
                if mcc is not None and getattr(mcc, "verbose", False):
                    sys.stderr.write("[fake-mcc] " + fmt % args + "\n")

            def _send(self, code, body):
                raw = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _authorized(self):
                if not mcc.token:
                    return True
                return self.headers.get("Authorization") == "Bearer " + mcc.token

            def do_GET(self):
                if self.path == "/api/health":
                    return self._send(200, {"status": "success", "fake": True,
                                            "token_required": bool(mcc.token)})
                if not self._authorized():
                    return self._send(401, {"status": "error", "error": "bad token"})
                m = re.match(r"^/api/motion/jobs/([^/]+)$", self.path)
                if m:
                    return self._send(*mcc._get(m.group(1)))
                self._send(404, {"status": "error", "error": "not found"})

            def do_POST(self):
                if not self._authorized():
                    return self._send(401, {"status": "error", "error": "bad token"})
                if self.path != "/api/motion/jobs":
                    return self._send(404, {"status": "error", "error": "not found"})
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return self._send(400, {"status": "error", "error": "body is not JSON"})
                if not isinstance(body, dict):
                    return self._send(400, {"status": "error", "error": "body must be an object"})
                mcc.received.append(body)
                if mcc.verbose:
                    sys.stderr.write("[fake-mcc] job %r -> %s\n"
                                     % (body.get("label"), json.dumps(body.get("targets"))))
                self._send(*mcc._create(body))

        return H

    verbose = False

    def start(self):
        threading.Thread(target=self.server.serve_forever, daemon=True,
                         name="fake-mcc").start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=5001)
    ap.add_argument("--seconds", type=float, default=3.0, help="每個作業幾秒走完")
    ap.add_argument("--token", default="", help="要求的 API token(留空 = 不檢查)")
    ap.add_argument("--fail", default="", help="每個作業都以這個 error 結束")
    args = ap.parse_args()
    sys.stderr.reconfigure(encoding="utf-8")

    mcc = FakeMCC(args.port, args.seconds, args.token)
    mcc.fail_with = args.fail or None
    mcc.verbose = True
    print("fake MCC on %s (each job takes %.1fs%s%s) - Ctrl+C to stop"
          % (mcc.url, mcc.seconds, ", token required" if args.token else "",
             ", every job fails" if args.fail else ""))
    try:
        mcc.server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
