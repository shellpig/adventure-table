# F2b — Import Finalize transaction、blocking gate 與 idempotency

## Scope

- 完成原 F2 的 `AdventureImportService.finalize_adventure(context, room_id, import_id, *, name, summary=None, expected_revision) -> AdventureDefinition`。在同一 transaction 內讀同 Room import、拒絕 cancelled；若 `target_adventure_id` 已設，直接回同一 Adventure，不改 revision、不重建。
- 對新 finalize 驗 `expected_revision`；未解 blocking warning 拒絕。兩種拒絕均零副作用。
- F1 的 `DraftEntry` 尚無 `title`／`body`／`visibility`；本步須以 v1 相容的 optional/default 欄位補齊並明確映射，不能假稱 draft 已有這些欄位。透過 F2a 的既有 Adventure authoring public API，在同一 transaction 建 draft Definition、非 ignored entries（pending 也建）、parent UUID 對應、draft 順序的 `sort_order`、`asset_ids` links，再 finalize Definition；最後 revision-guarded 設 Import `finalized`＋`target_adventure_id`。`source_ref` 只保留 Draft 稽核，不當作 entry asset。
- 任一步失敗整筆 rollback；不複製 P6-A authoring 邏輯。不做 F3 route、F4 MCP、F5 UI。

## 契約與輸入

- `docs/P6/實作規格.md`「P6-F」、`開發設計方針.md`「P6-F／Finalize transaction」、`測試指南.md`「P6-F／F.1、F.3、F.4」。前置 F1＋F2a。
- 核對 F2a 的實際 transaction-aware API、`AdventureImportService`／repository revision guard 與 P6-A payload／asset link schema。此步才修改 Import Service 建構、production DI 與既有測試 fixture。

## 驗收

- `tests/test_p6f_finalize.py`：entry 的 parent／sort_order／payload／visibility、ignored 排除、asset links、status／target 指向；double submit／retry（含不同 expected revision）不重複；blocking 拒絕及解決後成功；pending 可 finalize；中途非法 asset／entry 建立失敗整筆 rollback；MEMBER／跨 Room／cancelled 拒絕零副作用。
- 受影響 P6-A／P6-E／F1 regression 與 code quality gate 通過。

## 完成紀錄

- **起始與 worker**：2026-09-23，agy（Gemini 3.8 Flash High），1 回合，CLI 回報約 990 秒。
- **指揮者派工決策**（契約未明定，派工時定案）：`DraftEntry.visibility` 預設 `dm_only`（匯入內文是 DM 資料）；`expected_revision` 指 draft revision，與 F1 review intent 同義；被 Ignore 的 parent 由最近的未 Ignore 祖先接手，沒有則為 root；`asset_ids` 一律以 role `attachment` 連結（`image` role 要求圖片型 asset，draft 未記錄類型）；Import row 以 revision compare-and-set 設 `finalized`＋`target_adventure_id`，併發的第二筆整筆 rollback。
- **交付**：`DraftEntry` 新增 v1 相容的 `title`／`body`／`visibility`；`AdventureImportBlockingWarningsError`（繼承 `AdventureImportValidationError`，帶 `unresolved_warning_ids`）；`AdventureImportService.__init__` 新增 `adventure_service`，production DI 改用 `get_adventure_service(request)`；`finalize_adventure(context, room_id, import_id, *, name, summary=None, expected_revision) -> AdventureDefinition`；抽出 `_load_draft_state` 供 `_apply_draft_mutation` 與 finalize 共用 revision 檢查。四個既有 Import 測試 fixture 改接真 `AdventureService`。新增 `tests/test_p6f_finalize.py`（10 個 test function、12 cases）。
- **指揮者審核修正**：移除 agy 逐字抄進程式碼的 prompt 步驟註解；draft parent 形成循環時，原本的 fallback 會默默把循環成員改掛 root，改為 `AdventureImportValidationError` 並整筆 rollback（新增 `test_finalize_parent_cycle_rejected_and_rolled_back`）；建立順序改為單一 BFS，已知 key 改用索引存取；`_load_draft_state` 移除沒人用的 revision 回傳值；測試抽 `_import_with_draft`／`_section`／`_assert_no_adventure_rows`，刪除 `.rowcount` 死變數與未使用的 `Generator` import，invalid-asset rollback 改為第一個 entry 已建立後才失敗。
- **觀察（未修）**：已 finalize 的 retry 以 `AdventureService.get_definition` 讀回（另開 connection 的唯讀查詢，不在組合寫入路徑內）；`test_p6e_extraction.py`、`test_p6e_import_api.py`、`test_p6f_review_state.py` 與 `service.py`（`DraftQuestion`）有本步之前就存在的未使用 import，未擴大修改。
- **測試與證據**：指揮者在 `apps/server` 用專案 venv 執行 `pytest tests/test_p6f_finalize.py tests/test_p6f_review_state.py tests/test_p6f_authoring_transaction.py tests/test_p6e_import_service.py tests/test_p6e_import_api.py tests/test_p6e_extraction.py tests/test_p6e_import_schemas.py tests/test_p6e_import_persistence.py tests/test_p6e_no_llm_boundary.py tests/test_p6a_adventure_authoring.py tests/test_p6a_adventure_api.py tests/test_m03_import_boundary.py tests/test_code_quality_gate.py`，**192 passed**；全部 `tests/test_p6*.py` 589 個 0 failed（16 skipped，皆為缺 `P4_POSTGRES_URL`）；`git diff --check` 通過。驗證 code commit：`431877d2`。
- **未解與下一步**：本步無未解問題。F3 把 review／resolve／answer／finalize 接成 DM-only REST，並為 `AdventureImportBlockingWarningsError` 對應獨立 machine code。
