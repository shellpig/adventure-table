# P5-F — Tactical Combat UI & AI Tool Surface 實作紀錄

## 接手摘要

- **更新日期**：2026-09-28
- **目標與邊界**：把 P5-A～E 已交付的 Tactical backend（board、movement、targeting、AoE、OA）接上 Human Tactical UI 與 AI MCP tool surface；Human／AI 共用同一 application service，不新增第二套遊戲邏輯。契約：`docs/P5/實作規格.md` §10；`docs/P5/開發設計方針.md` §10、§11、§14；`docs/P5/測試指南.md` §3、F.1～F.7。
- **Branch**：`feat/p5f-tactical-combat-ui-ai-tools`（自 `main@fe75ffa9` 開出）
- **最近已驗證 commit**：F1 完成（Muse F1／F1b／F1c＋指揮者修正，本 commit）
- **Worker**：Muse（thread `https://muse.ai/thread/3c177caa-543a-46dd-8438-94f54b07df80`，使用者 2026-09-28 指定）。prompt 存 `C:\_work\AI_Work\Tools\agy-runs\muse-p5f-<step>.prompt.txt`。關門（F3）由指揮者做。
- **下一步**：F2 派工（frontend）
- **阻礙／未審**：無
- **本 Subphase 技術決策（契約未指定，指揮者拍板）**：
  1. **MCP tool 命名**沿用既有 `combat_` 前綴。全角色：`combat_get_board`（與 `GET .../board` 同一 audience projection）、`combat_preview_movement`、`combat_confirm_movement`、`combat_resume_movement`、`combat_check_target`（唯讀 range／reach／blocker 判定，重用 P5-C `validate_attack_target`／`validate_spell_target`，不寫狀態、不擲骰）、`combat_preview_aoe`（包既有 AoE preview service）。DM-only：`combat_start_tactical`、`combat_place_token`、`combat_reposition`、`combat_set_door_state`、`combat_cancel_pending_movement`；map 定義編輯（walls／doors／terrain objects）命名依 battle map 既有 route 語意取 `battle_map_` 前綴。名稱一經確定即列入 `_EXPECTED`，最終報告列出。
  2. **REST 與 MCP 共用 service**：MCP tool 只包既有 `MovementService`、`CombatBoardService`、targeting／AoE service 與 battle map service；輸入為 structured anchors／cells，不接受自然語言方向。F.5 以同一 fixture 比對 Human route 與 AI tool 的 position／cost／events。
  3. **Own-echo 白名單不擴充**：P5 新 `combat.*` event 一律照送（M06 預設），`OWN_ECHO_EVENT_KINDS` 不變，因此不需補 M06 B.7 型測試。
  4. **Tactical briefing**（F1c 修訂）：tactical 狀態以 `get_session_context`／`combat_get_context` 的 structured 欄位 `combat["tactical"]` 提供（mode、round、current turn、my units 的 position 與 movement used／budget／remaining、可見單位位置與距離（有上限）、pending movement／reaction、next required action），不塞進 briefing 字串；briefing 沿用既有 combat loop＋精簡 tactical 段並保留 MCP invocation rule，不輸出 ASCII map，維持 `BRIEFING_MAX_CHARS = 3_000`。
  5. **DM board view 補 wall visibility**（P5-A 已知限制）：DM projection 的 wall 帶 `visibility`，DM UI 可分辨 hidden wall；Player projection 不變。
  6. **Camera** 只在 client memory，不做 localStorage persistence；zoom／pan 不打任何 server API。
  7. **AoE renderer** 以 `apps/server/tests/fixtures/p5d_aoe_golden.json` 為前端單元測試 golden，與 server geometry 對齊；preview 以 server 回傳的 cells 為準，前端只畫模板輪廓與 server cells。
  8. **Player drag**：拖自己的 Token 只改 client draft path，呼叫 preview 顯示 used／remaining；只有 Confirm 呼叫 confirm route。DM 的 setup placement／reposition 與 gameplay movement 在 UI 上是不同模式（toolbar 切換），走不同 route。
- **跨步依賴**：F2 依賴 F1（DM wall visibility、`check-target` REST 若 F1 新增）；F3 依賴 F1、F2

## 步驟進度

| Step | 標題 | 狀態 | 依賴 | 紀錄 |
|---|---|---|---|---|
| F1 | Tactical MCP tools、tactical briefing、target check、DM wall visibility（backend，F.3～F.7 backend 面） | 完成 | — | [F1](P5-F_steps/F1.md) |
| F2 | Tactical Stage UI、camera、drag plan、DM toolbar、AoE／OA UI、locale、Playwright spec（F.1、F.2、F.7 frontend 面） | 待做 | F1 | [F2](P5-F_steps/F2.md) |
| F3 | 關門 gate、Docker E2E、closeout、合併 `main`（指揮者） | 待做 | F1、F2 | — |
