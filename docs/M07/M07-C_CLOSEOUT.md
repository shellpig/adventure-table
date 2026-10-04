# M07-C — Map Monster Placement & Combat Load · Closeout

日期：2026-10-04　Branch：`feat/m07c-map-monster-placement`（自 `main@3b8b2792`）　Worker：Muse（C1、C2，muse.ai thread「AT M07C」）、Muse Spark 1.3 經 OpenCode CLI（C3、C3b、E2E spec）、指揮者（審核修正、驗收測試、C4）

Commit：C1 `7198a956`＋`5ed50403`；C2 `43b7716f`、`9c11f15c`＋`ea6af5d9`；C3 `599881b5`、C3b `5911b046`；E2E `7a079692`；C4（本檔）。另含使用者決定留在本分支的 M07-A 修正 `39c32453`（UI 只改部分欄位時保留怪物完整規則），由本次關門 gate 一併驗證。

## 驗收對應

Backend 測試在 `apps/server/tests/`，前端測試在 `apps/web/src/`，E2E 在 `apps/web/e2e/`。

| 契約 | 證據 |
|---|---|
| C.1 來源恰一、同 Room、數量即 row 數；不存 count／HP／Instance | migration CHECK＋`test_m07c_placements.py::test_both_or_neither_source_is_422`、`test_missing_or_cross_room_custom_template_is_404`、`test_missing_builtin_key_is_404`、`test_non_monster_content_key_is_422`、`test_put_replaces_whole_set_and_bumps_revision`、`test_put_empty_placements_is_legal`<br>`test_m07c_postgres.py::test_m07c_0043_migrates_up_and_down_with_real_rows`、`test_m07c_0043_fk_restrict_and_cascade_on_real_rows` |
| C.1 編輯不建立 Instance、不改 Character；拖放／移除／hidden | `test_editing_placements_creates_no_instances_or_character_changes`、`test_put_replaces_whole_set_and_bumps_revision`<br>E2E `M07-C editor places a public built-in and a hidden custom monster, saves, and reopens with both`（搜尋放 Goblin、hidden 自訂怪、重開仍在、首頁以外的 Large 模板重開畫成 2×2） |
| C.1 objects PUT／patch 不清配置；幾何衝突整筆拒絕 | `test_objects_put_does_not_clear_placements`、`test_conflicting_geometry_change_rejected_with_zero_side_effects`、`test_patch_shrink_conflicting_with_placements_rejected` |
| C.1 copy 新配置 id、保留有效引用；他圖 id 不可沿用 | `test_copy_copies_placements_with_new_ids`、`test_placement_id_owned_by_another_map_is_422` |
| C.1 封存模板：已存可留、不可新增 | `test_newly_archived_custom_template_rejected_with_problems`、`test_unchanged_archived_reference_resend_succeeds`、`test_changed_to_archived_template_is_rejected`、`test_new_placement_cannot_add_second_archived_reference`；開戰照載 `test_m07c_combat_load.py::test_archived_template_loads_from_saved_config` |
| C.1 不該操作的 actor 零副作用 | `test_member_and_other_room_owner_cannot_put_or_read`、`test_dm_seat_controller_without_room_authority_cannot_put`、`test_put_stale_revision_rejected_with_zero_side_effects` |
| C.1 配置算模板引用 | `test_delete_custom_template_with_placement_ref_is_409_not_500` |
| C.1 只載入地圖合法、Quick 不載入 | `test_load_flag_rejected_without_battle_map_source`、`test_m07c_rest_load.py::test_rest_load_flag_without_battle_map_is_422`<br>E2E `M07-C loading map only starts combat without any monsters` |
| C.2 最新模板 Size；整批問題列出；一筆壞配置整場零副作用 | `test_load_uses_latest_template_size_not_placement_time_size`、`test_one_bad_placement_rolls_back_entire_start`、`test_dangling_builtin_template_reference_is_404`、`test_rest_bad_placement_is_409_with_problems`<br>`test_m07c_acceptance.py::test_ai_dm_bad_batch_after_template_growth_leaves_table_untouched`（MCP，計數與 event cursor 不變）<br>E2E `M07-C grown template blocks load-with-monsters until the DM fixes the placement in the editor` |
| C.2 各 Instance 獨立、快照凍結；名稱快照 | `test_load_map_monsters_happy_path`、`test_rules_snapshot_carries_presentation_and_provenance`、`test_snapshot_frozen_against_later_template_edits`、`test_snapshot_frozen_against_spellcasting_edit`<br>前端 `sessionCombat.test.ts`（名稱選擇規則）；E2E `M07-C built-in monster names follow the UI locale in the placement picker` |
| C.2 Party 維持既有 initiative gate | `test_party_initiative_gate_still_applies_with_loaded_monsters` |
| C.2 idempotency：同 key 原結果、不同意圖 409、End／Abandon 後 retry、AI 撤銷拒絕、新 key 不能在已結束 Session 開戰 | `test_idempotent_retry_same_intent_returns_original_combat`、`test_idempotent_retry_after_template_edit_does_not_respawn`、`test_idempotent_retry_different_intent_is_409`、`test_start_intent_captures_source_flag_and_geometry`、`test_retry_after_session_end_returns_original_combat`、`test_retry_after_session_abandon_returns_original_combat`、`test_retry_after_combat_end_returns_original_result`、`test_retry_after_map_archived_returns_original_without_touching_map`、`test_ai_grant_revoked_old_key_is_rejected_with_zero_side_effects`、`test_new_key_cannot_start_in_ended_session`、`test_rest_idempotency_conflict_is_409` |
| C.2 Player 不可帶載入選項開戰 | `test_player_cannot_start_tactical_with_load_flag`、`test_rest_player_cannot_start_with_load_flag` |
| C.3 Human／AI Player 不洩 hidden 存在、數量、id、名稱、位置；DM 可讀；Reveal | `test_m07c_secrecy.py`：`test_player_view_hides_hidden_and_densifies_turn_ordinals`、`test_player_board_hides_hidden_positions`、`test_player_detail_omits_hidden_and_carries_name_presentation`、`test_dm_detail_sees_hidden_with_full_snapshot`、`test_ai_player_sees_same_projection_as_human_player`、`test_player_suggested_order_excludes_hidden`、`test_player_tied_totals_exclude_hidden`、`test_combat_started_event_redacts_hidden_for_player`、`test_reveal_exposes_loaded_monster_to_player`<br>`test_m07c_acceptance.py::test_ai_player_mcp_reads_never_reveal_hidden_loaded_monster`（AI Player 走 `combat_get_active`／`get_combat_context`／`combat_get_board`／`get_pending_events`，含 `start_intent` 不外洩）<br>E2E `M07-C players never see hidden map monsters in DOM, network, or API until revealed`（Player 每筆 combat／events GET 回應不含 hidden id／instance id／名稱；可見怪物數 1；DM 以 UI Reveal 後才出現） |
| PG race | `test_m07c_postgres_race.py`：`test_pg_concurrent_same_key_start_yields_one_combat`、`test_pg_concurrent_different_keys_one_wins`、`test_pg_load_vs_placement_edit_race_stays_atomic`、`test_pg_failed_load_rolls_back_with_cursor_unchanged`、`test_pg_load_vs_template_patch_two_connections`、`test_pg_load_vs_template_archive_two_connections`、`test_pg_load_vs_template_delete_two_connections`；`test_m07c_postgres.py::test_m07c_put_transaction_on_postgres` |
| 新 UI／錯誤雙語 | `battleMapLibraryCopy.test.ts`、`tacticalCopy.test.ts`、`sessionMessages` parity；E2E zh-TW／en 名稱 |
| M03 boundary／schema parity | `test_m03_import_boundary.py`、`test_m03d_schema_parity.py`（新表納入） |

## 關門 gate

- **全套 backend pytest**（`P4_POSTGRES_URL=…/adventure_table_p4`，`7a079692`）：exit 0，3,224 passed、39 skipped、0 failed。39 個 skip 與 M07-A／B 相同，是 P2／P3 專屬 PG job 的環境條件；M07 與 P4／P5 的 PG 測試全部實跑。
- **Frontend**：`npm test -- --run` 121 files、982 passed；`npm run build` 通過（只有既有 chunk-size 警告）。
- **`docker compose config`**：通過。
- **m07c E2E**（Docker，`adventure_table_e2e`）：`m07c-map-monsters.spec.ts` 5 passed，worker 端連跑兩次各約 12 秒。受影響的 `m07b-map-library`、`p5g-map-editor-save` 3 passed（其中一次出現 KI-ENV-002 的 worker crash 簽章 `3221226505`，重跑全過）。
- **全套 E2E**（`npm run test:e2e:docker` 無參數，`7a079692`，隔離的 `adventure_table_e2e`）：
  - `parallel`：115 passed、3 failed、3 skipped，script 隨即中止。通過的包含 `m07a-monster-library`（含驗證 `39c32453` 的 `M07-A editing a custom monster in the UI preserves…`）、`m07b-map-library`、`m07c-map-monsters` 全部 5 個、`p4e-quick-combat`、`p5f-tactical-combat`、`p5g-*`。
  - 失敗 `p1g-level-up`、`p2d-lobby-seats`：`docker compose --profile e2e restart server-e2e` 後單跑通過（p1g 1 passed、p2d 2 passed），屬 server-e2e 長跑後退化的既有現象。
  - 失敗 `p1f-character-creation`：重啟後單跑仍失敗，頁面為 `1 blocking`「Choose two from Animal Handling…／required number of selections」，與 `KI-P1F-001`（main 上即穩定失敗）同一簽章。M07-C 沒有改動 Builder 或角色 API，依該條目放行。
  - 補跑另外兩組：`baseline-room` 30 passed、1 skipped；`serial-restart` 2 passed。

## 已知事項

- 合併 main 後，daily server 啟動時會照常升到 `0043_m07c_map_monster_placements`。
- 已結束戰鬥的 hidden Monster 歷史洩漏仍是 `KI-P5A-001`，依使用者 2026-10-03 決定由 P7-A 處理，本 Subphase 不涉及。
- Human Resume REST 沒有獨立 backend 測試；同一 Player projection 已由 MCP 驗收測試與 E2E 的 Player 網路斷言涵蓋。
