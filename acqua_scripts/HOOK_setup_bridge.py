# -*- coding: utf-8 -*-
"""⚠️ 這支**不是**從 ACQUA 匯出的副本,是要貼進 ACQUA 的新程式。

    放這裡只是方便 review 與改版。真正要生效,得用 ACQUA 自己的腳本編輯器
    貼進專案層級的 `before_each_measurement.py` —— 直接改 File_Cache 沒有用,
    ACQUA 會用資料庫裡的版本蓋掉。

====================================================================
  擺位橋接掛鉤 —— ACQUA 主導的那條路
====================================================================

為什麼需要它
────────────
擺位有兩條驅動路線:

    我們主導   網頁按執行 -> /api/run 逐筆送出,送之前自己把機構移好
    ACQUA 主導 有人直接在 ACQUA 按執行,完全繞過我們的網頁 ← **這支管的**

第二條路一定會發生 —— 工程師習慣在 ACQUA 裡操作。沒有這支的話,
那些量測會在**當下的機構位置**進行,而且沒有任何紀錄。

它做什麼(對應計畫書 5.0.4 的三條規則)
──────────────────────────────────────
    1. 有 Setup 標籤,擺位找得到  -> 叫服務移動,等到位,繼續量測
    2. 有 Setup 標籤,找不到      -> **不移動**、回報一筆、繼續量測
    3. 沒有 Setup 標籤            -> 什麼都不做,沿用當下擺位

⚠️ **這支絕對不 raise。**
   擺位有問題的代價是一筆數據可疑;raise 的代價是整晚的批次停在第 3 筆,
   早上回來發現什麼都沒跑。所以失敗一律走「回報 + 繼續」,
   由跑完的摘要、CSV 與報告旁邊的警告清單去承接(計畫書防線 ⑤)。

部署前要先確認的事(計畫書第 0 階段)
────────────────────────────────────
把 SELFTEST_SLEEP 設成 10 -> 60 -> 180 各跑一筆 Record,確認:
  - ACQUA 撐得住掛鉤卡住這麼久嗎
  - 我們網頁的心跳會不會把它誤判成 COM 死掉
**分段加上去,不要一次跳到 180 秒。**
"""
import json
import time
import urllib.error
import urllib.request

# 刻意用 urllib 而不是 requests。ACQUA 的腳本環境兩個都有(計畫書 §3.5),
# 但 urllib 是標準庫 —— 少一個「換台機器就可能不見」的相依,
# 而且我們自己的測試環境不用為了測它多裝一個套件。
try:                                # ACQUA 腳本環境才有
    from ACQUAlyzer import Tags, Smd
except ImportError:                 # 在外面執行時讓它至少 import 得過
    Tags = Smd = None

# ── 設定 ────────────────────────────────────────────
SERVICE = "http://127.0.0.1:5000"
TAG = "Setup"

#: 移動最多等多久。機構一次整組擺位實測 51 秒,真機會更久 ——
#: 但不能無限等,服務掛了的話這裡會變成整批卡死的地方。
MOVE_TIMEOUT = 900

#: 連得上服務算多久逾時。這個要短 —— 服務沒開的話每一筆都要等這麼久。
HTTP_TIMEOUT = 10

#: 第 0 階段用:在這裡硬睡幾秒,測 ACQUA 容不容得下會卡住的掛鉤。
#: 正式上線一定要是 0。
SELFTEST_SLEEP = 0


def _log(msg):
    """ACQUA 視窗看得到。這只是輔助 —— 無人值守時沒人看得到,
    真正的紀錄要靠 _report_not_applied() 送回服務。"""
    print("[setup] %s" % msg)


def _get(path):
    with urllib.request.urlopen(SERVICE + path, timeout=HTTP_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(path, body):
    req = urllib.request.Request(
        SERVICE + path, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 4xx 也帶著 JSON 回來(例如「找不到擺位」)—— 那是答案,不是故障
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:                                   # noqa: BLE001
            return {"ok": False, "error": "HTTP %s" % e.code}


def _report_not_applied(wanted, reason):
    """把「這一筆沒套用到指定擺位」送回服務(計畫書防線 ⑤)。

    連記錄都失敗就算了 —— 絕對不能因為記不了而擋住量測。
    """
    try:
        _post("/api/room/not-applied",
              {"smd": getattr(Smd, "Title", ""),
               "wanted": wanted, "reason": reason})
    except Exception as exc:                                # noqa: BLE001
        _log("連回報都失敗了(繼續量測):%s" % exc)


def ensure_setup():
    if SELFTEST_SLEEP:
        _log("自我測試:故意卡住 %d 秒…" % SELFTEST_SLEEP)
        time.sleep(SELFTEST_SLEEP)
        _log("自我測試:醒來了")

    if Tags is None or not Tags.Exists(TAG):
        return                                  # 規則 3:沒標,沿用當下

    wanted = (Tags.Value(TAG) or "").strip()
    if not wanted:
        return                                  # 標了空字串,當作沒標

    try:
        now = _get("/api/room/current")
    except Exception as exc:                                # noqa: BLE001
        # 服務沒開是最常見的情況 —— 訊息要直接講出來,
        # 不然現場只會看到一串網路層的例外文字。
        _report_not_applied(wanted, "連不上自動化服務:%s" % str(exc)[:60])
        return

    if now.get("setup") == wanted:
        _log("已經在「%s」上,不用移動" % wanted)
        return

    _log("要移動到「%s」(目前:%s)" % (wanted, now.get("setup")))
    try:
        r = _post("/api/room/apply", {"setup_name": wanted})
    except Exception as exc:                                # noqa: BLE001
        _report_not_applied(wanted, "送出移動失敗:%s" % str(exc)[:60])
        return

    if not r.get("ok"):
        # 規則 2:名稱找不到對應 -> 不移動、記一筆、繼續
        _report_not_applied(wanted, r.get("error") or "移動被拒絕")
        return

    # ── 等它走完 ──
    # ⚠️ 判斷「還在動」要看 moving,**不要**看有沒有 job ——
    #    作業跑完不會被清掉,只是狀態變成 done(2026-11-16 踩過)。
    deadline = time.time() + MOVE_TIMEOUT
    while time.time() < deadline:
        try:
            now = _get("/api/room/current")
        except Exception:                                   # noqa: BLE001
            time.sleep(2)           # 移動中服務忙,偶爾逾時是正常的
            continue
        if not now.get("moving"):
            break
        time.sleep(2)
    else:
        _report_not_applied(wanted, "移動逾時(超過 %d 秒)" % MOVE_TIMEOUT)
        return

    if now.get("setup") != wanted:
        _report_not_applied(wanted, "移動完成但位置對不上(現在是 %s)"
                            % now.get("setup"))
        return

    _log("已就位:「%s」" % wanted)


# ACQUA 每一筆量測開始前會跑這個檔。整支包起來 ——
# 任何沒想到的例外都不該把量測擋掉。
try:
    ensure_setup()
except Exception as exc:                                    # noqa: BLE001
    print("[setup] 掛鉤自己出錯了,照常量測:%s" % exc)
