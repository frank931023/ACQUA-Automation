# -*- coding: utf-8 -*-
"""現在 labCORE 載入的是哪一組硬體設定?

為什麼需要這支
──────────────
COM API 給的是**狀態**(哪些接點通了、各區塊什麼參數),不給名字;
名字只存在 ACQUAlyzer5.XML 的 <labCoreSetting><Name> 裡。
所以「現在是哪一組」要用比對的:

    把 labCORE 目前作用中的接線抓出來
    跟 XML 裡 12 組設定各自的接線比
    完全吻合的那一組,就是現在載入的

沒有這個,就沒辦法回答「ACQUA 跑測項時會不會自己換硬體設定」——
因為看不出來有沒有換。

比對方式
────────
每條接線正規化成 frozenset{(block,pin), (block,pin)},再整組比。
用 set 是因為 Pin1/Pin2 哪個在前沒有意義,XML 跟 COM 的順序也不保證一致。

用法
────
    python tools/labcore_which_setup.py            印出最像的幾組
    python tools/labcore_which_setup.py --json     給程式用
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

import pythoncom
import win32com.client as w

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

XML = r"C:\ProgramData\HEAD acoustics\ACQUA\ACQUAlyzer5.XML"


def live_connections():
    """labCORE 上目前**作用中**的接線。"""
    c = w.Dispatch("MfeControlLib.LabCoreControl")
    dev = c.Items(0)
    conns = dev.AudioWiring.ActiveConnections
    out = set()
    for i in range(conns.Count):
        cn = conns.Items(i)
        try:
            if hasattr(cn, "Active") and not cn.Active:
                continue
        except Exception:                                   # noqa: BLE001
            pass
        try:
            p1, p2 = cn.Pin1, cn.Pin2
            out.add(frozenset(((p1.Block.ID, p1.ID), (p2.Block.ID, p2.ID))))
        except Exception:                                   # noqa: BLE001
            continue
    return out, dev


def stored_setups():
    """XML 裡存的每一組設定,連同它的接線。"""
    t = io.open(XML, encoding="utf-8", errors="replace").read()
    setups = {}
    for blk in re.findall(r"<labCoreSetting>(.*?)</labCoreSetting>", t, re.S):
        m = re.search(r"<Name>([^<]*)</Name>", blk)
        if not m:
            continue
        conns = set()
        for c in re.findall(r"<Connection>(.*?)</Connection>", blk, re.S):
            def pick(tag):
                mm = re.search(r"<%s>([^<]*)</%s>" % (tag, tag), c)
                return mm.group(1) if mm else ""
            b1, p1 = pick("Block1"), pick("Pin1")
            b2, p2 = pick("Block2"), pick("Pin2")
            if b1 and b2:
                conns.add(frozenset(((b1, p1), (b2, p2))))
        setups[m.group(1)] = conns
    default = re.search(
        r"<labCoreSettings>.*?<DefaultSetting>([^<]*)</DefaultSetting>", t, re.S)
    return setups, (default.group(1) if default else "")


def score(live, stored):
    """回 (吻合率, 相同數, 只在硬體上, 只在設定裡)。"""
    both = live & stored
    union = live | stored
    return (len(both) / len(union) if union else 0.0,
            len(both), len(live - stored), len(stored - live))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    pythoncom.CoInitialize()
    live, dev = live_connections()
    setups, default = stored_setups()

    # 排序準則:先看「硬體上有沒有出現設定裡沒有的接線」(only_hw)。
    # 實測發現 ActiveConnections 只列**作用中**的,而設定檔列的是全部,
    # 所以現況通常是設定的子集 —— 用完全相等去比會全部落空。
    # only_hw == 0 代表「硬體沒有多出東西」,那才是候選。
    ranked = sorted(((score(live, s), name) for name, s in setups.items()),
                    key=lambda x: (x[0][2], -x[0][1]))

    best_name = ranked[0][1] if ranked else None
    best_pct = ranked[0][0][0] if ranked else 0.0
    # 吻合率門檻:接線完全一樣才敢說「就是這組」。
    # 差一條就可能是使用者手動改過,不該硬套一個名字上去。
    # 「硬體沒有多出接線」且「至少對上幾條」= 現況相容於這組設定。
    # 注意這不保證唯一 —— 兩組設定可能都是現況的超集。
    exact = ranked and ranked[0][0][2] == 0 and ranked[0][0][1] > 0

    if args.json:
        print(json.dumps({
            "serial": str(dev.Device.SerialNumber),
            "live_connection_count": len(live),
            "best_match": best_name,
            "match_ratio": round(best_pct, 4),
            "exact": exact,
            "acqua_default": default,
            "ranking": [{"name": n, "ratio": round(s[0], 4), "same": s[1],
                         "only_hw": s[2], "only_cfg": s[3]}
                        for s, n in ranked[:5]],
        }, ensure_ascii=False, indent=2))
        return 0

    print("labCORE %s ・ 目前作用中的接線 %d 條\n"
          % (dev.Device.SerialNumber, len(live)))
    print("%-44s %7s %6s %7s %7s" % ("設定名稱", "吻合", "相同", "只在硬體", "只在設定"))
    print("-" * 76)
    for s, name in ranked:
        print("%-44s %6.1f%% %6d %7d %7d"
              % (name[:44], s[0] * 100, s[1], s[2], s[3]))
    print()
    if exact:
        cands = [n for s, n in ranked if s[2] == 0 and s[1] == ranked[0][0][1]]
        if len(cands) == 1:
            print("=> 目前載入的是:%s" % best_name)
        else:
            print("=> 現況相容於這幾組(接線分不出來):")
            for n in cands:
                print("     %s" % n)
    else:
        print("=> 沒有任何一組完全吻合(最接近 %s,%.1f%%)"
              % (best_name, best_pct * 100))
        print("   接線可能被手動改過,或這組設定沒存起來")
    print("   ACQUA 的預設設定 = %s" % (default or "(未設)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
