# A4c — web：Campaign page Attached Adventures

## Scope

- `RoomCampaignPage.tsx` campaign detail 區加「Attached Adventures」：列表（name／status）、detach、attach picker（只列 Room 內 `finalized` 且尚未 attach 的 Adventure）；409 `adventure_already_attached`／`adventure_not_finalized` 顯示 copy 訊息；member 不顯示此區塊的寫入控制。
- `adventuresCopy.ts` 追加兩 locale。
- Vitest：`RoomCampaignPage.test.ts` 追加 attach／detach／picker 過濾／409 訊息。

## 對應契約

實作規格 P6-A「Campaign 可 attach / detach 多個 finalized Adventure」「Human UI…Attach」；設計「REST / UI surface ▸ Campaign：Attached Adventures」。

## 前置

A4a clients；A3 route。

## 驗收

- `npm test -- --run`、`npm run build`（cwd `apps/web`）通過。

## 紀錄

（派工後補）
