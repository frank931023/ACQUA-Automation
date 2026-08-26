# -*- coding: utf-8 -*-
"""自動校正的實機測試:序號位移時,能不能靠鄰居找回原本那一筆。

要防的是什麼
────────────
測項的序號是「依樹狀順序在同名組裡的第幾個」。有人在 ACQUA 裡插一筆、
刪一筆、或把組內兩筆對調,序號就整組位移 —— 而位移之後
(路徑, 名稱, 序號) 仍然全部對得上,只是對到別的測項。

鄰居簽章(前後各兩筆的 路徑+名稱)不會跟著位移,所以拿它在同名組裡
找回原本那一筆,自動校正,不必問人。

⚠️ 會暫時建立幾個名為 __SH 的計畫,跑完自動刪掉。
   需要伺服器在 127.0.0.1:5000 跑著,而且已經開好一個專案。

用法:  python tools/test_selfheal.py
"""
import copy
import io as _io
import json
import os
import sys
import urllib.request
import collections

ROOT = r"c:\Users\autom\OneDrive\Desktop\ACOPT18 ACQUA COM Interface\ACQUA Automation"
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

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
print("專案 %d 筆測項" % len(smds))
print("每一筆都有鄰居簽章:%s"
      % all(s.get("sig") for s in smds))

dup = collections.Counter((s.get("path"), s.get("title")) for s in smds)
key = [k for k, n in dup.items() if n > 1][0]
group = [s for s in smds if (s.get("path"), s.get("title")) == key]
print("\n同名組:%r × %d" % (key[1][:40], len(group)))
sigs = [s.get("sig") for s in group]
print("   鄰居簽章:%s" % sigs[:5])
print("   簽章互不相同:%s  ← 這是能校正的前提"
      % (len(set(sigs)) == len(sigs)))

base = [{"row_id": s["row_id"], "title": s["title"], "path": s["path"],
         "occ": s["occ"], "sig": s["sig"], "smd_type": s.get("smd_type")}
        for s in group]


def run(label, items, ctx_same=True):
    r = post("plans", {"title": "__SH", "items": items})
    pid = r["plan"]["id"]
    if not ctx_same:
        path = os.path.join(ROOT, "plans", pid + ".json")
        d = json.load(_io.open(path, encoding="utf-8"))
        d["source"]["ctx"] = "OTHER|OTHER|999"
        _io.open(path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(d, ensure_ascii=False, indent=2))
    res = (post("plans/%s/prepare" % pid, {}).get("resolution") or {})
    print("\n── %s" % label)
    print("   對應 %d ・ 自動校正 %d ・ 沒把握 %d ・ 無法分辨 %d"
          % (len(res.get("resolved") or []), len(res.get("corrected") or []),
             res.get("needs_review", 0), len(res.get("ambiguous") or [])))
    for c in (res.get("corrected") or [])[:4]:
        print("      校正:%s  序號 %s → %s  → #%s"
              % (c["title"][:26], c["from_occ"], c["to_occ"], c["row_id"]))
    urllib.request.urlopen(
        urllib.request.Request(B + "plans/" + pid, method="DELETE"),
        timeout=60).read()
    return res


want_ids = [s["row_id"] for s in group]

# ① 正常
r1 = run("① 序號正確(對照組)", base)
got1 = [x["row_id"] for x in r1["resolved"]]

# ② 序號整組位移 —— 模擬「前面插了一筆同名的」
shifted = copy.deepcopy(base)
for it in shifted:
    it["occ"] = it["occ"] + 1
    it["row_id"] = 999000 + it["occ"]      # 讓 row_id 失效,逼它走序號那條路
r2 = run("② 序號整組 +1(有鄰居簽章)", shifted)
got2 = [x["row_id"] for x in r2["resolved"]]

# ③ 同樣位移,但把鄰居簽章拿掉 —— 這是修正前的行為
noSig = copy.deepcopy(shifted)
for it in noSig:
    it.pop("sig", None)
r3 = run("③ 序號整組 +1(沒有鄰居簽章)", noSig)
got3 = [x["row_id"] for x in r3["resolved"]]

# ④ 組內順序對調 —— 指紋抓不到的那一種
swapped = copy.deepcopy(base)
swapped[0]["occ"], swapped[1]["occ"] = swapped[1]["occ"], swapped[0]["occ"]
for it in swapped:
    it["row_id"] = 999500 + it["occ"]
r4 = run("④ 組內順序對調(指紋抓不到的那種)", swapped)
got4 = [x["row_id"] for x in r4["resolved"]]

print("\n" + "=" * 62)
print("原本的 row_id      :%s" % want_ids)
print("① 正常             :%s" % got1)
print("② 位移+有簽章 校正後:%s  %s"
      % (got2, "✅ 找回原本那幾筆" if sorted(got2) == sorted(want_ids) else "❌"))
print("③ 位移+無簽章       :%s  %s"
      % (got3, "(對到別人 —— 這就是修正前的行為)"
         if sorted(got3) != sorted(want_ids) else "(碰巧一樣)"))
print("④ 順序對調 校正後   :%s  %s"
      % (got4, "✅ 各自對回自己" if sorted(got4) == sorted(want_ids) else "❌"))

ok = (sorted(got2) == sorted(want_ids)
      and len(r2.get("corrected") or []) > 0
      and sorted(got4) == sorted(want_ids))
print("\n結論:%s" % ("✅ 序號位移能自動校正,不必問人" if ok else "❌ 校正沒生效"))
sys.exit(0 if ok else 1)
