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
         "templates/home.html", "templates/_runmini.html"]

# 共用 partial 的元素給宿主頁面用,所以要合在一起看
SHARED = read("templates/_runmini.html")


print("=== A. JS 取用的元素,HTML 裡都有嗎 ===")
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
      'error="還沒開啟專案' in app and 'error="還沒選定量測物件' in app)
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


print("\n" + ("結論:全部通過" if not fails
              else "結論:%d 項未通過 —— %s" % (len(fails), "、".join(fails))))
sys.exit(1 if fails else 0)
