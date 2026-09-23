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

- **起始與 worker**：2026-09-23，agy（Gemini 3.8 Flash High），1 回合，CLI 回報約 986 秒。
- **交付**：`app/domain/adventures/service.py` 新增 `AdventureAuthor = RoomAccessContext | TableActorContext`；`require_adventure_author` 對 table actor 要求同 Room、`role == "dm"` 且 `is_current_dm`；`get_definition`／`create_definition`／`create_entry`／`link_entry_asset`／`finalize` 的 `context` 改為 `AdventureAuthor`，其餘方法仍只收 `RoomAccessContext`。`AdventureImportService` 新增必填依賴 `table_event_service`，`_require_active_author(connection, author)` 在同一 transaction 內以 `require_active_table_actor` 重新驗證，inactive／revoked／stale 一律轉 `AdventureImportForbiddenError`；`create_import`、三種 add source、`get_draft`、`update_draft`、三個 review intent、`finalize_adventure` 改收 `AdventureAuthor`，AI 的 asset source 走 `open_content_for_table_actor`。production DI 接 `get_table_event_service`，六個既有 fixture 改接真 `TableEventService`。新增 `tests/test_p6f_import_ai_authority.py`（3 個 test function、59 cases）。
- **使用者決策（2026-09-23）與 A.1 契約衝突處理**：全部 P6 regression 抓到 `test_p6a_campaign_adventures.py::test_adventure_domain_has_no_gameplay_actor_entry_point` 失敗（P6-A A.1 證據要求 `AdventureService` 只收 `RoomAccessContext`，與派工決策 3「AI DM 可 finalize」不相容；agy 的測試範圍未含該檔）。使用者選擇「允許，只限 draft」：table actor 只能對 draft 狀態的 Adventure `create_entry`／`link_entry_asset`（新增 `_require_draft_for_table_actor`，finalized 一律 `AdventureForbiddenError`），`finalize` 本來就只接受 draft。A.1 測試改為：只有上述五個方法接受 `AdventureAuthor`，其餘仍必須是 `RoomAccessContext`；MCP tool 名稱 allowlist 加入 `import_adventure_source`、`finalize_adventure`；並新增 `test_table_actor_cannot_modify_finalized_adventure` 證明 table actor 無法對 finalized Adventure 新增 entry、連結 asset 或再次 finalize。
- **指揮者審核修正**：刪除 agy 在 `require_adventure_author`、`_require_active_author`、`add_asset_source` 放的三個不可能走到的「Invalid author context」分支；inactive actor 的三種錯誤抽成 `_INACTIVE_TABLE_ACTOR_ERRORS` 共用；測試 70 行 if-chain 改為 intent dispatch map，計數快照改為迴圈；移除改動後未使用的 import。
- **觀察（未修）**：`P6-A_CLOSEOUT.md` 的 A.1 對應說明仍寫「Adventure service 只接受 `RoomAccessContext`」，建議 verifier 依本決策同步 closeout 與 `開發設計方針.md` P6-F 段；`AdventureService` 本身不驗 Session activeness，靠唯一的 table actor 呼叫端（Import service）在同一 transaction 先驗。
- **測試與證據**：指揮者在 `apps/server` 用專案 venv 執行全部 `tests/test_p6*.py`＋`test_code_quality_gate.py`＋`test_m03_import_boundary.py`＋`test_m03d_schema_parity.py`，**678 個 0 failed**（16 skipped，皆缺 `P4_POSTGRES_URL`）；`git diff --check` 通過。驗證 code commit：`931c08ff`。
- **未解與下一步**：F4b 的六個 MCP tool 直接以 `_actor(token)` 取得的 `TableActorContext` 呼叫上述 intent，不再另做授權判斷。
