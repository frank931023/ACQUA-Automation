# -*- coding: utf-8 -*-
"""上下文一致性檢查 —— 確保「換資料庫/換專案」不會留下舊資料。

背景
────
2026-08-21:使用者換了資料庫,SQL 目錄還連在舊那顆,於是載回舊庫的 309 筆
測項,而 ACQUA 開的是另一個庫的 1477 筆。兩庫的 idTreeItem 必然重疊 ——
送進 StartSingleMeasurement 不會報錯,只會安靜地跑到別的測項。

當時是「補一個呼叫點」。這支程式的目的是讓那件事不能再靠人記得:
把規則寫在 acqua/context.py,由這裡檢查程式碼有沒有照著做。

用法:  python tools/check_context.py       (回傳碼 0 = 通過)
"""
from __future__ import annotations

import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from acqua import context as C            # noqa: E402
from acqua.state import SharedState       # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []


def check(name, ok, detail=""):
    print("   %-46s %s%s" % (name, "OK" if ok else "!! 失敗",
                             ("  " + detail) if detail and not ok else ""))
    if not ok:
        fails.append(name)


def read(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8").read()


print("=== 1. 狀態欄位都分類過了嗎 ===")
snap = SharedState().snapshot()
missing = C.check_coverage(snap.keys())
check("snapshot 的每個欄位都有歸類", not missing,
      "未歸類:" + ", ".join(missing))

st = SharedState()
ghost = [f for f in C.DATABASE_SCOPED if not hasattr(st, f)]
check("列為上下文的欄位都真的存在", not ghost, "找不到:" + ", ".join(ghost))

print("\n=== 2. 後端有照規則作廢嗎 ===")
be = read("acqua/backend_com.py")

def fn_body(src, name):
    """粗略取出某個方法的內容 —— 到下一個同縮排的 def 為止。"""
    m = re.search(r"\n    def %s\(" % re.escape(name), src)
    if not m:
        return ""
    rest = src[m.end():]
    nxt = re.search(r"\n    def ", rest)
    return rest[:nxt.start()] if nxt else rest

check("connect() 換庫會作廢",
      '_reset_context(' in fn_body(be, "connect"))
check("open_project() 換專案會作廢",
      '_reset_context(' in fn_body(be, "open_project"))
check("connect() 會重算 ctx", "_update_context(" in fn_body(be, "connect"))
check("open_project() 會重算 ctx", "_update_context(" in fn_body(be, "open_project"))
check("_reset_context 換庫時丟掉 SQL 目錄",
      "self.sql = None" in fn_body(be, "_reset_context"))

print("\n=== 3. 開跑前的最後一道閘 ===")
check("run_smds() 驗證測項歸屬",
      "_assert_rows_in_project(" in fn_body(be, "run_smds"))
check("_assert_rows_in_project 用 rProject 過濾",
      "rProject" in fn_body(be, "_assert_rows_in_project"))

print("\n=== 4. 前端有跟著作廢嗎 ===")
idx = read("templates/index.html")
check("index 用 s.ctx 當快取 key", "s.ctx !== ctxKey" in idx)
check("ctx 變動時清空勾選", re.search(r"s\.ctx !== ctxKey[\s\S]{0,260}selected\.clear\(\)", idx) is not None)
check("ctx 變動時清空結果對照", re.search(r"s\.ctx !== ctxKey[\s\S]{0,260}resultMap = \{\}", idx) is not None)
check("ctx 變動時清空精靈選項", re.search(r"s\.ctx !== ctxKey[\s\S]{0,260}wizGroups = \[\]", idx) is not None)

pl = read("templates/plans.html")
check("計畫頁會比對 ctx", "plansMismatch" in pl)
check("存計畫時記下 ctx", 'ctx=s.get("ctx")' in read("app.py"))

print()
print("=== 4b. 開跑時有聲明上下文嗎 ===")
# 存在性檢查擋不住跨庫重疊:實測同一個 idTreeItem 在兩個庫都存在,
# 指的卻是完全不同的測項。所以呼叫端必須聲明 ctx,由伺服器比對。
check("index 送出 row_ids 時帶 ctx", "ctx: S.ctx" in idx)
check("plans 送出 row_ids 時帶 ctx", "ctx: plan.ctx" in pl)
check("run 路由比對 ctx", "want_ctx != cur_ctx" in read("app.py"))

print("\n=== 5. 換頁不該中斷測試 ===")
for f in ("templates/index.html", "templates/plans.html"):
    src = read(f)
    check("%s 站內換頁不攔截" % os.path.basename(f), "leavingInternally" in src)
    check("%s 沒有殘留錯誤說法(會卡住)" % os.path.basename(f),
          "會讓 ACQUA 卡住" not in src)

print("=== 6. 路由送出的命令都註冊了嗎 ===")
# check_rows 曾經漏註冊 —— 症狀是「連正確的測項也被擋下」,而且錯誤訊息
# (未知的命令)看起來很像驗證生效,非常容易誤判成閘門正常。
wk = read("acqua/worker.py")
known = set(re.findall(r'^\s*"([a-z_]+)": lambda', wk, re.M))
used = set(re.findall(r'(?:worker\.submit|_cmd)\(\s*"([a-z_]+)"', read("app.py")))
unreg = sorted(used - known)
check("app.py 用到的命令都在 worker 命令表裡", not unreg,
      "未註冊:" + ", ".join(unreg))

# 兩個 backend 介面要一致,不然切到模擬模式就炸
mock = read("acqua/backend_mock.py")
com = read("acqua/backend_com.py")
need = [m for m in ("check_rows", "run_smds", "list_smds")
        if ("def %s(" % m) in com and ("def %s(" % m) not in mock]
check("mock 後端有實作同樣的介面", not need, "缺少:" + ", ".join(need))


print("\n" + ("結論:全部通過" if not fails
              else "結論:%d 項未通過 —— %s" % (len(fails), "、".join(fails))))
sys.exit(1 if fails else 0)
