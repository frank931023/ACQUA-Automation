"""階段 1 工具:唯讀走訪 ACQUA 的 TypeLib,列出所有介面、方法與列舉數值。

⭐ 這是整個專案最先該跑的東西。目的:
   1. 取得 EMEResult 的實際數值(pass/fail 判定必需,CHM 沒有記載)
   2. 確認 ACQUA 6 有沒有 CHM(2012 年版)沒寫的新方法
   3. 找出有沒有可以「列舉全部 SMD」的方法

⚠️ 這個工具是**純唯讀**的:
   - 用 LoadRegTypeLib 直接讀型別資訊,不呼叫 CoCreateInstance
   - **不會啟動 ACQUA**
   - 不產生 gencache 快取檔(不會動到 Python 安裝目錄)

用法:
    python tools/dump_typelib.py                  # 全部
    python tools/dump_typelib.py --enums-only     # 只列列舉(找 EMEResult 用)
    python tools/dump_typelib.py --grep EMEResult # 只看符合的項目
"""
import argparse
import sys

TYPELIBS = [
    ("Acqua3",               "{1E189209-517B-46E7-AF7D-269A505ABD2F}"),
    ("HEADACQUAlyzer",       "{E7763016-A964-11D3-875C-00A024540BF1}"),
    ("ACQUAReportGenerator", "{82891022-D04B-4D90-BB9A-14F0A2118211}"),
    ("AcquaDBMask",          "{CF42356C-CABD-4875-9875-EA06D1BB80D6}"),
    ("HEADObjectDatabase",   "{0EB1EF39-35E7-4140-BBD5-D4BAFD852B86}"),
]

HIGHLIGHT = ("emeresult", "erst", "eur", "emeet", "esdm", "essm")


def _kind_name(pythoncom, kind):
    return {
        pythoncom.TKIND_ENUM: "ENUM",
        pythoncom.TKIND_RECORD: "RECORD",
        pythoncom.TKIND_MODULE: "MODULE",
        pythoncom.TKIND_INTERFACE: "INTERFACE",
        pythoncom.TKIND_DISPATCH: "DISPATCH",
        pythoncom.TKIND_COCLASS: "COCLASS",
        pythoncom.TKIND_ALIAS: "ALIAS",
        pythoncom.TKIND_UNION: "UNION",
    }.get(kind, f"KIND_{kind}")


def _invkind(pythoncom, k):
    return {
        pythoncom.INVOKE_FUNC: "method",
        pythoncom.INVOKE_PROPERTYGET: "get",
        pythoncom.INVOKE_PROPERTYPUT: "put",
        pythoncom.INVOKE_PROPERTYPUTREF: "putref",
    }.get(k, str(k))


def find_registered(pythoncom, guid):
    """在註冊表裡找出這個 TypeLib 已註冊的版本。"""
    from win32com.client import selecttlb
    hits = []
    for tlb in selecttlb.EnumTlbs():
        try:
            if str(tlb.clsid).lower() == guid.lower():
                hits.append((int(tlb.major), int(tlb.minor), tlb.desc))
        except Exception:                                   # noqa: BLE001
            continue
    return hits


def dump(pythoncom, name, guid, enums_only=False, grep=None):
    print("\n" + "=" * 78)
    print(f"  {name}    {guid}")
    print("=" * 78)

    versions = find_registered(pythoncom, guid)
    if not versions:
        print("  ✗ 註冊表中找不到這個 TypeLib(該元件可能未安裝)")
        return
    major, minor, desc = versions[0]
    print(f"  已註冊:v{major}.{minor}  「{desc}」")

    try:
        tlb = pythoncom.LoadRegTypeLib(pythoncom.MakeIID(guid), major, minor, 0)
    except Exception as exc:                                # noqa: BLE001
        print(f"  ✗ 載入失敗:{exc}")
        print("    若你用的是 64-bit Python,這通常是因為 TypeLib 只註冊了 win32 分支")
        print("    → 改用 32-bit Python")
        return

    count = tlb.GetTypeInfoCount()
    print(f"  型別數量:{count}\n")

    enums, others = [], []
    for i in range(count):
        try:
            ti = tlb.GetTypeInfo(i)
            attr = ti.GetTypeAttr()
            tname = tlb.GetDocumentation(i)[0]
            (enums if attr.typekind == pythoncom.TKIND_ENUM else others).append((tname, ti, attr))
        except Exception:                                   # noqa: BLE001
            continue

    # ── 列舉 ────────────────────────────────────────
    if enums:
        print("  ── 列舉常數 " + "─" * 55)
        for tname, ti, attr in sorted(enums, key=lambda x: x[0]):
            if grep and grep.lower() not in tname.lower():
                continue
            print(f"\n    ▸ enum {tname}")
            for v in range(attr.cVars):
                try:
                    vd = ti.GetVarDesc(v)
                    vname = ti.GetNames(vd.memid)[0]
                    star = " ⭐" if vname.lower().startswith(HIGHLIGHT) else ""
                    print(f"        {vname:<40} = {vd.value!r}{star}")
                except Exception:                           # noqa: BLE001
                    continue

    if enums_only:
        return

    # ── 介面 / CoClass ──────────────────────────────
    print("\n  ── 介面 / CoClass " + "─" * 49)
    for tname, ti, attr in sorted(others, key=lambda x: x[0]):
        if grep and grep.lower() not in tname.lower():
            continue
        kind = _kind_name(pythoncom, attr.typekind)
        print(f"\n    ▸ {kind} {tname}   (funcs={attr.cFuncs}, vars={attr.cVars})")
        for f in range(attr.cFuncs):
            try:
                fd = ti.GetFuncDesc(f)
                names = ti.GetNames(fd.memid)
                fname = names[0]
                params = ", ".join(names[1:]) if len(names) > 1 else ""
                tag = _invkind(pythoncom, fd.invkind)
                print(f"        [{tag:<6}] {fname}({params})")
            except Exception:                               # noqa: BLE001
                continue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--enums-only", action="store_true")
    ap.add_argument("--grep", help="只顯示名稱含此字串的型別")
    args = ap.parse_args()

    try:
        import struct
        import pythoncom
    except ImportError:
        print("✗ 找不到 pywin32。請執行:pip install pywin32")
        return 1

    bits = struct.calcsize("P") * 8
    print(f"Python {sys.version.split()[0]}  ({bits}-bit)")
    if bits != 32:
        print("⚠️ ACQUA 的 TypeLib 只註冊了 win32 分支,64-bit 很可能載入失敗。")

    for name, guid in TYPELIBS:
        try:
            dump(pythoncom, name, guid, args.enums_only, args.grep)
        except Exception as exc:                            # noqa: BLE001
            print(f"  ✗ {name} dump 失敗:{exc}")

    print("\n" + "=" * 78)
    print("下一步:把 ⭐ 標記的數值抄進 acqua/constants.py")
    print("       最重要的是 emeresultMeasDoneOk 與 emeresultMeasDoneNotOk")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
