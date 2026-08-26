"""ConditionalExecution 評估器 —— 在不啟動量測的前提下,預測「這組變數會跑哪些測項」。

## 為什麼需要這個

MS Teams 那套有 4,304 個測項,其中 754 個節點帶條件式。實際要跑哪些,
是 ACQUA 在**執行時**依變數算出來的 —— 資料庫裡沒有存結果:

- `TreeItems.StateIconKey` 全部是 -1,不反映啟用/停用
- `acqua.Variables` 是空表(變數只存在 %TEMP%/AcquaTmp/UsedVars.ini)

所以要「先看看會跑幾項」只能自己算。這個模組就是做這件事。

## 條件式長什麼樣(SP2 實測)

```xml
<ConditionalExecution>
  <Conditions>
    <Condition><Variable>DUT_premium_reqs</Variable><Relation>7</Relation><Value/></Condition>
  </Conditions>
  <MatchConditions>0</MatchConditions>
  <Action>1</Action>
  <Disabled>false</Disabled>
  <RepeatIfNotOK>false</RepeatIfNotOK>
  <NumberOfRepetitions>1</NumberOfRepetitions>
</ConditionalExecution>
```

## 語意(依 SP2 的 754 個實例推導)

| Relation | 意義 | 證據 |
|---|---|---|
| 0 | 等於 | `DUT_speakerphone_type == 'Personal'`(134 次) |
| 1 | 不等於 | `DUT_connection_type != 'USB'`(2 次) |
| 6 | 為假 / 沒設定 | `DUT_is_ANC` 空值,與 7 成對出現 |
| 7 | 為真 | `DUT_premium_reqs`(348 次,全部空值) |
| 2 | 大於等於 | 見下方「數值比較的推導」 |
| 3 | 小於等於 | 同上 |
| 4 | 小於 | 同上 |
| 5 | 大於 | 未見實例,由 (2,3)/(4,5) 的成對關係推得 |

⚠️ **以下兩點是推論,尚未經 ACQUA 驗證:**
  - `Action`: **1 = 條件成立就跳過**;0 = 條件成立才跑
  - `MatchConditions`: 0 = 全部條件都要成立(AND);1 = 任一成立(OR)

✅ 校準結果(2026-08-20,MS Teams SP2 Speakerphone)
─────────────────────────────────────────────────
先試過拿 `OnBeginMeasurements.NbrOfMeasurements` 當對照 —— **那條路不通**:

    0 個變數 → 1151    設了變數 → 1151    專案 SMD 總數 → 1151

那個數字就是測項總數,不隨變數變。ConditionalExecution 的篩選發生在
**執行過程中**(跑到才跳過),開跑前不會先算。

改用測項庫自己的命名規律當標準答案就分辨出來了 ——
設 `DUT_speakerphone_type=Personal` 時,標題含 "Personal" 的應該跑、
含 "Shared" 的應該跳過(31 + 38 筆樣本):

    Action 1=跑   ・ Match 0=AND  →   6%    ← 原本的寫法
    Action 1=跑   ・ Match 0=OR   →  36%
    Action 1=跳過 ・ Match 0=AND  →  97%    ← 正確
    Action 1=跳過 ・ Match 0=OR   →  64%

單筆佐證(樹狀順序第 39 筆 `Prep: Receive path - output level - Personal`):

    條件 DUT_speakerphone_type == "Shared" ・ Action=1
    設 Personal 時條件不成立,而這是 Personal 專用的測項 —— 它必須要跑。
    ⟹ Action=1 只能解釋成「條件成立就跳過」。

剩下的 3%(31 筆 Personal 裡有 2 筆判為跳過)是因為那些項目還帶了
其他條件(例如要求某個距離變數為真),不是語意判斷錯。

wizard 設的 `DUT_*` 變數只用到 Relation 0/1/6/7,那幾個是有把握的。

✅ 數值比較的推導(2026-08-25,兩個資料庫共 754 筆條件式、90 個數值實例)
──────────────────────────────────────────────────────────────
沒有文件也沒有 TypeLib 列舉,只能從實際資料反推。關鍵是三個互相制約的案例:

**① 同一個測項上,同一個變數用了兩種 Relation**

    #2424 Noise level (100Hz-19kHz) during ultrasound - MaxVol
        Lvl_CodedUS_MAX  REL2  70
        Lvl_CodedUS_MAX  REL4  55
        MatchConditions=1 (OR) ・ Action=1 (成立就跳過)

    ⟹ 跑的條件是 ¬(x REL2 70) ∧ ¬(x REL4 55)

**② 同一個變數在另一個測項單獨出現**

    #2429 Volume Control Mode for Ultrasound Level Determination
        Lvl_CodedUS_MAX  REL4  70
        MatchConditions=0 ・ Action=1

    ⟹ 跑的條件是 ¬(x REL4 70)

把 (REL2, REL4) 代入試:

    (≥, <)  → ① 跑 55 ≤ x < 70   ② 跑 x ≥ 70   兩者互補且不重疊 ✅
    (>, ≥)  → ① 跑 x < 55        ② 跑 x < 70   互相包含,而且 ① 的 70 變成廢條件 ✗
    (<, >)  → ① 永遠不跑                                              ✗

只有 (≥, <) 讓兩個測項構成一個乾淨的分段 —— 這是人為編寫測試計畫時會有的樣子。

**③ REL3 只有一種讀法說得通**

    #152 P16A Receive path - Single Frequency PEAK 24dB20uPa
        RCV_SFI_VIOL  REL3  0  ・ Action=1

    RCV_SFI_VIOL 是「單頻干擾違規數」,這個測項是「有違規才要做的追加量測」。

    REL3 = ≤  → 違規數 ≤ 0 就跳過,也就是**有違規才跑** ✅
    REL3 = <  → 違規數 < 0 就跳過;計數不可能為負,等於這條件從來不生效 ✗

    一個永遠不生效的條件不會有人寫進 754 筆資料裡 48 次。

於是 (2,3) = (≥,≤)、(4,5) = (<,>),成對關係也一致。

⚠️ 這仍是推論而非文件確認。但要推翻它,得同時解釋為什麼 ① 的兩個測項不互補、
   以及為什麼有人寫了 48 次不會生效的條件。

實務上影響很小:這些變數(`Lvl_CodedUS_MAX`、`RCV_SFI_VIOL`)都是**量測過程
產生的**,開跑前根本還不存在,所以事前預測時一律走「變數未設定」那條路。
"""
import re

# Relation 代碼
REL_EQ = "0"
REL_NE = "1"
REL_IS_FALSE = "6"
REL_IS_TRUE = "7"
REL_GE = "2"        # >=
REL_LE = "3"        # <=
REL_LT = "4"        # <
REL_GT = "5"        # >  (未見實例)

#: 數值比較。語意見模組說明的「數值比較的推導」。
_NUMERIC = {
    REL_GE: lambda a, b: a >= b,
    REL_LE: lambda a, b: a <= b,
    REL_LT: lambda a, b: a < b,
    REL_GT: lambda a, b: a > b,
}


def _as_number(v):
    """轉成數字。轉不動回 None —— 呼叫端得自己決定怎麼辦。"""
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None

_RE_COND = re.compile(r"<Condition>(.*?)</Condition>", re.S)
_RE_VAR = re.compile(r"<Variable>(.*?)</Variable>", re.S)
_RE_REL = re.compile(r"<Relation>(.*?)</Relation>", re.S)
_RE_VAL = re.compile(r"<Value>(.*?)</Value>", re.S)
_RE_ACT = re.compile(r"<Action>(.*?)</Action>", re.S)
_RE_MATCH = re.compile(r"<MatchConditions>(.*?)</MatchConditions>", re.S)
_RE_DIS = re.compile(r"<Disabled>(.*?)</Disabled>", re.S)


def _truthy(v):
    """ACQUA 變數的「為真」判定。INI 存的是字串,所以要寬鬆一點。"""
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s not in ("", "0", "false", "no", "off")


def parse(xml: str) -> dict:
    """把 ConditionalExecution XML 拆成好處理的結構。無條件式回傳 None。"""
    if not xml or "<Condition>" not in xml:
        return None
    conds = []
    for c in _RE_COND.findall(xml):
        v = _RE_VAR.search(c)
        r = _RE_REL.search(c)
        val = _RE_VAL.search(c)
        if not v:
            continue
        conds.append({
            "var": v.group(1).strip(),
            "rel": (r.group(1).strip() if r else ""),
            "val": (val.group(1).strip() if val else ""),
        })
    if not conds:
        return None
    a = _ACT = _RE_ACT.search(xml)
    m = _RE_MATCH.search(xml)
    d = _RE_DIS.search(xml)
    return {
        "conditions": conds,
        "action": (a.group(1).strip() if a else "1"),
        "match": (m.group(1).strip() if m else "0"),
        "disabled": (d.group(1).strip().lower() == "true") if d else False,
    }


def eval_condition(cond: dict, variables: dict):
    """回傳 (成立與否, 是否有把握)。變數沒設定時視為「未定義」。"""
    var, rel, val = cond["var"], cond["rel"], cond["val"]
    present = var in variables
    cur = variables.get(var)

    if rel == REL_IS_TRUE:
        return (present and _truthy(cur)), True
    if rel == REL_IS_FALSE:
        return (not present) or (not _truthy(cur)), True
    if rel == REL_EQ:
        return (present and str(cur).strip() == val), True
    if rel == REL_NE:
        return (not present) or (str(cur).strip() != val), True

    op = _NUMERIC.get(rel)
    if op is not None:
        # 這些變數是量測過程產生的,開跑前通常還不存在。
        # 值不存在或不是數字時不硬猜 —— 回「成立且沒把握」,
        # 讓上層知道這一筆的判定不可靠(寧可高估要跑的,也不要漏掉)。
        a, b = _as_number(cur), _as_number(val)
        if not present or a is None or b is None:
            return True, False
        return op(a, b), True

    return True, False      # 沒看過的 Relation,同樣不硬猜


def eval_node(xml: str, variables: dict):
    """回傳 (是否啟用, 是否有把握, 說明)。沒有條件式 → 永遠啟用。"""
    spec = parse(xml)
    if spec is None:
        return True, True, ""
    if spec["disabled"]:
        return False, True, "節點本身被停用"

    results, sure = [], True
    for c in spec["conditions"]:
        ok, confident = eval_condition(c, variables)
        results.append(ok)
        sure = sure and confident

    # ✅ 已驗證(2026-08-20):MatchConditions 0 = AND,1 = OR
    matched = all(results) if spec["match"] == "0" else any(results)
    # ✅ 已驗證(2026-08-20):**Action 1 = 條件成立就「跳過」**,0 = 成立才跑
    #    (原本寫反了,正確率只有 6%;改正後 97%)
    enabled = (not matched) if spec["action"] == "1" else matched

    desc = " %s " % ("AND" if spec["match"] == "0" else "OR")
    why = desc.join(
        "%s %s %s" % (c["var"],
                      {"0": "==", "1": "!=", "2": ">=", "3": "<=", "4": "<",
                       "5": ">", "6": "is false", "7": "is true"}.get(
                          c["rel"], "rel" + c["rel"]),
                      c["val"] or "")
        for c in spec["conditions"])
    why += "  ->  %s" % ("啟用" if enabled else "略過")
    return enabled, sure, why


def predict(tree_rows: list, variables: dict) -> dict:
    """對整棵樹做預測。

    tree_rows 需要有:idTreeItem, Title, ItemType, LeftNode, RightNode,
                     ConditionalExecution

    ⭐ 會處理**繼承**:MMD 被停用時,底下所有 SMD 一併停用
       —— 這點很重要,MMD 層級的條件會一次關掉整組測項。

    回傳 {"will_run": [...], "skipped": [...], "uncertain": [...],
          "total_smds": int}
    """
    rows = sorted(tree_rows, key=lambda r: r["LeftNode"])
    verdict = {}          # idTreeItem -> (enabled, sure, why)
    for r in rows:
        verdict[r["idTreeItem"]] = eval_node(r.get("ConditionalExecution"), variables)

    mmds = [r for r in rows if r["ItemType"] == "IType_MMD"]
    will_run, skipped, uncertain = [], [], []

    for r in rows:
        if r["ItemType"] != "IType_SMD":
            continue
        own_ok, own_sure, own_why = verdict[r["idTreeItem"]]
        enabled, sure, why = own_ok, own_sure, own_why

        # 祖先只要有一個被關掉,自己就跑不了
        if enabled:
            for m in mmds:
                if m["LeftNode"] < r["LeftNode"] and m["RightNode"] > r["RightNode"]:
                    mok, msure, mwhy = verdict[m["idTreeItem"]]
                    sure = sure and msure
                    if not mok:
                        enabled = False
                        why = "上層 MMD「%s」被關閉:%s" % (
                            (m.get("Title") or "").strip(), mwhy)
                        break

        item = {
            "row_id": int(r["idTreeItem"]),
            "title": (r.get("Title") or "").strip(),
            "why": why,
            "sure": sure,
        }
        (will_run if enabled else skipped).append(item)
        if not sure:
            uncertain.append(item)

    return {
        "will_run": will_run,
        "skipped": skipped,
        "uncertain": uncertain,
        "total_smds": len(will_run) + len(skipped),
    }
