# -*- coding: utf-8 -*-
"""前端與路由的機械化盤點 —— 「按下去會不會沒反應」這類問題。

為什麼要有這支
──────────────
這個專案沒有測試框架,而前端的錯法有個共同特徵:**頁面照樣載入**,
壞的地方要等使用者按下去才發現。實際踩過的三種:

  1. 區間替換不小心刪掉函式  → renderBlocking is not defined(整段 JS 死掉)
  2. 按鈕留在 HTML 沒接 handler → 按了沒反應,不會報錯
  3. fetch 打到不存在的路由     → 404,只在 Console 看得到

這三種都能靠比對抓出來,不必等人回報。

檢查項目
────────
  A. JS 取用的元素 id,HTML 裡都有嗎
  B. HTML 上的按鈕,都有人接嗎(直接 onclick 或委派監聽)
  C. 前端打的 /acqua/api/... 都有對應的 Flask 路由嗎
  D. worker 命令表裡的每個命令,兩個 backend 都實作了嗎
  E. 需要專案/量測物件的路由,有沒有先檢查前置條件

用法:  python tools/check_ui.py       (回傳碼 0 = 通過)
"""
from __future__ import annotations

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

fails = []


def check(name, ok, detail=""):
    print("   %-48s %s%s" % (name, "OK" if ok else "!! 失敗",
                             ("  " + detail) if detail and not ok else ""))
    if not ok:
        fails.append(name)


def read(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8").read()


def scripts_of(html):
    """把 <script> 區塊接起來。Jinja 的 {% %} 不會出現在 JS 裡,不用處理。"""
    return "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", html, re.S))


PAGES = ["templates/index.html", "templates/plans.html",
         "templates/home.html", "templates/soundproofroom.html",
         "templates/_runmini.html"]

# 共用 partial 的元素給宿主頁面用,所以要合在一起看
SHARED = read("templates/_runmini.html")


print("=== 0. 結構完整性 ===")
for page in PAGES:
    html = read(page)
    ids = re.findall(r'\bid="([^"]+)"', html)
    dup = sorted({i for i in ids if ids.count(i) > 1})
    check("%s 的 id 不重複(%d 個)" % (os.path.basename(page), len(ids)),
          not dup, "重複:" + ", ".join(dup))
    # <div> 開關要平衡 —— 用字串替換做區塊編輯時最容易弄壞的就是這個
    op = len(re.findall(r"<div\b", html))
    cl = len(re.findall(r"</div>", html))
    check("%s 的 <div> 平衡(%d/%d)" % (os.path.basename(page), op, cl), op == cl)



print("=== 0b. CSS 變數 ===")
_tokens = set(re.findall(r"--([a-z0-9-]+):", read("templates/_ui.html")))
for _p in PAGES:
    _t = read(_p)
    _used = set(re.findall(r"var\(--([a-z0-9-]+)", _t))
    _own = set(re.findall(r"--([a-z0-9-]+):", _t))
    _miss = sorted(_used - _tokens - _own)
    check("%s 沒有懸空的 CSS 變數" % os.path.basename(_p), not _miss,
          "未定義:" + ", ".join(_miss))
check("切換開關:開=品牌色", ".sw input:checked + i { background:var(--brand); }"
      in read("templates/index.html"))

print("\n=== A. JS 取用的元素,HTML 裡都有嗎 ===")
for page in PAGES:
    html = read(page)
    js = scripts_of(html)
    if page != "templates/_runmini.html":
        html += SHARED          # partial 會被 include 進來
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    want = set(re.findall(r"""\$\(['"]#([A-Za-z0-9_-]+)['"]\)""", js))
    want |= set(re.findall(r"""getElementById\(['"]([A-Za-z0-9_-]+)['"]\)""", js))
    want |= set(re.findall(r"""\bel\(['"]([A-Za-z0-9_-]+)['"]\)""", js))
    miss = sorted(want - ids)
    check("%s 取用 %d 個 id" % (os.path.basename(page), len(want)),
          not miss, "找不到:" + ", ".join(miss))


print("\n=== B. 按鈕都有人接嗎 ===")
for page in PAGES:
    html = read(page)
    js = scripts_of(html)
    if page != "templates/_runmini.html":
        js += scripts_of(SHARED)
    # 只看有 id 的 <button>;沒有 id 的通常是 modal 內的靜態裝飾
    btns = re.findall(r'<button[^>]*\bid="([^"]+)"', html)
    dead = []
    for b in btns:
        # 直接綁、或被委派監聽用 dataset / closest 處理到
        if re.search(r"['\"]#%s['\"]" % re.escape(b), js):
            continue
        dead.append(b)
    check("%s 的 %d 顆按鈕都有接" % (os.path.basename(page), len(btns)),
          not dead, "沒接:" + ", ".join(dead))
    # 委派型按鈕(data-* 驅動)另外看:HTML 產生的 data 屬性有人讀嗎
    datas = set(re.findall(r"data-([a-z]+)=", html))
    unread = sorted(d for d in datas
                    if not re.search(r"dataset\.%s\b|data-%s" % (d, d), js))
    check("%s 的 data-* 都有人讀" % os.path.basename(page),
          not unread, "沒人讀:" + ", ".join(unread))


print("\n=== C. 前端打的 API 都有路由嗎 ===")
app = read("app.py")
routes = set()
for m in re.finditer(r'@(?:app|acqua_bp)\.route\(\s*"([^"]+)"', app):
    p = m.group(1)
    routes.add(p if p.startswith("/acqua") or not p.startswith("/") else p)
# blueprint 掛在 /acqua 底下
bp_prefix = re.search(r'Blueprint\([^)]*url_prefix\s*=\s*"([^"]+)"', app)
prefix = bp_prefix.group(1) if bp_prefix else "/acqua"
full = set()
for m in re.finditer(r'@app\.route\(\s*"([^"]+)"', app):
    full.add(m.group(1))
for m in re.finditer(r'@acqua_bp\.route\(\s*"([^"]+)"', app):
    full.add((prefix.rstrip("/") + m.group(1)).replace("//", "/"))


def norm(u):
    """把 /acqua/api/plans/abc123 之類的變數段換成 <>,並去掉 query。"""
    u = u.split("?")[0].rstrip("/") or "/"
    return re.sub(r"<[^>]+>", "<>", u)


known = {norm(r) for r in full}
# 有變數段的路由,拿掉最後一段也算命中(前端是用字串拼的)
known_prefix = {norm(r).rsplit("/", 1)[0] for r in full if "<" in r}

for page in PAGES:
    js = scripts_of(read(page))
    # 記下每個網址字串後面接的是不是 `+`(前端在拼字串)
    used = {}
    for m in re.finditer(r"""['"`](/acqua/api/[^'"`\s?]*)['"`\s]*(\+?)""", js):
        u, dyn = m.group(1), bool(m.group(2))
        used[u] = used.get(u, False) or dyn
    bad, dynamic = [], []
    for u, dyn in used.items():
        n = norm(u)
        if n in known:
            continue
        # 前端拼字串:'/acqua/api/plans/' + id  或  '/acqua/api/' + to
        # 這種只能驗到「有路由以它開頭」。放過但要列出來,不然等於沒檢查。
        if dyn or n in known_prefix or n.rstrip("/") in known_prefix:
            hit = [r for r in known if r.startswith(n.rstrip("/"))]
            (dynamic if hit else bad).append(u + ("+…" if dyn else ""))
            continue
        bad.append(u)
    check("%s 打的 %d 個 API 都存在" % (os.path.basename(page), len(used)),
          not bad, "找不到路由:" + ", ".join(sorted(bad)))
    if dynamic:
        print("       (動態組合,只驗到前綴:%s)" % "、".join(sorted(dynamic)))


print("\n=== D. worker 命令兩個 backend 都實作了嗎 ===")
wk = read("acqua/worker.py")
cmds = re.findall(r'^\s*"([a-z_]+)": lambda \*\*kw: self\.backend\.([a-z_]+)\(', wk, re.M)
com, mock = read("acqua/backend_com.py"), read("acqua/backend_mock.py")
base = read("acqua/backend_base.py")
miss_com = [m for _, m in cmds if ("def %s(" % m) not in com]
miss_mock = [m for _, m in cmds if ("def %s(" % m) not in mock
             and ("def %s(" % m) not in base]
check("%d 個命令在 COM backend 都有" % len(cmds), not miss_com,
      "缺:" + ", ".join(sorted(set(miss_com))))
check("%d 個命令在 mock / base 都有" % len(cmds), not miss_mock,
      "缺:" + ", ".join(sorted(set(miss_mock))))


print("\n=== E. 需要專案 / 量測物件的動作有先檢查嗎 ===")
# 這些 backend 方法沒有專案就一定失敗,必須自己先擋 —— 不然錯誤只進 log,
# 前端會停在「準備中」等到超時(2026-08-21 踩過)。
NEED = {
    "run_smds": ("self.project is None", "self.mo is None"),
    "list_smds": ("self.project is None",),
    "create_report": ("self.project is None", "self.mo is None"),
    "wizard_options": (),          # 走 SQL,專案標題不在也只是回空
}
for fn, needs in NEED.items():
    m = re.search(r"\n    def %s\(" % re.escape(fn), com)
    body = ""
    if m:
        rest = com[m.end():]
        nxt = re.search(r"\n    def ", rest)
        body = rest[:nxt.start()] if nxt else rest
    ok = all(n in body for n in needs)
    check("backend.%s 有前置檢查" % fn, ok or not needs)

check("/api/run 送出前先擋前置條件",
      'error="No project open"' in app and 'error="No measurement object selected"' in app)
check("/api/run 同步驗證測項歸屬", '"check_rows"' in app)


print("\n=== F. 切換專案不能靜靜開錯 ===")
# 2026-08-24 實測:要求 Headset 卻拿到 Handset,而且 API 回 ok=True。
# SelectAsActive 是非同步的,SelectedProjectLoaded 在舊專案還開著時就是 True。
check("等到 SelectedProject.Title 真的變成要求的那一個",
      "def arrived():" in com and "SelectedProject.Title).strip() == want" in com)
check("切不過去會明說目前是哪一個", '目前仍是' in com)
check("Standards 範本給人看得懂的說明", "cannot be modified" in com and "標準範本" in com)
check("ProjectGroups 集合失效會重讀一次", "重讀 ProjectGroups 再試" in com)
check("標題比對去頭尾空白(實測有尾巴帶空格的群組)",
      "str(pg.Title).strip() != want_g" in com)


print("\n=== G. 不可逆的動作要先確認 ===")
idx_html = read("templates/index.html")
pl_html = read("templates/plans.html")

# 存成計畫:按下去之前先攤開內容,存完清空 —— 不清很容易把同一批重複存
check("存成計畫先跳確認視窗", 'id="planov"' in idx_html and "btn-pv-save" in idx_html)
check("確認視窗列出勾選的項目", 'id="pv-items"' in idx_html)
check("存好後顯示成功並倒數關閉",
      "Saved plan" in idx_html and "Closing in" in idx_html)
check("存好後清空輸入框與勾選",
      "$('#plan-title').value = '';" in idx_html and "selected.clear();" in idx_html)

# 刪除計畫:沒有復原,所以要打名稱
check("刪除要先跳視窗", 'id="delov"' in pl_html)
check("刪除要把名稱完整打一次",
      "$('#dl-input').value.trim() === p.title" in pl_html)
check("名稱沒對上時刪除鈕是停用的", "$('#dl-go').disabled = !same" in pl_html)
check("刪除後顯示成功字樣", "Deleted \"" in pl_html)

check("計畫庫有關鍵字搜尋", 'id="q"' in pl_html and "function matches(p)" in pl_html)
check("搜尋涵蓋名稱/說明/來源/setup",
      "s.database, s.project, s.measurement_object" in pl_html)


print("\n=== H. 序列每一步的設定 ===")
# 每一步各自帶 run 名稱與 Word 輸出 —— 同一個計畫在不同輪次要用不同名字
for f in ("run_name", "doc_name", "doc_dir"):
    check("序列步驟有 %s 欄位" % f, ('data-f="%s"' % f) in pl_html)
check("序列步驟是物件,且吃得下舊的純 id 陣列",
      "const newStep = (id)" in pl_html and "typeof x === 'string' ? newStep(x)" in pl_html)
check("欄位改動即時存進 localStorage",
      "st[el.dataset.f] = el.value" in pl_html and "saveSeq();" in pl_html)
check("打字時不會被輪詢重繪洗掉",
      "$('#seq').contains(document.activeElement)" in pl_html)
check("這一步填了名稱就優先用它", "st.run_name.trim()" in pl_html)
check("跑完會依設定產出 Word", "async function makeReport" in pl_html)
check("報告同名不覆蓋,自動加編號",
      "if (!sv.exists)" in pl_html and "_${n}${ext}" in pl_html)
check("計畫細節看得到完整測項", 'id="detov"' in pl_html
      and "async function openDetail" in pl_html)

print()
print("=== J. 序列的執行流程 ===")
check("兩步之間會跑 Moving to new setup", "function movingToSetup" in pl_html)
check("那段目前是 mock,並在程式裡註明",
      "目前是 mock" in pl_html and "Raspberry Pi" in pl_html)
check("移動階段可以被中止", "if (abort) { clearInterval(timer)" in pl_html)
check("縮小視窗涵蓋整個序列(含移動階段)",
      "window.__miniInfo" in pl_html
      and "window.__miniInfo === 'function'" in read("templates/_runmini.html"))
check("跑完列出產生的 Word", "madeDocs.push" in pl_html and "dn-files" in pl_html)
check("完成視窗五秒後自動關閉", "秒後自動關閉" in pl_html and "closeRunOv" in pl_html)
check("滑鼠一動就取消自動關閉", "auto-close cancelled" in pl_html)
check("舊的手動 setup 對話框已移除",
      "btwov" not in pl_html and "waitSetup" not in pl_html)

# 跨庫/跨機時每台受測物名稱不同 —— 執行當下才決定要寫進哪個 MO
check("序列步驟可選 DUT", 'data-f="mo"' in pl_html and 'select data-f' in pl_html)
check("DUT 選單來自該計畫來源專案", 'plans/<plan_id>/mos' in read("app.py")
      and "def list_mobjects" in read("acqua/sqlcat.py"))
check("新增 DUT 失敗會明講(AddMeasurementObject 回 -1)",
      "int(idx) < 0" in read("acqua/backend_com.py"))
check("執行時把 DUT 名稱送給 prepare",
      "measurement_object: st.mo.trim()" in pl_html)
ap = read("app.py")
check("換機/換庫的判斷比對 (server, database)",
      '(srv, db) != (now.get("server"), now.get("database"))' in ap)
check("prepare 收得到 DUT 覆寫", 'mo_override = str(body.get("measurement_object")' in ap)
# 選單裡的名稱都是既有的,所以一律不建立(COM 也建不了)
check("選 DUT 一律不嘗試建立", "title=mo, create_if_missing=False" in ap)

print()
print("=== I2. 涵蓋率:對所有 SMD / 專案 / 資料庫都成立嗎 ===")
sq = read("acqua/sqlcat.py")
wz = read("acqua/wizard.py")

# 測項身分:(路徑,名稱) 實測不唯一(ZoomRooms 有 11%),所以必須帶序號
check("測項身分帶序號", chr(34) + "occ" + chr(34) + ": occ" in sq)
check("還原用三層索引(序號 → 路徑名稱 → 名稱)",
      "by_exact" in com and "路徑+名稱+序號" in com)
check("存計畫時帶序號", "occ: s.occ" in idx_html)

# 分類:型別 + 標題兩層。只靠標題清單一定會漏(實測漏了 3 種)
check("測項分類看型別也看標題",
      "def _classifier" in com and "script_smd_types" in com)
check("mock 後端有同樣的分類", "def _classifier" in read("acqua/backend_mock.py"))
check("腳本測項會事先提醒", "script item(s) in this batch" in idx_html)

# 精靈變數:看它怎麼被使用,不看名字前綴
check("精靈變數靠關係運算子篩選",
      "_SETTABLE_RELS" in wz and "rset & _SETTABLE_RELS" in wz)

# 沒有量測物件的專案跑不了,而且程式建不出來 —— 開專案當下就要講
check("開專案時檢查有沒有量測物件", "底下沒有任何量測物件" in com)

# 序號會被專案樹的編輯打亂,而且打亂之後身分鍵仍然「對得上」——
# 必須有獨立證據才察覺得到
check("存計畫時記下結構指紋", "tree_fingerprint" in read("acqua/testplans.py")
      and "def fingerprint_of" in sq)
check("還原時比對指紋", "expect_fingerprint" in com and "tree_changed" in com)
check("同專案時 row_id 是權威且會反驗標題",
      "same_ctx and it.get" in com and "專案樹被改過" in com)
check("型別是獨立的一票", "型別對不上" in com)
check("對應有把握與否會回報", '"confident": sure' in com)
check("樹變動時執行前會問人", "res.tree_changed" in pl_html)
# 序號會位移,鄰居不會 —— 這是自動校正的依據
check("每筆測項都有鄰居簽章", "def _neighbour_sig" in sq and '"sig"' in sq)
check("簽章看 ±2 且含鄰居路徑(±1 或不含路徑會碰撞)",
      "_SIG_WINDOW = 2" in sq and 's.get("path") or ""' in sq)
check("序號位移會自動校正回原本那一筆", "已自動校正" in com and "corrected" in com)
check("簽章分不出來時退回序號,不丟掉整筆",
      "簽章是**額外**的證據" in com or "不能把整筆丟掉" in com)
check("有自動校正的實機測試",
      os.path.exists(os.path.join(ROOT, "tools", "test_selfheal.py")))
check("有還原的實機測試",
      os.path.exists(os.path.join(ROOT, "tools", "test_resolve.py")))
# 移機與長期運作:設定要能抽離、環境要能重現、啟動前要能自檢
check("機器專屬設定可從 .env 抽離",
      os.path.exists(os.path.join(ROOT, "acqua", "env.py"))
      and os.path.exists(os.path.join(ROOT, ".env.example")))
check(".env 不進版控", ".env" in read(".gitignore"))
check("相依套件釘到完整快照", read("requirements.txt").count("==") >= 8)
check("有啟動前自檢", os.path.exists(os.path.join(ROOT, "tools", "preflight.py")))
check("有開機自動啟動的安裝腳本",
      os.path.exists(os.path.join(ROOT, "tools", "install_task.ps1")))
check("序列可以拖曳排序", "dragstart" in pl_html and "data-grip" in pl_html)
check("縮小後點一下回到原本的視窗", "__miniRestore" in pl_html
      and "__miniRestore" in read("templates/_runmini.html"))
# 側邊欄三頁 + 3D 頁都要有,而且 logo 要能回首頁
_nav = read("templates/_nav.html")
for _p in ("index", "plans", "soundproofroom"):
    check("%s 掛了側邊欄" % _p, "_nav.html" in read("templates/%s.html" % _p))
check("logo 連到首頁", 'class="logo" href="/"' in _nav)
check("同一張卡的段落之間有間距", ".panel > h2 ~ h2" in read("templates/_ui.html"))
check("有涵蓋率盤點工具",
      os.path.exists(os.path.join(ROOT, "tools", "survey.py")))


print("\n=== I. 計畫庫的排序與分頁 ===")
check("有排序選單", 'id="sort"' in pl_html and "function sorted(" in pl_html)
check("時間與名稱都可正反排",
      all(k in pl_html for k in ("created_desc", "created_asc",
                                 "title_asc", "title_desc")))
check("一頁十筆", "const PAGE = 10" in pl_html)
check("有上一頁 / 下一頁", 'id="pg-prev"' in pl_html and 'id="pg-next"' in pl_html)
check("顯示目前第幾頁", "Page ${page} of ${pages}" in pl_html)
check("換搜尋或排序會回第一頁", pl_html.count("page = 1;") >= 3)
check("過濾後頁數縮水會自動修正", "if (page > pages) page = pages;" in pl_html)


print("\n=== J. 服務活性與收工 ===")
_gate = read("templates/_gate.html")
_wk = read("acqua/worker.py")
app_py = read("app.py")
# 忙碌 != 死掉。少了這一條,任何超過 30 秒的命令都會被判成 COM 不通,
# 使用者會被要求去檢查一個根本沒問題的 dongle。
check("忙碌時不判成 COM 死掉", "alive = bool(busy_cmd)" in app_py)
check("活性看執行緒不看啟動閂鎖", "worker.is_alive()" in app_py)
check("命令跑完也更新心跳",
      _wk.count("self.last_pump_ok = time.monotonic()") >= 2)
check("健康檢查會說出正在跑什麼", "running_command()" in app_py)
check("就緒視窗有停止服務", 'id="gate-stop"' in _gate)
check("停止是兩段式確認", "'Confirm'" in _gate)
check("停止有對應路由",
      "/api/shutdown" in app_py and "/api/shutdown" in _gate)
check("測試進行中不准關", "A test is running" in app_py)
check("關掉會真的釋放 port", "os._exit(0)" in app_py)


print("\n" + ("結論:全部通過" if not fails
              else "結論:%d 項未通過 —— %s" % (len(fails), "、".join(fails))))
sys.exit(1 if fails else 0)
