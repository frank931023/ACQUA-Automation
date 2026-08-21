# -*- coding: utf-8 -*-
"""「現在在哪個資料庫的哪個專案」—— 所有衍生資料的歸屬。

為什麼要有這個檔
────────────────
2026-08-21 踩到:使用者在網頁上換了資料庫,但 SQL 目錄還連在舊那顆,
於是「載入測項」載回舊庫的 309 筆 MS Teams,而 ACQUA 其實開著 ZoomRooms
的 1477 筆。兩個庫的 idTreeItem 各自從小編號開始、必然重疊,所以那些
row_id 送進 StartSingleMeasurement 不會報錯 —— 只會安靜地跑到別的測項。

當下的修法是把 _catalog() 補上重連。但那只堵住一個呼叫點。真正的問題是
「哪些東西屬於哪個專案」從來沒有被寫下來過,所以每多一個狀態欄位,
就多一個可能忘記清的地方 —— 而且症狀都一樣:安靜地用錯資料。

所以這裡把規則寫成程式:

  CONTEXT_KEY        目前上下文的字串表示 (server | database | idProject)
  PROJECT_SCOPED     換專案就必須作廢的欄位
  DATABASE_SCOPED    換資料庫就必須作廢的欄位(含上面全部)
  UNSCOPED           明確宣告「不屬於任何上下文」的欄位
  check_coverage()   state 的欄位若兩邊都沒列到就報錯 —— 新增欄位時會被抓出來

最後一道閘在 backend_com.run_smds():開跑前驗證每個 row_id 都屬於當前
專案。就算上面每一層都漏了,那道閘會擋下來。
"""
from __future__ import annotations


#: 換「專案」就作廢 —— 這些東西的意義完全繫於某一個 idProject。
PROJECT_SCOPED = (
    "measurement_object",   # MO 掛在專案底下
    "smds",                 # row_id 只在該專案有意義
    "results",              # 用 row_id 當索引
    "variables",            # 條件執行變數,隨專案
    "prediction",           # 依變數算出的「會跑哪些」
    "values",               # 依 row_id 讀回的數值
    "wizard_groups",        # 從該專案的 ConditionalExecution 反推
    "current",              # 正在跑的那一筆
)

#: 換「資料庫」就作廢 —— 專案清單本身也換了一批。
DATABASE_SCOPED = PROJECT_SCOPED + (
    "project_groups",
    "open_group",
    "open_project",
)

#: 明確宣告不屬於上下文的欄位。列在這裡 = 「我想過了,它跨專案有效」。
UNSCOPED = frozenset({
    # 連線層
    "backend", "backend_kind", "acqua_ready", "connected", "server", "database",
    "databases",            # 屬於 server,不屬於某個 database
    # 執行層
    "running", "cancel_requested", "paused", "progress", "run_mode",
    "blocking_window",
    # ACQUA 全域設定(實測:硬體設定是跨專案共用的)
    "hardware_settings", "hardware_active",
    # 來自 config.json,不是從資料庫算的
    "wizard_scopes",
    # 純衍生 / 傳輸用
    "summary", "seq", "ctx",
})

#: 作廢時要塞回去的值。沒列到的一律設 None。
_EMPTY = {
    "smds": list, "results": list, "variables": list, "values": list,
    "wizard_groups": list, "project_groups": list,
}


def context_key(server, database, project_id) -> str:
    """(server, database, idProject) 的字串表示。

    前端拿它當快取的 key —— 值一變就把勾選、結果對照表、精靈選項全丟掉。
    用字串而不是 tuple 是為了能直接放進 JSON。
    """
    return "{0}|{1}|{2}".format(server or "", database or "",
                                "" if project_id is None else int(project_id))


def clear_values(fields) -> dict:
    """把一組欄位變成「作廢後該有的值」,可直接餵給 state.set()。"""
    return {f: (_EMPTY[f]() if f in _EMPTY else None) for f in fields}


def check_coverage(snapshot_keys) -> list:
    """快照裡有沒有欄位是兩邊都沒歸類的。回傳漏掉的名單(空 = 通過)。

    新增狀態欄位時如果忘了決定它屬不屬於某個專案,這裡會叫出來 ——
    這正是先前那個 bug 的成因:欄位一個個加,清除清單沒跟著長。
    """
    known = set(DATABASE_SCOPED) | UNSCOPED
    return sorted(k for k in snapshot_keys if k not in known)
