# P4-E — Quick Combat UI, DM Adjudication & AI Tool Surface 實作紀錄

最後更新：2026-09-17

## 目標與邊界

本紀錄對齊 `實作規格.md` P4-E（1～16）、`開發設計方針.md` §8、`測試指南.md` P4-E（E.1～E.5）。P4-E 把 P4-A～D 的 Combat Engine 接成真人與外部 AI 都能跑的桌面體驗；不得建立第二套規則引擎、不做 geometry、不提前建 P6 Adventure / Scene runtime。

實作以步驟切分，每步獨立可驗證、獨立 commit；步驟由 agy worker 執行、Claude 審 diff / 跑 focused test / commit。每步完成後更新下表。

## 步驟進度

| 步 | 內容 | 對應契約 | 狀態 |
|---|---|---|---|
| E1 | Monster persisted cast：`CombatSpellRepository.cast_monster_spell` | 實作規格 14；設計 §8.5「Monster cast」；測試 E.5 第 1 點 | ✅ |
| E2 | Monster concentration canonical state + 受傷 CON save | 實作規格 15；設計 §8.5「Monster concentration」；測試 E.5 | ✅ |
| E3 | Concentration roll routing：通用 resolve 拒絕，只走 `complete_check` | 實作規格 16；設計 §8.5「Concentration roll routing」；測試 E.5 | ✅ |
| E4a | Combat detail projection + `GET .../combat/detail`：DM 完整 vs Player secrecy | 實作規格 2、3；設計 §4.3、§8.1；測試 E.2（REST） | ✅ |
| E4b | Event payload projector + 既有 P4-C mutation response 對 Player 的 redaction | 設計 §8.2「Player-safe event payload」；測試 E.2（event / response） | ✅ |
| E5 | Spell / reaction / concentration REST route | 實作規格 7、11；設計 §8.1、§8.2 | ✅ |
| E6 | DM adjudication REST（range / cover / AoE / OA） | 實作規格 5；設計 §8.3 | ✅ |
| E7a | Monster Instance REST（DM-only：from-content / quick-enemy / list） | 實作規格 7、10；設計 §4.2 | ✅ |
| E7b | Combat MCP tools：lifecycle / monster / initiative / turn / action | 實作規格 8、10、11；設計 §8.4；測試 E.3 | ✅ |
| E7c | Combat MCP tools：spell / reaction / concentration / adjudication + `get_combat_context` | 實作規格 8、10、11；設計 §8.4；測試 E.3 | ⬜ |
| E8 | `get_session_context` / briefing Combat context | 實作規格 9；設計 §8.6；測試 E.4 | ⬜ |
| E9 | Session page：Combat Header + Initiative + Combatants UI | 實作規格 1、2、4、6；測試 E.1 | ⬜ |
| E10 | Quick Action Bar + target 選擇 + adjudication UI | 實作規格 4、5；測試 E.1 | ⬜ |
| E11 | Chat / Log 呈現 + 雙語 copy + guide | 實作規格 12、13；測試 E.4 | ⬜ |
| E12 | focused E2E spec + Subphase 關門 gate | 測試指南 P4-E 全段 | ⬜ |

步驟粒度可在實作中再切；新增子步以 `E9a` 之類接續，不重編已完成項目。

## 步驟紀錄

### E1 — Monster persisted cast

- 起始：2026-09-16，agy worker（Gemini 3.8 Flash High）；兩輪：實作 + refactor。
- 交付：`CombatSpellRepository.cast_monster_spell`，走 `resolve_monster_spell_source` + `resolve_monster_spell`，扣 `monster_instances.resources`、target state、roll record、`combat_actions`、event 同一 transaction；`attack_modifier` / `save_dc` 未傳時 fallback 到 stat block；self-target / utility 的 effects 落在 caster 自己的 `effects[]`。
- 與 `cast_character_spell` 共用五個 private helper（`_load_spell_target`、`_write_spell_target_state`、`_insert_spell_formal_roll`、`_request_concentration_check_for_damaged_character`、`_write_spell_action_and_event`）+ `_append_monster_effects_and_conditions`；Character 版行為與測試期望不變。
- 測試：`tests/test_p4e_monster_cast.py` 7 條（slot 扣一次 / duplicate idempotency / insufficient slot 零副作用 / 無 spellcasting / unknown spell / wrong caster kind / stat-block attack bonus fallback）。focused gate：p4e + p4d + p4c_resolution + m03 boundary 58 passed。
- 留給 E2：monster concentration pointer 未記錄（`TODO(E2)`）；留給 E3：Concentration roll routing。

### E2 — Monster concentration canonical state

- 起始：2026-09-16，agy worker 一輪（1054s）+ Claude 小清理。
- 交付：web migration `0026_p4e_monster_concentration`（`monster_instances.concentration` nullable JSON，同 `CharacterConcentrationState` 形狀；standalone / character track 不動）；`cast_monster_spell` 記錄 / 替換 concentration pointer 並以 `strip_linked_effects` 清舊 linked effects；`apply_damage` Character / Monster 分支共用同一段 CON save request 建立；`complete_check` 接受 Monster target，失敗清 pointer 與所有 combatant 的 linked effects；domain 新增 `evaluate_concentration_check` 供 Character / Monster 共用判定。
- 清理：`strip_monster_items` 改公開名；Monster concentration 一律在讀取點 normalize 成 `CharacterConcentrationState`，不在 domain 接 `Mapping`；移除 `create_instance` 未使用的 `concentration` 參數。
- 測試：`tests/test_p4e_monster_concentration.py` 8 條；`tests/test_p4e_postgres_migration.py` 2 條（`P4_POSTGRES_URL` gated）；既有 migration head 斷言更新到 `0026`。focused gate 108 passed。
- 留給 E3：Concentration roll routing（通用 resolve 拒絕 / 轉送）。

### E3 — Concentration roll routing

- 起始：2026-09-16，agy worker 一輪（709s）+ Claude 小清理。
- 實際漏洞：P3-C 通用路徑已由 `CombatAwareRollRepository` 在 DI 層擋掉 combat-targeted row，但 P4-C `CombatCoreRollRepository.complete_saving_throw` 會把 Concentration request 當一般 save 解掉、pointer 不清——這才是「靜默殘留」入口。
- 交付：新 domain service `CombatConcentrationService.complete_check`（`app/domain/combat/concentration.py`）：驗 Concentration request、沿用 P4-C `_authorize_roll` 規則（Monster target 只有 DM）、Character CON modifier 走 P3-C `modifier_resolver`、Monster 走共用 `monster_save_modifier`（自 `CombatCoreRollService` 抽到 `concentration_triggers.py`）、server / physical d20、已 resolved 時 replay 既有結果。`CombatCoreRollService.complete_saving_throw` 遇 Concentration request 轉送到該 service（DI 注入 `concentration_service`）；`CombatCoreRollRepository.complete_saving_throw` 與 `RollRepository.complete_request` 在 lock 內拒絕 label=`Concentration` 的 request，零副作用。`dependencies.py` 新增 `get_combat_concentration_service`。
- 清理：移除 `RollRepository.complete_request` 每次 formal roll 多打一次的 pre-lock label 查詢，只留 lock 內檢查。
- 測試：`tests/test_p4e_concentration_routing.py` 6 條；focused gate 103 passed，P3-C API / P3-E regression 62 passed。
- 備註：`get_resolution_event` 沿用 P4-D `_source_metadata` 的 session event Python 掃描方式（O(n)），未新增索引查詢；長場次可在 P4-F 收斂。

### E4a — Combat detail projection

- 起始：2026-09-16，agy worker 一輪（905s）+ Claude 重寫 `character_to_combatant`。
- 交付：`CombatantState` additive 加 `concentration` / `death_saves` / `exhaustion_level`（full projection 含，enemy allowlist 不變）；`character_to_combatant(character, *, entry, registry)`（max HP `calculate_max_hp`、AC `calculate_armor_class`、speed `effective_movement`、conditions 以 `condition_ref` 呈現、effects 以 `tag`）；`monster_instance_to_combatant` 可帶 `entry` 取 P4-B 的 initiative / reaction economy，並把 P4-D 型 `{condition_ref, effect_id}` 條目納入 public / hidden 名單；`StoredCombatEntry` 補讀 `is_hostile` 與 death-save 欄位；`CombatService.get_active_combat_detail` → `CombatDetailView`（`CombatView` + `combatants[]`，hidden enemy 對 Player 整筆省略）；route `GET .../sessions/{session}/combat/detail`。`CombatService` 改為必帶 `ContentRegistry`。
- 清理：拿掉 agy 版的 `getattr` / `Any` 防禦式寫法、`lru_cache` fallback registry、`NewCombatEntry.is_hostile` override（P4-B 契約：只由 subject kind 決定）與重複的 `/active/detail` route。
- 測試：`tests/test_p4e_combat_detail_secrecy.py` 7 條（DM 完整 / Player raw JSON key 缺席 / 自己角色精確 / hidden monster 省略 / 非本場 participant 拒絕 / DM+Player token REST / 無 active combat → null）。focused gate 106 passed。
- 未做（E4b）：event payload projection、既有 `POST /damage` 等 P4-C mutation response 對 Player 的 redaction；MonsterRevealState 尚未持久化（DM reveal 行為留 E6 / E10）。

### E4b — Player-safe event payloads and mutation responses

- 起始：2026-09-16，agy worker 一輪在 1434s 撞到 quota（429，partial：16 檔已改、測試未寫）；其餘由 Claude 收尾。
- 交付：各 combat repository 在 payload 寫入 `target_is_hostile` / `caster_is_hostile` / `target_injury_level`（write-time facts，DM 內容不變）；單一 projector `project_combat_event_payload(kind, payload, audience)`（`app/domain/combat/event_projection.py`）對 Player 移除 hostile target 的 HP / AC / resources / affinities / adjusted_by_type / hp_lost / temp_hp_absorbed 等精確欄位，保留 amount / hit / critical / injury level；掛在 `TableEventService._present(stored, actor=...)`——list / long-poll / Resume / MCP 全部經過同一點，`actor` 為必填（fail-closed）。`POST /damage` / `/healing` 改回 `SemanticResolutionView`，`AttackResolutionView` 對 Player 遇 hostile target 時 `target_ac` / `before_hp` / `after_hp` 為 None，`resolution_result` 走同一 projector；MCP adapter 直接 `model_dump(exclude_none=True)` 同一 view。`injury_level` 拆出 `calculate_injury_level(current, max, status)` 供 write-time 使用。
- 清理：移除 agy 在 `request_death_save` 加的壞掉 payload 重寫（`event_id` 未定義、death save 永遠是 Character）；`_present` / `_resolution_view` 的 `actor=None` 預設改為必填；兩處重複的 view 建構收成一份。
- 測試：`tests/test_p4e_event_secrecy.py` 7 條（Player event stream 無敵人 HP 但有 amount + injury level / long-poll 與 list 一致 / 友方 Character 精確 / stored resolution 對 Player 與 DM 的 view 差異 + DM REST / Player attack 結果與 `roll.resolved` event 無 AC、DM 有 / hostile caster spell payload 無 DC、modifier / 非 combat kind 不動）。gate 186 passed（含 P3-A/B/C/E/F、M04、P4-B/C/D regression）。
### E5 — Spell / reaction / concentration REST route

- 起始：2026-09-16；修復：2026-09-17。
- 交付：
  1. `SpellDefinitionResolver`（`app/domain/combat/spell_content_adapter.py`）：完整從 `ContentRegistry` 解析法術模式（Attack / Save / Heal / Utility）、升環與戲法 scaling 傷害骰（例如 `"8d6"`, `"1d10"`）、`"1d8 + MOD"` 治療加值、狀態效果，並由 Character（`spell_save_dc`、`spell_attack_modifier`、multiclass profile 匹配）與 Monster（`resolve_monster_spell_source`）權威解析 DC、Attack modifier、目標 AC 與目標豁免加值。
  2. `CombatSpellService`（`app/domain/combat/spell_service.py`）：整合 `SpellDefinitionResolver`；`CastSpellInput` 與 `ProposeAoeSpellInput` 收斂為純識別與配置欄位（繼承 `StrictModel`，`extra="forbid"`），徹底封閉 client 傳遞 `save_dc`、`attack_modifier`、`target_ac` 等 raw rule 參數的 escape hatch（違者 422 拒絕）。
  3. P3-C RNG 串接：所有 d20 與傷害骰全面經由 `roll_service.engine` 擲骰，淘汰 `random.randint`，且對敵人豁免嚴格限制不得由攻擊方 client 藉 `raw_dice` 指定數值。
  4. `CombatReactionService`（`app/domain/combat/reaction_service.py`）：封裝 `open_reaction_window`、`resolve_reaction`、`get_reaction_window`，處理反應窗口與 reaction economy，內部 locally 委派 `actor_binding` 避免循環相依。
  5. `CombatConcentrationRepository.drop_concentration` / `CombatConcentrationService.drop_concentration`（`app/persistence/combat/concentration.py` & `app/domain/combat/concentration.py`）：支援主動中斷專注，呼叫 `strip_linked_effects` 移除關聯效果並發送 `combat.concentration_changed` 事件。
  6. REST Routes 與 DI：
     - `POST .../combat/spells/cast`
     - `POST .../combat/spells/aoe/propose`
     - `POST .../combat/spells/aoe/resolve`
     - `POST .../combat/concentration/roll`
     - `POST .../combat/concentration/drop`
     - `POST .../combat/reactions/open`
     - `POST .../combat/reactions/resolve`
     - `GET .../combat/reactions`
     - DI providers：`get_combat_spell_service`、`get_combat_reaction_service`。
- 測試：`tests/test_p4e_spells_reactions_routes.py` 6 條（含 `test_cast_spell_rejects_raw_rule_fields_with_422`、Character single-target cast、Monster spell cast 與權限拒絕、AoE propose 與 resolve、Concentration drop 與 linked effects 移除、Reaction window open/resolve/get 完整生命週期）。
- 驗證：P4-E focused tests 41 passed (2 skipped for postgres)；`tests/test_m03_import_boundary.py` 5 passed；P4-B/C/D 回歸 48 passed。

### E6 — DM adjudication REST（range / cover / AoE / OA）

- 起始：2026-09-17，agy worker 一輪（715s）+ 一輪 review 修正（1263s）+ Claude 小清理。
- 既有 substrate：P4-C 已有 range（attack）/ reach（grapple / shove）adjudication，P4-D 已有 AoE affected-target propose / resolve；三者都以 `combat_actions.resolution_status="dm_adjudication_required"` + `payload["adjudication"]` 存放。E6 不重做這些，只補統一讀取與缺的兩種 kind。
- 交付：
  1. `CombatAdjudicationService`（`app/domain/combat/adjudication_service.py`）+ `CombatAdjudicationView`（kind = `range | reach | affected_targets | opportunity_attack | special`；`dm_hints` 只給 DM，Player 一律 `None`）；`list_pending` 對 Player 只回自己 seat 為 subject 的 request。單一 `row_to_adjudication_view(StoredCombatAction)` mapper。
  2. `AttackAdjudicationInput` 加 `roll_mode`（cover / circumstance 的 adv / disadv override）與 `note`；`adjudicate_attack_range` 以 override 建立 formal Attack RollRequest 的 `modifier_mode`，decision 寫進 payload 與 `combat.adjudication_resolved`。不加 cover AC bonus（實作規格 5 只要 adv/disadv）。
  3. Opportunity attack：`POST .../combat/adjudications/opportunity-attack`（Player 需控制 reactor 或 mover；`action_kind="opportunity_attack"`、`economy_cost="none"`）；DM `POST .../adjudications/{action_id}/resolve` `trigger=True` 時在**同一個 transaction_projection** 內以 `open_opportunity_attack_window(dm_adjudicated=True)` 寫 reactor 的 reaction window（`CombatReactionRepository.set_window` 的 projection 抽成 module-level `write_reaction_window` / `load_reaction_scope` 共用）；window 寫入失敗整筆 rollback、row 仍 pending。
  4. Special / freeform：`POST .../combat/adjudications/special`（`action_kind="special_adjudication"`，question 必填）；resolve 需 `ruling`，只做 bookkeeping 不改 state。
  5. 通用 resolve route 對 range / reach / affected_targets row 回 409 並指名專用 route；不在本 Session 的 action_id 回 404。
  6. `GET .../combat/adjudications`、DI `get_combat_adjudication_service`；`_map_combat_error` 納入 adjudication / reaction 的 not-found / conflict。
  7. `StoredCombatAction` additive 加 `target_entry_id` / `resolution_status` / `resolution_result`，`combat_action_from_row` 抽成 module-level。
- 清理：拿掉 raw dict rows、try/except 授權控制流、未用的 `get_adjudication`、function 內 import、兩段重複的 request projection（收成 `_insert_pending_adjudication`）、硬寫的 `target_is_hostile: False`、`combat_action_from_row` 的 `"col" in row` 防禦讀。
- 測試：`tests/test_p4e_adjudication_routes.py` 7 條（DM / acting Player / 其他 Player 的 pending 可見性與 `dm_hints` 缺席、disadvantage override、OA trigger 原子開窗 + 強制失敗零副作用、OA no-trigger、special 宣告 / Player 不可 resolve / 缺 ruling 拒絕 / event 可見、通用 resolve 拒絕 range row + 404、Player 不可替非受控 reactor 宣告）。gate：E6 focused + P4-B/C/D/E regression + M03 boundary 117 passed。
- 留給 E7：MCP tools（`combat_list_adjudications` / `combat_request_opportunity_attack` / `combat_request_special_adjudication` / `combat_resolve_adjudication`，加上 E5 的 spell / reaction / concentration / detail）；留給 E8：`get_session_context` 的 pending adjudication / reaction 摘要。MonsterRevealState 持久化與 DM combatant bookkeeping（實作規格 7）仍未做，排 E10 前處理。

### E7a — Monster Instance REST

- 起始：2026-09-17，agy worker 一輪（578s）+ Claude 小清理。
- 為什麼有這步：P4-A closeout 記錄 `monster_instances` 只有 repository、沒有 REST / MCP 入口；E9 的 Human DM UI 與 E7b 的 AI DM 都需要建立 SRD Monster / Quick Enemy 的 server 入口。
- 交付：`MonsterInstanceService`（`app/domain/combat/monster_instances.py`，DM-only，`require_actor_current` 後非 DM 一律 403）：`create_from_content`（`content_key` 經 `parse_stable_key` 驗 kind=monster → `monster_to_reusable_rules` → `template_key=content_key`）、`create_quick_enemy`（走既有 `MonsterRepository.create_quick_enemy` / `normalize_monster_action`）、`list_instances`（只回本 Campaign）；`MonsterInstanceView` 為 DM 完整視圖，Player 只能經 E4a detail projection 看到 monster。`initial_monster_resources(rules_snapshot)` 以 `monster_casting_sources`（自 `spell_resources` 公開）同一組 casting block 種下 `spell_slot:<level>`；innate / recharge 未種。Idempotency 無專表：`uuid5(campaign_id, idempotency_key)` 決定 instance id，重送回既有 row。Routes：`GET/POST .../sessions/{session}/monster-instances`、`/from-content`、`/quick-enemy`；`_map_combat_error` 納入 `ContentNotFoundError` → 404、`MonsterPersistenceError` → 409。不發 session event（加入 Combat 時已有 `combat.entry_added`）。
- 清理：改用 `monster_casting_sources` 取代自行重掃 traits、抽 `_idempotent_instance` 去掉兩份重複、移除未用 import。既有 E1 / E5 測試的手工 `spell_slot` dict 改呼叫 `initial_monster_resources`。
- 測試：`tests/test_p4e_monster_instance_routes.py` 6 條（SRD mage from-content → 加入 Combat → cast / Quick Enemy 有無 attack / Player 403 零 row / unknown key 與非 monster key 拒絕 / idempotency 同 id 一 row / list 只含本 Campaign）。gate 78 passed。
- 限制：template search 沿用既有 `GET /api/rules/content/monsters`；Monster long-form `desc` 仍未 expose 給 UI，首次 expose 的步驟要補 zh-TW。

### E7b — Combat MCP tools：lifecycle / monster / initiative / turn / action

- 起始：2026-09-17，agy worker 一輪（811s）+ Claude 小修正。
- 交付：`CombatAIToolApplicationService` 擴充 14 個 facade 方法（只做 actor 解析 + 委派 + `model_dump`，無規則邏輯），DI 注入 `CombatInitiativeService` 與 E7a `MonsterInstanceService`。新 MCP tools：
  - DM-only：`combat_start`、`combat_add_character`、`combat_add_monster`、`combat_create_monster`（E7a from-content）、`combat_create_quick_enemy`、`combat_list_monster_instances`（DM 完整視圖）、`combat_request_initiative`、`combat_finalize_initiative`、`combat_advance_turn`、`combat_end`、`combat_remove_entry`、`combat_withdraw_entry`。
  - Shared：`combat_roll_initiative`（`_server_roll` → `complete_initiative`）、`combat_use_action`。
  - 不提供：suggested-order / ties / reorder、P4-B `set_reaction_window`（P4-D reaction service 取代）、任何 raw HP / turn / JSON setter。
  - `CombatMutationToolInput` / `CombatEntryMutationToolInput` 定義在 `ai_tools.py`（不從 `app.api` import）。`_WHEN_TO_USE` 雙語、DM gameplay 描述含 `active_session_required`；`guide_tool_names._EXPECTED` 與 `test_m04c_tool_descriptions` 的固定 catalog 同步。
- 修正：agy 把 `combat_withdraw_entry` 設成 shared，但 `CombatService.withdraw_entry` 是 `_require_dm`——改為 DM-only，避免 Player catalog 廣告一個永遠失敗的 tool；描述改為「Player 以敘事表達撤退並請 DM 處理」。
- 測試：`tests/test_p4e_mcp_combat_lifecycle.py` 5 條（catalog 角色面 + pre-session DM catalog 相等 / AI DM wire-level journey：quick enemy → start → add monster → initiative request / roll / finalize → advance → end，並與 REST `GET .../combat` 對照同一 state / AI Player 呼叫 DM tool 在 facade 前被拒 + 非受控 entry 的 `combat_use_action` 零 row / Take Back 與 Session End 後舊 token 的 combat tool 回同一 invalidation error 零副作用 / DM from-content + list）。gate（E7b focused + P4-C MCP adapter + M04-C descriptions / guide parity / briefing + P3-E MCP tools / invalidation / event loop / protocol / official client + P4-B API + E7a）80 passed。
- 留給 E7c：spell / reaction / concentration / adjudication tools 與 `get_combat_context`（Player 版無 enemy secrets）。
