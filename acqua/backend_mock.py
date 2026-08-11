"""模擬後端 —— 不需要 ACQUA、不需要資料庫、不需要量測硬體。

用途:在環境備妥之前,先把 Web UI、選測項邏輯、重試策略、結果匯總全部寫完並測過。
等真的 COM 後端可用時,只要把 config 的 backend 改成 "com" 就切換過去。

模擬的行為刻意貼近真實:
  - 啟動有延遲
  - 量測是逐筆進行、有進度回報
  - 有一定比例的失敗,可觸發重試路徑
  - 取消要等當前這筆跑完才生效(跟 ACQUA 的 EUserReaction 行為一致)
"""
import random
import time

from .backend_base import AcquaBackend
from .constants import EMEEventType, EVariableState, EVariableType

# 模擬用的假資料 —— 模仿電聲/通訊測試常見的測項命名
_FAKE_TREE = {
    "Standards": {
        # 名稱刻意包含 Shared / Personal / Premium / Bluetooth,
        # 讓 conditional 模式的變數篩選看得出效果
        "Speakerphone Certification": [
            "Sending Loudness Rating",
            "Receiving Loudness Rating",
            "POLQA MOS Sending",
            "POLQA MOS Receiving",
            "Sending Frequency Response",
            "Receiving Frequency Response",
            "Personal Space - Pickup at 0.5m",
            "Personal Space - Desktop Reflection",
            "Shared Space - Pickup at 2.3m",
            "Shared Space - Pickup at 3.5m",
            "Shared Space - Speaker Coverage 4.5m",
            "Premium - Full Band Speech Quality",
            "Premium - Stereo Calling Separation",
            "Bluetooth HFP Codec Negotiation",
            "Bluetooth Link Quality vs Distance",
        ],
        "Echo & Noise": [
            "Terminal Coupling Loss TCLw",
            "Echo Loss vs Time",
            "Idle Channel Noise Sending",
            "Idle Channel Noise Receiving",
            "Shared Space - Double Talk Performance",
        ],
    },
    "Headset Tests": {
        "ANC Performance": [
            "Passive Attenuation",
            "Active Attenuation 100-1000Hz",
            "Total Attenuation",
            "Premium - ANC Depth Full Band",
        ],
    },
}

_MOCK_FAIL_RATE = 0.18
_MOCK_SECONDS_PER_SMD = (0.8, 2.2)


class MockBackend(AcquaBackend):
    def __init__(self, state, config):
        super().__init__(state, config)
        self._mos = {}          # project -> [mo titles]
        self._smd_cache = {}
        self._rng = random.Random(20260805)
        self._attempts = {}
        self._vars = {}         # ACQUA 變數(混合模式用)

    # ── 生命週期 ────────────────────────────────────
    def initialize(self):
        self.state.set(backend_kind="mock")
        self.state.log("【模擬模式】啟動中 —— 沒有連接真實的 ACQUA", "warn")
        time.sleep(0.6)
        self.state.set(acqua_ready=True)
        self.state.log("【模擬模式】ACQUA 已就緒")

    def pump(self):
        pass    # 模擬模式沒有 COM 訊息要處理

    def shutdown(self):
        self.state.log("【模擬模式】已關閉")

    # ── 操作 ────────────────────────────────────────
    def connect(self, server, database, win_auth, username="", password=""):
        time.sleep(0.4)
        if not database:
            self.state.log("資料庫名稱是空的", "error")
            return False
        self.state.set(connected=True, server=server, database=database)
        self.state.log(f"【模擬模式】已連線 {server} / {database}")
        return True

    def list_databases(self, server=""):
        dbs = [
            {"name": "61_Demo_SMDs_Rev07", "is_acqua": True, "online": True,
             "smds": 132, "mmds": 61, "results": 0},
            {"name": "AUTOMATION_TEST_0806", "is_acqua": True, "online": True,
             "smds": 0, "mmds": 10, "results": 0},
        ]
        self.state.set(databases=dbs)
        self.state.log(f"【模擬模式】列出 {len(dbs)} 個資料庫")
        return dbs

    def refresh_project_groups(self):
        groups = [{"name": g, "projects": list(p.keys())} for g, p in _FAKE_TREE.items()]
        self.state.set(project_groups=groups)
        return groups

    def open_project(self, group, project):
        time.sleep(0.5)
        self.state.set(open_group=group, open_project=project, measurement_object=None, smds=[])
        self.state.log(f"已開啟專案:{group} / {project}")

    def select_measurement_object(self, title, create_if_missing=True):
        key = (self.state.open_group, self.state.open_project)
        existing = self._mos.setdefault(key, ["DUT_001"])
        if title not in existing:
            if not create_if_missing:
                raise RuntimeError(f"找不到量測物件:{title}")
            existing.append(title)
            self.state.log(f"已新增量測物件:{title}")
        self.state.set(measurement_object=title)
        self.state.log(f"已選定量測物件:{title}")

    def write_metadata(self, props):
        for k, v in props.items():
            if v:
                self.state.log(f"  UpdateProperty({k!r}, {v!r})")

    def list_smds(self, search=""):
        group, project = self.state.open_group, self.state.open_project
        if not project:
            raise RuntimeError("尚未開啟專案")
        titles = _FAKE_TREE[group][project]
        base = self._smd_cache.setdefault(
            (group, project),
            [{"row_id": 1000 + i, "title": t,
              # 假的階層 —— 讓 UI 的「顯示階層架構」開關在模擬模式也看得到效果
              "group": (t.split(" - ")[0] if " - " in t else "General"),
              "path": f"{project} / " + (t.split(" - ")[0] if " - " in t else "General"),
              "smd_type": -1, "needs_ref": False, "ref_file": "", "conditional": False}
             for i, t in enumerate(titles)],
        )
        smds = [s for s in base if search.lower() in s["title"].lower()] if search else list(base)
        self.state.set(smds=smds)
        return smds

    def run_smds(self, row_ids):
        by_id = {s["row_id"]: s for s in self.state.smds}
        targets = [by_id[r] for r in row_ids if r in by_id]
        total = len(targets)
        max_retries = int(self.config.get("run", {}).get("max_retries", 0))
        stop_on_fail = bool(self.config.get("run", {}).get("stop_on_first_failure", False))

        self._attempts = {}
        self.state.clear_results()
        self.state.set(running=True, cancel_requested=False)
        self.state.log(f"=== 開始:共 {total} 筆測項(模擬)===")

        i = 0
        while i < total:
            if self.state.cancel_requested:
                self.state.log("使用者要求中止", "warn")
                break

            smd = targets[i]
            attempt = self._attempts.get(smd["row_id"], 0)
            self.state.set(current={"title": smd["title"], "index": i + 1, "total": total})
            self.state.log(f"[{i + 1}/{total}] 量測中:{smd['title']}"
                           + (f"(重試 {attempt})" if attempt else ""))

            # 模擬量測期間的進度回報
            duration = self._rng.uniform(*_MOCK_SECONDS_PER_SMD)
            steps = 8
            for s in range(steps):
                if self.state.cancel_requested:
                    break
                time.sleep(duration / steps)
                self.state.set(progress={"text": smd["title"], "value": s + 1, "total": steps})

            passed = self._rng.random() > _MOCK_FAIL_RATE
            status = "MEAS_DONE_OK" if passed else "MEAS_DONE_NOT_OK"

            if not passed and attempt < max_retries:
                self._attempts[smd["row_id"]] = attempt + 1
                self.state.log(f"    → FAIL,重試({attempt + 1}/{max_retries})", "warn")
                continue        # 不遞增 i,重跑同一筆

            self.state.add_result(smd["title"], smd["row_id"], status, passed, attempt)
            self.state.log(f"    → {'PASS' if passed else 'FAIL'}",
                           "info" if passed else "error")

            if not passed and stop_on_fail:
                self.state.log("設定為失敗即停 —— 中止剩餘測項", "error")
                break
            i += 1

        self.state.set(running=False, current=None, progress=None)
        snap = self.state.snapshot()["summary"]
        self.state.log(f"=== 結束:{snap['passed']} PASS / {snap['failed']} FAIL ===")

    def create_report(self, output_path, selection_type):
        time.sleep(0.5)
        self.state.log(f"【模擬模式】已「產生」報告:{output_path}(selection_type={selection_type})")

    # ── ⭐ 混合模式:變數驅動 ────────────────────────
    def list_variables(self):
        out = [{"name": k, "value": v, "type": EVariableType.infer(v),
                "state": EVariableState.USER_DEFINED,
                "state_text": EVariableState.describe(EVariableState.USER_DEFINED),
                "comment": "set by automation"}
               for k, v in sorted(self._vars.items())]
        self.state.set(variables=out)
        return out

    def set_variables(self, values):
        n = 0
        for k, v in (values or {}).items():
            if k.startswith("_"):
                continue
            self._vars[k] = v
            self.state.log(f"  變數 {k} = {v!r}")
            n += 1
        self.state.log(f"【模擬模式】已寫入 {n} 個變數")
        self.list_variables()
        return n

    def read_results(self, latest_only=True, smd_row_ids=None):
        """模擬數值結果 —— 依已跑過的測項編出合理的數字與極限值。"""
        out = []
        for r in self.state.results:
            if smd_row_ids and r["row_id"] not in smd_row_ids:
                continue
            lo, hi = 3.0, 5.0
            val = round(self._rng.uniform(lo, hi) if r["passed"]
                        else self._rng.uniform(1.0, lo - 0.1), 2)
            out.append({
                "result_id": r["row_id"],
                "smd": r["title"], "smd_row_id": r["row_id"],
                "dut": self.state.measurement_object or "",
                "status": 2 if r["passed"] else 3,
                "created": "",
                "values": [{
                    "title": "MOS", "value": val, "unit": "", "precision": 2,
                    "channel": "1", "lower_limit": lo, "upper_limit": hi,
                    "status": 2 if r["passed"] else 3, "type": 16,
                }],
            })
        self.state.set(values=out)
        self.state.log(f"【模擬模式】讀到 {len(out)} 筆結果")
        return out

    def _conditional_filter(self):
        """模擬 ConditionalExecution:依變數決定哪些測項會被跑。

        真實的 ACQUA 是每個 SMD/MMD 自己帶條件式,這裡用簡化規則示意:
          DUT_speakerphone_type = Personal → 略過標題含 "Shared" 的
          DUT_premium_reqs      = False    → 略過標題含 "Premium" 的
          DUT_connection_type   = USB      → 略過標題含 "Bluetooth" 的
        """
        smds = list(self.state.smds)
        sp_type = self._vars.get("DUT_speakerphone_type")
        conn = self._vars.get("DUT_connection_type")
        premium = self._vars.get("DUT_premium_reqs", True)

        kept, skipped = [], []
        for s in smds:
            t = s["title"].lower()
            reason = None
            if sp_type == "Personal" and "shared" in t:
                reason = "DUT_speakerphone_type=Personal"
            elif sp_type == "Shared" and "personal" in t:
                reason = "DUT_speakerphone_type=Shared"
            elif not premium and "premium" in t:
                reason = "DUT_premium_reqs=False"
            elif conn == "USB" and "bluetooth" in t:
                reason = "DUT_connection_type=USB"
            (skipped if reason else kept).append((s, reason))
        return [s for s, _ in kept], [(s, r) for s, r in skipped]

    def predict_run_set(self, variables=None):
        if variables:
            self._vars.update(variables)
        kept, skipped = self._conditional_filter()
        r = {
            "will_run": [{"row_id": s["row_id"], "title": s["title"], "why": "", "sure": True}
                         for s in kept],
            "skipped": [{"row_id": s["row_id"], "title": s["title"], "why": why, "sure": True}
                        for s, why in skipped],
            "uncertain": [],
            "total_smds": len(kept) + len(skipped),
        }
        self.state.set(prediction={
            "will_run": len(r["will_run"]), "skipped": len(r["skipped"]),
            "uncertain": 0, "total": r["total_smds"],
            "run_ids": [x["row_id"] for x in r["will_run"]],
            "sample_skipped": r["skipped"][:40],
        })
        self.state.log(f"【模擬模式】預測 {len(kept)}/{r['total_smds']} 個測項會執行")
        return r

    def run_all(self):
        """模擬「設變數 → 一次跑完」。ACQUA 會自己略過不符條件的項目。"""
        kept, skipped = self._conditional_filter()
        self.state.log(f"=== 開始:整個專案(變數條件篩選後 {len(kept)}/"
                       f"{len(self.state.smds)} 項)===")
        for s, reason in skipped:
            self.state.log(f"  略過 {s['title']} —— {reason}", "warn")
        if not kept:
            self.state.log("條件篩選後沒有任何測項可跑", "warn")
            return
        self.run_smds([s["row_id"] for s in kept])
