# P4-D Closeout Checklist

P4-D — Spells, Conditions, Concentration & Reactions closeout scope。編號對應 [實作規格](實作規格.md) 的「完成後必須為真」；D.0～D.5 對應 [測試指南](測試指南.md)。

- [x] 1. Spell Skeleton：`SpellResolutionSpec` 支援 `cast_mode = attack | save | heal | utility`、`save_damage_mode = none | half`、`concentration`、`apply_effects`、upcast（`minimum_slot_level` + `slot_level`）；AoE 走 `aoe_adjudication` 的 identity target list。單體 `resolve_spell` 對 attack / save / heal 分支走 P4-C `resolve_attack_roll` / `apply_damage` / `apply_healing`，save-for-half 保留 damage type 再過 affinity（`test_p4d_d1_save_half_retains_damage_types`、`test_p4d_single_target_attack_and_heal_resolution`）。
- [x] 2. Cast Spell 只用既有 Character rules / Current State：`authorize_character_spell()` 讀 `CharacterBuild.spellcasting_profiles` / `spell_access_entries` 與 `CharacterState.prepared_spells` / legacy `prepared_spell_entry_ids`，normal multiclass slot 走 `state.spell_slots`、Pact Magic 走既有 `pact_resource_key()` counter，兩池不合併（`test_p4d_d1_prepared_normal_slot_spend_and_upcast`、`test_p4d_d1_known_pact_magic_stays_separate_from_normal_slots`）；未 prepared 在扣資源前就被拒（`test_p4d_d1_unprepared_spell_fails_before_resource_spend`）。Monster casting source 讀 P4-A `rules_snapshot.traits[].spellcasting`（`modifier` / `dc` / `slots` / `spells[].url`）與 instance live `resources`，不偽造 Character class source；SRD `mage` 實 snapshot 可 resolve（`test_p4d_d1_monster_spell_source_uses_p4a_snapshot_and_live_resource`）。Combat layer 沒有第二套 slot 計算：AoE 與單體 persisted cast 都經 `authorize_character_spell` → `spend_character_spell`。
- [x] 3. AoE 由 acting user 提 target identity、DM confirm 後才 resolve：`propose_aoe` / `confirm_aoe`（confirmed ⊆ proposed、不可空）；`CombatSpellRepository.propose_character_aoe` 進 `dm_adjudication_required`，`resolve_character_aoe` 在同一 transaction 建 group saves（每 target 一張 `roll_requests` + `roll_results`）、依成功／失敗分支套 damage、扣一次 slot。Server 沒有 radius / coordinate / cell（`test_p4d_d2_aoe_requires_confirmation_and_resolves_each_confirmed_target_once`、`test_aoe_spell_resolution_is_atomic_durable_and_idempotent`）。
- [x] 4. Concentration 由 Server canonical state 追蹤：`CharacterState.concentration`（`source_ref` + `effect_ids`）。開始新 concentration 結束舊的並移除 linked effects（domain `resolve_spell`；persisted cast 透過 `effects.strip_linked_effects` 連其他 combatant 上的 effect 一起清）。受傷後 `CombatResolutionRepository.apply_damage` 對正在 concentrating 的 Character 建 `label="Concentration"` 的正式 CON `roll_requests`，DC = `max(10, damage // 2)`，0 damage 不建（`test_p4d_d4_zero_damage_does_not_trigger_concentration_check`、`test_damage_concentration_request_is_atomic_durable_and_idempotent`）；`CombatConcentrationRepository.complete_check` 消費該 request，失敗清 pointer 與所有 combatant 上的 linked effects / conditions（`test_p4d_d4_concentration_replacement_and_damage_failure_cleanup`、`test_single_target_spell_cast_is_atomic_durable_and_idempotent` 末段）。`end_combat()` 不碰 `CharacterState.concentration`。
- [x] 5. 2014 Conditions 全 14 個 + Exhaustion：`Condition` enum 與 `CONDITION_SEMANTICS` 逐一定義；每個都有 content registry entry 與 zh-TW name（`test_p4d_d3_all_2014_conditions_have_semantics`、`test_p4d_d4_every_condition_has_registry_entry_and_zh_tw_name`）；Exhaustion 1～6 累積與 recovery（`test_p4d_d3_exhaustion_is_cumulative_and_recovers`）。
- [x] 6. Conditions 不是 icon-only：`ConditionSemantics` 為 typed flags（blocks_actions / speed_zero / attacks_disadvantage / auto_fail_*_saves / adjacent_hit_is_critical / damage_resistance_all …），需要來源可見性、5 呎距離等 contextual rule 的以 conditional flag 表達而非猜 geometry。`condition_to_state` / `condition_from_state` 對應 `srd5.1:condition:*` stable key（`test_condition_adapter_uses_canonical_stable_key`）。沒有 universal effect DSL。
- [x] 7. Temporary Effects：`TypedModifier(scope = ac | speed | attack | save | check | damage, mode = bonus | advantage | disadvantage)` 與 `DurationSpec`（rounds / until turn start / end / short rest / long rest / concentration / manual / instant），`expire_effects()` 依 boundary deterministic 過期（`test_p4d_d3_typed_effect_modifier_and_expiry`）。Speed scope 存在但 P4 Quick 不算 movement feet。
- [x] 7a. Shared Character Current State additive 擴充：`concentration` / `exhaustion_level` / `death_saves` / `temporary_effects` 與 `conditions[].effect_id`，全部 default-safe，不 reference Room / Session / Combat row（`test_m03b_schema_inventory.py` NON_REF_STATE_FIELDS 逐欄登記；`content_ref_walker` 走 `concentration.source_ref` / `temporary_effects[].source_ref`）。`combat_entries` 只留 initiative / economy / surprise / `ready_state` / `pending_reaction_state` / death-save bookkeeping。round / turn-bounded effect 不可靜默降級進 CharacterState（`test_round_bounded_effect_is_not_silently_degraded_in_character_state`）。
- [x] 7b. Character JSON `schema_version="1"` 不變；`{"current_hp": 7}` 這種舊 payload 得到 backward-compatible defaults（`test_p4d_d0_character_state_additive_defaults_and_roundtrip`）；既有 v1 / legacy unstable fixture import 測試（`test_m03c_commit.py`、`test_p2a_legacy_fixture.py`）全綠；新欄位 Web → Standalone → Web export/import 不遺失（`test_p4d_d0_new_state_fields_survive_web_standalone_roundtrip`）。無 DB migration：`character_states.state_payload` JSON 直接承載。
- [x] 8. ReactionRequest durable：`ReactionWindow`（trigger kind / source / eligible set / optional target / safe-secret payload / status / session_ref）存在 `combat_entries.pending_reaction_state`，`CombatReactionRepository.set_window` / `get` / `resolve_window` 走 P3 event projection；新 repository instance reload 得到同一 window、accept 驗 controller eligibility 與 `reaction_available` 並消耗 reaction、重複 resolve 被拒、retry 不重扣（`test_p4d_d5_reaction_payload_roundtrip_and_single_resolution`、`test_reaction_window_survives_reload_and_retry_without_double_spend`）。
- [x] 9. Quick OA 不自動偵測：`open_opportunity_attack_window` 沒有 DM adjudication 就 `PermissionError`；movement prose 不產生 geometry 判斷（`test_p4d_d5_opportunity_attack_is_dm_adjudicated_only`）。
- [x] 10. Ready 用同一 reaction substrate：Ready 宣告走 P4-B `declare_action(action_kind=ready)`（消耗 Action、payload 寫 `combat_entries.ready_state`），P4-D `ReadyState` 是該 payload 的 typed shape（trigger / response / 可選 spell_ref + slot / concentration_started），自由文字 trigger 由 DM 判斷；owner 下一 turn 開始時 lifecycle 重置 `ready_state`，即 durable expiry，不退已消耗的 action / slot（`test_p4d_d5_ready_roundtrip_and_owner_turn_expiry_no_refund`；P4-B `test_p4b_permissions_cleanup.py` 的 ready reset）。
- [x] 11. Lightweight Legendary Action：只在其他 creature turn end 可用、扣 durable resource；lair / 特殊 timing 留 description + DM（`test_p4d_d5_legendary_action_requires_other_creature_turn_end_and_resource`）。
- [x] 12. 原子提交與 idempotent retry：spell cast（單體 `cast_character_spell`、AoE propose / resolve）、concentration check、reaction resolve 全部是一個 `TableEventRepository.append(transaction_projection=...)`，state mutation 走 `character_states` revision CAS（writer guard allowlist 登記 `spells.py` / `concentration.py` / `effects.py`），同 `idempotency_key` retry 回同一 action / event、slot 與 HP 不重扣、roll rows 不重建、`combats.revision` 不變（`test_single_target_spell_cast_is_atomic_durable_and_idempotent`、`test_aoe_spell_resolution_is_atomic_durable_and_idempotent`、`test_damage_concentration_request_is_atomic_durable_and_idempotent`、`test_reaction_window_survives_reload_and_retry_without_double_spend`）。

## 契約以外的實作決定

| 項目 | 決定 |
|---|---|
| Migration | 無。P4-D 新增的 PC truth 全部 additive 進 `character_states.state_payload` JSON；reaction / ready 用 P4-B 既有 `combat_entries.pending_reaction_state` / `ready_state`；AoE / cast 用 P4-C `combat_actions`（`action_kind = spell_aoe | spell_cast`）。Alembic heads 仍為 `0015_character_state_revision` / `0025_p4c_core_resolution`。 |
| 事件 | `combat.spell_aoe_adjudication_requested` / `combat.spell_aoe_resolved` / `combat.spell_cast_resolved` / `combat.concentration_resolved` / `combat.reaction_requested` / `combat.reaction_resolved`（P4-B 的 `combat.reaction_window` 保留給舊 dict 路徑）；damage 觸發的 CON save 附在 `combat.damage_applied` payload 的 `concentration_check`。 |
| Effect 落點 | 單體 cast 的 `applied_effects` 落在 target（Character `temporary_effects` + `conditions[].effect_id`；Monster `effects[]` + `conditions[].effect_id`），caster 只存 `concentration.effect_ids`。`effects.strip_linked_effects` 在 concentration 被取代或 CON save 失敗時掃同場所有 active entry 移除。 |
| 表面 | 本 Subphase 只到 repository / domain；REST、realtime、MCP、Human UI 依 P4 拆分本來就屬 P4-E。P4-E 對 P4-D 的三個交接項已寫進正式三份文件（實作規格 P4-E 14–16、開發設計方針 8.5、測試指南 E.5）。 |
| 非正式紀錄 | `P4-D實作紀錄.md` 是實作期間的工作紀錄，不是契約；契約與驗收以三份 P4 文件與本 closeout 為準。 |
| Test 調整 | `test_m03c_commit.py` 由 byte-equality 改為 `CharacterState.model_validate` canonical 比較（additive 欄位進 dump）；`test_m01f_http_closeout.py` 的 condition literal 補 `effect_id: None`。兩者都是 additive 欄位造成，不改既有語意。 |

## Verification 過程中修正的缺口

| # | 缺口 | 處理 |
|---|---|---|
| G1 | 首版 P4-D 只有純 domain 模組，零 persistence / caller；Monster casting source 讀不存在的 `rules_snapshot["spellcasting"]`，對 SRD `mage` 直接 `ValueError`；AoE resolver 自己扣 slot | `ef61f5c9`～`09331937`：改讀 `traits[].spellcasting`、AoE / cast 走 `authorize_character_spell` / `spend_character_spell`、concentration 改用 canonical `CharacterState` |
| G2 | 新接線無 DB-backed 測試；CON save request 建了但沒有 consumer | `993f3635`～`4cc6c99e`：`persistence/combat/spells.py` / `concentration.py` / `reactions.py` + `test_p4d_persistence.py` |
| G3 | `fd8b4c0d` 在 `CombatRepository` 留下未測試的重複 reaction methods | `9e26034e` 移除 |
| G4 | 單體 spell（attack / heal / save）只有 domain resolve，沒有 persisted command；concentration 結束不會清其他 combatant 上的 linked effects | `19c67ff7`：`cast_character_spell` + `effects.strip_linked_effects`，`ConditionState.effect_id` |
| G5 | D.4 registry / locale 與 D.0 Web↔Standalone roundtrip 沒有 P4-D 專屬證據 | `38620d46`：`test_p4d_closeout_contracts.py` |

## Verification evidence

分支 `feat/p4d-spells-effects-reactions`，最終 code SHA `38620d46`。本 closeout 與 `PROJECT_BRIEF.md` 為其後的 docs-only commit。依 P4 subphase merge policy，關門後以 `--no-ff` 合併回 `main`。

```text
Alembic heads（apps/server: alembic heads）
  0015_character_state_revision (character) (head)
  0025_p4c_core_resolution (web) (head)

Backend pytest（全套，cwd apps/server，..\..\.venv\Scripts\python.exe）
  38620d46 本機：exit 0，無 failure；skip 全為 PostgreSQL env-gated（P2 / P3 / P4-A / P4-B / P4-C 的 *_postgres_* 測試，
  由 GitHub postgres-migrations job 執行）

Focused P4-D backend（38620d46，本機）
  tests/test_p4d_spells_effects_reactions.py 18
  tests/test_p4d_effect_adapters.py 4
  tests/test_p4d_persistence.py 5
  tests/test_p4d_closeout_contracts.py 2
  合計 29 passed

PostgreSQL gate（GitHub, P4-D Non-E2E Regression / postgres-migrations）
  38620d46 run 35085871458：success（另一 trigger run 35085863957 亦 success）
  b52ef31b（code 19c67ff7 + docs）run 35085122990 / 35085118190：success
  9e26034e run 35080667791：success

Frontend unit / build（本 Subphase 未動 apps/web）
  本機 vitest 78 files / 381 passed；vite build success

docker compose config
  exit 0（本機）

GitHub Actions
  P4-D Non-E2E Regression @ 38620d46 run 35085871458：backend / postgres-migrations / frontend / compose-config 全 success
  P4-C Non-E2E Regression @ 38620d46 run 35085871568：success（cross-phase regression）
  P4-B Non-E2E Regression @ 38620d46 run 35085871515：success（cross-phase regression）

E2E（Subphase 關門本身不需要：backend-only diff；以下為合併回 main 的 gate）
  本機 npm run test:e2e:docker（ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1，
  走 U01-A 的 adventure_table_e2e + server-e2e / web-e2e，rebuild server + web image）
  執行於 b52ef31b 工作樹（apps/server/app 與 38620d46 完全相同，38620d46 只多一支 backend 測試檔）：
    主套件 127 tests：123 passed / 4 skipped（9.2m）
    disabled-pack 套件 7 tests：7 passed
  exit 0
```

## 已知限制 / 留給後續 Subphase

- **Monster caster 沒有 persisted cast**：`resolve_monster_spell_source` / `resolve_monster_spell` 只到 domain；P4-E 實作規格第 14 點。
- **Monster 沒有 concentration canonical state**：`apply_damage` 的 monster 分支不建 CON save；P4-E 實作規格第 15 點。
- **Concentration CON save 必須由 `CombatConcentrationRepository.complete_check` 消費**：它是普通 `roll_requests` row，P3-C 通用 roll resolve 目前不會拒絕它；P4-E 實作規格第 16 點。
- 單體 cast 的 `target_ac` / `save_modifier` 與 AoE 的 `save_modifiers` 由 caller（P4-E service）依 rules 算好傳入，repository 不算 AC / save modifier，與 P4-C attack repository 同一模式。
- Character state PATCH DTO（`/characters/{id}/state`）尚未 expose `concentration` / `exhaustion_level` / `death_saves` / `temporary_effects`；DM Direct Edit 這些欄位屬 P4-E UI surface。
- `ConditionSemantics` 已定義但 P4-C attack / save 計算尚未讀它（advantage / disadvantage / auto-fail 未自動套用）；P4-E 接 UI 時一併接進 attack / save modifier pipeline，或明列為 P4-F 項目。
- P4-C 留下的 Monster 0 HP outcome action、`grappled` escape、Character affinity 欄位仍未處理，歸屬 P4-E / M01。
