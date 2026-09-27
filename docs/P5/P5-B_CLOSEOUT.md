# P5-B — Movement & Path Resolution Closeout

- **關門日期**：2026-09-27
- **Branch**：`feat/p5b-movement-path-resolution`（自 `main@63f63f95`）
- **最終驗證 code**：`6e4ec630`（其後 `7935b7d3` 只改一個測試的數字，已單跑通過）
- **Worker**：Muse（B1 `259d1b97`、`544c3e79`；B2 `86ddc19b`）；指揮者修正 `6e4ec630`、`7935b7d3`。步驟紀錄見 [P5-B實作紀錄](P5-B實作紀錄.md)。

## 範圍

Backend only：`0038_p5b_movement_bookkeeping`（`combat_entries` 四個 `movement_*` 欄位，併入既有同一批 lifecycle reset）、`app/domain/spatial/pathing.py`（`grid_distance`、`step_cost`、切角、`validate_movement_path`）、`app/domain/combat/speeds.py`（walk speed＋condition／exhaustion 修正）、`app/domain/combat/movement.py`（Preview、Confirm、DM reposition）、routes `POST .../combat/board/movement/preview`、`/movement/confirm`、`/board/reposition`，error `combat_movement_invalid`（400）、`combat_movement_stale`（409）、`combat_movement_conflict`（409），event `combat.movement_committed`、`combat.movement_interrupted`、`combat.position_corrected`。Tactical UI／MCP tools 屬 P5-F；OA 與 `pending_movement_state` 的實際使用屬 P5-E。

## 驗收對應（測試指南 B.1～B.8）

| 項目 | 測試 |
|---|---|
| B.1 5/10 diagonal | `test_p5b_b2.py`：`test_orthogonal_move_costs_5_feet`、`test_diagonal_steps_alternate_5_10_5_10`、`test_move_attack_move_keeps_diagonal_parity`、`test_new_turn_resets_movement_bookkeeping`、`test_dash_increases_budget_without_resetting_parity` |
| B.2 Terrain | `test_difficult_terrain_costs_double_and_blocked_rejects_at_service_level`、`test_public_door_closed_blocks_service_preview`、`test_door_state_locked_blocks_open_and_broken_pass`；`test_p5b_movement.py`：`test_validator_rejects_blocked_terrain_and_wall_crossing`、`test_validator_open_and_broken_doors_do_not_block` |
| B.3 Creature space | `test_validator_creature_space_rules`、`test_validator_footprint_sweep_blocks_large_mover`、`test_validator_rejects_large_footprint_diagonal_corner_cut`、`test_validator_large_diagonal_wall_on_leading_edge` |
| B.4 Split movement | `test_split_movement_across_attack_keeps_bookkeeping`（10 → Attack → 15 = 25）、`test_bonus_action_and_extra_attack_do_not_reset_movement`、`test_finalize_initiative_resets_movement_bookkeeping`、`test_advance_turn_resets_movement_bookkeeping`、`test_end_combat_resets_movement_bookkeeping`、`test_withdraw_entry_resets_movement_bookkeeping`、`test_remove_entry_resets_movement_bookkeeping` |
| B.5 Stale preview | `test_confirm_rejects_stale_board_after_door_change`、`test_confirm_rejects_stale_position_after_token_moved`、`test_confirm_rejects_stale_position_after_reposition` |
| B.6 Atomicity | `test_confirm_rejects_illegal_path_with_zero_side_effects`、`test_confirm_rejects_stale_revisions_with_zero_side_effects`、`test_confirm_is_idempotent_on_retry`、`test_confirm_replay_happens_after_authorization`、`test_confirm_rejects_idempotency_key_entry_mismatch`、`test_confirm_rejects_idempotency_key_actor_mismatch` |
| B.7 Hidden interruption | `test_hidden_monster_does_not_block_player_preview_but_blocks_dm`、`test_hidden_wall_does_not_block_player_preview_but_blocks_dm`、`test_player_confirm_interrupted_by_hidden_monster`、`test_player_confirm_interrupted_by_hidden_wall`、`test_interrupted_confirm_response_json_has_no_hidden_details`、`test_interrupted_event_projection_is_player_safe_and_dm_complete`、`test_interrupted_retry_returns_same_result_without_duplicate_event`、`test_dm_caller_is_never_interrupted`、`test_unrevealed_hidden_door_blocks_player_as_plain_wall` |
| B.8 DM reposition | `test_dm_reposition_moves_without_budget_or_parity`、`test_reposition_is_allowed_off_turn`、`test_reposition_appends_audited_event_with_player_safe_projection`、`test_reposition_hidden_monster_event_is_dm_only`、`test_player_reposition_is_rejected_with_zero_side_effects`、`test_ai_controller_reposition_is_rejected_with_zero_side_effects`；「不觸發 OA」依測試指南留待 P5-E cross-test |
| 不該操作的 actor | `test_player_cannot_move_other_character_or_monster`、`test_cannot_move_off_turn`、`test_non_participant_preview_and_confirm_rejected`、`test_actor_from_another_campaign_is_rejected`、`test_quick_combat_rejects_movement` |
| Migration | `test_p5b_postgres_migration.py::test_p5b_postgres_migration`（真 PostgreSQL，passed） |

## 關門 gate

- 全套 backend pytest（`P4_POSTGRES_URL=…/adventure_table_p4`，`6e4ec630`）：exit 0，2,886 個中 2,847 passed、39 skipped、0 failed。focused（`test_p5b_*`＋`test_p5a_*`＋M03 boundary／schema parity／migration heads／code quality）199 passed、0 skipped。
- `docker compose config`：通過。未動 `apps/web`，不需 `npm test`／`npm run build`。
- **全套 Docker E2E**（`ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1 npm run test:e2e:docker`，`7935b7d3`）：`parallel` 102 passed／3 skipped／2 failed（`p1f-character-creation`、`m01c-backgrounds`）；script 在第一趟失敗後停止，另補跑 `baseline-room` 30 passed／1 skipped、`serial-restart` 2 passed；`m01c-backgrounds` 單跑 2 passed（Builder draft 等待逾時，長跑 flake）。`p1f` 為 `main` 上既有穩定失敗（見 P6-D closeout），與 P5-B 無關。

## 指揮者審核修正

- B1：Confirm 的 idempotency replay 在授權之前執行且不核對 entry／acting seat；多格 footprint 斜走切角只看 anchor 格；多條測試指南項目缺測。Muse 報告聲稱已有 `test_confirm_ignores_entry_id_mismatch`，但推送的 tree 沒有該測試與檢查。以上交 B2 修正並補測。
- B2：指揮者在 B2 scope 誤寫「Player Preview 不受未揭露 hidden door 影響」，Muse 據此讓 Player 規劃時移除未揭露 hidden door；但 Player board 把它畫成牆，導致可規劃穿牆、門為 open 時 Confirm 甚至能穿過而洩漏暗門。`6e4ec630` 改為 movement 一律使用與 board 相同的 audience projection。
- `7935b7d3`：split movement 測試改用測試指南 B.4 的數字。

## 已知限制

- Hostility 沿用 subject kind（Character vs Monster）；同陣營 Monster 互為 nonhostile、召喚物／魅惑等無法表達，待後續 M 處理 `is_hostile`。
- Player 撞到 hidden wall／hidden monster 被 interrupted 時，雖然 payload 不含座標，但 Player 可從「這條路走不過去」推知附近有東西；這是桌上實際情況，交 DM 敘事處理。
- Budget 在本 Turn 第一次正式 movement 時以當下 speed 固定；回合中途 condition 變化（例如移動後才被 grappled）不會回頭調整已給的 budget，交 DM reposition／裁定。
- Walk speed 缺資料時 fallback 30 ft.（與 P5-A size fallback 同一原則）。
- 事件 hidden monster 過濾仍依 P5-A 的固定 key 名單；`combat.movement_interrupted` 的 Player 投影改用 allowlist，不受此限。
- Muse B2 的最終報告因其網站卡在「連結中」未能讀取；交付以 commit 與本機驗證為準。
