# P4-E — Quick Combat UI, DM Adjudication & AI Tool Surface 實作紀錄

最後更新：2026-09-16

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
| E4b | Event payload projector + 既有 P4-C mutation response 對 Player 的 redaction | 設計 §8.2「Player-safe event payload」；測試 E.2（event / response） | ⬜ |
| E5 | Spell / reaction / concentration REST route | 實作規格 7、11；設計 §8.1、§8.2 | ⬜ |
| E6 | DM adjudication REST（range / cover / AoE / OA） | 實作規格 5；設計 §8.3 | ⬜ |
| E7 | Combat MCP tools（DM / Player catalog） | 實作規格 8、10、11；設計 §8.4；測試 E.3 | ⬜ |
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

