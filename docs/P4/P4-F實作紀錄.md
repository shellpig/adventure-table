# P4-F — Full P4 Integration & Closeout 實作紀錄

最後更新：2026-09-17

## 目標與邊界

本紀錄對齊 `實作規格.md` P4-F（1～11）、`開發設計方針.md` §9、§10、`測試指南.md` P4-F（F.1～F.4）。P4-F 以真正可玩的完整 Quick Combat journey 驗證 P4，並收掉 P4-C／P4-D／P4-E closeout 留下、已明列歸 P4-F 的缺口。不做 P5 geometry、不建 P6 runtime、不加 Undo。

branch：`feat/p4f-full-p4-integration-closeout`（自 `main` `6ed11d24` 開出）。實作以步驟切分，每步獨立可驗證、獨立 commit；步驟由 agy worker 執行、Claude 審 diff / 跑 focused test / commit（流程見 `docs/others/conductor-handbook.md`）。每步完成後更新下表。

已拍板（2026-09-17）：`ConditionSemantics` 接進 attack / save modifier pipeline納入 P4-F（F7），排在真實 AI gate 之前的最後一個 code step，不阻塞 F.3。

## 步驟進度

| 步 | 內容 | 對應契約 | 狀態 |
|---|---|---|---|
| F1 | Monster 0 HP outcome：DM 選 dead / unconscious / surrendered / fled / other；migration `0027` 放寬 `combat_entries.status` / `monster_instances.combat_status`；REST + MCP + event | 實作規格 P4-C 10、P4-E 7、P4-F 1；規格企劃「Monster 0 HP / Combat End」 | ✅ |
| F2 | Monster Instance bookkeeping：DM PATCH name / visibility / position_note + reveal toggles（AC / description / position note）；`MonsterRevealState` 持久化（migration `0028`）；REST + MCP + event | 實作規格 P4-E 7（部分→完整）、3 | ✅ |
| F3 | F1 / F2 的 Session table UI：DM 卡片 outcome / visibility / reveal / position note 控制、新 entry status 標籤、Player 可見 outcome、雙語 copy、web client | 實作規格 P4-E 1、2、13 | ⬜ |
| F4 | `grappled` escape action + Character state PATCH DTO 補 `concentration` / `exhaustion_level` / `death_saves` / `temporary_effects` | P4-C / P4-D closeout 留下 | ⬜ |
| F5 | 真 PostgreSQL + server restart / reconnect：Round ≥ 2、pending save 或 reaction → restart → 狀態完整、resolve 一次不重擲 | 實作規格 P4-F 3；測試指南 F.1 | ⬜ |
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
- 留給 F3：UI（DM 卡片 outcome / visibility / reveal / position note 控制、新 status 標籤、Player 端呈現）。依使用者指示 F3 暫不派工。
