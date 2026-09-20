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

- **起始**：2026-09-20，worker agy（`Gemini 3.8 Flash (High)`），1 回合 4 分 51 秒，prompt `C:/_work/AI_Work/Tools/agy-runs/agy-p6a-A2a.prompt.txt`，conversation `f288d9ed-00f0-40e1-96ca-8cd484a2e5ee`。
- **交付**：`domain/adventures/payloads.py`（12 個 kind 的 StrictModel、`kind` discriminator union、`parse_entry_payload`／`dump_entry_payload`、`AdventureEntryPayloadError` 包裝 pydantic 錯誤；`map` 無任何幾何欄位）；`schemas.py`（`AdventureDefinition`／`AdventureEntry` view、Create／Patch／Reorder input、5 個 domain error）；`persistence/adventures/repository.py`（`StoredAdventureDefinition`／`StoredAdventureEntry`、definition／entry CRUD、`set_status`、`next_sort_order`、`reorder_entries` 單 transaction、`UNSET` sentinel）；`service.py::AdventureService`（`_require_author` 每個方法含讀取都先過、`_definition_or_404`、`_writable_definition`、`_validate_parent` 含 cycle 檢查；無任何 `TableActorContext` 入口）；`tests/test_p6a_adventure_authoring.py` 10 個測試（含 12 kind × valid／invalid parametrize）。
- **指揮者審核修正**：
  - repository 在兩個 Stored dataclass 加了 `__post_init__` 把 SQLite 回傳的 naive datetime 硬轉 UTC——這是為了讓測試 9 拿 create() 的 aware 值和 DB 回讀的 naive 值比較而寫的 production workaround。刪除；測試改為前後都經 `get_definition`／`get_entry` 回讀再比較，並多斷言 status 仍為 finalized。
  - service 從 repository import 私有 `_UNSET` → 改為公開 `UNSET` 並列入 `__all__`。
  - `patch_entry` 內 `if payload.data is None: raise` 是 validator 已擋掉的死分支 → 收斂為 `if payload.data is not None`。
  - 移除 repository 未使用的 `timezone` import。
- **測試**：`pytest tests/test_p6a_adventure_authoring.py tests/test_p6a_room_assets.py tests/test_m03_import_boundary.py tests/test_code_quality_gate.py` 49 passed；全套 backend pytest 全綠（1 既有 skip）。
- **未解問題／下一步**：`KNOWN_ENTRY_KINDS` 與 `AdventureEntryKind` Literal 重複列舉 12 個 kind（可改由 Literal `__args__` 推導），留給 A2b 若碰同檔順手收；A2b。
