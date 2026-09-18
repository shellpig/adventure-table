# P4-F — Full P4 Integration & Closeout 實作紀錄

最後更新：2026-09-18

## 目標與邊界

本紀錄對齊 `實作規格.md` P4-F（1～11）、`開發設計方針.md` §9、§10、`測試指南.md` P4-F（F.1～F.4）。P4-F 以真正可玩的完整 Quick Combat journey 驗證 P4，並收掉 P4-C／P4-D／P4-E closeout 留下、已明列歸 P4-F 的缺口。不做 P5 geometry、不建 P6 runtime、不加 Undo。

branch：`feat/p4f-full-p4-integration-closeout`（自 `main` `6ed11d24` 開出）。實作以步驟切分，每步獨立可驗證、獨立 commit；步驟由 agy worker 執行、Claude 審 diff / 跑 focused test / commit（流程見 `docs/others/conductor-handbook.md`）。每步完成後更新下表。

已拍板（2026-09-17）：`ConditionSemantics` 接進 attack / save modifier pipeline納入 P4-F（F7），排在真實 AI gate 之前的最後一個 code step，不阻塞 F.3。

## 步驟進度

| 步 | 內容 | 對應契約 | 狀態 |
|---|---|---|---|
| F1 | Monster 0 HP outcome：DM 選 dead / unconscious / surrendered / fled / other；migration `0027` 放寬 `combat_entries.status` / `monster_instances.combat_status`；REST + MCP + event | 實作規格 P4-C 10、P4-E 7、P4-F 1；規格企劃「Monster 0 HP / Combat End」 | ✅ |
| F2 | Monster Instance bookkeeping：DM PATCH name / visibility / position_note + reveal toggles（AC / description / position note）；`MonsterRevealState` 持久化（migration `0028`）；REST + MCP + event | 實作規格 P4-E 7（部分→完整）、3 | ✅ |
| F3a | F3 前半：DM detail projection 帶 `reveal` flags（Player 不得收到）；web client `setMonsterOutcome` / `updateMonsterInstance`；新 entry status 標籤 unconscious / surrendered / fled；combat log 兩個新 event；雙語 | 實作規格 P4-E 2、3、12、13 | ✅ |
| F3b | F3 後半：DM 卡片 per-monster 控制元件（outcome / visibility / reveal toggles / position note）接進 Stage；Player 不渲染；雙語 copy；tests | 實作規格 P4-E 1、2、7、13 | ✅ |
| F4a | `escape_grapple`：新 `SpecialAttackKind`，走 P4-C opposed-check substrate；耗整個 Action、免 reach 裁定、成功同 transaction 移除 `grappled`；REST / MCP 共用既有 `kind` | P4-C closeout 留下 | ✅ |
| F4b | Character state PATCH DTO（`/characters/{id}/state` 與 table `TableCharacterStatePatch`）補 `concentration` / `exhaustion_level` / `death_saves` / `temporary_effects`；active Combat 中比照 HP 走 DM correction-only | P4-D closeout 留下 | ✅ |
| F4c | server：special-attack 骰與 reach 裁定的 canonical 判別（修 P4-E 遺留：`shove_*` / 防守方骰落成 `skill`、`shove_*` 裁定未歸 reach）+ `escape_grapple` 判別 | 實作規格 P4-E 4、8；P4-E 遺留 | ✅ |
| F4d | web：kind 改 `shove_prone` / `shove_push` / `escape_grapple`（修 UI shove 422）、escape 選項只在自己被 grappled 時出現、roll handler、combat log、雙語 | 實作規格 P4-E 4、12、13 | ✅ |
| F5 | 真 PostgreSQL + server restart / reconnect：Round ≥ 2、pending save 或 reaction → restart → 狀態完整、resolve 一次不重擲 | 實作規格 P4-F 3；測試指南 F.1 | ✅ |
| F6 | Full browser journey spec（F.2 全項：spell / save、damage / healing、condition、concentration 或 reaction、0 HP outcome、Session boundary resume、End cleanup）+ `P4 Full-Stack E2E` workflow | 實作規格 P4-F 1、2、4、5、6；測試指南 F.2 | ⬜ |
| F7 | `ConditionSemantics` 接進 attack / save modifier pipeline（advantage / disadvantage / auto-fail / adjacent crit） | P4-D closeout 留下；P4-F 已拍板納入 | ⬜ |
| F8 | 真實 ChatGPT Web Combat gate（人工，含 `wait_for_event` / reconnect continuity）+ DM proxy audit 與 secrecy 三層證據彙整 | 實作規格 P4-F 5、6、9、10；測試指南 F.3 | ⬜ |
| F9 | static review + Non-E2E / PostgreSQL / standalone boundary regression 彙整 + P4-F closeout + P4 Phase closeout | 實作規格 P4-F 7、8、11；測試指南 F.4 | ⬜ |

步驟粒度可在實作中再切；新增子步以 `F1a` 之類接續，不重編已完成項目。

## 步驟紀錄

### F1 — Monster 0 HP outcome

- 2026-09-17，agy worker（Gemini 3.8 Flash (High)，1 回合 11.5 分鐘），Claude 審核修正與 commit。prompt：`C:\_work\AI_Work\Tools\agy-runs\agy-p4f-f1.prompt.txt`。
- 交付：migration `0027_p4f_monster_outcome`（`combat_entries.status` 加 dead / unconscious / surrendered / fled；`monster_instances.combat_status` 加 unconscious / surrendered / fled；downgrade 還原）；`MonsterOutcomeChoice`（outcome / note / idempotency_key，`other` 必填 note）與 `MonsterOutcomeInput`（+ entry_id）；`CombatRepository.set_monster_outcome` → `_set_entry_status(monster_outcome=True, extra_payload=...)` 同一 transaction 改 entry status + `monster_instances.combat_status`、append 公開 event `combat.monster_outcome_set`（payload：combat_id / entry_id / monster_instance_id / outcome / status / note）；`other` → status `removed`；`CombatService.set_monster_outcome`（DM-only、current-turn guard、`_notify`）；REST `POST .../combat/entries/{entry_id}/outcome`（body `MonsterOutcomeChoice`）；MCP `combat_set_monster_outcome`（DM，input 直接用 `MonsterOutcomeInput`）；`calculate_injury_level` 把 `unconscious` 視為 down。migration head 引用（m04b / p3c / p3d / p4b / p4c / p4e）全部改到 `0027`。
- **Claude 審核修正**：agy 把 `_set_entry_status` 的 transaction 整段複製成第二份（~35 行）→ 改為 `_set_entry_status` 加 `extra_payload` / `monster_outcome` 兩個參數，`set_monster_outcome` 只做 Monster entry 前置檢查後委派；REST body `MonsterOutcomeBody` 與 MCP `CombatMonsterOutcomeToolInput(pass)` 各自重複 validator → 收成 `MonsterOutcomeChoice` 基底 + `MonsterOutcomeInput` 子類，REST / MCP 直接用。
- 測試：`tests/test_p4f_monster_outcome.py` 6 條（四種 outcome 的 entry / instance / event / Player projection；`other` 缺 note 在寫入前拒絕；Player 拒絕零副作用；current-turn guard 與 advance 後成功；idempotency 與 Character entry 拒絕；End Combat 保留 outcome；REST + MCP parity）；`tests/test_p4f_postgres_migration.py` 2 條（PostgreSQL gate：0026 → heads → downgrade，constraint 接受 / 拒絕 `surrendered`）。本機 P4-B～F + M04-C + M03 + migration contract 全通過；`alembic heads` = `0015` / `0027`。
- 新增 `.github/workflows/p4f-non-e2e.yml`（P4-E 版改 branch / focused / `test_p4f_postgres_migration.py`）。
- 留給 F3：UI 的 outcome 控制與新 status 標籤；F2：Monster Instance bookkeeping。

### F2 — Monster Instance bookkeeping

- 2026-09-17，agy worker（Gemini 3.8 Flash (High)，1 回合 13.5 分鐘），Claude 審核修正與 commit。prompt：`C:\_work\AI_Work\Toolsgy-runsgy-p4f-f2.prompt.txt`。
- 交付：migration `0028_p4f_monster_reveal_state`（`monster_instances.reveal_state` JSON NOT NULL default `{}`）；`StoredMonsterInstance.reveal_state`；`MonsterRevealState.from_mapping` / `to_mapping`，`monster_instance_to_combatant` 未傳 reveals 時直接讀 instance 持久化狀態（`get_active_combat_detail` 的「尚未持久化」占位移除）；`MonsterRevealPatch` / `MonsterInstancePatchInput`（name / visibility / position_note / reveal，`model_fields_set` 區分省略與 null，空 patch 拒絕）；新 `MonsterBookkeepingRepository.update_instance`（單一 `append(transaction_projection=...)`：鎖 instance、merge reveal、name 變更同步 active `combat_entries.display_name` 並 bump `combats.revision`、公開 event `combat.monster_instance_updated`，payload 只有 monster_instance_id / combat_entry_id / name / visibility / changed / reveal flags）；`MonsterInstanceService.update_instance`（DM-only、notifier wake）；REST `PATCH .../monster-instances/{instance_id}`；MCP `combat_update_monster_instance`（DM）。head 引用改到 `0028`。
- **Claude 審核修正**：① `MonsterInstanceService` 新增 optional `bookkeeping_repository` 參數並在 None 時自建 → 改為永遠由 service 自建（它本來就有 engine 與 event repository），dependencies.py 與測試 fixture 不再注入；② `MonsterRepository.update_instance` 加了沒人呼叫的 `reveal_state` 參數 → 移除；③ repository 內對已是 bool 的 reveal patch 再 `isinstance` 過濾、對 Literal 已驗證的 visibility 再驗一次 → 移除；④ agy 改 `test_p4c_postgres_migration.py` head 集合時把 `P4C_HEAD =` 那行刪掉，P4 regression collection 直接 NameError → 補回。
- 測試：`tests/test_p4f_monster_bookkeeping.py` 6 條（name 傳播到 entry + revision + event + idempotency；hidden → public 後 Player detail 才出現且仍無 AC / HP；reveal AC / position note 只開放對應欄位；Player 拒絕零副作用 / 他 Campaign instance 404 / 空 patch；REST + MCP parity；event payload 無秘密）；`tests/test_p4f_postgres_migration.py` +1（0027 → heads 加欄位、既有 row 得 `{}`、downgrade 移除）。本機 P4-B～F + M04-C + M03 + migration contract 全通過；`alembic heads` = `0015` / `0028`。
- 留給 F3：UI（DM 卡片 outcome / visibility / reveal / position note 控制、新 status 標籤、Player 端呈現）。

### F3a — DM projection reveal flags、web client、status 標籤、combat log

- 2026-09-18，agy worker（Gemini 3.8 Flash (High)，1 回合 9 分鐘），Claude 審核與 commit。prompt：`C:\_work\AI_Work\Toolsgy-runsgy-p4f-f3a.prompt.txt`。F3 拆成 F3a / F3b 兩步，避免 UI 大步 timeout。
- 契約缺口（Claude 派工前發現）：DM detail projection 只有 `visibility`，沒帶 F2 持久化的 reveal 狀態，UI 無法呈現 toggle 現況；F3a 補上。
- 交付：`project_combatant` DM audience 且 `kind == "monster"` 時加 `reveal: {armor_class, description, position_note}`；Player friendly / enemy projection 不帶該 key（secrecy test forbidden_keys 加 `reveal`，own character 斷言無 `reveal`；`test_p4f_monster_reveal_toggles` 斷言 DM `reveal` 隨 PATCH 翻轉）。web `api/combat.ts`：`CombatantProjection.reveal?`、`MonsterOutcome` / `MonsterOutcomeInput` / `MonsterRevealPatch` / `MonsterInstancePatchInput`、`setMonsterOutcome`（POST `.../combat/entries/{entryId}/outcome`）、`updateMonsterInstance`（PATCH `.../monster-instances/{instanceId}`）。`sessionCopy.ts` 加 `combatStatusUnconscious` / `combatStatusSurrendered` / `combatStatusFled`（雙語），`SessionCombatStage.getStatusLabel` 處理三種新 status。`sessionCombatLog.ts`：`combat.monster_outcome_set`（`<entry> · <outcome label>`，note 作 detail）與 `combat.monster_instance_updated`（`<name> · 敵人資訊已更新`，`changed` 欄位名 localized 作 detail，不印 reveal bool）；copy 10 key 雙語。
- **Claude 審核修正**：只有 vitest 案例名多了 `(i)` 前綴，直接改掉；其餘零修改。
- 測試：pytest 焦點 5 檔 32 passed；P4-B～F + M04-C + M03 boundary 全通過（exit 0）；`npm test -- --run` 85 files / 469 passed；`npm run build` 乾淨。長行數對照 HEAD 無新增。
- 留給 F3b：per-card DM 控制元件與 Stage 接線、Player 不渲染測試。（已完成，見下）

### F3b — DM 卡片 Monster 控制元件

- 2026-09-18，agy worker（Gemini 3.8 Flash (High)，1 回合 4.5 分鐘），Claude 審核與 commit。prompt：`C:\_work\AI_Work\Tools\agy-runs\agy-p4f-f3b.prompt.txt`。
- 交付：新元件 `SessionCombatMonsterControls.tsx`（root `data-monster-controls=<entry.id>`）：reveal 三個 checkbox（`data-monster-reveal`，由 DM projection `reveal` 驅動，缺 `reveal` 時不渲染該列）、visibility 切換鈕（`data-monster-visibility`）、name + position note 表單（`data-monster-save`，只送有變更的欄位，空 note 送 `null`，無變更不呼叫 API）、outcome 表單（`data-monster-outcome` / `-note` / `-submit`，只在 `entry.status === 'active'` 渲染；running 且該 entry 為 current turn 時停用並顯示 `combatOutcomeCurrentTurnHint`；`other` 缺 note 停用）。全部走 `runCombatMutation` + `requestId`。`SessionCombatStage` 只在 `isCurrentDm && subject_kind === 'monster' && monster_instance_id !== null` 時於卡片尾端渲染，`refresh` 用 `refreshCombatResources`。`sessionCopy.ts` 19 個 key 雙語；`sessionTable.css` 兩個 class。
- **Claude 審核修正**：`projection.reveal && typeof projection.reveal === 'object'` 多餘 guard → `projection.reveal ?? null`；vitest 案例名 `(1)`～`(6)` 前綴移除。其餘零修改。
- 測試：`SessionCombatMonsterControls.test.tsx` 6 條（reveal 全 false / armor_class true 勾選 / current turn 停用 + hint / fled 無 outcome 但保留其他控制 / hidden 顯示「Show to Players」/ zh-TW 文案）；`SessionCombatStage.test.tsx` +1（DM 有 goblin 控制、character 卡無、Player 完全無 `data-monster-controls`）。`npm test -- --run` 86 files / 476 passed；`npm run build` 乾淨。對照 `e2e/p4e-quick-combat.spec.ts` 的卡片斷言（`not.toContainText('Position Note:')`、scoped `getByLabel`）不受新表單影響；瀏覽器實測留給 F6 full journey。
- F3 完成。留給 F4：`grappled` escape action + Character state PATCH DTO。

### F4a — escape_grapple

- 2026-09-18，agy worker（Gemini 3.8 Flash (High)，1 回合 8 分鐘），Claude 審核修正與 commit。prompt：`C:\_work\AI_Work\Tools\agy-runs\agy-p4f-f4a.prompt.txt`。
- 設計：抓者由 escaper 明確指定 `target_entry_id`（不從 condition note 反推）；escaper 用 Athletics / Acrobatics 較高者、抓者用 Athletics；tie 逃脫失敗（同 grapple 規則）；不做 reach 裁定，request 直接開兩張 roll request；耗整個 Action（`action_available=False`，`attacks_used` 不動）。
- 交付：`SpecialAttackKind.ESCAPE_GRAPPLE`、`SpecialAttackOutcome.condition_to_remove`、`resolve_escape_grapple`（`resolve_grapple_or_shove` 對 escape 拋 ValueError）；service `_is_grappled` / `_best_escape_unit`（grapple defender 與 escape attacker 共用）、`request_special_attack` escape 分支 → 新 repository `request_escape`（event `combat.escape_grapple_requested`，idempotency prefix `p4f-escape-request:`，`_validate_escape_turn` / `_consume_action`）；`adjudicate_reach` 的 in_reach 分支抽成 `_open_opposed_rolls` 與 escape 共用；`_apply_condition` 改為 `_mutate_conditions` + `_remove_condition_from_entry`；`complete_roll` 依 kind 分派 resolver，result 統一多 `condition_to_remove` key，escape 成功移除 escaper 的 `grappled`。MCP `_WHEN_TO_USE` / `_desc` 兩個 special-attack tool 文案補 escape（雙語），無新 tool、無新 route、無 migration（`combat_actions.action_kind` 無 CHECK）。
- **Claude 審核修正**：① `request` / `request_escape` 兩份相同的 combat / attacker / target 鎖定區塊 → 抽 `_lock_request_context`；② `request_escape` 對 `_open_opposed_rolls` 回傳值重設 `kind` / `status`（已由 helper 設定）→ 移除；③ `complete_roll` 巢狀 `if kind is ESCAPE / else` 三層 → 攤平成單層 `condition_to_remove` / `condition_to_apply` 鏈；④ 測試 `escape_actions` 查了沒斷言 → 補 `== []`；測試名 `test_1_`～`test_5_` 前綴移除。
- 測試：`tests/test_p4f_escape_grapple.py` 5 條（Monster 逃脫成功 + idempotency；失敗與 tie 保留 grappled 且 Action 已耗；Character 逃脫成功、其他 condition 保留、`state_revision` +1；四種拒絕零副作用 + grapple 仍需裁定；REST `POST .../special-attacks/request` + MCP `combat_request_special_attack` / `combat_roll_special_attack` parity）。焦點 11 檔 76 passed；P4-B～F + M04-C + M03 boundary 全通過（exit 0）；長行對照 HEAD 無新增。
- 留給 F4b：Character state PATCH DTO（已完成，見下）；F4c：web action bar + log。

### F4b — Character state PATCH DTO 補 P4-D 欄位

- 2026-09-18，agy worker（Gemini 3.8 Flash (High)，1 回合 6.5 分鐘），Claude 審核修正與 commit。prompt：`C:\_work\AI_Work\Tools\agy-runs\agy-p4f-f4b.prompt.txt`。
- 交付：`TableCharacterStatePatch`（table）與 `CharacterStatePatch`（Workshop / standalone `/api/characters/{id}/state`）各加 `concentration` / `exhaustion_level`（0..6）/ `death_saves` / `temporary_effects`；nullable 集合加 `concentration`（null = 清除；其餘三欄不得 null）。新常數 `COMBAT_CORRECTION_ONLY_FIELDS`（六欄：HP 兩欄 + 這四欄）取代 service 與 persistence 兩處內嵌的 `{"current_hp","temporary_hp"}` guard：active Combat 中 Player 拒絕、DM 需 `correction_reason`，event 照舊記 `correction` / `changed_fields`。Workshop 路由維持無 Room / Combat import。明確非目標：raw `concentration: null` 不清其他 combatant 的 linked effects（歸 `CombatConcentrationRepository.complete_check`），寫在測試 docstring。
- **Claude 審核修正**：錯誤訊息 "Active Combat Combat-owned state changes…" 語病 → "Combat-owned state changes during active Combat…"（兩處四句）；`test_table_state_patch_p4d_validation_rejects_before_any_write` 建了沒用到的 service / actor / events → 移除。
- 測試：`test_p4c_semantic_hp_boundary.py` +1（四欄 outside Combat 正常、active Combat Player 零副作用拒絕、DM 無 reason 拒絕、DM 有 reason 成功且 event 帶 correction；既有 HP 測試改用共用 `_assert_combat_mutation_refused_zero_side_effects` helper，並補零副作用斷言）；`test_p3c_table_character_state.py` +1（`exhaustion_level=7` / `death_saves.successes=3` / `death_saves=null` 寫入前拒絕；`concentration=None` 單獨算真實變更）；`test_p1g_character_versions.py` +1（Workshop 路由 200 / 422）。P4-B～F + P3-C + M03 + P1-F/G + character_state 共 79 檔全通過（exit 0）。
- F4 剩 F4c（server 判別修正）與 F4d（web）。

### F4c — special-attack 骰與裁定的 canonical 判別

- 2026-09-18，agy worker（Gemini 3.8 Flash (High)，1 回合 10 分鐘），Claude 審核修正與 commit。prompt：`C:\_work\AI_Work\Tools\agy-runs\agy-p4f-f4c.prompt.txt`。
- 起因（Claude 準備 web escape UI 時發現，P4-E 遺留）：① web 送 `kind: 'shove'`，server enum 只有 `shove_prone` / `shove_push`（UI Shove 會 422，F4d 修）；② `pending_combat_roll_request_type` 只認 `"grapple"` / `"shove"`（後者永不出現），且 `list_pending_requests` 只透過 `combat_actions.roll_request_id` join 到攻方那張骰 → shove 兩張骰、grapple 防守方那張骰都變 `request_type="skill"`，前端無 handler；③ adjudication 分類用 `("grapple","shove")` → `shove_*` reach 裁定不歸 `reach`、不導向專用 route。
- 交付：`resolution.REACH_ADJUDICATED_KINDS`（grapple / shove_prone / shove_push，不含 escape）供 `row_to_adjudication_view` 與 `resolve_adjudication` 共用；`core_rolls.special_attack_request_type`（`shove_*`→`"shove"`、`escape_grapple`→`"escape_grapple"`）與 `_SPECIAL_ATTACK_LABEL_TO_KIND`（由 `SpecialAttackKind` 派生的 title-case label 對照）；`pending_combat_roll_request_type` 在 `action_kind` 為 None 時改用 `roll_groups.label` 判別（同 Concentration / Initiative 既有慣例，無 JSON SQL、無額外 query）；`get_request` 補上與 `list_pending_requests` 相同的 `combat_actions` outer join。
- **Claude 審核修正**：`pending_combat_roll_request_type` 的 if / elif 兩段各自呼叫 helper → 合併為「先解 kind（action_kind 或 label）再一次查表」並加註解；其餘零修改。
- 測試：`test_p4e_pending_rolls_route.py` parametrize 改為 `shove_prone` / `shove_push` / `escape_grapple` 與 label 路徑（移除不可能的 `action_kind="shove"`）；`test_p4c_special_attacks.py` +1 parametrize（grapple / shove_prone / escape 真實流程：DM 看到兩張 request_type 一致的骰、Player 只看到自己那張）；`test_p4e_adjudication_routes.py` +2（`shove_prone` 裁定列為 `reach`、dm_hints 同 grapple；`resolve_adjudication` 導向專用 route 的 conflict）。焦點 10 檔 64 passed；P4-B～F + P3-C + M04-C + M03 共 71 檔全通過（exit 0）；長行對照 HEAD 無新增。
- 留給 F4d：web（已完成，見下）。

### F4d — web：special-attack kinds 與 escape UI

- 2026-09-18，agy worker（Gemini 3.8 Flash (High)，1 回合 8 分鐘），Claude 審核修正與 commit。prompt：`C:\_work\AI_Work\Tools\agy-runs\agy-p4f-f4d.prompt.txt`。
- 交付：`api/combat.ts` 新 `SpecialAttackKind` union（grapple / shove_prone / shove_push / escape_grapple），`SpecialAttackRequestInput.kind` 改用（修 UI Shove 送 `'shove'` 被 422 的 P4-E bug）。`SessionCombatActionBar`：`ActionKind` 擴為六種，select 改由 `ACTION_KINDS` allowed-list 收窄（無 `as` cast），選項順序 attack / grapple / shove (prone) / shove (push) / escape grapple（只在 `combatantFor(acting).projection.conditions` 含 `srd5.1:condition:grappled` 時出現，失去 grappled 時自動退回 attack）/ spell；`isSpecialAttackKind` 統一四種 special kind 的 target 必填與 submit label；roll handler `escape_grapple` → `rollSpecialAttack`；`requestTypeLabel` 加 escape。`sessionCombat.pendingCombatRollHandler` 加 `escape_grapple`。`sessionCombatLog`：`combat.escape_grapple_requested` 行、`specialAttackKindLabel` 加 escape、`condition_to_apply` / `condition_to_remove` 共用新 `formatConditionRefDetail`。copy：`combatActionKindShove` 拆成 `ShoveProne` / `ShovePush`，新 `combatActionKindEscapeGrapple` / `combatRollTypeEscapeGrapple`，log copy `escapeGrapple` / `conditionRemoved`，皆雙語。
- **Claude 審核修正**：`SpecialAttackView.kind: SpecialAttackKind | string`（等於 string）→ `string`；`escape_grapple_requested` 的 `stringField(payload,'kind') ?? 'escape_grapple'` 多餘 fallback → 直接用 `copy.escapeGrapple`。其餘零修改。
- 測試：`SessionCombatActionBar.test.tsx` +3（無 grappled 時無 escape 選項且有兩種 shove；有 grappled 時出現 `value="escape_grapple"`；`request_type: 'escape_grapple'` pending roll 顯示 escape label 並派給 `rollSpecialAttack`）、`sessionCombat.test.ts` +1、`sessionCombatLog.test.ts` +3（requested 雙語、resolved escape 顯示移除狀態、grapple 仍顯示套用狀態）、`combat.test.ts` 改送 `shove_prone`。`npm test -- --run` 86 files / 478 passed；`npm run build` 乾淨；長行對照 HEAD 無新增。`e2e/p4e-quick-combat.spec.ts` 不碰 grapple / shove 文案，不受影響。
- **F4 完成**（F4a～F4d）。瀏覽器實測 escape 流程留給 F6 full journey。

### F5 — 真 PostgreSQL restart / reconnect

- 2026-09-18，agy worker（Gemini 3.8 Flash (High)，1 回合 19.7 分鐘），Claude 審核修正與 commit。prompt：`C:\_work\AI_Work\Tools\agy-runs\agy-p4f-f5.prompt.txt`。
- Restart 模型：沿用 P3-F 先例（`test_p3f_postgres_restart_recovery.py`）——process 內丟掉 engine / pool / notifier / 全部 service 物件，只留 JSON-plain 的 `ids` dict，再從 PostgreSQL 重建 `_Services`（constructor 對照 `app/api/rooms/dependencies.py` 逐一接線，含 `ProcessLocalTableEventNotifier`）。真 process 層級的 restart 留給 F6 Docker E2E 補。
- 交付：`tests/test_p4f_postgres_restart_recovery.py`（`P4_POSTGRES_URL` gate，schema reset + `alembic upgrade heads`）。場景：`support._setup()` 以 monkeypatch 的 PostgreSQL engine 建世界 → 1 Character + 2 quick enemy → Quick Combat → initiative → 推到 Round 4 Player turn → 同時掛著一張 pending saving throw、一個 open reaction window（advance_turn 會清 incoming combatant 的 `pending_reaction_state`，所以 window 在推到 Player turn 之後才開）、一個 Player attack 的 `dm_adjudication_required` 裁定 → dispose + del → 重建 → Human DM / Human Player / AI participant 重新驗證 → DM detail、Player detail（仍無 monster `current_hp` / `armor_class`）、DM + Player pending rolls、reaction window、adjudication list 逐欄等於 restart 前 dump，`combats.revision` 與 `session_events` max seq 不變（重連不寫 event）→ AI participant 經 `CombatAIToolApplicationService.combat_get_active` / `combat_get_context` 看到同一 Round / current turn → save 用實體骰 resolve 一次（`roll_results` 恰一列，同 key retry 不增、revision 不變）、reaction resolve + retry、DM in-range 裁定 + retry → 第二次 restart 確認落地。`.github/workflows/p4f-non-e2e.yml` postgres job 加入該檔。
- 契約說明：Session 的 DM controller 單值（human 或 ai），Human DM 在場時 AI DM grant 不能驗證，所以「AI reconnect」以 AI participant（`let_ai_control_player`）證明；產品規格如此，非缺口。
- **Claude 審核修正**：helper `ai_dm` 實際是 AI participant → 改名 `ai_participant`。
- **順帶修 CI（P4-F PostgreSQL job 自 F1 起紅，本機因 gate 跳過而未察覺）**：① `test_p4f_postgres_migration.py` 的 raw `INSERT INTO rooms (id, name)` 缺 `code` / password / key hash / timestamps 等 NOT NULL 欄 → 抽 `_seed_room_and_campaign` 補齊全部 NOT NULL 欄；② `test_p4e_postgres_migration.py` 在 `upgrade heads` 後斷言 `P4E_HEAD in _revision_set()`，但 head 已是 `0028` → 改為 `P4E_APPLIED_HEADS` 交集（同 P4-C 測試既有做法）。
- 測試：本機 `P4_POSTGRES_URL`（專用 DB `adventure_table_p4f`）跑 P4-A～F 全部 PostgreSQL migration / concurrency / restart 測試 exit 0；無 env 時 restart 測試 SKIPPED（gate 生效）。
- 留給 F6：full browser journey + Docker `docker compose restart server` 補真 process restart。

