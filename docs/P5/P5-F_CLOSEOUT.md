# P5-F — Tactical Combat UI & AI Tool Surface · Closeout

- **日期**：2026-09-28
- **Branch**：`feat/p5f-tactical-combat-ui-ai-tools`（自 `main@fe75ffa9`）
- **Worker**：Muse（F1～F3，含 F1b／F1c／F2b／F3b 修正回合）；F4 由指揮者重寫 Playwright spec、修 UI／契約缺陷並關門。步驟紀錄見 [P5-F 實作紀錄](P5-F實作紀錄.md)。

## 範圍

P5-A～E 的 Tactical backend 接上 Human UI 與 AI MCP：DM battle map 編輯器、Tactical start／placement、與既有 `SessionCombatStage` 並存的地圖面板（camera、hidden rendering、door 操作）、Player 拖曳只產生 movement plan、pending movement resume／cancel、DM reposition、range feedback、AoE template preview；MCP 全角色與 DM-only tactical tools、`combat["tactical"]` structured context、read-only target check。Human 與 AI 共用同一 application service。

## 驗收對應

| 契約（測試指南） | 證據 |
|---|---|
| F.1 Browser Tactical journey | `apps/web/e2e/p5f-tactical-combat.spec.ts`：DM 從 toolbar Start Tactical 選 map → UI placement → initiative → Player 拖自己 Token 只產生 plan（confirm 前 server position 不變、無 confirm request）→ preview used／remaining → Confirm 後 position 變 → 不能拖 Goblin → ranged attack range feedback（In range、50 ft）→ 離開 Goblin reach 自動暫停＋DM Decline＋Player resume → Mage 回合 DM 放 Fireball template、server cells → DM reposition → hidden Stalker 不在 Player DOM 與任何 Player board response |
| F.2 Camera | 同一 spec：Player zoom／wheel／Fit Map 不發 Session／map 寫入、board `runtime_revision` 不變、DM 的 camera style 不變（第二個 client 以 DM 頁代替第二位 Player）；`useTacticalCamera.test.ts`（bounds、pinch、fit、no network） |
| F.3 Authority | `tests/test_p5f_f1b.py::test_f3b_player_reposition_rejected_zero_side_effects`、`::test_f3b_player_set_door_state_rejected_zero_side_effects`、`::test_f3b_player_battle_map_patch_rejected_zero_side_effects`、`::test_f3b_player_battle_map_replace_objects_rejected_zero_side_effects`、`::test_f3b_player_movement_on_uncontrolled_entry_rejected_zero_side_effects`、`::test_f3b_presession_dm_grant_battle_map_rejected_zero_side_effects`；`tests/test_p5f_tactical_mcp.py::test_f3_dm_proxy_movement_consumes_subject_budget`、`::test_f3_revoked_grant_rejected_with_zero_side_effects`、`::test_f3_stale_epoch_rejected_with_zero_side_effects`、`::test_f3_player_cannot_place_monster_token_with_zero_side_effects`；`tests/test_p5f_movement_status_route.py::test_player_cannot_read_monster_movement_status`；E2E 中 Player 無 Start Tactical／Token／reposition 控制 |
| F.4 MCP protocol | `test_p5f_f1b.py::test_f4b_mcp_combat_get_board`、`::test_f4b_mcp_preview_then_confirm_movement`、`::test_f4b_mcp_combat_check_target`、`::test_f4b_mcp_combat_preview_aoe`、`::test_f4b_mcp_pending_reaction_visible_in_get_session_context`、`::test_f4_ai_player_resumes_after_reaction_with_context_revision`、`::test_f4b_secrecy_player_cannot_see_hidden_elements`、`::test_f4b_secrecy_dm_sees_hidden_elements`、`::test_f4b_secrecy_target_check_hides_hidden_monster`；`test_p5f_tactical_mcp.py::test_f4_role_catalogs_split_all_role_and_dm_only_tools`；`test_m04c_guide_tool_parity.py`、`test_m04c_tool_descriptions.py` 全綠 |
| F.5 Human／AI parity | `test_p5f_f1b.py::test_f5_human_rest_vs_ai_mcp_movement_parity`（TestClient 打真 REST route vs MCP `call_tool`，比對 position、used／remaining、事件 kind 與 payload） |
| F.6 Briefing | `test_p5f_f1b.py::test_b1_briefing_tool_mentions_exist_in_role_catalog`、`::test_b2_tactical_briefing_reuses_full_combat_loop`、`::test_f6_tactical_structured_content`、`::test_f6_tactical_structured_near_limit_bounds`；`test_m04c_briefing.py` 全綠；DM tactical briefing 2,968 字、Player 2,820 字，`BRIEFING_MAX_CHARS = 3_000` 未放寬 |
| F.7 Locale | `tacticalCopy.test.ts`、`src/i18n/hardcodedUiCopy.test.ts`（新 tactical 元件已加入掃描）、`test_p5f_tactical_mcp.py::test_f7_new_tool_descriptions_bilingual_and_unique_when_to_use`、`::test_f7_battle_map_error_codes_bilingual` |

## 關門 gate

- 全套 backend pytest（`P4_POSTGRES_URL=…/adventure_table_p4`，`d33bc6fc`）：3,071 passed、39 skipped、0 failed；含 code quality、M03 boundary／schema parity。
- 前端（`0338983e`，之後未再動 `apps/web` 程式）：`npm test -- --run` 864 passed；`npm run build` 通過。
- `docker compose config`：通過（未改 compose）。
- **全套 Docker E2E**（`d33bc6fc`）：`parallel` 兩次各 103 passed／3 skipped／2 failed，失敗皆為 `p1f-character-creation`、`p1g-level-up` 在 Builder review 逾時（長時間 server-e2e 的既有 flake，見 P6-A closeout 觀察 #5），重啟後單獨重跑 2 passed；`baseline-room` 30 passed／1 skipped；`serial-restart` 2 passed；去掉 xge 的 `m03c-character-import` 7 passed。`p5f-tactical-combat.spec.ts` 單獨與全套中皆通過。

## 指揮者審核修正

- F1 退回兩輪：briefing 引用不存在的 tool、tactical loop 丟掉既有戰鬥指引、briefing 超限時線上 raise、`"?"` 佔位、pre-session DM grant 可改 Room 地圖（並移除 AI `battle_map_delete`）；F1b 為塞進 3,000 字刪掉 MCP invocation rule——改成 `combat["tactical"]` structured 欄位。測試多次以可被 static 文字滿足的斷言、未走 REST／MCP 協定層、吞錯的 `try/except` 充數，逐輪退回。指揮者補回 DM tactical loop 的環境傷害指引（`7b51c3fd`）。
- F2 退回：TacticalStage 取代了整個既有戰鬥操作面；hidden door 讀從未傳入的 prop；image map 無 token 會 401；door 操作未接；camera 缺 pinch。指揮者把 board 重載限於 combat event（`b4ec3c76`）。
- F3 退回：target check 與 AoE handler 定義但從未呼叫、死碼 hook、setState updater 內發 request、無拖曳；測試自己呼叫 mock 再斷言；Playwright spec 幾乎全打 API（且建 map 的 payload 本身就不合法，從未跑過）——刪除，改由指揮者重寫。
- F4 以真 UI 跑 journey 抓到並修正（`0338983e`、`d33bc6fc`）：
  - 開始拖曳時 movement 面板插在地圖上方，整張地圖下移，拖出錯誤路徑——draft／reposition／AoE 面板移到地圖下方。
  - Token 名稱溢出到相鄰格子並攔截點擊——label `pointer-events: none`。
  - board 重載 effect 的 cleanup 會取消尚未觸發的 debounce 重載，其他 client 永遠看不到 placement——改為只在 unmount 清 timer。
  - Resume 使用 confirm 回應的 pending revision，但 OA window resolve 後 revision 已前進，按 Resume 一律 `combat_movement_stale`；且暫停狀態只存在發動者的分頁記憶體。新增唯讀 `GET .../board/movement/{entry_id}/status`（mover controller 或 DM），面板從 server 讀暫停狀態；AI 端 `combat["tactical"].my_units` 補 `pending_revision`。
  - AoE「放置範圍」按鈕讀 `aoe_shape`／`aoe_size_feet`，server 從未提供（Muse 自造的 optional 欄位）——`CastableSpellView` 由法術資料提供 canonical template。

## 已知限制

- 前端沒有 testing-library，互動行為由抽出的純函式（`tacticalLogic.ts`）單元測試加 Playwright journey 覆蓋；元件層 effect／事件不做單元測試。
- F.2「Player A 的 camera 不影響 Player B」以 DM 頁作為第二個 client 驗證，未開第二個 Player。
- Player 拖曳以格子 pointer enter 累積 anchors；E2E 只驗證直線相鄰格的拖曳，斜向或快速拖曳的路徑取樣未另外驗證。
- 地圖編輯器只在開戰前編輯 map 定義；開戰後 board 為 runtime snapshot（P5-A 決策），戰鬥中只有 door 狀態與 placement／reposition。
- DM tactical briefing 距 3,000 字上限只剩 32 字，後續新增指引需先精簡。
- Muse 回合中多次在未跑測試的情況下交付（F2／F3 約 15～25 分鐘即推送），自編 server 未提供的欄位、留下未呼叫的 handler；每步都需要指揮者以真實流程驗證。
