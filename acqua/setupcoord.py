# -*- coding: utf-8 -*-
"""擺位協調 —— 每一筆測項送出前,需要的話把機構移到它的擺位。

    setuptags.py   標籤怎麼讀、怎麼繼承(純資料,不碰機構)
    setupcoord.py  這裡:拿那份結果去動機構、記下沒套用到的
    roomsetups.py  擺位存檔
    crane.py       機構橋接

跟任何資料庫、專案、測項都無關 —— 專案由 ctx 決定,擺位由名稱決定,
所以同一份程式碼套用到每一個 ACQUA 資料庫。

一批的生命週期
──────────────
    prepare(ctx, row_ids, smds)   讀標籤、清掉上一輪的警告、需要時重排
    before_item(smd)              每一筆送出前呼叫,**絕不丟例外**
    note_not_applied(...)         沒套用到 -> 記一筆(也給 ACQUA 掛鉤用)

為什麼沒套用到要記下來(計畫書防線 ⑤)
──────────────────────────────────────
擺位有問題時選擇「繼續量」而不是停下來 —— 一個字打錯不該讓整晚的批次
跑不起來。代價是那幾筆可能在錯的位置量到。無人值守時沒有人看得到執行
中的訊息,所以警告必須活到跑完的摘要、CSV 與報告旁的警告清單。
唯一的那份放在 state.setup_not_applied,這裡不另存。
"""
from __future__ import annotations

import time

from . import setuptags
from .context import parse_ctx
from .crane import AXES

#: 判斷「已經在這個擺位上」的容差。線性軸 1 公分、旋轉軸 1 度 ——
#: 機構回報的位置本來就有誤差,要求完全相等的話每一筆都會重跑一次移動。
POSITION_TOLERANCE = {"m": 0.01, "deg": 1.0}


def match_position(now, setups) -> tuple:
    """機構目前的位置對上哪個擺位。

    now     {axis_id: 位置}
    setups  RoomSetups.list() 的結果

    回 (命中的擺位或 None, 每個擺位的比對 [{id, name, worst_diff, match}])。
    比對清單照差距排序,方便告訴人「最接近的是哪個」。
    擺位裡有、這台機構沒有的軸不列入比對。
    """
    matched, scored = None, []
    for s in setups:
        worst, ok = 0.0, True
        for axis_id, target in (s.get("axes") or {}).items():
            ax = AXES.get(axis_id)
            if ax is None or axis_id not in now:
                continue
            diff = abs(float(now[axis_id]) - float(target))
            worst = max(worst, diff)
            ok = ok and diff <= POSITION_TOLERANCE.get(ax.unit, 0.01)
        scored.append({"id": s.get("id"), "name": s.get("name"),
                       "worst_diff": round(worst, 4), "match": ok})
        if ok and matched is None:
            matched = s
    scored.sort(key=lambda x: x["worst_diff"])
    return matched, scored


def group_keys(smds, row_ids) -> dict:
    """每個測項屬於哪個群組,{row_id: 群組鍵}。重排時用來**不拆散群組**。

    群組裡常常是「錄音 -> 分析」,拆開分析就找不到錄音。用已載入的
    測項清單算:同一個群組的測項 `path` 相同。查不到的自成一組。
    """
    by_id = {int(s["row_id"]): s for s in (smds or [])}
    return {int(r): (by_id.get(int(r)) or {}).get("path") or ("__loose__%d" % int(r))
            for r in row_ids}


class SetupCoordinator:
    """把 Setup 標籤變成機構動作。

    state     SharedState —— 寫 log 與 setup_not_applied
    setups    RoomSetups
    query     raw_query(server, database, sql) —— 讀測項樹用
    bridge    CraneBridge;None 表示沒有機構(啟動後才接上)
    """

    def __init__(self, state, setups, query, *, bridge=None,
                 move_timeout=900.0, poll_seconds=1.0):
        self.state = state
        self.setups = setups
        self.query = query
        self.bridge = bridge
        self.move_timeout = float(move_timeout)
        self.poll_seconds = float(poll_seconds)
        self._by_row = {}           # 這一批 {row_id: 擺位名稱}
        self._ambiguous = {}        # 這一批判斷不出來的 {row_id: resolve 結果}

    # ── 讀 ─────────────────────────────────────────
    def resolve(self, ctx) -> dict:
        """ctx 指的那個專案,每一筆測項的擺位(含資料夾繼承)。

        吃 ctx 而不是「目前開著的專案」—— 序列裡的計畫可能屬於別的
        資料庫,開跑前就要能檢查。純 SQL,不碰 COM。

        **不丟例外。** 讀不到就回 {}:照原順序跑、不移動機構。
        擺位是加分項,不能讓量測因為它跑不起來。
        """
        server, database, pid = parse_ctx(ctx)
        if not (server and database and pid is not None):
            return {}
        try:
            return setuptags.resolve(
                setuptags.load_tree(server, database, pid, self.query))
        except Exception as exc:                            # noqa: BLE001
            self.state.log("讀擺位標籤失敗(照原順序執行,不移動機構):%s"
                           % str(exc)[:80], "warn")
            return {}

    def check(self, ctx, row_ids) -> dict:
        """開跑前的標籤檢查,見 setuptags.check()。"""
        return setuptags.check(row_ids, self.resolve(ctx), self.setups.names())

    def current(self):
        """機構現在停在哪個擺位的名稱。判不出來回 None。"""
        if self.bridge is None:
            return None
        axes = self.bridge.snapshot().get("axes") or {}
        hit, _ = match_position({k: v["value"] for k, v in axes.items()},
                                self.setups.list())
        return (hit or {}).get("name")

    # ── 一批的生命週期 ──────────────────────────────
    def prepare(self, ctx, row_ids, smds, regroup=True) -> list:
        """開跑前呼叫一次。回實際要跑的順序(可能為了少移動而重排)。

        重排以群組為單位、只在真的比較少切換時才採用,見
        setuptags.reorder_if_better()。
        """
        resolved = self.resolve(ctx)
        self._by_row = setuptags.by_row(resolved)
        self._ambiguous = {rid: v for rid, v in resolved.items()
                           if v["source"] == setuptags.AMBIGUOUS}
        self.state.set(setup_not_applied=[])    # 上一輪的警告不能跟到這一輪

        names = self.setups.names()
        report = setuptags.check(row_ids, resolved, names)
        if report["total"] == report["untagged"]:
            return list(row_ids)                # 這批跟擺位無關

        if regroup:
            row_ids, plan, was = setuptags.reorder_if_better(
                row_ids, self._by_row, group_keys(smds, row_ids), names)
            if plan["switches"] < was:
                self.state.log("擺位:重排順序,切換次數 %d -> %d"
                               % (was, plan["switches"]))
        else:
            plan = setuptags.plan_for(row_ids, self._by_row, names)
        self._log_report(report, plan)
        return list(row_ids)

    def before_item(self, smd):
        """每一筆送出前呼叫。**絕不丟例外** —— 有問題記一筆,照常量。"""
        try:
            self._before_item(int(smd.get("row_id", 0)), smd.get("title", ""))
        except Exception as exc:                            # noqa: BLE001
            self.note_not_applied(smd.get("row_id", -1), smd.get("title", ""),
                                  "?", "擺位處理出錯:%s" % str(exc)[:80])

    def note_not_applied(self, row_id, title, wanted, reason):
        """記下「這一筆沒套用到指定擺位」(防線 ⑤)。"""
        rows = list(self.state.snapshot().get("setup_not_applied") or [])
        rows.append({"row_id": row_id, "title": title,
                     "wanted": wanted, "reason": reason})
        self.state.set(setup_not_applied=rows)
        self.state.log(f"    ⚠️ 擺位未套用:「{wanted}」—— {reason}(照常執行)",
                       "warn")
        return len(rows)

    # ── 內部 ───────────────────────────────────────
    def _before_item(self, rid, title):
        amb = self._ambiguous.get(rid)
        if amb:
            # 不猜,但要留紀錄 —— 不記的話它看起來就跟「沒標」一樣
            self.note_not_applied(
                rid, title, "、".join(amb.get("choices") or []),
                "資料夾「%s」裡標了不只一種擺位,請在這一筆自己標"
                % amb.get("folder"))
            return

        wanted = self._by_row.get(rid)
        if not wanted:
            return                              # 一路都沒標 -> 沿用當下
        problem = self._move_to(wanted)
        if problem:
            self.note_not_applied(rid, title, wanted, problem)

    def _move_to(self, name):
        """把機構移到名為 name 的擺位。成功回 None,否則回原因。"""
        if self.bridge is None:
            return "沒有機構橋接"
        target = self.setups.find(name)
        if target is None:
            return "找不到這個擺位"
        if self.current() == name:
            return None                         # 已經在位置上,不白跑

        self.state.log(f"    移動到擺位「{name}」…")
        moves = [(k, v) for k, v in (target.get("axes") or {}).items()
                 if k in AXES]
        try:
            self.bridge.submit(moves, label=name)
        except Exception as exc:                            # noqa: BLE001
            return str(exc)[:80]

        # 機構沒有中止指令,只能等 —— 但不能無限等。
        # ⚠️ 「還在動」一定要問 bridge.busy()。作業跑完不會被清掉,
        #    只是 state 變成 "done";看 job 有沒有值的話永遠等不到結束。
        #    2026-11-16 真機踩到:51 秒就到位,卻白等 900 秒再報逾時。
        deadline = time.time() + self.move_timeout
        while self.bridge.busy():
            if time.time() > deadline:
                return "移動逾時"
            time.sleep(self.poll_seconds)

        # 走完了不代表走好了 —— 出錯跟被中止分開記,才查得到真正原因
        job = self.bridge.snapshot().get("job") or {}
        if job.get("state") == "error":
            return "移動失敗:%s" % str(job.get("error") or "")[:60]
        if job.get("state") == "aborted":
            return "移動被中止"
        if self.current() != name:
            return "移動完成但位置對不上"
        self.state.log(f"    已就位:「{name}」")
        return None

    def _log_report(self, report, plan):
        log = self.state.log
        log("擺位:%d 筆自己標 ・ %d 筆從資料夾繼承 ・ %d 筆沒有 ・ "
            "會切換 %d 次 ・ 用到 %s"
            % (report["own"], report["inherited"], report["untagged"],
               plan["switches"], "、".join(plan["used"]) or "(無)"))
        for u in report["unknown"]:
            hint = ("—— 是不是「%s」?" % u["suggestion"]) if u["suggestion"] else ""
            log("⚠️ 擺位「%s」找不到對應(%d 筆照常執行,不移動機構)%s"
                % (u["name"], len(u["rows"]), hint), "warn")
        if report["ambiguous"]:
            log("⚠️ %d 筆判斷不出擺位:所在資料夾裡標了不只一種,"
                "請在那幾筆自己標(照常執行,不移動機構)"
                % len(report["ambiguous"]), "warn")
