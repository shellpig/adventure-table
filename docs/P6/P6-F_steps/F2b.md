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

（待填）
