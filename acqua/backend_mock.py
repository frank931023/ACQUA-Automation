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
            # 這三個模擬 ACQUA 的互動精靈 —— 用來驗證「自動排除需人工項目」
            "DUT & Measurement Wizard",
            "BGN Wizard",
            "Hardware options",
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
        # 跟真機一致:標出需要人工操作的項目
        is_manual = self._manual_matcher()
        for s in smds:
            s["manual"] = is_manual(s.get("title"))
        self.state.set(smds=smds)
        return smds

    def check_rows(self, row_ids):
        """模擬模式沒有真的資料庫,一律放行。"""
        return True

    def run_smds(self, row_ids):
        """逐項執行(模擬)。中止/暫停的語意跟真機一致。"""
        return self._run_titles(row_ids)

    def _run_titles(self, row_ids):
        by_id = {s["row_id"]: s for s in self.state.smds}
        targets = [by_id[r] for r in row_ids if r in by_id]
        total = len(targets)
        # ⚠️ 不模擬重試與「失敗即停」——
        #    真機那條路已經沒有了(ByRef 回傳送不到 ACQUA,REDO_THIS 無效)。
        #    mock 的行為必須跟真機一致,否則測起來會給錯誤的信心。
        self._attempts = {}
        self.state.clear_results()
        self.state.set(running=True, cancel_requested=False)
        self.state.log(f"=== 開始:共 {total} 筆測項(模擬)===")

        rl = self.state.runlog
        if rl:
            rl.start(mode="batch", database=self.state.database,
                     project_group=self.state.open_group,
                     project=self.state.open_project,
                     measurement_object=self.state.measurement_object,
                     planned=[{"row_id": s["row_id"], "title": s["title"]}
                              for s in targets])

        i = 0
        while i < total:
            if self.state.cancel_requested:
                self.state.log(f"■ 已中止 —— 跑了 {i} / {total} 筆", "warn")
                break
            while self.state.paused and not self.state.cancel_requested:
                time.sleep(0.1)
            if self.state.cancel_requested:
                self.state.log(f"■ 已中止 —— 跑了 {i} / {total} 筆", "warn")
                break

            smd = targets[i]
            attempt = 0
            self.state.set(current={"title": smd["title"], "index": i + 1, "total": total})
            self.state.log(f"[{i + 1}/{total}] 量測中:{smd['title']}")

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

            self.state.add_result(smd["title"], smd["row_id"], status, passed, attempt)
            if rl:
                rl.record(smd["row_id"], smd["title"], status, passed, attempt)
            self.state.log(f"    → {'PASS' if passed else 'FAIL'}",
                           "info" if passed else "error")

            i += 1

        self.state.set(running=False, current=None, progress=None)
        if rl:
            rl.finish(canceled=self.state.cancel_requested)
        snap = self.state.snapshot()["summary"]
        self.state.log(f"=== 結束:{snap['passed']} PASS / {snap['failed']} FAIL ===")

    def create_report(self, output_path, selection_type, result_index=0,
                      settle_timeout=600):
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
        # 跟真機一致:自動勾選時排除需要人工操作的項目
        is_manual = self._manual_matcher()
        run_ids, manual_hits = [], []
        for x in r["will_run"]:
            (manual_hits if is_manual(x["title"]) else run_ids).append(
                {"row_id": x["row_id"], "title": x["title"]} if is_manual(x["title"])
                else x["row_id"])
        self.state.set(prediction={
            "will_run": len(run_ids), "skipped": len(r["skipped"]),
            "uncertain": 0, "total": r["total_smds"],
            "run_ids": run_ids,
            "manual_excluded": manual_hits,
            "uncertain_items": [],
            "sample_skipped": r["skipped"][:40],
        })
        self.state.log(f"【模擬模式】預測 {len(kept)}/{r['total_smds']} 個測項會執行")
        return r

    def run_measurements(self, variables=None):
        """模擬「設變數 → 一次跑完」。ACQUA 會自己略過不符條件的項目。"""
        if variables:
            self.set_variables(variables)
        kept, skipped = self._conditional_filter()
        self.state.log(f"=== 開始:整個專案(變數條件篩選後 {len(kept)}/"
                       f"{len(self.state.smds)} 項)===")
        for s, reason in skipped:
            self.state.log(f"  略過 {s['title']} —— {reason}", "warn")
        if not kept:
            self.state.log("條件篩選後沒有任何測項可跑", "warn")
            return
        self._run_titles([s["row_id"] for s in kept])

    # ── 硬體設定(模擬)────────────────────────────
    _MOCK_HW = ["BK+GRAS Mouth_3QUEST_v5_HRPF off_251029",
                "BK+GRAS Mouth_2talker_v5_HRPF off_251028",
                "Teams_chamber_v5", "ZRs_SND_RCV_headphone_250804"]

    def list_hardware_settings(self):
        act = getattr(self, "_hw_active", self._MOCK_HW[0])
        out = [{"name": n, "active": n == act} for n in self._MOCK_HW]
        self.state.set(hardware_settings=out, hardware_active=act)
        return out

    def set_hardware_setting(self, name):
        self._hw_active = str(name)
        self.state.log(f"【模擬模式】硬體設定切換為:{name}")
        return self.list_hardware_settings()

    def active_hardware_setting(self):
        return getattr(self, "_hw_active", self._MOCK_HW[0])

    # ── 設計 A:需要人工操作的測項 ────────────────
    def _manual_matcher(self):
        import fnmatch
        m = self.config.get("manual_items") or {}
        titles = {str(x).strip() for x in (m.get("titles") or [])}
        pats = [str(x) for x in (m.get("title_patterns") or [])]
        def is_manual(title):
            t = (title or "").strip()
            return t in titles or any(fnmatch.fnmatch(t, p) for p in pats)
        return is_manual

    def wizard_options(self):
        """模擬版:直接給一組跟真機同名的選項,方便測 UI。"""
        groups = [
            {"title": "量測範圍", "items": [
                {"name": "DUT_speakerphone_type", "kind": "choice",
                 "values": ["Personal", "Shared"], "used_by": 105}]},
            {"title": "連接方式", "items": [
                {"name": "DUT_connection_type", "kind": "choice",
                 "values": ["Android", "Bluetooth", "USB", "USB dongle"], "used_by": 26}]},
            {"title": "DUT 特性", "items": [
                {"name": "DUT_premium_reqs", "kind": "bool", "values": [], "used_by": 94},
                {"name": "DUT_is_deskphone", "kind": "bool", "values": [], "used_by": 4}]},
        ]
        self.state.set(wizard_groups=groups,
                       wizard_scopes=self.config.get("wizard_scopes") or {})
        self.state.log("【模擬模式】精靈選項 %d 組" % len(groups))
        return groups
