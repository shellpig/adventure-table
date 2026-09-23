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

（待填）
