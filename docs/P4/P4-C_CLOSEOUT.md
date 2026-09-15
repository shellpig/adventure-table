# P4-C Closeout Checklist

P4-C — Attack, Damage & Core Action Resolution closeout scope。編號對應 [實作規格](實作規格.md) 的「完成後必須為真」。

- [x] 1. Character 與 Monster 都能從合法 attack definition 建立正式 Attack action。`AttackDefinitionResolver` 把 Character weapon / feature attack 與 Monster Instance `MonsterAction` normalize 成同一個 `ResolvedAttack`（`source_ref` / `attack_bonus` / `attack_kind` / `damage_parts` / crit 行為）；`GET /entries/{entry_id}/attacks` 列出可用 definition。`CombatAttackService.request_attack()` 沿用 P4-B `_authorize_entry()`：Player 只能操作自己 Seat 的 combatant，current DM 可 proxy 任意 Player 或操作敵人；Player 拿敵方 entry 當 attacker 或直接對敵方 `apply_damage()` 皆 `TableEventActorUnauthorizedError`（`test_player_cannot_operate_enemy_combatant_or_directly_mutate_enemy_hp`）。
- [x] 2. Attack roll 走 P3 formal roll substrate。`request_attack()` 建 `roll_requests`（`target_combat_entry_id`），`complete_attack()` 以 P3-C `FormalRollInput`（physical / server）resolve，`resolve_attack_roll()` 支援 `RollMode.NORMAL / ADVANTAGE / DISADVANTAGE`、Nat 20 / Nat 1，`selected_d20` 與 modifier 留在 `roll_results` 與 resolution payload（`test_attack_roll_table`）。
- [x] 3. Nat 20 只 double dice、不 double flat modifier：`DamageRollPart(dice, critical_dice, flat_modifier)`，crit 時 `raw_total = dice + critical_dice + flat`（`test_critical_adds_dice_but_not_flat_modifier`：5 + 4 + 3 = 12）。Nat 1 即使 modifier +99 對 AC 1 也 miss（`test_attack_roll_table` 最後一列）。
- [x] 4. 命中後 Server 直接算傷害並套用 target state，沒有逐擊 DM confirm；`complete_attack()` 在同一 transaction 內 resolve roll、算 damage、更新 Character Current State 或 `monster_instances.current_hp` / `temp_hp`、消耗 attack budget（`test_dm_in_range_resumes_same_action_then_formal_roll_resolves_it`）。
- [x] 5. Temp HP 先吸收再扣 Current HP，Healing 不補 Temp HP（`test_temp_hp_absorbs_before_current_hp`、`test_healing_from_zero_resets_death_saves_removes_unconscious_but_keeps_prone`）。active Combat 的一般受傷／治療統一走 `CombatResolutionService.apply_damage()` / `apply_healing()` semantic boundary（`POST /combat/damage` / `/healing`、MCP `combat_apply_damage` / `combat_apply_healing`）。`TableCharacterStateService.apply_patch()` 在 active Combat 中拒絕 Player / AI Player 的 raw `current_hp` patch（`TableCharacterStateCombatMutationError`）；current DM 必須帶 `correction_reason` 才能 absolute set，並以 `character.state.updated` event 記 `correction=True` / `correction_reason` / `changed_fields`，不觸發 damage consequence；outside Combat 的既有 patch 行為不變（`test_raw_hp_patch_is_normal_outside_combat_but_correction_only_during_combat`）。Concentration 依本次修訂的實作規格第 5 點正式留 P4-D。
- [x] 6. Resistance / Immunity / Vulnerability：Monster 從 `monster_instances.rules_snapshot` 的 `damage_resistances` / `damage_immunities` / `damage_vulnerabilities` 讀取並套用，同 type 多段先合計再 halve（`test_multi_part_damage_applies_each_damage_type_affinity`、`test_same_type_parts_are_aggregated_before_resistance_rounding`）。Character Current State 目前沒有 machine-readable affinity 欄位，因此 Character 一律不套用，見「已知限制」。
- [x] 7. Saving throw：`CombatCoreRollService.request_saving_throws()` 對一或多個 target 各建一張正式 `roll_requests`，以 Character ability modifier 或 Monster stat block save modifier 計算，`dc` / `ability_ref` / `visibility` 由 DM 指定；`complete_saving_throw()` 走同一 formal roll resolve（`test_multi_target_formal_saving_throw_uses_character_and_monster_modifiers`）。Secret 資料仍由 P3 event visibility / recipient 過濾。
- [x] 8. Quick Combat 不猜距離。`request_attack()` 一律先進 `dm_adjudication_required`（Player 自稱 `range_confirmed=True` 不算數），pending state 存在 `combat_actions`，新 repository instance reload 得到同一 status；只有 current DM 可 `adjudicate_attack()`。DM `in_range=False` → action `resolved`、`resolution_result={"status":"invalid","reason":"out_of_range"}`、`action_available` 與 `attacks_used` 不變；`in_range=True` → 沿同一 `action_id` 進 `waiting_for_roll` 並建 roll request，不重擲前置骰（`test_player_geometry_claim_stays_pending_and_survives_repository_reload`、`test_dm_in_range_resumes_same_action_then_formal_roll_resolves_it`）。
- [x] 9. Grapple / Shove：`resolve_special_attack_constraints()` 驗 free hand、size（target 最多大一級）、reach；違反者在 geometry adjudication 之前就 invalid、不消耗 attack（`test_grapple_requires_free_hand_size_and_reach`、`test_grapple_without_free_hand_is_invalid_and_does_not_spend_attack`、`test_too_large_target_is_invalid_before_geometry_and_spends_nothing`）。合法者走與 attack 相同的 adjudication → formal opposed roll 流程（Athletics vs Athletics / Acrobatics），tie 攻方失敗（`test_grapple_opposed_check_tie_fails_attacker`），成功套 `grappled` / `prone` 或 shove-away outcome（`test_special_attack_success_outcomes`、`test_shove_prone_uses_same_formal_flow_and_applies_prone`）；DM `out_of_reach` 不消耗 attack（`test_out_of_reach_adjudication_resolves_without_consuming_attack`）。拖行距離與 hazard geometry 由 DM。
- [x] 10. PC 到 0 HP 同 transaction 套 `unconscious` + `prone` 並開 death-save state（`test_character_exact_zero_starts_death_saves_and_conditions`）；massive damage（剩餘傷害 ≥ max HP）直接 `dead`（`test_massive_damage_can_instantly_kill_character`）；已在 0 HP 再受傷加 1 failure（`test_damage_while_already_at_zero_adds_death_failure`）。Monster 到 0 HP 不自動 `dead`，resolution payload 帶 `monster_outcome_required=True` 留給 DM（`test_monster_zero_hp_requires_dm_outcome_instead_of_auto_dead`）。
- [x] 11. Death Save 全 branch：10–19 success、2–9 failure、Nat 20 → 1 HP 並清空、Nat 1 → 2 failures、三成功 `stable`、三失敗 `dead`（`test_death_save_branches` 8 列）。Healing > 0 移除 `unconscious`、重置 death saves、保留 `prone`（`test_healing_from_zero_resets_death_saves_removes_unconscious_but_keeps_prone`）。正式 death save 走 `request_death_save()` / `complete_death_save()`，Nat 20 在同一 transaction 回 1 HP（`test_formal_death_save_nat20_atomically_recovers_hp_and_retry_is_idempotent`）。
- [x] 12. 原子性與 idempotency：所有 resolve 都走 P3 `TableEventRepository.append(transaction_projection=...)`，state mutation、roll result、economy 與 event 同 transaction。同 `idempotency_key` sequential retry 回傳 canonical result、不重擲、不重扣（`test_dm_in_range_resumes_same_action_then_formal_roll_resolves_it` 的 duplicate 段、death save retry、grapple retry）。真 PostgreSQL 兩個 thread 同時送同一 damage 只有一次 HP change / 一筆 event（`test_concurrent_duplicate_semantic_damage_changes_hp_once`）；在 event insert 後／HP projection 後注入例外，HP、event count 與 `session_table_runtime.revision / last_event_seq` 全部回到原值（`test_semantic_damage_transaction_failure_leaves_no_half_state[False/True]`）。DB 層有 `ck_combat_entries_death_save_*` 範圍約束。
- [x] 13. Human HTTP 與 MCP 共用同一 service。`app/domain/combat/ai_tools.py` 的 MCP facade 只做 validation 與 delegate，`combat_roll_attack` 走 server formal roll 進同一 `CombatAttackService`，`combat_apply_damage` 直接轉 `SemanticDamageInput`、不自算 HP（`test_mcp_dispatch_only_validates_then_delegates_to_combat_facade`、`test_mcp_facade_uses_server_formal_roll_and_shared_attack_service`、`test_mcp_facade_forwards_semantic_damage_without_recalculating_hp`）；Player / DM tool catalog 依 role 切（`test_mcp_combat_catalog_enforces_role_surface`）。
- [x] 14. 沒有 spell skeleton、concentration、reaction chain；`domain/combat/resolution.py` 明寫 Concentration 留 P4-D subscribe 本 semantic boundary。

## 契約以外的實作決定

| 項目 | 決定 |
|---|---|
| Migration | `0025_p4c_core_resolution`（接 `0024_p4b_combat_roll_targets`）：`combat_entries` 加 `death_save_successes` / `death_save_failures` / `death_save_stable` / `death_save_dead`；`combat_actions` 加 `target_entry_id` / `roll_request_id` / `roll_result_id` / `resolution_result` 與對應 index。character track head 仍為 `0015_character_state_revision`。 |
| 事件 | `combat.adjudication_requested` / `combat.adjudication_resolved` / `combat.damage_applied` / `combat.healing_applied` / `combat.saves_requested` / `combat.save_resolved` / `combat.death_save_resolved` / `combat.special_attack_adjudication_requested` / `combat.special_attack_adjudicated` / `combat.special_attack_roll_resolved`；attack / save / death save 的 roll 本身沿用 P3-C `roll.requested` / `roll.resolved`，attack outcome 寫在 `roll.resolved` payload 與 `combat_actions.resolution_result`。 |
| HTTP | 同 P4-B prefix 下新增 `GET /entries/{entry_id}/attacks`、`POST /attacks/request`、`/attacks/adjudicate`、`/attacks/roll`、`/saving-throws/request`、`/saving-throws/roll`、`/death-saves/request`、`/death-saves/roll`、`/damage`、`/healing`；`/combat/special-attacks/request`、`/adjudicate`、`/roll`。Human-only，只做 actor resolution + DTO + error mapping。 |
| MCP | 14 個 `combat_*` tool（`combat_get_active` / `combat_list_attacks` / `combat_request_attack` / `combat_adjudicate_attack` / `combat_roll_attack` / `combat_apply_damage` / `combat_apply_healing` / `combat_request_saving_throws` / `combat_roll_saving_throw` / `combat_request_death_save` / `combat_roll_death_save` / `combat_request_special_attack` / `combat_adjudicate_special_attack` / `combat_roll_special_attack`），adjudicate 與 `combat_request_saving_throws` 為 DM-only；`guide_tool_names.py` 與 M04-C catalog 測試同步更新。 |
| Writer guard | `test_character_state_writer_guard.py` allowlist 加入 `persistence/combat/attacks.py` / `core_rolls.py` / `resolution.py` / `special_attacks.py`：combat resolution 需在同一 transaction 內更新 Character Current State，屬刻意決定，且仍受 revision compare-and-set 保護（「Character State changed during semantic HP resolution」conflict）。 |
| P4-B contract 調整 | `test_p4b_combat_api_contract.py` 由 `actual == EXPECTED_ROUTES` 改為 `EXPECTED_ROUTES <= actual`，讓後續 Subphase 加 route 不需回改 P4-B 測試；M04-B / P3-C / P3-D migration chain 測試改以 `0025` 為 web head。 |
| Bot commits | `26124c5c`（cross-phase regression contracts）與 `bb8cb8c7`（contract evidence gaps）由 branch 上暫時的 GitHub Actions autofix workflow 產生，兩個 workflow 已分別在 `47679e47` / `c0996b41` 移除。兩次 diff 都經人工 review：前者只更新 successor-phase 常數與 allowlist，後者只新增測試與修訂文件。 |

## Verification 過程中修正的缺口

| # | 缺口 | 處理 |
|---|---|---|
| G1 | 測試指南 C.4.2 要求 damage 建立 Concentration save request，但實作規格第 14 點又把 concentration 留 P4-D，程式沒實作 | `bb8cb8c7`：實作規格第 5 點改為 Concentration canonical state 與 CON save request 留 P4-D，C.4.2 正式移至 D.3 |
| G2 | C.2「transaction failure 在 event append 前／後不留半套狀態」沒有 P4-C 專屬測試 | `bb8cb8c7`：`test_semantic_damage_transaction_failure_leaves_no_half_state`（真 PostgreSQL，parametrize before / after projection） |
| G3 | 第 1 點 Player 授權只靠 P4-B `_authorize_entry()` 的單元測試 | `bb8cb8c7`：`test_player_cannot_operate_enemy_combatant_or_directly_mutate_enemy_hp` |
| G4 | Character 抗性不套用未被文件承認 | `bb8cb8c7`：測試指南 C.1 明列為已知限制 |

## Verification evidence

分支 `p4-c-attack-damage-core-action-resolution`，最終 code SHA `c0996b41`。本 closeout 與 `PROJECT_BRIEF.md` 為其後的 docs-only commit。依 P4 subphase merge policy，關門後以 `--no-ff` 合併回 `main`。

```text
Alembic heads（apps/server: alembic heads）
  0015_character_state_revision (character) (head)
  0025_p4c_core_resolution (web) (head)

Backend pytest（全套，cwd apps/server，..\..\.venv\Scripts\python.exe）
  執行於 47679e47：1618 tests collected，exit 0，無 failure（-q 摘要行被輸出截尾吃掉，skip 數未記錄；
  skip 全為 PostgreSQL env-gated，同 P4-B）
  47679e47 → c0996b41 未動 apps/server/app，只新增 3 支測試（見下列 focused 結果）

Focused P4-C backend（c0996b41，本機，PG env 全開）
  tests/test_p4c_resolution.py 14（含 attack roll 6 列、death save 8 列 parametrize）
  tests/test_p4c_adjudication.py 3
  tests/test_p4c_core_rolls.py 2
  tests/test_p4c_special_attacks.py 5
  tests/test_p4c_semantic_hp_boundary.py 1
  tests/test_p4c_mcp_adapter.py 4
  tests/test_p4c_postgres_concurrency.py 2（PG，含 before / after projection 2 列）
  tests/test_p4c_postgres_migration.py 2（PG）
  加 test_p4b_postgres_migration 2 / test_p4b_postgres_concurrency 1 / test_p4a_postgres_migration 3
  合計 54 passed / 0 skipped（26.5s）
  PG 以 docker postgres 上的一次性 scratch DB adventure_table_p4c_scratch 執行，跑完即 drop；
  未觸碰 daily adventure_table 與 adventure_table_e2e
  無 PG 的一輪（47679e47）：42 passed / 3 skipped

PostgreSQL gate（GitHub, P4-C Non-E2E Regression / postgres-migrations）
  47679e47 run 34955357543：success
  c0996b41 run 34963903132：success

Frontend unit / build（本 Subphase 未動 apps/web）
  本機 vitest 78 files / 381 passed；vite build success

docker compose config
  exit 0（本機）

GitHub Actions
  P4-C Non-E2E Regression @ 47679e47 run 34955357543：backend / postgres-migrations / frontend / compose-config 全 success
  P4-C Non-E2E Regression @ c0996b41 run 34963903132：backend / postgres-migrations / frontend / compose-config 全 success

E2E（Subphase 關門本身不需要：backend-only diff；以下為合併回 main 的 gate）
  本機 npm run test:e2e:docker（ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1，
  走 U01-A 的 adventure_table_e2e + server-e2e / web-e2e，rebuild server + web image）
  執行於 c0996b41 工作樹：
    主套件 127 tests：123 passed / 4 skipped（10.3m）
    disabled-pack 套件 7 tests：7 passed
  exit 0（第一輪同樣 exit 0，但輸出被截尾未留計數，故重跑一輪留證據）
```

## 已知限制 / 留給後續 Subphase

- Character 的 Resistance / Immunity / Vulnerability 不自動套用：Character Current State 沒有 machine-readable affinity 欄位，M01 種族抗性（Dwarf poison 等）目前由 DM 用 correction path 或口頭處理。要自動化需先在 Character State 加結構化欄位（M01 track）。
- Monster 到 0 HP 只在 resolution payload 帶 `monster_outcome_required=True`，沒有 DM 選 Dead / Unconscious / Surrendered / Other 的正式 outcome action；Monster Instance `combat_status` 與 P4-B `removed` 語意的連動留 P4-E。
- `end_combat()` 未重置 `combat_entries.death_save_*` 欄位。因 entry row 屬於該場 Combat、ended Combat 的 entry 不會被重用，實際無影響；P4-E 若要顯示歷史 Combat 摘要再決定是否清。
- Concentration trigger 未接：`apply_damage()` 回傳的 `DamageOutcome` 已含 P4-D 建 CON save request 所需的 HP transition，但沒有 caller。
- HTTP 層與 P4-B 同等級：route 集合、error mapping、DI 共享由測試涵蓋，沒有帶 Room access 的真請求 browser journey；由 P4-E Combat UI E2E 與 P4-F 整合補。
- Multiattack 仍依 P4-B `attacks_allowed=1`，Monster Multiattack 的 budget 消耗未特別處理。
- Grapple / Shove 的 `grappled` condition 只寫進 target state，沒有 grappler 移動時的自動連動或 escape action；P4-D conditions 一併處理。
