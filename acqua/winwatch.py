# -*- coding: utf-8 -*-
"""量測期間的視窗監看器。

為什麼需要這個
──────────────
ACQUA 跑到某些測項會開視窗等人操作。實測確認有 **三種** class:

    TfrmDocViewer   (Delphi)   Info 說明文件
    TkTopLevel      (Tcl/Tk)   DUT & Measurement Wizard / BGN Wizard / Hardware options
    #32770          (Win32)    'Missing Associations' 等標準對話框
                               —— 這個在 StartMeasurements **一開始**就跳,
                                  不處理的話整批完全不動、連 OnBeginMeasurements
                                  都不會發,看起來像 COM 壞掉

實測(2026-08-17 / 08-20)確認:**這些視窗開著的時候 `IsMeasuring` 是 True,
但一個 COM 事件都不會發。** 所以「等事件 + 逾時」的寫法永遠等不到東西 ——
那正是先前 Info 測項卡住 30 分鐘的成因。

必須從視窗這一側處理,COM 那一側看不到。

⚠️ 這個模組同時是**唯一的流程控制手段**
─────────────────────────────────────────
實測結論(2026-08-20,MS Teams v5 Rev05 SP2 - Speakerphone,1151 筆):

    OnFinishedSingleMeasurement 回傳 REDO_THIS(2)  → 沒有任何一筆重跑
    OnFinishedSingleMeasurement 回傳 CANCEL_ALL(3) → 照樣跑下一筆
    MeasurementEngine.CancelCalculation()          → 無效
    對 TfrmMeasState 送 WM_CLOSE                    → 無效
    TypeLib 全域搜尋 Cancel/Stop/Abort              → 只有 IPlayer/IRecorder 的 Stop()

也就是 **pywin32 的 ByRef 回傳完全沒有送達 ACQUA**,整批量測沒有程式化中止。
(舊註解說「已驗證 DO_NEXT 生效」是假陽性 —— DO_NEXT 就是預設行為,
 回不回傳結果一樣,那個測試分辨不出任何事。)

所以「暫停」的實作方式是:**停止關閉阻塞視窗**,量測就會停在下一個對話框
不再前進。已驗證兩次有效,而且停得很乾淨。要真正中止仍需在 ACQUA 視窗上操作
(例如 'Missing Associations' 的「取消」鈕 —— 實測 0.3 秒整批就停了)。

處理策略刻意分兩種
──────────────────
    Info 文件   → 自動關。它沒有量測內容(OnEvent 會說 "No data to store"),
                  關掉零風險。
    互動精靈    → **不自動關**,推到 UI 問人。關掉精靈可能等於「取消」,
                  會改變接下來跑什麼 —— 不該由程式自作主張。

規則放在 config.json 的 blocking_windows,之後冒出新的對話框加一行即可。
"""
from __future__ import annotations

import fnmatch
import threading
import time

try:
    import win32gui
    import win32con
    import win32process
    _WIN32 = True
except ImportError:                                     # pragma: no cover
    _WIN32 = False


# 絕不關的視窗 —— 關掉會直接毀掉使用者的 ACQUA
NEVER_CLOSE = {
    "TFormApplicationMain",     # ACQUA 主視窗
    "TfrmMarkAnalyzer",         # ACQUAlyzer 主視窗
    "TApplication",             # Delphi 的隱形應用程式視窗
    "TfrmMeasState",            # 量測狀態視窗(關了會失去進度顯示)
}

DEFAULT_RULES = [
    {"class": "TfrmDocViewer", "title": "*", "action": "close",
     "note": "Info 說明文件 —— 沒有量測內容,自動關"},
    {"class": "TkTopLevel", "title": "*Wizard*", "action": "ask",
     "note": "互動精靈 —— 關掉可能等於取消,問過再說"},
    {"class": "TkTopLevel", "title": "*", "action": "ask",
     "note": "其他 Tcl/Tk 對話框(例如 Hardware options)"},
    # #32770 是 Windows 標準對話框 class。實測 StartMeasurements 一開始就會跳
    # 'Missing Associations'(量測物件沒有欄位關聯),按「取消」會整批中止。
    # 一律問人 —— 自動按「Ignore」等於默許用有問題的設定往下跑。
    {"class": "#32770", "title": "*", "action": "ask",
     "note": "ACQUA 的標準對話框 —— 內容與按鈕會一起回報"},
]

# ACQUA 的行程名(小寫比對)
ACQUA_EXE = {"acqua6.exe", "acqualyzer.exe", "acqua.exe"}


def acqua_pids():
    """目前 ACQUA 相關行程的 PID。抓不到就回空集合(代表不限定行程)。"""
    try:
        import win32com.client
        wmi = win32com.client.GetObject("winmgmts:")
        out = set()
        for p in wmi.ExecQuery("SELECT ProcessId, Name FROM Win32_Process"):
            try:
                if str(p.Name).lower() in ACQUA_EXE:
                    out.add(int(p.ProcessId))
            except Exception:                           # noqa: BLE001
                continue
        return out
    except Exception:                                   # noqa: BLE001
        return set()


def list_windows(pids=None):
    """列出可見的頂層視窗。pids 給了就只回那些行程的。

    回傳 [{hwnd, pid, cls, title}]
    """
    if not _WIN32:
        return []
    found = []

    def cb(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            cls = win32gui.GetClassName(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pids and pid not in pids:
                return True
            if not title and not cls.startswith(("Tfrm", "TForm", "TkTop")):
                return True
            found.append({"hwnd": hwnd, "pid": pid, "cls": cls, "title": title})
        except Exception:                               # noqa: BLE001
            pass
        return True

    try:
        win32gui.EnumWindows(cb, None)
    except Exception:                                   # noqa: BLE001
        pass
    return found


def dialog_controls(hwnd):
    """列出對話框的子控制項。回傳 [{hwnd, cls, text}]。

    用來把 ACQUA 對話框的訊息與按鈕原封不動端到網頁上,
    讓人看到「ACQUA 到底在問什麼」,而不是只看到一個乾巴巴的視窗標題。
    """
    if not _WIN32:
        return []
    out = []

    def cb(h, _):
        try:
            out.append({"hwnd": h,
                        "cls": win32gui.GetClassName(h),
                        "text": win32gui.GetWindowText(h)})
        except Exception:                               # noqa: BLE001
            pass
        return True

    try:
        win32gui.EnumChildWindows(hwnd, cb, None)
    except Exception:                                   # noqa: BLE001
        pass
    return out


def dialog_buttons(hwnd):
    """對話框上的按鈕文字清單。"""
    return [c["text"] for c in dialog_controls(hwnd)
            if c["cls"].lower() == "button" and c["text"]]


def dialog_message(hwnd):
    """對話框的訊息文字(按鈕以外的靜態文字,串起來)。"""
    parts = [c["text"] for c in dialog_controls(hwnd)
             if c["cls"].lower() in ("static", "edit") and c["text"]]
    return "\n".join(parts)


def click_button(hwnd, text):
    """按下對話框上文字符合的按鈕。text 支援萬用字元。"""
    if not _WIN32:
        return False
    for c in dialog_controls(hwnd):
        if c["cls"].lower() != "button" or not c["text"]:
            continue
        if c["text"] == text or fnmatch.fnmatch(c["text"], text):
            try:
                win32gui.SendMessage(c["hwnd"], win32con.BM_CLICK, 0, 0)
                return True
            except Exception:                           # noqa: BLE001
                return False
    return False


def match_rule(win, rules):
    """找出第一條符合的規則。class 與 title 都支援萬用字元。"""
    for r in rules:
        if not fnmatch.fnmatch(win["cls"], r.get("class", "*")):
            continue
        if not fnmatch.fnmatch(win["title"], r.get("title", "*")):
            continue
        return r
    return None


class WindowWatcher:
    """背景監看 ACQUA 的阻塞視窗。

        w = WindowWatcher(rules, log=print, on_blocked=cb)
        w.start()
        ...  量測進行中  ...
        w.stop()

    on_blocked(info)  在偵測到需要人工決定的視窗時呼叫一次。
    外部用 w.answer(hwnd, "close" / "ignore") 回覆。
    dry_run=True 時只偵測與回報,絕不真的關視窗 —— 拿來驗規則用。
    """

    def __init__(self, rules=None, log=None, on_blocked=None,
                 poll=0.4, dry_run=False, restrict_to_acqua=True):
        self.rules = list(rules or DEFAULT_RULES)
        self.log = log or (lambda *_a, **_k: None)
        self.on_blocked = on_blocked
        self.poll = float(poll)
        self.dry_run = bool(dry_run)
        self.restrict = bool(restrict_to_acqua)

        self._stop = threading.Event()
        self._thread = None
        self._pids = set()
        self._handled = set()          # 已處理過的 hwnd,避免重複動作
        self._lock = threading.Lock()

        # 目前正在等人回答的視窗 {hwnd: info}
        self.pending = {}
        # 統計
        self.closed = []
        self.asked = []

    # ── 生命週期 ────────────────────────────────
    def start(self):
        if not _WIN32:
            self.log("[winwatch] 沒有 pywin32,視窗監看停用", "warn")
            return self
        self._pids = acqua_pids() if self.restrict else set()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="winwatch")
        self._thread.start()
        self.log(f"[winwatch] 已啟動,監看 {len(self.rules)} 條規則"
                 + (f",限定 ACQUA 行程 {sorted(self._pids)}" if self._pids else "")
                 + ("(dry-run,不會真的關視窗)" if self.dry_run else ""))
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None
        return self

    def __enter__(self):
        return self.start()

    def __exit__(self, *_exc):
        self.stop()
        return False

    # ── 外部回覆 ────────────────────────────────
    def answer(self, hwnd, action):
        """UI 回覆某個待決視窗要怎麼處理。

            "close"              送 WM_CLOSE
            "click:<按鈕文字>"    按下對話框上的某顆按鈕(支援萬用字元)
            其他                  保留不動
        """
        with self._lock:
            info = self.pending.pop(int(hwnd), None)
        if not info:
            return False
        action = str(action or "")
        if action.startswith("click:"):
            label = action.split(":", 1)[1]
            ok = click_button(info["hwnd"], label)
            self.log(f"[winwatch] {'已按下' if ok else '找不到按鈕'} {label!r}"
                     f" @ {info['title']!r}", "info" if ok else "warn")
            return ok
        if action == "close":
            self._close(info, why="使用者選擇關閉")
            return True
        self.log(f"[winwatch] 保留視窗:{info['title']}")
        return True

    def snapshot(self):
        """給 UI 用:目前有哪些視窗在擋。"""
        with self._lock:
            return list(self.pending.values())

    # ── 內部 ────────────────────────────────────
    def _close(self, info, why=""):
        if info["cls"] in NEVER_CLOSE:
            self.log(f"[winwatch] 拒絕關閉主視窗 {info['cls']}", "warn")
            return False
        if self.dry_run:
            self.log(f"[winwatch] (dry-run)本來會關:[{info['cls']}] {info['title']!r}")
            self.closed.append(info)
            return True
        try:
            win32gui.PostMessage(info["hwnd"], win32con.WM_CLOSE, 0, 0)
            self.closed.append(info)
            self.log(f"[winwatch] 已關閉 [{info['cls']}] {info['title']!r}"
                     + (f" —— {why}" if why else ""))
            return True
        except Exception as exc:                        # noqa: BLE001
            self.log(f"[winwatch] 關閉失敗 {info['title']!r}:{exc}", "warn")
            return False

    def _loop(self):
        n = 0
        while not self._stop.is_set():
            try:
                # 定期重抓 PID —— ACQUA 可能中途才拉起 ACQUAlyzer 這類子程序
                if n % 25 == 0 and self.restrict:
                    fresh = acqua_pids()
                    if fresh and fresh != self._pids:
                        self._pids = fresh
                        self.log(f"[winwatch] ACQUA 行程更新為 {sorted(fresh)}")
                self._scan()
            except Exception as exc:                    # noqa: BLE001
                self.log(f"[winwatch] 掃描出錯:{exc}", "warn")
            n += 1
            self._stop.wait(self.poll)

    def _scan(self):
        # ⚠️ 限定 ACQUA 模式下抓不到行程時**什麼都不做**。
        #    不能退回掃全系統 —— TkTopLevel 是通用 Tcl/Tk class,
        #    誤關使用者自己的 Tk 工具會很難查。
        if self.restrict and not self._pids:
            if not getattr(self, "_warned_nopid", False):
                self._warned_nopid = True
                self.log("[winwatch] 找不到 ACQUA 行程,暫停動作"
                         "(避免誤關其他程式的視窗)", "warn")
            return
        self._warned_nopid = False

        alive = set()
        for win in list_windows(self._pids or None):
            alive.add(win["hwnd"])
            rule = match_rule(win, self.rules)
            if not rule:
                continue
            action = rule.get("action", "ask")
            if action == "ignore":
                continue
            if win["cls"] in NEVER_CLOSE:
                continue

            key = (win["hwnd"], win["cls"], win["title"])
            if action == "close":
                if key in self._handled:
                    continue
                self._handled.add(key)
                info = dict(win, rule=rule)
                self._close(info, why=rule.get("note", ""))

            elif action == "click":
                # 規則直接指定要按哪顆按鈕(給已知安全的對話框用)
                if key in self._handled:
                    continue
                self._handled.add(key)
                label = rule.get("button", "")
                ok = click_button(win["hwnd"], label) if label else False
                self.log(f"[winwatch] {'已按下' if ok else '按不到'} {label!r}"
                         f" @ [{win['cls']}] {win['title']!r}",
                         "info" if ok else "warn")

            elif action == "ask":
                with self._lock:
                    if win["hwnd"] in self.pending:
                        continue
                    if key in self._handled:
                        continue
                    self._handled.add(key)
                    info = dict(win, rule=rule, since=time.time(),
                                buttons=dialog_buttons(win["hwnd"]),
                                message=dialog_message(win["hwnd"]))
                    self.pending[win["hwnd"]] = info
                self.asked.append(info)
                btn = ("  按鈕:" + " / ".join(info["buttons"])) if info["buttons"] else ""
                self.log(f"[winwatch] ⏸ ACQUA 開了視窗在等人:"
                         f"[{win['cls']}] {win['title']!r}{btn}", "warn")
                if self.on_blocked:
                    try:
                        self.on_blocked(info)
                    except Exception:                   # noqa: BLE001
                        pass

        # 視窗被關掉(不管是誰關的)就從待決清單移除
        with self._lock:
            for h in [h for h in self.pending if h not in alive]:
                self.pending.pop(h, None)


# ── 自我測試:只看不關 ──────────────────────────────
if __name__ == "__main__":                              # pragma: no cover
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    print("=== 目前 ACQUA 行程 ===")
    pids = acqua_pids()
    print("   ", sorted(pids) or "(找不到 ACQUA)")

    print("\n=== 目前可見視窗 ===")
    for w in list_windows(pids or None):
        r = match_rule(w, DEFAULT_RULES)
        tag = ""
        if r:
            tag = f"  ← 符合規則 action={r['action']}"
            if w["cls"] in NEVER_CLOSE:
                tag += "(但在保護名單內,不會動)"
        print("   [%-22s] %-46s%s" % (w["cls"], repr(w["title"])[:44], tag))

    print(f"\n=== dry-run 監看 {secs} 秒(不會關任何視窗)===")
    w = WindowWatcher(log=lambda m, lv="info": print("   " + m), dry_run=True)
    with w:
        time.sleep(secs)
    print(f"\n偵測到要關的 {len(w.closed)} 個 ・ 要問人的 {len(w.asked)} 個")
