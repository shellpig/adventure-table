# P4-B Closeout Checklist

P4-B — Combat Lifecycle, Initiative & Action Economy closeout scope。編號對應 [實作規格](實作規格.md) 的「完成後必須為真」。

- [x] 1. 只有 current DM 可 Start / End Quick Combat。`CombatService.start_quick_combat()` / `end_combat()` 先過 `_require_dm()`；Player actor 呼叫兩者皆 `TableEventActorUnauthorizedError`（`test_only_current_dm_controls_combat_lifecycle_and_mode_is_fixed_quick`）。HTTP 層由 `_map_combat_error()` 對映 403 `table_actor_unauthorized`。
- [x] 2. Start 不需要 EncounterTemplate。`StartCombatInput(include_active_party=True)` 把本場每個 Player Seat 的 Active Character 直接建成 `combat_entries`；DM 之後可 `add_monster()`（Monster Instance / Quick Enemy）或 `add_character()` 加 mid-combat entrant；`include_active_party=False` 可建立只有敵人的 Combat。
- [x] 3. 同 Campaign 最多一場 active Combat。Service 先查 `get_active()`；DB 另有 partial unique index 鎖 `campaign_id WHERE status IN ('initiative_pending','running')`，重複 Start 轉成 `ActiveCombatExistsError`（409 `active_combat_exists`）。真 PostgreSQL 兩個 thread 同時 Start 只有一個成功、DB 只剩一場 active（`test_concurrent_start_quick_combat_has_one_database_winner`）。
- [x] 4. mode 建立時固定 `quick`。`StartCombatInput` 沒有 `mode` 欄位（`extra=forbid`，`{"mode":"tactical"}` 直接 ValidationError），`combats.mode` 由 DB CheckConstraint 鎖 `quick`；沒有任何 route / service 改 mode。
- [x] 5. Initiative 走既有 RollGroup / RollRequest substrate。`CombatInitiativeService.request_initiative()` 對每個 entry（或同 `initiative_group_key` 的一組 monster）建一張 `roll_requests`，新增 `target_combat_entry_id`；`complete_initiative()` 呼叫 P3-C `RollService` 產生 `roll_results`（`raw_dice` / `kept_dice` / `formula` / `base_modifier` / `subject_combat_entry_id`），再由 `record_initiative_result()` 把 total 寫回 entry。PC 公式 `1d20+DEX`（`test_pc_initiative_is_formal_d20_plus_character_dexterity_modifier`：raw 10、DEX +2、total 12）；advantage / disadvantage 走 `2d20kh1` / `2d20kl1`；group initiative 一張 request 綁多個 entry；tie 由 `tied_totals()` 揭露、DM 只能在同 total 內排序（`test_dm_can_only_adjudicate_ties_not_override_initiative_totals`）；surprise 見第 8 條；mid-combat entrant 由 `request_initiative(entry_ids=...)` + `CombatOrderService.reorder_running()` 插入 canonical order。Combat roll 不進舊 P3 Check list / resume projection（`CombatAwareRollRepository`）。
- [x] 6. Canonical state 可恢復。`combats`：`status` / `round_number` / `current_turn_entry_id` / `revision`；`combat_entries`：`turn_order` / `initiative_total` / `initiative_roll_request_id` / `initiative_roll_result_id` / `surprised` / `action_available` / `bonus_action_available` / `reaction_available` / `attacks_allowed` / `attacks_used` / `ready_state` / `pending_reaction_state` / `is_hostile` / `status`。Session B 的 `get_active_combat()` 拿到與 Session A 完全相同的 round / current turn / entry 順序與 economy（`test_lifecycle_midcombat_reorder_and_cross_session_resume`、`test_changed_party_and_abandoned_session_do_not_rebind_or_clear_combat`）。
- [x] 7. Turn advance 是 Server transaction。`CombatRepository.advance_turn()` 在 `with_for_update` 下依 `turn_order` 取下一個 active entry、必要時 round+1、重置該 entry 的 economy，並寫 `combat.turn_advanced` event；client 沒有任何寫 `current_turn_entry_id` 的入口。
- [x] 8. Action economy 與 surprise 由 Server 驗。`consume_action()`：Action / Bonus Action 只能在 `current_turn_entry_id == entry_id` 時使用；Action / Bonus 各只能消耗一次；Extra Attack 以 `attacks_used < attacks_allowed`（Fighter 5 fixture = 2）計；Reaction 需 `reaction_available` 且 `pending_reaction_state.open`，可在他人 Turn 使用，於自己下一 Turn 開始恢復；`surprised` entry 不能用 Action / Bonus Action、`reaction_available=False`，自己第一個 Turn 結束時由 `advance_turn()` 解除（`test_surprise_blocks_first_turn_economy_and_clears_when_own_turn_ends`）。DM proxy 消耗 subject entry 自己的 economy：`execution_mode="dm_proxy"`、`subject_seat_id` 為 Player Seat，`acting_seat_id` 為 DM（`test_turn_action_bonus_reaction_extra_attack_and_round_refresh`）。Player 在非自己 Turn 提交 Attack 被 409 拒絕。
- [x] 9. Dash / Disengage 只消耗 Action。`CombatActionKind.DASH` / `DISENGAGE` 鎖 `economy_cost=ACTION`（`test_structured_actions_cannot_bypass_action_economy`），`combat_actions.payload` 為 `{}`、沒有任何 movement 欄位；是否避開 OA留 DM。
- [x] 10. Dodge / Search / Ready / Freeform 有最小 representation。`CombatActionKind` = `attack_budget / dash / disengage / dodge / search / ready / freeform`；structured kind 鎖定 economy cost，`FREEFORM` 可帶 `none / action / bonus_action / reaction` 但仍過同一個 economy validator，不能繞過 turn invariant；`READY` 的 intent 寫進 `ready_state`，於下一 Turn 開始或 End Combat 清除。
- [x] 11. Combat 跨 Session。`combats` 是 Campaign-scoped，`started_session_id` / `ended_session_id` 只是 audit；Session End / Abandon 不碰 `combats` / `combat_entries`。`_authorize_entry()` 以 Character 為 identity、每次用本場 `TableActorContext` 重新 resolve controller：同一 Character 本場仍有 Seat → 該 Player 以 `self` 操作既有 entry、不新增 duplicate（`test_same_character_in_next_session_keeps_existing_entry_authority`）；Character 本場缺席 → 任何 Player `TableEventActorUnauthorizedError`，current DM 可 `advance_turn()` 跳過、`withdraw_entry()` / `remove_entry()` 或明確 proxy，audit `acting_seat_id=DM`、`subject_seat_id=None`、`subject_character_id=Character`，不偽造舊 Seat（`test_changed_party_and_abandoned_session_do_not_rebind_or_clear_combat`、`test_p4b_combat_authority.py`）；新 Session 換上的新 Character 不自動進 Combat，只有 DM `add_character()` + initiative + reorder 後才進 order。
- [x] 12. 只有 current DM 可 End Combat；沒有 hostile 只提示。`combat_entries.is_hostile`（Monster entry = True、Character entry = False）；`CombatView.warnings` 在 active Combat 沒有 `status='active' AND is_hostile` entry 時帶 `"no_hostile_combatants"`，Combat 仍是 `running`，不自動 end（`test_withdraw_remove_and_no_hostile_warning_do_not_auto_end_combat`）。
- [x] 13. End Combat 只清 combat bookkeeping。`end_combat()` 把 `combats.round_number` / `current_turn_entry_id` 設 NULL、`status='ended'`，每個 entry 的 initiative request / result / total、`turn_order`、`surprised`、action / bonus / reaction、`attacks_used`、`ready_state`、`pending_reaction_state` 全部重置；`monster_instances.current_hp` / `temp_hp` / `conditions` / `resources` 與 Character Current State 不動（`test_end_combat_clears_only_combat_bookkeeping`）。Death Save cleanup 由 P4-C 引入 death save 時接在同一個 `end_combat()` projection。
- [x] 14. 不做 attack / damage / spell resolution。`attack_budget` 只計 Extra Attack 次數，沒有 to-hit / damage 計算；沒有 spell、condition、concentration 表；`CombatEntryView` 不含 HP / AC，P4-A 的 `project_combatant()` secrecy projection 未被本 Subphase 的 view 繞過。

## 契約以外的實作決定

| 項目 | 決定 |
|---|---|
| Migration | `0023_p4b_combat_lifecycle`（`combats` / `combat_entries` / `combat_actions`，接 `0022_p4a_monster_instances`）、`0024_p4b_combat_roll_targets`（`roll_requests.target_seat_id` / `roll_results.subject_seat_id` 改 nullable，新增 `target_combat_entry_id` / `subject_combat_entry_id` FK → `combat_entries` ON DELETE CASCADE，`ck_roll_requests_target_present` 保證至少一個 target）。character track head 仍為 `0015_character_state_revision`。`is_hostile` 是在 branch 未合併前直接加進 `0023`，沒有任何環境用過舊版 0023。 |
| 事件 | `combat.started` / `combat.entry_added` / `combat.initiative_ordered` / `combat.initiative_reordered` / `combat.turn_advanced` / `combat.action_used` / `combat.reaction_window` / `combat.entry_withdrawn` / `combat.entry_removed` / `combat.ended`；initiative request / resolve 沿用 P3-C 的 `roll.requested` / `roll.resolved`。全部走 P3 `TableEventRepository.append(transaction_projection=...)`，state 與 event 同 transaction。 |
| HTTP | `/api/rooms/{room_id}/campaigns/{campaign_id}/sessions/{session_id}/combat` 底下 16 條 route（GET active、start、entries/characters、entries/monsters、initiative/request、initiative/roll、initiative/suggested-order、initiative/ties、initiative/finalize、initiative/reorder、turn/advance、actions、reaction-window、entries/{id}/withdraw、entries/{id}/remove、end）；只做 actor resolution + DTO + error mapping，Human-only，AI / MCP tool surface 留 P4-E。 |
| DI | `get_combat_service` / `get_combat_initiative_service` / `get_combat_order_service` 掛在 `app.state` cache；`get_roll_service` 改用 `CombatAwareRollRepository`，P3 Check 路徑不變。 |

## Static review findings 與處理

| # | Finding | 處理 |
|---|---|---|
| R1 | Extra Attack 第 2 擊可繞過 `action_available`；structured action 可用 `economy_cost=none` 繞 economy | `d95468da` / `512b463b`：`CombatActionInput` model validator 鎖 structured kind 的 cost |
| R2 | DM `resolve_initiative_order()` 可任意覆蓋 initiative total 順序 | `17911ad0` / `3c3e0da5`：只允許同 total 內調整，running reorder 保留 totals |
| R3 | 缺席 Character 的 DM proxy 沒有合法路徑 | `57548655`：`_authorize_entry()` 對無 current Seat 的 Character entry 允許 DM `dm_proxy`，`subject_seat_id=None` |
| R4 | surprise 只有欄位沒有 enforcement | `b6e287a8`：`consume_action()` / `advance_turn()` / `_insert_entry()` / `resolve_initiative_order()` 全部看 `surprised` |
| R5 | `withdraw_entry` 無測試、`removed` 無 service | `9dbdfb47` / `7c5538ab`：`_set_entry_status()` 共用，`remove_entry` + route |
| R6 | 「沒有 hostile 只提示」未實作 | `5e9bd339` / `0fb1e326` / `a1d7ef4a`：`is_hostile` 欄位 + `CombatView.warnings` |
| R7 | reaction 無 window 路徑無測試 | `d7c02fc2`：`test_p4b_lifecycle_gaps.py` |
| R8 | `p3c_runtime.py` metadata 缺 0024 的 FK | `5a47a27f` / `1d52e518` / `73d68d33`：metadata 補 FK，`test_p4b_metadata_parity.py` 對 migration 比對 |
| R9 | HTTP 層零測試 | `4aad426f` / `4f33bff9`：route 集合、main app OpenAPI mount、error code、DI cache |
| R10 | 測試指南 B.4 第一條「同一 Character 續控 existing entry」缺測試；`test_p4b_session_boundaries.py` inline `__import__` | `0f369bdd`：`test_same_character_in_next_session_keeps_existing_entry_authority`，改 top-level import |

## Verification evidence

分支 `p4-b-combat-lifecycle-initiative-action-economy`，最終 code SHA `0f369bdd`。本 closeout 與 `PROJECT_BRIEF.md` 為其後的 docs-only commit。依 [實作規格](實作規格.md) 第 11 條，關門後以 `--no-ff` 合併回 `main`。

```text
Alembic heads（apps/server: alembic heads）
  0015_character_state_revision (character) (head)
  0024_p4b_combat_roll_targets (web) (head)
  0023 接 0022_p4a_monster_instances，0024 接 0023；character track 未變。

Backend pytest（全套，執行於 4f33bff9 + 0f369bdd 工作樹，cwd apps/server，..\..\.venv\Scripts\python.exe）
  1527 passed / 45 skipped（593s）@ 4f33bff9；0f369bdd 只新增 1 支測試，focused 22 passed
  skip 全為 PostgreSQL env-gated（M03B / M03C / P2 / P3 / P4-A / P4-B），本機未設對應 URL

Focused P4-B backend（0f369bdd，本機）
  tests/test_p4b_combat_lifecycle.py 2
  tests/test_p4b_initiative_economy.py 2
  tests/test_p4b_pc_initiative.py 1
  tests/test_p4b_initiative_order_invariants.py 1
  tests/test_p4b_permissions_cleanup.py 3
  tests/test_p4b_combat_authority.py 3
  tests/test_p4b_session_boundaries.py 2
  tests/test_p4b_lifecycle_gaps.py 2
  tests/test_p4b_combat_api_contract.py 4
  tests/test_p4b_metadata_parity.py 2
  tests/test_p4b_postgres_concurrency.py 1（PG）
  tests/test_p4b_postgres_migration.py 2（PG）
  合計 25：本機無 PG 22 passed / 3 skipped；PG 3 支加 test_p4a_postgres_migration 3 支
  以 docker postgres 上的一次性 scratch DB adventure_table_p4b_scratch 執行 6 passed，
  跑完即 drop；未觸碰 daily adventure_table（0021）與 adventure_table_e2e（0022）

PostgreSQL gate（GitHub, P4-B Non-E2E Regression / postgres-migrations）
  4f33bff9 run 34938109709：success（涵蓋 0022 → 0023 → 0024 upgrade / downgrade、concurrency、P3 / P2 / M03C legacy PG suites）

Frontend unit / build（本 Subphase 未動 apps/web）
  本機 vitest 381 passed；vite build success

docker compose config
  exit 0（本機）

GitHub Actions
  P4-B Non-E2E Regression @ 4f33bff9 run 34938109709：backend / postgres-migrations / frontend / compose-config 全 success
  P4-B Non-E2E Regression @ 0f369bdd run 34941921735：backend / postgres-migrations / frontend / compose-config 全 success

E2E（Subphase 關門本身不需要：backend-only diff；以下為合併回 main 的 gate）
  本機 npm run test:e2e:docker（ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1，
  走 U01-A 的 adventure_table_e2e + server-e2e / web-e2e，rebuild server + web image）
  執行於 0f369bdd 工作樹：
    主套件 127 tests：123 passed / 4 skipped（9.9m）
    disabled-pack 套件 7 tests：7 passed
  exit 0
```

## 已知限制 / 留給後續 Subphase

- `is_hostile` 目前只由 subject kind 決定（Monster = hostile、Character = friendly），DM 無法把友方 NPC Monster 標成 non-hostile 或把 Character 標成 hostile；`no_hostile_combatants` warning 因此只在「沒有 active Monster entry」時出現。要開放 DM 切換時在 P4-E UI 接線一併做。
- HTTP 層測試只驗 route 集合、OpenAPI mount、error code 對映與 DI 共享，沒有帶 Room access 的真請求 journey；與 P3-C 同等級。真請求證據由 P4-E Session table Combat UI 的 E2E 與 P4-F 整合補。
- `combat_entries.status='removed'` 與 `withdrawn` 目前語意相同（都離開 turn order、保留 row），只差 event kind；P4-C 引入 0 HP / dead 後再決定 `removed` 是否連動 Monster Instance `combat_status`。
- Reaction window 只有 DM 手動 `set_reaction_window()`；Ready trigger、OA 等自動開窗留 P4-D。
- `attacks_allowed` 只從 Character Extra Attack feature 算；Monster Multiattack 仍是 `attacks_allowed=1`，由 P4-C 的 action resolution 決定 Multiattack 怎麼消耗 budget。
- `test_p4b_combat_authority.py` 用 `SimpleNamespace` stub 驗 `_authorize_entry()`，屬 domain 單元測試；整合證據在 `test_p4b_session_boundaries.py`。
