# P4-E Closeout Checklist

P4-E — Quick Combat UI, DM Adjudication & AI Tool Surface closeout scope。編號對應 [實作規格](實作規格.md) 的「完成後必須為真」；E.1～E.5 對應 [測試指南](測試指南.md)。步驟級的實作過程見 [P4-E實作紀錄.md](P4-E實作紀錄.md)（工作紀錄，不是契約）。

- [x] 1. Quick Combat 沿用 Session table layout：`SessionCombatStage` 掛在既有 Main Stage 區塊內（Combat Header / Initiative List / Combatants / Quick Action Bar），Chat / Dice / Log 分頁與 Stage editor 不變（`SessionCombatStage.test.tsx`、`SessionTableSurface.test.tsx`；Playwright `p4e-quick-combat.spec.ts` 於 Combat 進行中切換 Log 分頁）。
- [x] 2. Combat Header 顯示 Round / Current Turn（`round_number` 為數字才顯示 Round，否則 Preparing）；Combatants 顯示公開名稱、conditions、action economy、optional Position Note（`SessionCombatStage.test.tsx` 5+2 條；E2E 第 9 點：Quick Enemy 有 Position Note、SRD Monster 沒有，兩者同場正常跑）。
- [x] 3. DM 完整 / Player secrecy：`GET .../combat/detail` 依 audience 投影，Player raw JSON 無敵人 HP / AC / resources / hidden conditions / dm_notes（`test_p4e_combat_detail_secrecy.py` 7）；event payload 與 P4-C mutation response 對 Player redaction（`test_p4e_event_secrecy.py` 7，`event_projection.py`）；MCP `get_combat_context` / `get_session_context` Player 版同一份 allowlist（`test_p4e_mcp_combat_context_and_effects.py`、`test_p4e_session_context_combat.py`）。E2E 第 7、8 點：Player 卡片無 `HP:` / `AC:`、Player detail API `current_hp` / `armor_class` 為 null，DM 卡片有；Player Log 行無 `HP` / `AC`，DM Log 行有。
- [x] 4. Player 選 Action → target，不需 Scene / EncounterTemplate / Map：Quick Action Bar（Attack / Grapple / Shove / Spell）直接以 CombatEntry 為 target（`SessionCombatActionBar.test.tsx`；E2E 第 5 點 Player 在自己 turn Request Attack）。
- [x] 5. DM adjudication：range / reach / OA trigger / affected targets / special ruling 的 REST（`test_p4e_adjudication_routes.py` 7）、MCP（`combat_request_adjudication` / `combat_request_opportunity_attack` / `combat_resolve_adjudication`，`test_p4e_mcp_combat_context_and_effects.py`）、UI（`SessionCombatAdjudicationPanel.test.tsx`）。E2E 第 10 點：Player attack 進 range adjudication → DM「In range」→ Player pending roll 出現並擲骰。
- [x] 6. Position Note / Main Situation optional：E2E 第 9 點；`test_p4e_monster_instance_routes.py`（Quick Enemy 有無 attack / note）。
- [x] 7. Human DM 直接調整 Monster Instance / combatant status 走正式 mutation：Monster Instance 建立（from-content / quick-enemy，含 visibility / position note）、`withdraw` / `remove` entry、DM absolute HP set（P4-C `correction_reason`）皆為 server mutation + event，無 Undo。**部分**：建立後的 visibility / position note 修改與 MonsterRevealState 尚無 REST / UI（見「已知限制」）。
- [x] 8. MCP tool catalog 依 role：38 個 `combat_*` tool，DM / Player 各自合法集合，Player 呼叫 DM tool 在 facade 前被拒且零 row；沒有 raw HP patch tool（`test_p4e_mcp_combat_lifecycle.py` 5、`test_p4e_mcp_combat_context_and_effects.py` 6；`test_m04c_tool_descriptions.py` / `test_m04c_guide_tool_parity.py` 雙語 description parity）。
- [x] 9. `get_session_context` / briefing 在 active Combat 附 compact combat context（Round、Current Turn、自身可見 combatants、pending roll / reaction / adjudication、`next_required_action`），不含 `rules_snapshot`（`test_p4e_session_context_combat.py` 5）。
- [x] 10. AI DM / AI Player wire-level journey：quick enemy → start → add monster → initiative request / roll / finalize → advance → end，與 REST 同一 state（`test_p4e_mcp_combat_lifecycle.py`）；spell / reaction / concentration / adjudication tool（`test_p4e_mcp_combat_context_and_effects.py`）。
- [x] 11. AI 與 Human 共用 Combat services：MCP tools 只做 auth / DTO 轉接，全部呼叫 `CombatService` / `CombatAttackService` / `CombatSpellService` 等同一批 service（`app/domain/combat/ai_tools.py`）；REST ↔ MCP DTO parity（`test_p4e_attack_provenance.py`、`test_p4e_pending_rolls_route.py`）。
- [x] 12. Chat / Log 分工：敘事留 Chat（`isSessionChatEvent`），Combat 機械結果以 compact Log 呈現（`sessionCombatLog.ts`：attack / spell / save / death save / concentration / reaction / adjudication / lifecycle / special attack；`sessionCombatLog.test.ts` 23 條）。E2E 第 6 點：命中後 DM 卡片 HP、DM detail API、DM Log 行三者一致。
- [x] 13. 雙語同 Subphase 交付：UI copy（`sessionCopy.ts` 兩 locale 等量 key，`hardcodedUiCopy.test.ts`）、Combat Log copy（`sessionCombatLog.ts`）、Combat REST error codes（`sessionMessages.ts` `P4E_SESSION_REQUEST_CODES` 13 個 + `test_p4e_combat_error_codes.py`）、tool descriptions 與 guide / briefing（`test_p4e_session_context_combat.py::test_5`、M04-C parity tests）。
- [x] 14. Monster caster persisted cast：`CombatSpellRepository.cast_monster_spell` 扣 `monster_instances.resources`、target state、roll record、event 同一 transaction（`test_p4e_monster_cast.py` 7；REST / MCP `test_p4e_spells_reactions_routes.py`）。
- [x] 15. Monster concentration canonical state：migration `0026_p4e_monster_concentration`（`monster_instances.concentration`），受傷建 CON save、`complete_check` 接受 Monster target 並清 linked effects（`test_p4e_monster_concentration.py` 8；`test_p4e_postgres_migration.py` 2，PostgreSQL gate）。
- [x] 16. Concentration CON save 只由 `CombatConcentrationRepository.complete_check` 消費：P3-C 通用 roll resolve 拒絕 `label="Concentration"` request，UI / MCP 走 `/concentration/roll` / `combat_roll_concentration`（`test_p4e_concentration_routing.py` 6）。

## 契約以外的實作決定

| 項目 | 決定 |
|---|---|
| Migration | `0026_p4e_monster_concentration`（web track）：`monster_instances.concentration` nullable JSON。Character track 不動（仍 `0015`）。Standalone 不含 Monster Instance / Combat tables，boundary test 未變。 |
| 事件 | 新增 `combat.*`：`adjudication_requested` / `adjudication_resolved` / `saves_requested` / `save_resolved` / `death_save_resolved` / `special_attack_*`（3）/ `spell_cast_resolved` 等；initiative / attack / save 的 request 與 result 沿用 P3 `roll.requested` / `roll.resolved` 並帶 `combat_id`（E12 起 initiative `roll.resolved` 也帶），前端以 `combat_id` 判定為 Combat state change 觸發 refetch。 |
| Long-poll wake | 所有 Combat service mutation 在成功後呼叫 `TableEventService.notifier.notify(session_id)`；`CombatService` / `CombatOrderService` 原本漏掉，E12 Playwright 揭露後補上（`test_p4e_combat_wake_notifications.py`）。 |
| Attack 名稱雙語 | `ResolvedAttack.content_ref` + `presentation_field`（inventory → item `name`；SRD monster action → template `data.actions.<idx>.name`）隨 DTO / event 送出，前端用 `useContentPresentations.fieldFor` 解析；Quick Enemy / 自訂名稱不假造 content ref。 |
| REST error code | `combat_reactions` / `combat_spells` / `combat_special_attacks` 的 missing Combat 統一為 `combat_not_found`；MCP 端維持 M04 `structured_tool_error` 粗粒度雙語 code。 |
| E2E 決定論 | Quick Enemy AC 1 讓 attack 幾乎必中；spec 仍以最多 6 輪「advance 回自己 turn → 再攻擊」迴圈處理 natural 1。 |
| Worker | E1～E9b agy、E10a～E11a-fix2b ChatGPT Web、E11a-fix3 本機 worker、E11b agy、E12 指揮者；流程與踩坑見 `docs/others/conductor-handbook.md`。 |

## Verification 過程中修正的缺口

| # | 缺口 | 處理 |
|---|---|---|
| G1 | `CombatService`（start / add / advance / use_action / reaction window / withdraw / remove / end）與 `CombatOrderService.reorder_running` 不喚醒 long-poll waiters，其他參與者要等 30 s timeout 才看到 Combat 變化 | `08e46b19`：`_notify(actor)`；`test_p4e_combat_wake_notifications.py` |
| G2 | Session page 只把 `combat.*` 當 Combat event，initiative / attack 的 `roll.requested` / `roll.resolved` 不觸發 refetch，Player 看不到自己的 Roll Initiative 按鈕 | `08e46b19`：`isCombatEvent` 接受帶 `combat_id` 的 `roll.*`；initiative `roll.resolved` 補 `combat_id` |
| G3 | `saves_requested` compact log 把 ability 吞成 null；`sessionCombatLog.test.ts` 68 處缺第 5 個 resolver 導致 build 失敗 | `e16e7d47` |
| G4 | 13 個 Combat REST error code 在 web 端無 zh-TW / en 訊息 | `5244e5ab`（E11b） |
| G5 | 分支沒有 P4-E CI workflow，`0026` migration 無 PostgreSQL 證據 | `08e46b19`：`.github/workflows/p4e-non-e2e.yml` |

## Verification evidence

分支 `feat/p4e-quick-combat-ui-adjudication-ai-tools`，最終 code SHA `08e46b19`。本 closeout 與 `PROJECT_BRIEF.md` / `P4-E實作紀錄.md` 為其後的 docs-only commit。依 P4 subphase merge policy，關門後以 `--no-ff` 合併回 `main`。

```text
Alembic heads（apps/server: alembic heads）
  0015_character_state_revision (character) (head)
  0026_p4e_monster_concentration (web) (head)

Backend pytest（全套，cwd apps/server，..\..\.venv\Scripts\python.exe）
  08e46b19 本機：1693 passed / 52 skipped，exit 0；skip 全為 PostgreSQL env-gated

Focused P4-E backend（08e46b19，本機，含 P4-B / P4-C / P4-D regression 與 M03 boundary：exit 0）
  test_p4e_adjudication_routes 7 · attack_provenance 3 · castable_spells_route 3 · combat_detail_secrecy 7
  combat_error_codes 5 · combat_wake_notifications 1 · concentration_routing 6 · event_secrecy 7
  mcp_combat_context_and_effects 6 · mcp_combat_lifecycle 5 · monster_cast 7 · monster_concentration 8
  monster_instance_routes 6 · pending_rolls_route 5 · postgres_migration 2（PostgreSQL gate）
  session_context_combat 5 · spells_reactions_routes 6

PostgreSQL gate（GitHub, P4-E Non-E2E Regression / postgres-migrations）
  08e46b19 run 35235702182：tests=37 passed=37 skipped=0（含 test_p4e_postgres_migration.py 2）

Frontend unit / build（08e46b19，本機）
  vitest 85 files / 466 passed；vite build success

docker compose config
  exit 0（本機）

GitHub Actions
  P4-E Non-E2E Regression @ 08e46b19 run 35235702182：backend / postgres-migrations / frontend / compose-config 全 success

E2E（Subphase 關門 + 合併回 main 的 gate）
  本機 npm run test:e2e:docker（ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1，
  走 U01-A 的 adventure_table_e2e + server-e2e / web-e2e，rebuild server + web image）@ 08e46b19：
    主套件 128 tests：124 passed / 4 skipped（12.3m，與 full backend pytest 並行執行）
    含新 spec e2e/p4e-quick-combat.spec.ts：P4-E E.1 DM + Player Quick Combat journey（5.1s）
    disabled-pack 套件 7 tests：7 passed
  exit 0
```

## 已知限制 / 留給後續 Subphase

- **實作規格 7 只到部分**：Monster Instance 建立後無法經 REST / UI 改 visibility（reveal）或 position note；`MonsterRevealState` 未持久化；DM 對 Monster HP 的 absolute set 走 P4-C `correction_reason` 路徑但 UI 未接。歸 P4-F。
- **Browser E2E 未涵蓋 spell cast / AoE 與 reaction window**：`SpellActionFields` 只有 unit test（E10d-2b 已知限制）；REST / MCP 層有測試。P4-F integration journey 補。
- **`ConditionSemantics` 仍未接進 attack / save modifier pipeline**（P4-D 留下）：advantage / disadvantage / auto-fail 未自動套用。歸 P4-F。
- **P4-C 留下的 Monster 0 HP outcome action、`grappled` escape、Character affinity 欄位**未在 P4-E 處理；Character state PATCH DTO 未 expose `concentration` / `exhaustion_level` / `death_saves` / `temporary_effects`。歸 P4-F / M01。
- **Monster long-form `desc` 尚未 expose 給 UI**，首次 expose 的 Subphase 要同步補 zh-TW。
- `get_resolution_event` 沿用 P4-D 的 session event Python 掃描（O(n)），長場次可在 P4-F 收斂。
- `test_p4e_combat_error_codes.py` 的 code 集合是手寫 frozenset，只鎖已知集合；新增 REST code 時需同步改此測試與 web SSOT。
