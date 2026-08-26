# -*- coding: utf-8 -*-
"""測項還原的交叉驗證 —— 六種情境的實機測試。

要防的是什麼
────────────
測項的身分鍵是 (路徑, 名稱, 序號)。序號依樹狀順序算,樹一改就整組位移 ——
而位移之後那三個欄位**仍然對得上**,只是對到別的測項。沒有任何欄位會
「不匹配」,所以不會有人發現。這是唯一會靜靜跑錯的情況。

三種獨立證據互相佐證:row_id(同專案才有意義)、結構指紋(樹動過沒有)、
型別。任何一項對不上都要浮出來。

⚠️ 這支會在資料庫裡暫時建立幾個名為 __FPT 的計畫,跑完自動刪掉。
   需要伺服器在 127.0.0.1:5000 上跑著,而且已經開好一個專案。

用法:  python tools/test_resolve.py
"""
import copy
import io as _io
import json
import os
import sys
import urllib.request

ROOT = r"c:\Users\autom\OneDrive\Desktop\ACOPT18 ACQUA COM Interface\ACQUA Automation"
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")
from acqua.sqlcat import fingerprint_of                      # noqa: E402

B = "http://127.0.0.1:5000/acqua/api/"


def get(p, t=180):
    return json.loads(urllib.request.urlopen(B + p, timeout=t).read().decode())


def post(p, b=None, t=400):
    r = urllib.request.Request(B + p, data=json.dumps(b or {}).encode(),
                               headers={"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(r, timeout=t).read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False}


post("connect", {})
post("refresh-groups", {})
post("restore", {})
smds = get("status").get("smds") or []
fp = fingerprint_of(smds)
print("專案 %d 筆測項 ・ 指紋 %s\n" % (len(smds), fp))

import collections                                           # noqa: E402
dup = collections.Counter((s.get("path"), s.get("title")) for s in smds)
key = [k for k, n in dup.items() if n > 1][0]
group = [s for s in smds if (s.get("path"), s.get("title")) == key]
base = [{"row_id": s["row_id"], "title": s["title"], "path": s["path"],
         "occ": s["occ"], "smd_type": s.get("smd_type")} for s in group]
print("測試用的同名組:%r × %d\n" % (key[1][:40], len(base)))


def run(label, items, fingerprint, ctx_same):
    r = post("plans", {"title": "__FPT", "items": items})
    pid = r["plan"]["id"]
    path = os.path.join(ROOT, "plans", pid + ".json")
    d = json.load(_io.open(path, encoding="utf-8"))
    d["source"]["tree_fingerprint"] = fingerprint
    if not ctx_same:
        d["source"]["ctx"] = "OTHER|OTHER|999"
    _io.open(path, "w", encoding="utf-8", newline="\n").write(
        json.dumps(d, ensure_ascii=False, indent=2))

    res = (post("plans/%s/prepare" % pid, {}).get("resolution") or {})
    ways = collections.Counter(x.get("matched_by", "") for x in (res.get("resolved") or []))
    print("── %s" % label)
    print("   對應 %d ・ 沒把握 %d ・ 衝突 %d ・ 樹變動=%s"
          % (len(res.get("resolved") or []), res.get("needs_review", 0),
             len(res.get("conflicts") or []), res.get("tree_changed")))
    for w, n in ways.most_common(3):
        print("      %-44s x%d" % (w[:44], n))
    for c in (res.get("conflicts") or [])[:2]:
        print("      衝突:%s" % c.get("why", "")[:66])
    urllib.request.urlopen(
        urllib.request.Request(B + "plans/" + pid, method="DELETE"), timeout=60).read()
    print()
    return res


ok = []

# ① 一切正常 —— row_id 直接對上
r = run("① 同專案 ・ 指紋相符(正常)", base, fp, True)
ok.append(("①", len(r["resolved"]) == len(base) and r["needs_review"] == 0
           and r["tree_changed"] is False))

# ② 同專案但測項被刪過(row_id 不在了)+ 樹也變了 → 最危險,必須標沒把握
gone = copy.deepcopy(base)
for it in gone:
    it["row_id"] = 999000 + it["occ"]          # 這些 id 不存在
r = run("② 同專案 ・ row_id 不在了 + 指紋不符(最危險)", gone,
        "deadbeef00000000:9999", True)
ok.append(("②", len(r["resolved"]) == len(base)
           and r["needs_review"] == len(base) and r["tree_changed"] is True))

# ③ 同專案 ・ row_id 不在了但樹沒變 → 仍該提高警覺
r = run("③ 同專案 ・ row_id 不在了 + 指紋相符", gone, fp, True)
ok.append(("③", r["needs_review"] == len(base) and r["tree_changed"] is False))

# ④ 跨專案 → 指紋不適用,不該亂警告
r = run("④ 跨專案(指紋不適用)", base, "deadbeef00000000:9999", False)
ok.append(("④", len(r["resolved"]) == len(base) and r["tree_changed"] is None))

# ⑤ 型別造假 → 獨立佐證,判衝突
bad = copy.deepcopy(base)
for it in bad:
    it["smd_type"] = 999
r = run("⑤ 型別對不上", bad, fp, True)
ok.append(("⑤", len(r["conflicts"]) == len(base)))

# ⑥ row_id 指到別的測項 → 判衝突
bad2 = copy.deepcopy(base)
other = next(s for s in smds if (s.get("path"), s.get("title")) != key)
bad2[0]["row_id"] = other["row_id"]
r = run("⑥ 同專案但 row_id 指到別人", bad2, fp, True)
ok.append(("⑥", len(r["conflicts"]) >= 1))

print("=" * 62)
for name, good in ok:
    print("   %s %s" % (name, "OK" if good else "!! 判錯"))
print("\n結論:%s" % ("✅ 六種情境全部判對" if all(g for _, g in ok) else "❌ 有情境判錯"))
sys.exit(0 if all(g for _, g in ok) else 1)
