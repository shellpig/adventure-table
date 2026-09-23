# G1a — Empty Campaign：Start 至 formal Check／Player roll

## Scope

- 新增 `apps/web/e2e/p6g-empty-campaign.spec.ts`，用現有 Room fixture 建零 Adventure Campaign、DM Seat、Player Seat／Character；正式 UI Start Session。
- 同一場次實際執行 DM narration、Quick Add NPC＋Fact、Player exploration action、DM Request Check、Player roll；以 UI／API 查驗事件與 Runtime，不只斷言按鈕點擊。
- Player 不得看到 DM world controls、DM Notes 或 Adventure direct-read；DM／Player 身分使用既有 fixture，不造 test-only bypass。
- 此步只到 formal Check；Combat、End／next Session 留 G1b。單獨執行本 spec 必須通過。

## 契約與輸入

- 規格 P6-G G.1；測試指南 G.1 前半及 G.5 必要權限；設計 P6-G 不新增 production core。
- 參考 `e2e/p6a-adventures.spec.ts` 的 empty Campaign、`p6b-campaign-runtime.spec.ts` 的 Quick Add、`p3b-exploration-chat-actions.spec.ts`、`p3c-roll-check-pending-action.spec.ts`、`support/quickCombat.ts`。修改前核對最新 helper 簽名、API route／DTO 與 UI label。

## 驗收

- Docker E2E `p6g-empty-campaign.spec.ts` 通過；原 `p6a-adventures.spec.ts`／`p6b-campaign-runtime.spec.ts` 相關路徑無回歸。
- `npm test -- --run`、`npm run build`、`tests/test_code_quality_gate.py` 通過；不改 server／既有正式契約。

## 完成紀錄

- **起始與 worker**：2026-09-23，agy（Gemini 3.8 Flash High）1 回合，CLI 回報約 743 秒；只新增 `apps/web/e2e/p6g-empty-campaign.spec.ts`，未改 production code／docs。
- **交付**：同一個 Room 內以現有 fixture 建零 Adventure Campaign、DM／Player Seat 與 Character，UI Start、DM narration、Quick Add NPC＋Fact、Player action、DM Request Check／Player formal roll；查事件、Runtime entity、Player Journal 與 server projection。Player 不見 DM world controls／NPC notes，直接 Adventure read 回 404。G1b 可接在已解的正式 roll 後。
- **指揮者審核修正**：無；核對 event kind、Room scoped Player credential、真 UI 操作與 persisted state 斷言，未發現 test-only bypass 或越界修改。
- **測試與證據**：指揮者於 `apps/web` 用受 guard 保護的獨立 Docker E2E DB 跑 `p6g-empty-campaign.spec.ts`＋`p6a-adventures.spec.ts`＋`p6b-campaign-runtime.spec.ts`，**5 passed**；全套 frontend Vitest **103 files／775 tests passed**、`npm run build` 通過；`apps/server` 專案 venv 的 `test_code_quality_gate.py` **2 passed**；`git diff --cached --check` 通過。驗證 code commit：`f106a5b8`。
- **未解與下一步**：本步無未解。G1b 已按指揮者手冊步長拆為 G1b-1（Combat）與 G1b-2（End／next Session）。
