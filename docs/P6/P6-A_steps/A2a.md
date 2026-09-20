# A2a — Adventure domain：typed payloads、repository、service

## Scope

- `app/domain/adventures/payloads.py`：每個 known kind 一個 Pydantic typed payload（`section`、`scene`、`npc`、`item`、`monster_ref`、`quest`、`secret`、`dm_note`、`suggested_check`、`map`、`lore`），`other` 用受限 `dict[str, str | int | bool]`；`parse_entry_payload(kind, data_json)` 單一入口，unknown kind 拒絕。`suggested_check` 至少含 ability／skill／DC；`monster_ref` 含 `monster_template_ref`（純字串 reference，不 FK）；`map` 只表達 caption，**不含任何座標／grid**。
- `app/domain/adventures/schemas.py`：`AdventureDefinition`、`AdventureEntry`、`AdventureDefinitionCreate/Patch`、`AdventureEntryCreate/Patch` view／input model；`status` StrEnum `draft | finalized | archived`。
- `app/persistence/adventures/repository.py`：`AdventureRepository`：definition CRUD、entry CRUD（含 `sort_order` 重排、`parent_entry_id` 同 Adventure 檢查）、`list_entries(adventure_id)`。
- `app/domain/adventures/service.py`：`AdventureService`：create／get／list／patch definition、create／patch／delete／reorder entry；authority：`RoomAccessContext.authority in {OWNER, DM}` 才可讀寫，MEMBER 任何讀寫 → `AdventureForbiddenError`（route 對映 404，不洩漏存在）；cross-Room → `AdventureNotFoundError`；`archived` Adventure 拒絕 entry 寫入；finalized 仍可 authoring 修正。**沒有任何接受 `TableActorContext` 的方法**。
- `tests/test_p6a_adventure_authoring.py`：只 Name 建立；每個 known kind 建一筆合法 entry；每個 known kind 一筆 invalid payload 被拒；`other` 合法；parent 跨 Adventure 拒絕；member 讀 definition／entries（任何 visibility）皆拒；cross-Room 拒；archived 拒寫；finalized 可 patch name／entry body。

## 對應契約

實作規格 P6-A「Adventure entry 至少可表達…」「finalized Adventure 仍可…」「對 Human Player / AI Player 第一版完全不可直接讀」；設計 §A.2、「Shared authority ▸ Human」；測試 A.1。

## 前置

A1a 表。

## 驗收

- `pytest tests/test_p6a_adventure_authoring.py tests/test_code_quality_gate.py`（cwd `apps/server`）全綠。

## 紀錄

（派工後補）
