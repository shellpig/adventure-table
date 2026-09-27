# P5-E — Opportunity Attack & Spatial Reactions · Closeout

- **關門日期**：2026-09-27
- **Branch**：`feat/p5e-opportunity-attack-spatial-reactions`（自 `main@7f08b266`）
- **Worker**：Muse（E1 `b1da6d19`；E1b `6e5d4c02`、`57705209`、`b74d571a`）、指揮者（審核、程式修正 `bb2606cb`、驗收測試 `e9f64b8c`、關門）

## 範圍

Backend only。`app/domain/spatial/opportunity.py`：reach crossing detector（previous footprint 在 reactor melee reach 內、next 在外、cause = voluntary），reach 取 `ResolvedAttack.reach_feet` 最大值（無 melee attack 時 unarmed 5 ft），多 reactor 依 initiative 再 entry order 排序。`open_opportunity_attack_window` 對 Server 已確認 geometry 的 Tactical 放寬（`tactical_geometry_confirmed`），Quick 仍要求 `dm_adjudicated=True`，既有 DM 手動 OA 保留。MovementService：confirm 在 trigger boundary（仍在 reach 內的格子）暫停，`pending_movement_state` 與 OA window 同一 transaction 寫入；`POST .../movement/resume`（mover controller 或 DM；有 accept 時只限 DM；重驗 HP／speed／position，剩餘 path 兩層驗證並重新偵測 OA，可再次暫停；同 key 只續一次）、`POST .../movement/cancel-pending`（DM only、audit）。`advance_turn` 在 window 仍 open 時 409 零副作用；stale pending 由既有 incoming-entry reset、End Combat、withdraw／remove 清空。Migration `0039_p5e_disengaged`：Disengage 後不觸發 OA。Hidden reactor 不自動 OA、只留 DM-only `combat.opportunity_crossing_noted`；hidden mover 的暫停／續走／取消事件 DM-only。Shove push：方向由 attacker 指向 target，request 時以 caller 投影、complete 時以 truth 驗目的地，位移與擲骰結算同一 transaction，不觸發 OA、不自動掉落傷害。Grapple drag：`drag_entry_id` 需被 mover grapple（P4-C condition note），成本加倍（小兩級以上除外），被拖者每步走同一 path validator，confirm／pause／resume 同一 transaction。UI／MCP tools 屬 P5-F。

## 驗收對應

| 契約（測試指南） | 證據（`apps/server/tests/`） |
|---|---|
| E.1 Basic OA | `test_p5e_opportunity.py::test_oa_pauses_movement_and_opens_window`、`::test_full_decline_then_resume_completes`、`::test_crossing_detected`、`::test_disengage_suppresses_oa_crossing`、`::test_disengage_action_sets_flag`、`::test_disengage_flag_reset_on_turn_advance`；`test_p5e_e1b.py::test_accept_window_marks_reaction_unavailable`、`::test_reach_10_does_not_trigger_inside_5ft`、`::test_pause_anchor_stays_inside_reach`；`test_p5e_acceptance.py::test_clean_resume_continues_from_durable_index_to_path_end` |
| E.2 No false OA | `test_p5e_e1b.py::test_dm_reposition_opens_no_window`、`::test_dragged_target_opens_no_window`、`::test_quick_combat_oa_requires_dm_adjudicated`；`test_p5e_acceptance.py::test_shove_push_moves_the_target_5ft_without_oa_or_fall_damage`、`::test_hidden_reactor_does_not_pause_and_leaves_only_a_dm_note` |
| E.3 Multiple reactors | `test_p5e_e1b.py::test_two_windows_open_for_two_reactors`、`::test_windows_sorted_by_initiative_then_entry_order`、`::test_service_rebuild_preserves_window_order`、`::test_confirm_idempotency_no_second_windows` |
| E.4 Reaction changes mover | `test_p5e_acceptance.py::test_resume_stops_at_zero_hp_without_moving`、`::test_resume_stops_when_speed_drops_to_zero`、`::test_resume_after_reposition_cancels_remaining_path`、`::test_clean_resume_continues_from_durable_index_to_path_end`、`::test_resume_pauses_again_when_leaving_a_second_reach`、`::test_accepted_oa_makes_resume_dm_only_with_zero_side_effects_for_player` |
| E.5 Restart／advance guard／cleanup | `test_p5e_acceptance.py::test_postgres_restart_recovers_paused_movement_and_resumes_once`（真 PostgreSQL）、`::test_resume_replay_with_same_key_moves_only_once`、`::test_advance_turn_is_409_with_zero_side_effects_while_window_open`、`::test_dm_cancel_pending_is_audited_then_turn_can_advance`、`::test_lifecycle_operations_clear_pending_movement[end/withdraw/remove]`、`::test_stale_pending_is_cleared_at_the_movers_next_turn_start`、`::test_postgres_0039_disengaged_migration_round_trip` |
| E.6 Grapple／Shove | `test_p5e_e1b.py::test_drag_cost_doubles`；`test_p5e_acceptance.py::test_drag_is_not_doubled_when_the_target_is_two_sizes_smaller`、`::test_drag_into_an_occupied_cell_rejects_with_zero_side_effects`、`::test_drag_requires_the_grapple_to_come_from_the_mover`、`::test_shove_push_moves_the_target_5ft_without_oa_or_fall_damage`、`::test_illegal_shove_destination_is_409_at_request_without_rolls[wall/occupied/out_of_bounds]`、`::test_hidden_blocker_at_completion_keeps_target_and_leaks_nothing` |
| 不該操作的 actor | `test_p5e_opportunity.py::test_non_dm_cannot_cancel`；`test_p5e_e1b.py::test_player_cannot_cancel_pending`；`test_p5e_acceptance.py::test_player_cannot_resume_a_movement_they_do_not_control`、`::test_accepted_oa_makes_resume_dm_only_with_zero_side_effects_for_player` |
| Secrecy 兩視角 | `test_p5e_e1b.py::test_hidden_reactor_absent_from_player_view`、`::test_hidden_mover_pause_event_dm_only`；`test_p5e_acceptance.py::test_hidden_mover_resume_and_cancel_events_are_dm_only`、`::test_hidden_reactor_does_not_pause_and_leaves_only_a_dm_note`、`::test_hidden_blocker_at_completion_keeps_target_and_leaks_nothing` |

## 關門 gate

- 全套 backend pytest（`P4_POSTGRES_URL=…/adventure_table_p4`，`e9f64b8c`）：3,026 passed、39 skipped、0 failed（一個 `caplog` setup error 為指揮者加 `-p no:logging` 所致，該檔重跑全綠）。code quality、M03 boundary／schema parity 全綠。
- `docker compose config`：通過（未改 compose）。未動 `apps/web`，不需 `npm test`／`npm run build`。
- **全套 Docker E2E**（`e9f64b8c`）：`parallel` 104 passed／3 skipped、`baseline-room` 30 passed／1 skipped、`serial-restart` 2 passed，另 7 passed，0 failed。

## 指揮者審核修正

- E1 退回 E1b：resume 非原子、未限 accept 後 DM、未重驗、hidden mover 事件寫死 public；cancel 無 audit；drag／shove 未完成；測試缺大半，Muse 環境排除了 PostgreSQL 測試。
- E1b 後由指揮者補驗收測試（使用者同意），抓到並修正（`bb2606cb`）：shove 目的地驗證的 path 缺起點，所有 Tactical push 都 409（Muse 的 occupied／wall 測試假綠）；drag 以字串比較 `SizeCategory`，永遠加倍；被拖者路徑未驗證、加倍成本未檢查 budget、resume 忽略 drag；resume 再暫停的 window 缺 `mover_entry_id`，resolve 後移動卡死；`reaction_resolved` 事件把 mover id 送給 Player（洩漏 hidden mover）；resume 回放讀不存在的欄位。
- 刪除 `test_p5e_e1b.py` 中只測 `hasattr`／純幾何的假測試，以及未加 `xdist_group("postgres")`、平行執行時會清空共用 schema 的 E.5 class。

## 已知限制

- 接受 OA 後的攻擊結果沿用 P4 substrate：reaction 標記已用，傷害由 DM 以既有 semantic damage 套用後再 resume；不在 window 內建正式攻擊擲骰。
- Grapple 來源以 P4-C condition note 的 entry id 判定；不拖而離開 reach 時的 grapple 結束不自動化。
- 「完全不在本場的 actor」沿用 P4 `_authorize_entry`，未為 resume／cancel 另寫專屬測試。
- Muse 工作期間曾閒置約 50 分鐘未被發現、之後因 VM 重置重裝 PostgreSQL；監看方式已調整（每 10 分鐘讀任務狀態並催進度）。
