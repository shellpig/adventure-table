# P4-E — Quick Combat UI, DM Adjudication & AI Tool Surface 實作紀錄

最後更新：2026-09-16

## 目標與邊界

本紀錄對齊 `實作規格.md` P4-E（1～16）、`開發設計方針.md` §8、`測試指南.md` P4-E（E.1～E.5）。P4-E 把 P4-A～D 的 Combat Engine 接成真人與外部 AI 都能跑的桌面體驗；不得建立第二套規則引擎、不做 geometry、不提前建 P6 Adventure / Scene runtime。

實作以步驟切分，每步獨立可驗證、獨立 commit；步驟由 agy worker 執行、Claude 審 diff / 跑 focused test / commit。每步完成後更新下表。

## 步驟進度

| 步 | 內容 | 對應契約 | 狀態 |
|---|---|---|---|
| E1 | Monster persisted cast：`CombatSpellRepository.cast_monster_spell` | 實作規格 14；設計 §8.5「Monster cast」；測試 E.5 第 1 點 | ✅ |
| E2 | Monster concentration canonical state + 受傷 CON save | 實作規格 15；設計 §8.5「Monster concentration」；測試 E.5 | ⬜ |
| E3 | Concentration roll routing：通用 resolve 拒絕，只走 `complete_check` | 實作規格 16；設計 §8.5「Concentration roll routing」；測試 E.5 | ⬜ |
| E4 | Combat DTO / projection：DM 完整 vs Player secrecy | 實作規格 3；測試 E.2 | ⬜ |
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
