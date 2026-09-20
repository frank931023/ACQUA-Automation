# -*- coding: utf-8 -*-
"""把一個 COM 伺服器的型別庫整個倒出來(唯讀,不實體化物件)。

為什麼需要這支
──────────────
`Acqua3COM.chm` 只涵蓋 `Acqua3.*` 那 137 個主題,裡面沒有任何硬體 API。
但註冊表顯示 HEAD 還裝了一整組**沒有文件**的 COM 類別:

    MfeControlLib.LabCoreControl        -> MfeControl.exe
    MfeControlLib.MfeControl
    MfeControlLib.LabCoreVirtualConnections
    HEADMfeController.Application       -> HEADMfeController.exe
    HEADRemoteControl.Application       -> HEADRemoteControl.dll

要知道這些能不能設麥克風供電/極化電壓,就得看型別庫。

**刻意不呼叫 Dispatch()**:那會實體化真的硬體控制物件。
LoadTypeLib 只讀 PE 裡的 TypeLib 資源,不碰硬體、不碰執行中的行程。

用法
────
    python tools/dump_typelib.py "C:/.../MfeControl.exe"
    python tools/dump_typelib.py "C:/.../MfeControl.exe" --grep volt
"""
from __future__ import annotations

import argparse
import sys

import pythoncom

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# TYPEKIND
KIND = {0: "enum", 1: "record", 2: "module", 3: "interface",
        4: "dispatch", 5: "coclass", 6: "alias", 7: "union"}

# INVOKEKIND
INVOKE = {1: "method", 2: "get", 4: "put", 8: "putref"}

# VARTYPE —— 只列常見的,其餘直接印數字
VT = {0: "void", 2: "i2", 3: "i4", 4: "r4", 5: "r8", 7: "date", 8: "BSTR",
      9: "IDispatch", 11: "BOOL", 12: "VARIANT", 13: "IUnknown", 16: "i1",
      17: "ui1", 18: "ui2", 19: "ui4", 22: "int", 23: "uint", 24: "void",
      26: "ptr", 27: "safearray", 28: "carray", 29: "userdefined"}


def tname(tdesc, ta):
    """把 TYPEDESC 翻成看得懂的字。巢狀指標要往下追。"""
    vt = tdesc[1] if isinstance(tdesc, tuple) else tdesc
    if isinstance(tdesc, tuple):
        inner = tdesc[0]
        if vt == pythoncom.VT_PTR:
            return tname(inner, ta) + "*"
        if vt == pythoncom.VT_SAFEARRAY:
            return "array<%s>" % tname(inner, ta)
        if vt == pythoncom.VT_USERDEFINED:
            try:
                return ta.GetRefTypeInfo(inner).GetDocumentation(-1)[0]
            except Exception:                               # noqa: BLE001
                return "userdefined"
    return VT.get(vt, "vt%s" % (vt,))


def dump(path, grep=None):
    tlb = pythoncom.LoadTypeLib(path)
    n = tlb.GetTypeInfoCount()
    print("型別庫:%s" % path)
    print("  %s" % (tlb.GetDocumentation(-1)[0],))
    print("  %d 個型別\n" % n)

    needle = grep.lower() if grep else None
    shown = 0

    for i in range(n):
        ta = tlb.GetTypeInfo(i)
        attr = ta.GetTypeAttr()
        kind = KIND.get(attr.typekind, attr.typekind)
        name = tlb.GetDocumentation(i)[0]

        members = []
        # 列舉:把常數列出來 —— 電壓選項很可能就藏在這
        if attr.typekind == pythoncom.TKIND_ENUM:
            for v in range(attr.cVars):
                vd = ta.GetVarDesc(v)
                vname = ta.GetNames(vd.memid)[0]
                members.append("%-46s = %s" % (vname, vd.value))
        else:
            for f in range(attr.cFuncs):
                fd = ta.GetFuncDesc(f)
                names = ta.GetNames(fd.memid)
                fname = names[0]
                args = ", ".join(
                    "%s %s" % (tname(a[0], ta), (names[k + 1] if k + 1 < len(names) else "p%d" % k))
                    for k, a in enumerate(fd.args))
                members.append("%-8s %s(%s) -> %s" % (
                    INVOKE.get(fd.invkind, fd.invkind), fname, args,
                    tname(fd.rettype, ta)))

        if needle:
            members = [m for m in members if needle in m.lower()]
            if not (needle in name.lower() or members):
                continue

        shown += 1
        print("=== [%s] %s  (%d 個成員) ===" % (kind, name, len(members)))
        for m in members:
            print("   " + m)
        print()

    print("顯示 %d / %d 個型別" % (shown, n))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="含 TypeLib 的 .exe / .dll / .tlb")
    ap.add_argument("--grep", default=None, help="只顯示含這個字的成員")
    args = ap.parse_args()
    try:
        dump(args.path, args.grep)
    except pythoncom.com_error as exc:
        print("讀不到型別庫:%s" % (exc,))
        print("（可能是這支沒有內嵌 TypeLib,或位元數不合）")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
