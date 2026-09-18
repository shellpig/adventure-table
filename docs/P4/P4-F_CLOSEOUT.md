# P4-F Closeout Checklist

P4-F — Full P4 Integration & Closeout closeout scope。編號對應 [實作規格](實作規格.md) 的「完成後必須為真」；F.1～F.4 對應 [測試指南](測試指南.md)。步驟級的實作過程見 [P4-F實作紀錄.md](P4-F實作紀錄.md)（工作紀錄，不是契約）。

> **狀態：F9a（static review + regression + 全套 E2E 證據）已完成；F8 真實 ChatGPT Web Combat gate 未跑。** 第 9、10 項與 F.4 的「real ChatGPT Web gate」列在 F8 完成前留白，P4-F 不得關門、不得合併回 `main`，P4 Phase closeout 亦不得進行（測試指南 §5 blocker 最後一條）。

- [x] 1. Human browser journey：`e2e/p4f-full-combat-journey.spec.ts` 一條 spec 走完 Start Quick Combat → SRD Goblin + Quick Enemy → initiative → 多回合 Player / DM turns → shove_prone（condition）→ Cure Wounds（healing）→ Bless（concentration）→ DM 要求 DEX save → Player 擲 → attack → Quick Enemy 0 HP → DM outcome → End Combat（F6b / F6c）。
- [x] 2. 空間歧義交 DM adjudication 而非 fake geometry：`p4e-quick-combat.spec.ts` 第 10 點（Player attack → range adjudication → DM「In range」→ Player pending roll）；`test_p4c_adjudication.py` / `test_p4e_adjudication_routes.py`；F4c `REACH_ADJUDICATED_KINDS` 讓 grapple / shove 也走同一 reach 裁定。
- [x] 3. reload / reconnect / server restart 後 active Combat 可恢復且不重擲：process 層 `test_p4f_postgres_restart_recovery.py`（真 PostgreSQL，Round 4 + pending save + open reaction + pending adjudication → engine dispose 重建 → 逐欄相等、`revision` / `session_events` max seq 不變 → 每項 resolve 一次、同 key retry 不增）；browser 層 F6c step 10b（`restartE2EServer()` 真 `docker compose restart server-e2e` → 兩頁 reload → pending save 只 resolve 一次）。
- [x] 4. Session End 保持 active Combat、下一 Session resume、Combat End cleanup / preserved state：F6c step 10a（End Session → Start Session → 同一 `combat.id` / round / turn / outcome / condition）、step 11～12（End Combat 後 economy 歸零、HP / spell slot / concentration 保留）。
- [x] 5. Player / AI Player 敵人 secrecy 三層：browser（F6b / E2E 第 7 點 Player 卡片與 detail API 無 HP / AC；F3b Player 無 `[data-monster-controls]`）、API（`test_p4e_combat_detail_secrecy.py`、`test_p4e_event_secrecy.py` forbidden_keys 含 F3a `reveal`）、MCP（`test_p4e_mcp_combat_context_and_effects.py`、`test_p4e_session_context_combat.py`）。**真實 AI Player 的 browser-side 佐證留 F8。**
- [x] 6. DM proxy Player action 同一 rules / economy 且 audit 保留 acting DM 與 subject：`_authorize_roll` 回 `dm_proxy` execution_mode（`test_p4c_core_rolls.py`、`test_p4f_auto_fail_saves.py` DM 替 Monster 擲）；`test_p3c_*` execution_mode audit 未變。**真實 ChatGPT DM proxy 的 audit 證據留 F8。**
- [x] 7. P4 migration 真 PostgreSQL fresh + legacy；standalone boundary 乾淨：`test_p4f_postgres_migration.py` 4（0026 parent → heads、fresh heads、0028 與 0029 legacy upgrade / downgrade）；`test_p4a_*` / `test_p4b_*` / `test_p4c_*` / `test_p4e_*` postgres_migration 的 `*_APPLIED_HEADS` 均含 0029；`test_p3c_migration_contract.py` 鎖 0027 → 0028 → 0029 鏈；`test_m03_import_boundary.py` 通過（roll_requests / combat tables 皆多人層）。
- [x] 8. P0～P3 / M02～M04 regression 全綠：見 Verification evidence 的全套 backend pytest 與全套 E2E。
- [ ] 9. 真實 ChatGPT Web Plus 經 M04 connector 完成 Combat journey — **F8 待跑。**
- [ ] 10. 真實 AI gate 含 `wait_for_event` / reconnect continuity，M04 catalog / auth / role scope 未破壞 — **F8 待跑**（靜態面：`test_m04c_tool_descriptions.py` DM / Player catalog 集合、`test_m04c_guide_tool_parity.py` 於本分支通過）。
- [x] 11. static review、Non-E2E regression、Full-Stack E2E 與具名 closeout evidence：本檔。合併回 `main` 待 F8 通過後執行。

## 契約以外的實作決定

| 項目 | 決定 |
|---|---|
| Migration | web track 三個：`0027_p4f_monster_outcome`（放寬 `combat_entries.status` / `monster_instances.combat_status` 字彙）、`0028_p4f_monster_reveal_state`（`monster_instances.reveal_state` JSON NOT NULL `{}`）、`0029_p4f_roll_request_auto_fail`（`roll_requests.auto_fail` Boolean NOT NULL false）。Character track 不動（仍 `0015`）。 |
| Monster 0 HP outcome | DM 明選 dead / unconscious / surrendered / fled / other（`other` 必填 note），不自動判死；委派既有 `_set_entry_status` 加 `extra_payload` / `monster_outcome`，End Combat 保留 outcome。 |
| Monster reveal | `MonsterRevealState` 持久化在 instance；DM projection 帶 `reveal` flags，Player enemy allowlist 只在對應 flag 為真時才放 `armor_class` / `description` / `position_note`，`reveal` key 本身不送 Player。 |
| Conditions → 骰 | Quick Combat 無幾何：melee 視為 5 呎內、ranged 視為 5 呎外；frightened 需來源可見性 → `unresolved` 交 DM；adv / disadv 各一來源即抵銷；DM 裁定時的 `roll_mode` 是「選擇」不是繞過 conditions 的 override；save auto-fail 只看 STR / DEX，骰照擲、`roll_results` 照存一列，只有 `succeeded` 強制 False。 |
| escape_grapple | 走 P4-C opposed-check substrate，耗整個 Action、免 reach 裁定、成功同 transaction 移除 `grappled`。 |
| Character state PATCH | `COMBAT_CORRECTION_ONLY_FIELDS` 六欄（HP 兩欄 + concentration / exhaustion_level / death_saves / temporary_effects）在 active Combat 中一律 DM correction-only。 |
| E2E backend restart | `e2e/support/quickCombat.ts` `restartE2EServer()` 用 `docker compose --profile e2e restart server-e2e` + 等 `/api/meta`；spec 內 restart 於該 spec 結束前完成，後續 spec 打到已回來的 server。 |
| CI | `.github/workflows/p4f-non-e2e.yml`（push 本分支 / PR main）；`.github/workflows/p4-e2e.yml`（`P4 Full-Stack E2E`，`workflow_dispatch` only，與 `p3-e2e.yml` 只差 name / artifact）。後者要上 `main` 才會被 GitHub 註冊，本分支的全套 E2E CI run 以 `p3-e2e.yml --ref` 本分支取得。 |
| Worker | F1～F7c-1 agy（Gemini 3.8 Flash (High)），F3a / F3b / F6 / F7c-2 / F9 指揮者；agy 監看與判死規則寫進 `docs/others/conductor-handbook.md` §3.1（F7b 第一回合 35 分鐘空跑後新增）。 |

## Static review（F9a）

範圍：`git diff main...HEAD`（83 檔，+9118 / −609），對照 conductor-handbook §5 checklist。每步 diff 已在該步由指揮者逐一審過（見實作紀錄各步「Claude 審核修正」）；F9a 做整體掃描。

| # | 發現 | 判定 / 處理 |
|---|---|---|
| S1 | `persistence/combat/special_attacks.py` 以 `: Any` 標註 row / connection 參數的數量 8 → 18 | 沿用該檔既有寫法（SQLAlchemy `RowMapping` 未在此模組型別化），不新增型別債之外的行為；未改。留 M Phase 統一型別化。 |
| S2 | `app/mcp/tools.py` > 140 字元行 82 → 83（兩個新 tool 的單行 `_desc`） | 該檔 tool description 一律單行，與周圍一致；未改。 |
| S3 | `SessionCombatMonsterControls.test.tsx` 一條 `it(...)` 標題 > 140 | 測試標題，不影響行為；未改。 |
| S4 | REST 新 route（`/entries/{id}/outcome`、`PATCH /monster-instances/{id}`）用 `except Exception → _map_combat_error` | 與同檔既有 route 完全相同的錯誤映射樣式，不是吞錯；通過。 |
| S5 | REST ↔ MCP parity：`combat_set_monster_outcome` / `combat_update_monster_instance` / `combat_request_special_attack(kind=escape_grapple)` / saving-throw `auto_fail` 皆經同一 service，MCP 只做 auth / DTO 轉接 | 通過（`test_p4f_monster_outcome.py` / `test_p4f_monster_bookkeeping.py` / `test_p4f_escape_grapple.py` 各有 REST + MCP parity 案例）。 |
| S6 | 秘密過濾：`project_combatant` Player enemy 走固定 allowlist，`reveal` flags 僅 DM；web `SessionCombatMonsterControls` 只在 `isCurrentDm && monster` 時渲染 | 通過（`test_p4e_combat_detail_secrecy.py` forbidden_keys 含 `reveal`；`SessionCombatStage.test.tsx` Player 無 `data-monster-controls`）。 |
| S7 | 防禦式讀取：全分支唯一的 `payload.get("modifier_decision")`（F7b 前 legacy action）有註解與 `test_legacy_action_without_modifier_decision_completes_defensively` | 通過。 |
| S8 | `getattr` / `hasattr` / `lru_cache` / `# type: ignore` / TODO：新增 0 處 | 通過。 |

## Verification evidence（F9a）

分支 `feat/p4f-full-p4-integration-closeout`，code SHA `6c2082b4`（F9a：`7f39df33` F7c-2 之後只多兩個 backend chain 測試檔的 head 修正，產品碼與 `7f39df33` 相同）。本檔為其後的 docs-only commit。

```text
Alembic heads（apps/server: alembic heads）
  0015_character_state_revision (character) (head)
  0029_p4f_roll_request_auto_fail (web) (head)

Backend pytest（全套，cwd apps/server，..\..\.venv\Scripts\python.exe，
  P4_POSTGRES_URL=postgresql+psycopg://…@127.0.0.1:5432/adventure_table_p4f）
  6c2082b4 本機：1787 passed / 39 skipped，exit 0（18:50）
  39 skip 全為 P2 / P3 / M03 的 PostgreSQL env gate（P2_POSTGRES_URL / P3_POSTGRES_URL / M03B_POSTGRES_URL）；P4 相關 0 skip

Focused P4-F backend（6c2082b4，本機，PostgreSQL env 供給，無 silent skip）
  test_p4f_auto_fail_saves 7 · condition_modifiers 9 · condition_pipeline 7 · escape_grapple 5
  monster_bookkeeping 6 · monster_outcome 6 · postgres_migration 4 · postgres_restart_recovery 1
  P4-A～F + P3-C + M04-C + M03 boundary：451 passed / 3 skipped（4:12）；3 skip 為 test_p3c_* 的 P3_POSTGRES_URL gate，P4 檔 0 skip

PostgreSQL gate（GitHub, P4-F Non-E2E Regression / postgres-migrations）
  6c2082b4 run 35347332303：backend / postgres-migrations（tests=42 passed=42 skipped=0）/ frontend / compose-config 全 success
  （7f39df33 run 35345830928 backend job failure：test_m04b_oauth_schema.py / test_p3d_migration_contract.py 仍釘 0028 為 head，6c2082b4 修正）

Frontend unit / build（7f39df33，本機；6c2082b4 未動 apps/web）
  vitest 86 files / 482 passed；vite build success

docker compose config
  exit 0（本機）

E2E（本機 npm run test:e2e:docker，ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1，
  走 U01-A 的 adventure_table_e2e + server-e2e / web-e2e，rebuild server + web image）@ 7f39df33（產品碼同 6c2082b4）：
    主套件 129 tests：125 passed / 4 skipped（10.2m，與 full backend pytest 並行執行）
    含 e2e/p4e-quick-combat.spec.ts（5.4s）與 e2e/p4f-full-combat-journey.spec.ts（20.1s，內含真 server-e2e restart）
    disabled-pack 套件 7 tests：7 passed（6.6s）
  exit 0

E2E（GitHub Actions，p3-e2e.yml --ref 本分支，同一 Playwright 全套；只作 F.4「workflow run id」記錄，本機才是 gate）
  7f39df33 run 35346913894：124 passed / 4 skipped / 1 failed（20.0m）
    失敗：e2e/p4e-quick-combat.spec.ts 180s timeout（DM 頁 snapshot 停在 Round 1 hero turn、無 pending adjudication）
    同 spec 本機 5.4s 通過，且該 spec 於 CI 為首次執行（P4-E 只有本機 E2E 證據）；restart 在其後的 p4f spec，無關
  6c2082b4 run 35349598481：重跑一次確認是否穩定重現；使用者 2026-09-18 拍板「本機能跑的不用 CI」，結果不再納入 gate

Real ChatGPT Web Combat gate（測試指南 F.3）
  __F8__（未跑）
```

## 已知限制 / 留給後續

- **F8 未跑**：實作規格 9、10 與測試指南 F.3 為 P4 Phase closeout blocker，本檔第 9、10 項留白；跑完後補「日期 / client / 角色 / journey 結果 / tool error 實錄」再關門、合併。
- **Spell save 不走 conditions pipeline**：`persistence/combat/spells.py` 的 AoE save 在同 transaction 內自擲、直接 `resolved`，不經 `save_modifiers`；conditions 對 spell save 的 adv / disadv / auto-fail 不生效。F7a 起即為範圍限制，DM 仍可依規則口頭裁定。歸後續 M Phase。
- **frightened 的 attack disadvantage 不自動套**：需來源可見性，pipeline 回 `unresolved` 交 DM；Log / UI 不顯示 modifier sources（可選項未做）。
- **auto-fail 只有 unit 與 vitest 證據**：`p4f-full-combat-journey.spec.ts` 沒有 paralyzed / auto-fail 標記的 browser 斷言。
- **`get_resolution_event` 仍是 session event Python 掃描（O(n)）**（P4-D / P4-E 留下），P4-F 未收斂。
- **Monster long-form `desc` 尚未 expose 給 UI**（P4-E 留下）。
- **`p4-e2e.yml` 在合併回 `main` 前無法 dispatch**；本分支 CI 全套 E2E 以 `p3-e2e.yml` 代跑。**`p4e-quick-combat.spec.ts` 在 GitHub runner 上 timeout 一次、本機穩定通過**，原因未查；依使用者 2026-09-18 決定，本機能跑的 gate 一律以本機為準，不再為 CI-only 現象追查。
- Static review S1～S3 未改（見上表）。
