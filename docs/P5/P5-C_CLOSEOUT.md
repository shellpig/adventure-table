# P5-C — Range, Reach & Spatial Targeting Closeout

- **關門日期**：2026-09-27
- **Branch**：`feat/p5c-range-reach-spatial-targeting`（自 `main@6d3997a0`）
- **最終驗證 code**：`ceac4627`
- **Worker**：Muse（thread「AT P5C」；C1 `64747ad7`、`5a816648`）；指揮者修正 `ceac4627`。步驟紀錄見 [P5-C實作紀錄](P5-C實作紀錄.md)。

## 範圍

Backend only：`ResolvedAttack` 加 `reach_feet`／`range_normal_feet`／`range_long_feet`（`AttackDefinitionResolver` 唯一來源）；`app/domain/spatial/targeting.py`（spatial targeting result、hard blocker、reach query、spell range 解析）；Tactical attack 以空間結果取代 DM range adjudication，合法即進既有 P4 formal roll／damage／HP；long range → `attack:long_range` disadvantage；Tactical 以實際距離判斷「5 呎內／外」condition 效果（Quick 維持原假設）；targeted spell 依 `Self`／`Touch`／`N feet` 驗 range；error `combat_target_out_of_range`、`combat_target_blocked`（409）。不做 Cover、LOS／lighting、OA 觸發（P5-E）、AoE（P5-D）、UI／MCP（P5-F）。

## 驗收對應（測試指南 C.1～C.6）

全部位於 `tests/test_p5c_range_reach_spatial_targeting.py`。

| 項目 | 測試 |
|---|---|
| C.1 Shared distance | `test_c1_melee_distance_matches_grid_distance`、`test_c1_ranged_distance_matches_grid_distance`、`test_c1_spell_distance_matches_grid_distance` |
| C.2 Multi-cell range | `test_c2_large_footprint_uses_nearest_cell_pair`、`test_c2_anchor_to_anchor_would_be_wrong`、`test_c2_huge_footprint_nearest_pair` |
| C.3 Melee reach | `test_c3_glaive_reach_ten_through_resolver`、`test_c3_whip_reach_ten_through_resolver`、`test_c3_longsword_reach_five_default`、`test_c3_monster_reach_ten_action`、`test_c3_monster_melee_or_ranged_keeps_reach_and_range`、`test_tactical_reach_ten_hits_at_ten_feet`、`test_tactical_reach_five_rejects_ten_feet`、`test_c3_hard_wall_between_rejects_attack` |
| C.4 Ranged band | `test_c4_crossbow_light_range_through_resolver`、`test_c4_crossbow_light_range_bands_pure`、`test_c4_long_range_adds_disadvantage_source`、`test_c4_tactical_long_range_attack_declares_disadvantage`、`test_c4_tactical_crossbow_long_band_declares`、`test_c4_tactical_crossbow_beyond_long_range_rejected`、`test_c4_quick_crossbow_still_requires_dm_adjudication` |
| C.5 Door／wall／cover | `test_c5_wall_blocks_and_reports_kind`、`test_c5_closed_and_locked_doors_block`、`test_c5_closed_door_blocks_and_open_door_does_not`、`test_c5_locked_door_blocks_attack`、`test_c5_broken_door_does_not_block`、`test_c5_barrier_beside_the_sight_line_does_not_block`、`test_c5_all_pairs_must_be_blocked_for_large_attacker`、`test_c5_result_contract_has_no_ac_adjustment` |
| C.6 P4 reuse | `test_c6_tactical_attack_uses_p4_formal_roll_damage_and_hp`、`test_c6_tactical_and_quick_share_declare_path` |
| 5 呎 condition | `test_condition_prone_ranged_within_5ft_keeps_prone_source`、`test_condition_prone_melee_beyond_5ft_no_within_advantage`、`test_condition_prone_quick_fallback_unchanged`、`test_condition_adjacent_critical_uses_real_distance` |
| Targeted spell | `test_spell_120ft_in_range_casts`、`test_spell_out_of_range_rejected_with_zero_side_effects`、`test_spell_wall_blocked_rejected`、`test_spell_touch_range_adjacent_ok_and_far_rejected`、`test_spell_self_range_targets_caster_only`、`test_spell_unknown_range_skips_spatial_gate`、`test_parse_spell_range` |
| Secrecy／actor | `test_secrecy_player_sees_wall_for_hidden_wall`、`test_secrecy_dm_sees_hidden_wall`、`test_secrecy_hidden_door_blocks_as_wall_for_player`、`test_tactical_player_targeting_hidden_monster_rejected`、`test_spell_player_targeting_hidden_monster_rejected`、`test_tactical_uncontrolled_combatant_rejected_with_zero_side_effects` |
| Reach query（P5-E 用） | `test_is_within_reach_never_triggers_reactions`、`test_pure_ranged_attack_never_threatens_reach` |

## 關門 gate

- 全套 backend pytest（`P4_POSTGRES_URL=…/adventure_table_p4`，`ceac4627`）：exit 0，2,956 個中 2,917 passed、39 skipped、0 failed。focused（`test_p5c_*`＋`test_p5b_*`＋`test_p5a_*`＋`test_p4c_*`＋`test_p4d_*`＋M03 boundary＋code quality）全過。
- `docker compose config`：通過。未動 `apps/web`，不需 `npm test`／`npm run build`。
- **全套 Docker E2E**（`ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1 npm run test:e2e:docker`，`ceac4627`）：`parallel` 100 passed／3 skipped／4 failed（`p1f-character-creation`、`m01d-vgm-races`、`p1g-level-up`、`p4e-quick-combat`）；script 在第一趟失敗後停止，另補跑 `baseline-room` 30 passed／1 skipped、`serial-restart` 2 passed。`p4e`（180 秒整體逾時，非斷言失敗）、`m01d`、`p1g`（Builder 長跑 flake）以 1 worker 單跑共 6 passed；`p1f` 為 `main` 上既有穩定失敗（見 P6-D closeout）。這趟 parallel 比 P5-B 慢（8.5 分 vs 6.0 分），逾時判定為負載。

## 指揮者審核修正

- `ceac4627`：`is_within_reach` 對 ranged attack 把 `range_normal_feet` 當 reach（P5-E 判藉機攻擊時長弓會有 150 呎 reach），改為只看 `reach_feet`；SRD 18 個「Melee or Ranged」Monster action normalize 成 ranged 時 resolver 丟掉 reach 5，改為保留。補兩個測試。另核對 SRD 61 個 ranged Monster attack 全部有 range 資料。

## 已知限制

- Hidden wall／未揭露 hidden door 以 full truth 擋攻擊，Player 收到 `combat_target_blocked`（blocker 一律顯示為 `wall`），可推知目標與自己之間有東西；不另發 DM 通知（與 P5-B movement 的 interruption event 不同）。
- 無法解析的 spell range（Sight、Special 等）在 Tactical 不做空間檢查，沿用既有行為交 DM 口頭處理；attack 缺 range 資料則拒絕。
- Character 的 thrown 武器（Dagger、Handaxe 等）判定為 melee kind 並保留 thrown range；Monster 的「Melee or Ranged」action 判定為 ranged kind 並保留 reach。兩者對 prone 等 condition 的判斷都依實際距離，不受 kind 影響。
- 近戰距離內使用遠程攻擊的 disadvantage（hostile 在 5 呎內）未建模，沿用 P4 行為交 DM。
- Hard blocker 只判「每一對格子中心連線都被牆擋住」；牆角擦過不算擋。Cover 仍交 DM，不自動加 AC。
- Dodge 的「能看見攻擊者」、Frightened 的來源可見性仍交 DM（P4-F 已知限制）。
