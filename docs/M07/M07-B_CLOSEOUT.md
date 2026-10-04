# M07-B — Map Library Lifecycle & AI DM Boundary · Closeout

日期：2026-10-04　Branch：`feat/m07b-map-library`（自 `main@89a78a74`）　Worker：agy（B1 初稿、B2）、指揮者（B1 收尾、B3）

Commit：B1 `6aa98bed`、B2 `65418637`、B3（本檔與 PG 競爭測試補件）。

## 驗收對應

Backend 測試在 `apps/server/tests/`，前端測試在 `apps/web/src/`，E2E 在 `apps/web/e2e/`。

| 契約 | 證據 |
|---|---|
| B.1 無 Session 從 Room 建立、編輯、保存、重開 | `test_m07b_map_library.py::test_room_rest_create_edit_reopen_without_session`<br>E2E `m07b-map-library.spec.ts`（en／zh-TW）：從 Workspace 入口進地圖庫、建空白圖、畫牆、存檔、重開仍有牆 |
| B.1 上傳底圖建圖；複製產生新 map 與物件 id、共用底圖、不複製 bytes | `test_copy_gets_new_identity_and_object_ids_sharing_the_image`（`room_assets` 列數不變、改副本不影響來源）、`test_copy_accepts_a_name`<br>前端 `RoomBattleMapLibraryPage`：上傳用 `battle_map_image` kind |
| B.1 封存：預設列表不顯示、管理 filter 可見、仍可讀可複製；不能新開戰；既有 board 繼續 | `test_archive_hides_from_default_list_but_stays_readable_and_copyable`<br>`test_m07b_tactical_sources.py::test_archived_map_cannot_start_combat_but_an_existing_board_keeps_working`<br>E2E：封存副本預設隱藏、勾選後可見；Tactical Setup 只列未封存的原圖 |
| B.1 board／歷史 board 引用阻擋刪除；未引用可刪 | `test_active_and_ended_boards_block_map_delete`、`test_delete_requires_revision_and_removes_an_unreferenced_map` |
| B.1 stale revision（copy／archive／patch／delete）409 零副作用 | `test_stale_revision_is_409_with_zero_side_effects` |
| B.1 防連點、未知結果重新讀取 | `RoomBattleMapLibraryPage.test.tsx`（送出中停用、失敗重新讀取不重送；repo 慣例的原始碼斷言）＋ E2E 實際操作 |
| B.1 Room Hard Delete 清完整 graph | `test_room_hard_delete_clears_maps_with_historical_boards`；既有 `test_p5a_room_asset_battle_map.py::test_room_hard_delete_removes_battle_maps_and_asset_files` |
| B.2 AI list／get 只限 active DM grant；他 Room 不可讀 | `test_ai_dm_reads_maps_of_its_own_room_only`（含封存圖不列出、他 Room map → `not_found`）、`test_player_and_revoked_grants_cannot_read_maps`<br>`test_p5f_f1b.py::test_f3b_presession_dm_grant_battle_map_rejected_zero_side_effects`、`test_b5b_battle_map_scope_requires_session_dm_at_facade` |
| B.2 寫庫舊工具從清單、說明、guide、dispatch 移除；直接呼叫回協定錯誤 | `test_b5b_battle_map_delete_fully_removed`（definition／`_WHEN_TO_USE`／guide 名單／facade 方法）<br>`test_f3b_player_battle_map_patch_rejected_zero_side_effects`、`…_replace_objects_…`（回 `tool_not_found`、revision 不變）<br>`test_m04c_tool_descriptions.py` |
| B.2 臨時幾何只凍結進 board、不增加庫 row／assets；物件 id 由 Server 分配 | `test_temporary_map_freezes_into_the_board_without_library_rows` |
| B.2 互斥來源、非法物件、越界拒絕且零副作用 | `test_start_sources_are_mutually_exclusive`（5 種組合）、`test_invalid_temporary_geometry_is_rejected_with_zero_side_effects`（4 種）<br>Human REST：`test_human_rest_tactical_start_accepts_a_temporary_map`<br>MCP：`test_mcp_tactical_start_temporary_map_and_bilingual_errors`（含 `battle_map_archived` 雙語訊息） |
| B.2 Player 不可開臨時地圖戰鬥 | `test_player_cannot_start_a_temporary_map_combat`、Human REST 403 案例 |
| B.3 Room authority 與 Seat role 分離 | `test_room_authority_not_seat_role_decides_map_authoring`（Owner 坐 Player Seat 可建圖；Member 控 DM Seat 不可）、`test_member_and_other_room_cannot_copy_or_archive`<br>前端 `TacticalSetupPanel.test.tsx`：非 owner／dm 看不到建立／編輯，仍可開戰 |
| B.3 臨時棋盤 retry 只有一份 | `test_temporary_map_retry_returns_one_combat_and_one_board` |
| B.3 Quick 不需地圖 | `test_quick_combat_still_needs_no_map` |
| B.3 Join Kit／guide／tool registry 同步、雙語 | guide 本來就沒有地圖寫庫字樣；`guide_tool_names` 與 `_TOOL_DEFINITIONS` 同步移除；`combat_start_tactical` 雙語說明更新 |
| B.3 Player 不能透過 raw 庫 API／UUID 讀庫圖；合法 Stage asset 不受影響 | Member／他 Room 對 get／copy／archive／delete 一律 404（`test_member_and_other_room_cannot_copy_or_archive`、既有 `test_p5a_battle_maps.py::test_member_everything_is_404_with_zero_side_effects`）<br>Room asset 讀取路由本 Subphase 未改動，既有 P5-A asset 測試在全套 backend 中通過 |
| PG：真舊 map／已結束 board 的 SET NULL 改 RESTRICT | `test_m07b_postgres.py::test_m07b_0042_migrates_real_map_and_finished_board_rows`（真實 rows 降回 0041 再升 0042） |
| PG：引用建立 × 刪除、複製 × 編輯、封存 × 開戰競爭 | `test_m07b_tactical_start_vs_map_delete_race_leaves_no_dangling_reference`、`test_m07b_copy_vs_edit_race_copies_a_consistent_revision`、`test_m07b_archive_vs_tactical_start_race_never_starts_on_an_archived_map`（兩條真實 connection） |
| 新 UI／錯誤雙語 | `battleMapLibraryCopy.test.ts`、`sessionMessages` parity；E2E 兩 locale |

## 關門 gate

- **全套 backend pytest**（`P4_POSTGRES_URL=…/adventure_table_p4`，B1 `6aa98bed`）：exit 0，3,145 passed、39 skipped、0 failed。39 個 skip 與 M07-A 相同，是 P2／P3／M03B／M03C 專屬 PG job 的環境條件；M07-B 與 P4／P5 的 PG 測試全部實跑。B2 只動 `apps/web`，此結果仍有效。
- **B3 補件**：`test_m07b_postgres.py` 4 passed（真 PG），code quality gate 通過。
- **Frontend**：`npm test -- --run` 119 files、944 passed；`npm run build` 通過。
- **`docker compose config`**：預設與 `--profile e2e` 都通過。
- **受影響 E2E**（Docker，`adventure_table_e2e`）：`m07b-map-library` 2 passed；`p5f-tactical-combat`、`p5g-map-editor-save`、`p5g-tactical-full-journey`、`m07a-monster-library` 6 passed。
- **M03 boundary／schema parity**：已含在全套 backend 中。本 Subphase 沒有新增多人 package；新欄位由 schema parity 覆蓋；Standalone 仍只升 `character@head`。
- **合併前全套 Docker E2E**：見下節。

## 已知事項

- main 既有 import cycle：M07-A 的 `monster_library/references.py` 經 `app.persistence.adventure_imports` 回到 `app.domain.adventure_imports.schemas`。單獨跑 `tests/test_p5f_tactical_mcp.py` 會在收集階段失敗，main 上也一樣；全套因 import 順序剛好能過。不屬 M07-B 範圍，已另開背景任務處理。
- B1 執行中，agy 的 PG 測試誤升本機 daily `adventure_table` 到 0042，已 downgrade 回 0041 並核對（詳見 [B1](M07-B_steps/B1.md)）。合併 main 後，daily server 啟動時會照常升到 0042。
