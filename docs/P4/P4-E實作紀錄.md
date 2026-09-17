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
| E7c | Combat MCP tools：spell / reaction / concentration / adjudication + `get_combat_context` | 實作規格 8、10、11；設計 §8.4；測試 E.3 | ✅ |
| E8 | `get_session_context` / briefing Combat context | 實作規格 9；設計 §8.6；測試 E.4 | ✅ |
| E9a | Session page：combat API client + `useActiveCombat` + 唯讀 Combat Stage（Header / Initiative / Combatants、enemy secrecy 呈現） | 實作規格 1、2、3、6；測試 E.1 第 6–9 點呈現面 | ✅ |
| E9b | Session page：DM Combat 控制（Start / End、加 SRD Monster / Quick Enemy、initiative request / roll / finalize、advance turn）+ Player initiative roll | 實作規格 1、4、7；測試 E.1 第 1–4 點 | ✅ |
| E10a | attack / adjudication API client（型別鏡射 server model） | 實作規格 4、5 | ✅ |
| E10b | Quick Action Bar（attack → target → roll）+ `GET .../combat/pending-rolls` + DM adjudication panel（range / OA / special） | 實作規格 4、5；測試 E.1 第 5–8、10 點 | ✅ |
| E10c-1 | pending roll 全類型：domain `pending_combat_roll_request_type` 判定 + 4 個 roll client + Action Bar 各類型擲骰列與結果 | 實作規格 4、16 | ✅ |
| E10c-2 | reaction window 接受 / 拒絕、Grapple / Shove 動作、DM reach 裁定 | 實作規格 4、5 | ✅ |
| E10d-1 | `GET .../combat/entries/{entry}/spells`：可施法術清單（含可用 slot level）+ web client | 實作規格 4、14 | ✅ |
| E10d-2a | spell cast / AoE client 呼叫 + DM `affected_targets` 目標確認 | 實作規格 5、14 | ✅ |
| E10d-2b | Quick Action Bar 的 Spell 動作（單體 / self / AoE propose、slot level） | 實作規格 4、14 | ✅ |
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

### E7c — Combat MCP tools：spell / reaction / concentration / adjudication + `get_combat_context`

- 起始：2026-09-17，agy worker 一輪在 1176s 撞 print-timeout（production 已改、測試未過）+ 一輪測試修復（2460s）+ Claude 審核修正。
- 交付：11 個 MCP tools（facade 委派 E5 / E6 service，無規則邏輯）：
  - Shared：`get_combat_context`、`combat_cast_spell`、`combat_propose_aoe_spell`、`combat_roll_concentration`（`_server_roll` → `CombatConcentrationService.complete_check`，唯一可解 Concentration request 的 MCP 路徑）、`combat_drop_concentration`、`combat_respond_to_reaction`、`combat_request_opportunity_attack`、`combat_request_adjudication`。
  - DM-only：`combat_resolve_aoe_spell`、`combat_open_reaction_window`、`combat_resolve_adjudication`（`CombatAdjudicationDecisionToolInput` 繼承 `AdjudicationDecisionInput` 加 `action_id`）。
  - `get_combat_context` 回 compact dict：`combat`（E4a `CombatDetailView`，Player 版本身即 enemy-safe）、`current_turn_entry_id`、`round`、`my_entry_ids`、`pending_roll_requests`、`reaction_windows`（只列 caller 可代表的 entry，`ReactionWindowView` 本就不含 `secret_payload`）、`pending_adjudications`（E6 `list_pending`，Player 無 `dm_hints`）、`next_required_action`。決策表住 `next_combat_action()`（`ai_tools.py`）供 E8 共用：DM → 有 pending adjudication `resolve_adjudication`／current turn 是 Monster `take_turn`／否則 `wait_for_event`；Player → 有針對自己的 pending roll `roll_pending`／自己 entry 有 open window `respond_to_reaction`／輪到自己 `take_turn`／否則 `wait_for_event`。
- **Claude 審核發現並修正**：
  1. agy 把既有 20 個 `_WHEN_TO_USE` 文案（M04-C 契約）與 `MCPToolDefinition.wire()` 的 enum / range / default 呈現、`tool_catalog` / `_definition` 全部改寫——已從 HEAD 還原，`tools.py` 只剩純新增。
  2. 四個新 service 改為必填建構參數，移除每個方法的 `is None → RuntimeError` 防禦；移除未用的 `get_combat_context` alias；`my_entry_ids` 改 `frozenset[UUID]` 不再 str 來回轉換。
  3. **真正的 production gap**：agy 的 `pending_roll_requests` 走 `roll_service.list_requests`，但 production 的 `CombatAwareRollRepository` 刻意排除所有 combat-targeted rows（P4-B 起 initiative / attack / save / concentration 都有 `target_combat_entry_id`），所以 production 下 combat roll 永遠不會出現；agy 測試用一個 test-only repository 子類掩蓋了這點。修正：`CombatCoreRollRepository.list_pending_requests(session_id)` + `CombatCoreRollService.list_pending_rolls(actor)` → `CombatPendingRollView`（DM 全部含 DC；Player 只看 target 自己 seat 的 request 且 `dc=None`，因 monster save DC 是敵方秘密），`combat_get_context` 改走此路徑；測試改回 production `CombatAwareRollRepository`，並加 Player `dc is None` / DM `dc` 存在的斷言。
- 測試：`tests/test_p4e_mcp_combat_context_and_effects.py` 6 條（catalog 角色面 / Player context raw JSON 無敵人 HP、AC、resources、hidden conditions、concentration，無 `rules_snapshot` 字串，adjudication `dm_hints` 為 None，window 無 `secret_payload` / DM context 精確 HP + pending range adjudication → `resolve_adjudication` → 解決後不再是 / Concentration CON save → Player `roll_pending` + DC 隱藏 → `combat_roll_concentration` 解決、失敗清 concentration、`roll_pending` 對同 request 仍拒絕（實作規格 16）/ Player cast 結果無敵方 AC、DC，DM-only tools 在 facade 前被拒 / Player 宣告 OA → DM `combat_resolve_adjudication(trigger=True)` → Player context 見 window 且 `respond_to_reaction` → 接受後關閉）。gate（E7c + E7b + P4-C MCP adapter + M04-C 描述 / guide parity / guide / briefing / discover + P3-E MCP tools / invalidation / event loop / protocol / official client / shared roll + P4-C core rolls + E3 / E5 / E6 / E4a / E4b / E7a + M03 boundary）123 passed。
- 留給 E8：`get_session_context` 在 active Combat 時附 compact combat context（可直接重用 `combat_get_context` 的組裝與 `next_combat_action`）、briefing 的 combat mandatory loop 雙語、E.4 parity 測試。

### E8 — `get_session_context` / briefing Combat context

- 起始：2026-09-17，agy worker 一輪（637s）+ Claude 審核修正。
- 交付：`CombatAIToolApplicationService.get_session_context` override——先呼叫 base 組出一般 payload，`mode != active_session`（pre-session grant）原樣回傳；active session 時附 `combat`（無 active combat 為 `None`；有則為 `combat_get_context` 同一份 dict，組裝抽成 `_combat_context(actor)` 供兩個 tool 共用），並以 combat 的 `next_required_action` 覆蓋 stage hint、`briefing` 改為 `render_briefing(mode="active_combat")`。`ai_guidance.py` 新增 `_dm_combat_loop` / `_player_combat_loop`（en + zh-TW：讀 combat context → DM 裁定 / Monster turn → 只在自己 turn 或 reaction window 出手 → resolve 後立即 `wait_for_event`），active_session / active_combat 共用 `_format_active_briefing` 框架（invocation rule + guide 指標 + temporary_instruction 句）；`BRIEFING_MAX_CHARS` 維持 2,400（DM 2,349 / Player 2,388）。`guide.py` 在 flow 段後加 `[Combat]` / `【戰鬥】` 段，tool 名稱全部經 `GuideToolNames` 新欄位（`combat_context` / `resolve_adjudication` / `respond_reaction` / `request_adjudication` / `roll_concentration` / `advance_turn`），`_EXPECTED` 不變。`_WHEN_TO_USE["get_session_context"]` 補 combat context 與 turn / reaction / wait 指引，其他描述未動。
- **Claude 審核修正**：agy 的測試用 `_wire_exploration_services()` 在每個 test 內把 E7c fixture 的 `stage_service` / `pending_action_service` 從 `object()` 換成真 service；改為直接在 `mcp_combat_fixture` 建構真 `ExplorationStageService` / `PendingActionService`，E8 測試不再 mutate fixture。test_4 的 dependency override 改為還原先前值，不重建 lambda。
- 測試：`tests/test_p4e_session_context_combat.py` 5 條（無 combat 時 `combat=None`、briefing 與 next_required_action 同 active_session / DM wire-level 有 combat dict、top-level `next_required_action` 等於 combat 的、briefing 含 `MANDATORY DM COMBAT LOOP`、無 `rules_snapshot` / Player 版 hostile projection 無 HP、AC、resources、hidden_conditions、dm_notes、concentration，自身角色 HP 精確，briefing 不含 DM-only tools / pre-session grant 無 `combat` key 且 briefing 不變 / E.4 parity：guide、description、兩角色 combat briefing 在兩 locale 都含 current turn、reaction window、adjudication、`wait_for_event` token，長度 ≤ cap）。gate（E8 + M04-C briefing / guide parity / guide / descriptions / discover + P3-E tools / protocol / event loop / invalidation + E7b / E7c + P4-C MCP adapter + M03 boundary）85 passed。
- 留給 E9：UI 走 REST `GET .../combat/detail`（audience-projected），`combat.*` event 為 refetch 觸發；`next_required_action` 決策表可作 E10 action bar 提示。

### E9a — Session page：combat API client + `useActiveCombat` + 唯讀 Combat Stage

- 起始：2026-09-17，agy worker 一輪（424s）+ Claude 審核修正。
- 交付：`apps/web/src/api/combat.ts`（`CombatEntryView` / `CombatView` / `CombatantProjection`（allowlist 以外欄位全部 optional）/ `CombatantDetailView` / `CombatDetailView` 鏡射 server DTO；`conditionLabel()`；`getActiveCombatDetail()` 走 `GET .../combat/detail`，重用 `sessions.ts` 的 `request` / `tableBase`（改為 export））。`sessionCombat.ts`：`isCombatEvent` / `latestCombatEventSeq` / `orderedEntries`（有 turn_order 者升冪，未定者原序接尾）/ `myEntryIds` / `combatantFor`，以及 `useActiveCombat({ roomId, campaignId, sessionId, token, events, onError })` → `{ combat, refresh }`：mount 與最新 `combat.*` event seq 變動時 refetch，stale response 丟棄，非 combat event 不觸發。`SessionCombatStage.tsx` 掛在 `session-stage` 既有 canvas 上方（`combat` 非 null 才出現）：Combat Header（`round_number` 或 `combatPreInitiative`、current turn 名稱、your-turn badge、`data-combat-round` / `data-combat-current-turn`）、Initiative List（`aria-current`、hostile / status badge、未定先攻顯示 `combatAwaitingInitiative`；hidden enemy 只有 entry 沒 combatant 時仍列 display_name）、Combatants cards（name、public conditions、Action / Bonus / Reaction pill、attacks used/allowed（>1 才顯示）、position note / dm_notes 只在有值時出現、HP / AC 只在 projection 有數字時出現、injury level label；不印任何 "?" / hidden 佔位）。`SessionTableSurface` 以 `isCurrentDm ? 全部 participants : controlledParticipants` 的 `active_character_id` 推 `myEntryIds`。`sessionCopy.ts` 兩 locale 各加 27 個 `combat*` key；`sessionTable.css` 加 `session-combat*` 規則；`hardcodedUiCopy.test.ts` SOURCE_FILES 納入新元件。
- **Claude 審核修正**：拿掉不存在的 `combat.status === 'preparing'` 分支（server 只有 `initiative_pending` / `running` / `ended`），Header 改以 `round_number` 是否為數字決定；`conditionLabel` 參數型別由 `ConditionOrEffectItem | unknown`（等於 unknown）收成 `ConditionOrEffectItem` 並簡化實作；`combatantEntries` 型別改用 `CombatantDetailView`；移除未使用的 `combatConditions` copy key、hook 內多餘的空值防禦、與 `sessionExploration.test.ts` 重複的 copy parity 測試。
- 測試：`sessionCombat.test.ts` 6 條（helpers + `conditionLabel`）、`SessionCombatStage.test.tsx` 5 條（DM 精確 HP / AC / round / current turn；Player 同一場 enemy allowlist projection 只見 wounded label 與自身 HP，無敵人數字、無 dm_notes、無 "?"；position note 有無；your-turn badge；hidden enemy 仍列 initiative row）。`npm test -- --run` 80 files / 393 passed；`npm run build` 通過。
- 留給 E9b：DM 控制（Start / End、加 SRD Monster / Quick Enemy、initiative request / roll / finalize、advance turn）與 Player 自己 entry 的 initiative roll button；`useActiveCombat.refresh` 已可供 mutation 後呼叫。

### E9b — Session page：DM Combat 控制 + Player initiative roll

- 起始：2026-09-17，agy worker 一輪（753s，最終回覆 stream 中斷但程式與測試已完成）+ Claude 審核修正。
- 交付：`api/combat.ts` 補 `startCombat` / `endCombat` / `addMonsterToCombat` / `requestInitiative` / `rollInitiative` / `getSuggestedInitiativeOrder` / `finalizeInitiative` / `advanceTurn`（combat prefix）與 `createMonsterFromContent` / `createQuickEnemy`（monster-instances prefix），input / response 型別鏡射 server model，`MonsterInstanceView` 只型別 UI 用到的欄位。`sessionCombat.ts` 加 `useMonsterOptions(enabled)`：`listContent('monsters')` + `useContentPresentations(..., { includeSearchAliases: true })` → `SearchOption[]`（label 走 `nameFor` 取 zh-TW 名稱，description `CR x`）。`SessionTableSurface` 在 table header 列加 DM-only `session-table__combat-toolbar`：無 combat 顯示 Start Combat（`include_active_party: true`），有 combat 顯示 End Combat（`window.confirm` 後送出）；`requestId` 改為 export 供 combat 元件共用。`SessionCombatDmControls.tsx`（只在 `isCurrentDm` 時由 Stage 掛載，`data-combat-dm-controls`）：加敵人面板兩種模式——SRD Monster（`SearchableSelect` + 顯示名 override + visibility + position note → `createMonsterFromContent` → `addMonsterToCombat`）與 Quick Enemy（name / AC / max HP / optional attack / visibility / position note → `createQuickEnemy` → `addMonsterToCombat`），兩段各自 idempotency key、成功後清表單；`initiative_pending` 時顯示 Request initiative（全部 active entry 都已有 request 或 total 時 disabled）與 Finalize（每個 active entry 都有 `initiative_total` 才 enabled；`suggested-order` → `finalizeInitiative`）與等待提示；`running` 時顯示 Advance turn。`SessionCombatStage` Initiative row 在 `initiative_roll_request_id` 有值且 `initiative_roll_result_id` 為 null 時顯示 Roll initiative（`data-initiative-roll`）：DM 對所有 row、Player 只對 `myEntryIds` 內的 row；送 `rollInitiative({ source: 'server' })` 後 `refresh()`。`sessionCopy.ts` 兩 locale 各加 33 個 key；CSS 補 toolbar / dm-controls / form 規則；`hardcodedUiCopy.test.ts` 納入新元件。
- **Claude 審核修正**：agy 把 `roomId` / `campaignId` / `sessionId` / `token` / `isCurrentDm` / `onError` / `refresh` / `monsterOptions` 全部宣告成 optional 並在每個 handler 前加 `if (!roomId || ...) return` 防禦——改為 required prop、刪掉空值 guard 與 `refresh?.()` / `onError?.()`；Stage 不再接受 `monsterOptions` prop 覆寫，直接 `useMonsterOptions(isCurrentDm)`；DmControls 五段重複的 pending / try / refresh / onError / finally 收成 `runMutation()`；Quick Enemy 的 attack 只在 name 與 damage 都填時才送，不再用 `'Attack'` / `'1d6'` 補值偽造；測試改傳 required props。
- 測試：`SessionCombatDmControls.test.tsx` 5 條（加敵表單與模式 tab；一個 entry 缺 initiative → Request enabled / Finalize disabled + 提示；全有 total → Finalize enabled / Request disabled；`running` 只剩 Advance turn；`initiative_pending` 無 Advance turn）、`SessionCombatStage.test.tsx` +2（DM 有 controls 區與敵人 row 的 roll button；Player 無 controls、roll button 只在自己 entry、敵人 row 沒有）、`SessionTableSurface.test.tsx` +2（DM 有 Start Combat、Player 無 toolbar）、`api/combat.test.ts` 4 條（start / roll initiative / suggested-order / quick-enemy 的 URL、method、body、Bearer）。`npm test -- --run` 82 files / 407 passed；`npm run build` 通過。
- 未做 / 留給後續：browser 證據（E.1 第 1–4 點的 Playwright journey）在 E12；E10 需要 Quick Action Bar、target 選擇、attack / adjudication UI，可沿用 `runMutation` 模式與 `next_required_action`。

### E10a — attack / adjudication API client

- 起始：2026-09-17，改由 ChatGPT（GitHub connector，直接 commit + push 到 P4-E branch）實作，Claude pull 後審核；第一步刻意縮小以驗證 round trip。commit `acf64fc8`，4m34s。
- 交付：`api/combat.ts` 加 `listAttacks` / `requestAttack` / `rollAttack` / `adjudicateAttackRange` / `listAdjudications` / `requestOpportunityAttack` / `requestSpecialAdjudication` / `resolveAdjudication` 與對應型別（`AttackRequestInput` / `AttackAdjudicationInput` / `AttackDefinitionView` / `AttackRequestView` / `AttackResolutionView` / `CombatAdjudicationView` / `OpportunityAttackRequestInput` / `SpecialAdjudicationRequestInput` / `AdjudicationDecisionInput`）；`RollInitiativeInput` 改名 `FormalRollInput` 供 initiative / attack 共用。
- 審核：URL / method / body / 型別全部對 server；無越界改動。小瑕疵未改：View 型別把 server 必回欄位標成 optional、Input 的 `idempotency_key?: string | null` 與 E9b 的必填 `string` 不一致（皆合 server contract）。
- 測試：`combat.test.ts` +3；`npm test -- --run` 82 files / 410 passed；build 通過。

### E10b — Quick Action Bar attack flow + pending-rolls route + DM adjudication panel

- 起始：2026-09-17，ChatGPT 一輪（第一輪連線中斷、blobs 已備但未 commit；補一句「繼續」後完成）。commit `bb3eb32f` + Claude 審核修正 commit。
- 交付：
  - Server：`GET .../combat/pending-rolls` → `CombatCoreRollService.list_pending_rolls`（E7c 只給 MCP 的方法首次接 REST）；`tests/test_p4e_pending_rolls_route.py` 3 條（Player 只見自己的 attack roll 且 `dc` null / DM 見全部含 saving throw `dc`、無受控 seat 的第二個 Player 得空 list / 非本場 participant 與 `GET /detail` 同一拒絕、零 `roll_requests` 副作用）。
  - Web：`sessionCombat.ts` 把 `useActiveCombat` 抽成泛型 `useCombatEventResource`（mount + `combat.*` event seq 變動 refetch、stale 丟棄、`enabled` 關閉時回 initial），新增 `usePendingCombatRolls` / `usePendingAdjudications` / `actingEntryId` / `combatInjuryLabel`（自 Stage 搬出）/ `adjudicationKindLabel` / `runCombatMutation`（E9b DmControls 的 `runMutation` 抽成共用）。`SessionCombatActionBar.tsx`（`running` 時兩角色都掛，`data-combat-action-state` = `waiting` / `ready` / `adjudication-pending`）：attack select（`listAttacks(actingEntryId)`，只顯示名稱與 bonus）、target select（其他 active entry）、modifier、DM-only `range_confirmed` checkbox；`requestAttack` 回 `roll_request_id` 則顯示 Roll attack（`data-attack-roll`），為 null 則進 adjudication-pending 並等 `pendingAdjudications` 出現又消失後回 ready；pending attack roll 列表（`data-pending-roll`，Player 在 DM 裁定 in range 後由此擲）；Player 自己的 pending adjudication 唯讀列（`data-adjudication-pending`）；結果列 hit / miss / critical + damage，`after_hp` 為數字才顯示，否則顯示 injury label。`SessionCombatAdjudicationPanel.tsx`（DM-only，`data-combat-adjudications`）：range → roll_mode override + note + In range / Out of range（`adjudicateAttackRange`）、opportunity_attack → Trigger / No trigger、special → ruling textarea → `resolveAdjudication`；reach / affected_targets 只列不控（E10c）。Stage 接 `events` prop、`refreshCombatResources` 同時刷新 combat / rolls / adjudications。`sessionCopy.ts` 兩 locale 各 +29 key；CSS +87 行。
- **Claude 審核修正**：ChatGPT 在 route 層把 `request_type == "other"` 的 roll 逐筆查 `attack_service.repository.get_request` 再改成 `"attack"`（N+1，且 REST 與 MCP `get_combat_context` 對同一 view 給不同 `request_type`）。改為 `CombatCoreRollRepository.list_pending_requests` outer join `combat_actions.action_kind`，`StoredCombatCoreRollRequest.action_kind` additive，`list_pending_rolls` 以 `action_kind == "attack"` 判定 `request_type="attack"`，route 只剩委派；MCP 同步受益。test 3 把 `/detail` 的拒絕狀態硬寫成 403，實際是 404（E4a 已斷言 `{403, 404}`），改成同 E4a 並加 body 相等斷言。
- 測試：pytest E10b focused + E6 / E7c / E8 / P4-C core rolls / E3 / M03 boundary 34 passed；P4-B/C/D/E 全部 37 個檔案無 failure（PostgreSQL gated 者 skip）。`npm test -- --run` 84 files / 428 passed；build 通過。
- 留給 E10c：其餘 roll 種類的 pending 列表與擲骰（saving throw `/saving-throws/roll`、death save、concentration 走 `/concentration/roll`）、spell cast / AoE propose-resolve UI、reaction window 回應、reach / affected_targets adjudication 控制；attack roll request 的 `roll_groups.label` 兩條路徑不一致（`Attack: <name>` vs `<name>`）可順手統一。

### E10c-1 — pending roll 全類型

- 起始：2026-09-17，ChatGPT。原 E10c（rolls + reactions + grapple/shove + reach）連續兩回合 30 分鐘 timeout 零輸出；用「不呼叫工具只回答三題」診斷出**任務以附件送出時，OpenAI 會封鎖 GitHub 寫入工具**（「無法確定要求的安全狀態」），改把全文貼進對話後一回合完成。commit `07319cb3`（+574/-59）。
- 交付：domain `pending_combat_roll_request_type(StoredCombatCoreRollRequest)`（attack / death_save / grapple / shove 由 `action_kind`，Concentration / Initiative 由 `roll_group_label`，其餘沿用 stored `request_type`），`list_pending_rolls` 與 MCP `get_combat_context` 共用；parametrize 7 分支 + Player GET 同時列 saving_throw（`dc` null）與 death_save 的 route 案例。`api/combat.ts` 加 `rollSavingThrow` / `rollDeathSave` / `rollConcentration` / `rollSpecialAttack` 與 `SavingThrowResultView` / `DeathSaveResultView` / `ConcentrationCheckResultView` / `SpecialAttackView`。`sessionCombat.ts` 加 `PendingCombatRollDispatchTable` / `pendingCombatRollHandler`。Action Bar pending 列表改列 initiative 以外全部類型（label、saving throw 的 ability + DM-only DC），每列依 `request_type` 派送；結果列依類型顯示（attack 沿用；save total + 成功／失敗；death save d20 + 成功／失敗次數 + stable / dead；concentration total vs DC + 維持／失去；grapple / shove 只 refresh）。兩 locale 各 +17 key。
- Claude 修正：parametrize 參數名 `request` 是 pytest 保留字，collection error → 改 `stored`。
- 測試：pytest E10c-1 focused + E7c / E8 / P4-C core rolls / E3 / M03 boundary 35 passed；`npm test -- --run` 84 files / 431 passed；build 通過。

### E10c-2 — reaction window / Grapple–Shove / reach 裁定

- 起始：2026-09-17，ChatGPT。第一回合在 `create_blob` 途中撞時間上限（未被封鎖）；第二回合我為了省時叫它「不要重讀檔案、沿用 blobs」，結果它**憑記憶重生整份檔案並壓成長單行**（`combat.ts` / `combat.test.ts` / `SessionCombatStage.tsx` / `SessionCombatActionBar.tsx` / `SessionCombatAdjudicationPanel.tsx` 等，140 字以上的行從 3 行變 84 行，-991 行的 diff 幾乎全是排版）。commit `733d41d9`。
- 交付（語意面，已用 prettier 兩側比對確認只有新增）：`api/combat.ts` 加 `getReactionWindow` / `resolveReaction` / `requestSpecialAttack` / `adjudicateSpecialAttack` 與 `ReactionKind` / `ReactionWindowView` / `ReactionResolutionView` / `SpecialAttackRequestInput` / `SpecialAttackAdjudicationInput`；`sessionCombat.ts` 加 `useReactionWindows`（per-entry `GET /entries/{id}/reaction`，無 list route）與 `eligibleReactionEntry`；Action Bar 加 action kind select（Attack / Grapple / Shove，grapple / shove 走 `requestSpecialAttack`，無 roll id 時進 adjudication-pending）、reaction windows 區（`data-combat-reactions`、每個 window Accept / Decline `data-reaction-window`、`safe_payload` key: value）；panel 的 reach 列加 In reach / Out of reach → `adjudicateSpecialAttack`；Stage 依角色算 `reactionEntryIds`（DM 全部 active entry、Player 自己）並一起 refresh。兩 locale 各 +18 key。
- **Claude 審核修正**：用 `prettier@3 --no-semi --single-quote --print-width 100 --trailing-comma all` 把被壓扁的 6 個檔案重新展開（此設定與既有手寫風格只差 35 行 / 377 行，可視為專案風格），並以 prettier(6dd4faa4) vs prettier(733d41d9) 比對確認語意只有新增。專案未引入 prettier 依賴，只是一次性 `npx`。
- 教訓（已寫進 worker 流程）：**不要叫 ChatGPT「不用重讀」**——它會憑記憶重生檔案；每次寫入必須以 HEAD 的新鮮讀取為底，且只做最小 diff。
- 測試：`npm test -- --run` 84 files / 438 passed；build 通過。
- 留給 E10d：spell cast（單體）/ AoE propose–resolve UI、`affected_targets` 裁定；E11 接 Chat / Log 呈現。

### E10d-1 — 可施法術清單 route

- 起始：2026-09-17，ChatGPT 兩回合（第一回合整段花在 mandatory reading，沒建任何 blob；第二回合明講「不要再讀 docs/，只在寫入前重讀該檔 HEAD」後完成）。commit `e0ab444c`。
- 交付：`CombatSpellService.available_spells(actor, entry_id) -> tuple[CastableSpellView, ...]`（`spell_ref` / `name` / `level` / `profile_id` / `concentration` / `targeting` single｜self｜aoe / `cast_mode` / `castable_slot_levels`）。Character 逐 (profile, access entry, slot level) 呼叫 P4-D 的 `authorize_character_spell`，成功才收錄——資源與 prepared / known 規則不在此重寫；Monster 走 `monster_casting_sources` + `resolve_monster_spell_source`。授權沿用 `require_actor_current` + `combat_service._authorize_entry`（DM 任意 entry、Player 只限受控）。Route `GET .../combat/entries/{entry_id}/spells`，`_map_error` 沿用。`api/combat.ts` 加 `CastableSpellView` 與 `listCastableSpells`。
- **指揮者審核修正**：① ChatGPT 在 service 內自寫 `_monster_spell_ref`（自行 slug 化 url / name），與 `spell_resources.py` 既有 `_slug` / `_monster_spell_matches` 重複且規則可能漂移 → 抽成 `spell_resources.monster_spell_ref()` 公開函式並改為呼叫它。② Player 拒絕測試比對 `/attacks` route 的整份 JSON body，訊息字串不同而失敗，且跨 service 呼叫在整包執行時因未 override attack service 而噴 `no such table: sessions` → 改為只斷言本 route 的 403 + `table_actor_unauthorized` + 訊息關鍵字，零副作用斷言保留。
- 測試：P4-D + P4-E 全部 backend 檔 + M03 boundary 無 failure（2 skip 為 PostgreSQL gated）；P4-A/B/C regression 無 failure；`npm test -- --run` 84 files / 439 passed；build 通過。
- 留給 E10d-2：Action Bar 的 spell 動作（單體 / self 走 `POST /spells/cast`；AoE 走 `propose` → DM 確認 targets → `resolve`）、`affected_targets` 裁定控制項。

### E10d-2a — spell / AoE client 與受影響目標確認

- 起始：2026-09-17，ChatGPT 一回合（E10d-2 原本一整包連兩回合死在時間上限與「訊息遞送逾時」，拆成 2a / 2b 後各一回合完成）。commit `b5f108f7`。
- 交付：`api/combat.ts` 加 `SpellCastView` / `AoeSpellProposalView` / `AoeSpellResolutionView` / `CastSpellInput` / `ProposeAoeSpellInput` / `ResolveAoeSpellInput` 與 `castSpell` / `proposeAoeSpell` / `resolveAoeSpell`；輸入型別刻意不含 `save_dc` / `attack_modifier` / `target_ac` / `raw_dice`（E5 起 server 對 raw rule 欄位回 422）與 `save_modifiers` / `save_d20s` / `damage_parts` / `roll_source`（server 端預設）。`SessionCombatAdjudicationPanel` 的 `affected_targets` 列加每個 proposed target 一個 checkbox（預設全勾、名稱查 `combat.entries`）與 Resolve → `resolveAoeSpell`，允許零目標。兩 locale 各 +2 key。
- **指揮者審核修正**：無。型別、URL、排版、測試皆正確。
- 過程備註：worker 撞到 parent hash 過期（我在它跑的期間推了文件 commit），它正確地拒絕 force push 並改用當前 HEAD——prompt 的 GIT 段因此改為「以你 fetch 到的 HEAD 為 parent」，已寫進指揮者手冊。
- 測試：`npm test -- --run` 84 files / 440 passed；build 通過。

### E10d-2b — Quick Action Bar 的 Spell 動作

- 起始：2026-09-17，ChatGPT 兩回合（第一回合「訊息遞送逾時」死掉、無 push）。commit `26aeed4c`。
- 交付：action kind 加 `spell`（Attack / Grapple / Shove / Spell）；既有那個 `listAttacks` effect 改成 `Promise.all([listAttacks, listCastableSpells])`，不另開 effect；抽出 `SpellActionFields` 子元件（spell select、`castable_slot_levels` 多於一個時才出現的 slot level select、`targeting === 'single'` 才出現的 target select，`data-combat-spell*` 屬性供 E12）。送出分流：`aoe` → `proposeAoeSpell`（`proposed_target_ids` 為除施法者外全部 active entry）→ 進既有 adjudication-pending 狀態；否則 `castSpell`（`self` 送 `target_entry_id: null`），有 `roll_request_id` 走既有 local roll 按鈕，否則顯示由 `cast_mode` + `status` 組出的一行狀態。submit disabled 條件依 action kind 分開。兩 locale 各 +9 key。
- **指揮者審核修正**：`if (actionKind === 'spell' && selectedSpell)` 讓 TS 無法把後續的 `actionKind` 收斂成 `'grapple' | 'shove'`，`npm run build` TS2322 失敗（vitest 全綠，型別錯誤只有 build 會抓）→ 改成 `if (actionKind === 'spell') { if (!selectedSpell) return; … }`。
- 已知限制：spell 欄位的測試直接 render 匯出的 `SpellActionFields`，沒有透過 Action Bar 走「選 Spell → 非同步取 spells → 顯示欄位」的完整路徑；該接線留給 E12 的 Playwright journey。
- 測試：`npm test -- --run` 84 files / 442 passed；build 通過。

## E10 完成

E10a / E10b / E10c-1 / E10c-2 / E10d-1 / E10d-2a / E10d-2b 全部交付並驗證。Quick Combat UI 現在涵蓋：唯讀 Stage、DM 控制與 initiative、attack 流程、全類型 pending roll、reaction window 回應、Grapple / Shove、spell cast 與 AoE propose、DM 的 range / reach / OA / special / affected_targets 裁定。**依使用者指示，P4-E 在此暫停**；E11（Chat / Log 呈現 + 雙語 + guide）與 E12（focused E2E + Subphase 關門 gate）尚未開工。

### E11a — Compact Combat Log（驗證與修正中）

- 起始：2026-09-17，ChatGPT Web worker；指揮者為 Codex。首輪提交 `fb6b318d`，雙語／狀態修正 `a2072bd4`；尚未完成 E11a 驗收，不代表 E11 關門。
- 交付：`sessionCombatLog.ts` 與 formatter tests；`SessionTableSurface` 的 Log 接線、Chat predicate、可見 content name 批次解析。
- 指揮者審核：首輪英文 slug 被當繁中名稱、Monster `dropped_to_zero` 被推論為 unconscious/prone、主動解除專注 event 無呈現，已退回 fix1；再次核對 production，attack `source_ref` 是 `inventory:<id>` / `monster-action:<index>`，不能當 content StableKey，已縮成單檔派工待交付。
- 本機小修：新增 hook 使既有 5 個 `SessionTableSurface` 測試缺 Provider；`75ae8535` 使用真 `QueryClientProvider` / `LocaleProvider`，保留全部原斷言。`npm test -- --run`：85 files / 452 passed；`npm run build` 通過。此證據只涵蓋目前 tree，不表示 runtime attack 修正或完整 E11 驗收已完成。
- Worker 執行限制：fix1b 兩輪訊息遞送逾時；無工具診斷回覆沒有持續 connector 封鎖、沒有已完成正式 blobs/tree，工作停在讀檔搜尋。指揮者已縮為只改 `sessionCombatLog.ts`，禁止額外搜尋。
- 清理：worker 誤提交 `d02fb6c6` noop 空檔 `__tmp_should_not_exist`；指揮者移除該 orphan，保留既有歷史，不 force/rebase。
- 留給下一步：runtime attack source／可見名稱修正與真 payload regression；save/death-save/special-attack 等已存在事件及 spell damage/heal compact outcome（fix2）；E11b guide/catalog/briefing parity。E12 未開始。

#### E11a runtime attack source 小修

- 2026-09-17：單檔 worker 回合再次訊息遞送逾時，沒有正式提交；剩餘修正只有 source 判定，Codex 依指揮者小修原則本機收尾。
- `isContentReference` 排除 `inventory:` / `monster-action:` locator，僅 canonical 三段 reference 可走 attack name presentation；runtime attack 保留既有可見 `attack.name`。測試涵蓋 inventory id 內含 colon，避免誤判為 StableKey。
- `npm test -- --run`：85 files / 453 passed；`npm run build` 通過。尚缺 runtime source 至 content 的雙語名稱 mapping，不能將保留英文 canonical name 視為翻譯完成；需後續 E11 小步補真實來源接線。fix2 / E11b 尚未完成。
