# F4a — Importer 的 current AI DM authority 接線

## Scope

- 讓 Importer 所需的 service intent 可由 **active Session 的 current AI DM**（`TableActorContext`）呼叫，Human 路徑（`RoomAccessContext`）行為與簽名相容。拍板決策 3：AI Player、非 current DM、stale／revoked grant、controller_epoch 過期、非 active Session 一律拒絕且零副作用。**不得偽造 `RoomAccessContext`**，也不放寬 pre-session grant。
- Authority 型別：`require_adventure_author` 與 `require_import_author` 接受 `RoomAccessContext | TableActorContext`。`TableActorContext` 需 `role == "dm"` 且 `is_current_dm`，否則 Forbidden；`room_id` 不符則 NotFound（沿既有語意）。
- Active 驗證：`AdventureImportService` 新增 `TableEventService` 依賴；AI 路徑在每個讀寫 transaction／connection 內先以既有 `require_active_table_actor(connection, actor, repository)` 驗證，錯誤轉為 Import 既有錯誤型別。Human 路徑不變。
- 覆蓋 F4b 六個 tool 會用到的 intent：`create_import`、`add_text_source`、`add_url_source`、`add_asset_source`（AI 路徑走既有 `RoomAssetService.open_content_for_table_actor`）、`get_draft`、`update_draft`、`resolve_import_warning`、`answer_import_question`、`finalize_adventure`。`finalize_adventure` 呼叫的 `AdventureService` authoring intent 接受同一 author 型別；active 驗證由 Import service 在同一 transaction 完成。
- 不做 MCP tool、catalog、guide（F4b），不改 route、UI、migration。

## 契約與輸入

- 規格 P6-F（不放寬 P3-D pre-session grant、不建立 AI bypass）；設計 P6-F；測試 F.5。前置 F2b、F3。
- 參考：`app/domain/rooms/table_events.py`（`TableActorContext`、`require_active_table_actor`）、`app/domain/campaign_runtime/service.py`（`_require_active_dm_authority` 的 AI DM 驗證模式）、`app/domain/room_assets/service.py`（`open_content_for_table_actor`）、`app/api/rooms/dependencies.py`（`get_table_event_service`）。

## 驗收

- `tests/test_p6f_import_ai_authority.py`（real SQLite service，parametrize）：current AI DM 可建立 import、加入 text／url／asset source、update draft、resolve、answer、finalize；AI Player、非 current DM、revoked grant、stale binding、非 active Session 對上述 intent 全拒絕，import／draft／adventure 快照前後相等；跨 Room 的 actor 得到 NotFound。
- 既有 Human 路徑的 P6-A／P6-E／F1～F3 regression 與 M03 boundary、code quality gate 通過。

## 完成紀錄

（待填）
