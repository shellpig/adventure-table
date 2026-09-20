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

- **起始**：2026-09-20，worker agy（`Gemini 3.8 Flash (High)`），1 回合 2 分 44 秒，prompt `C:/_work/AI_Work/Tools/agy-runs/agy-p6a-A4c.prompt.txt`，conversation `cf066d78-1e18-4b6e-bf29-dc7f7fb67de1`。
- **交付**：`CampaignAdventuresSection.tsx`（pure `attachableAdventures`：finalized 且未附加；`AttachedAdventureList` presentational 沿用 `.adventure-card`，Open 連結＋Detach 走 confirm；`CampaignAdventuresSection({ roomId, campaignId, token })` 自帶 load／pending／error，attach bar 沿用 `.roster-add-bar`，無可附加時顯示 `noAttachable`＋前往 Adventures 連結）；`RoomCampaignPage` 只加 import＋`canManageRoster ?` 一行（member 不 mount、不呼叫 list）；`adventureStatusLabel` 抽到 `RoomAdventuresPage.tsx`，`AdventureList`／editor／section 三處共用；`adventuresCopy` 11 key 兩 locale＋`campaign_adventure_link_not_found`／`campaign_not_found` 對照；`CampaignAdventuresSection.test.tsx` 8 tests。
- **指揮者審核修正**：初次載入 effect 整段複製 `reload()` 內容（約 15 行）→ 改為 `void reload().catch(...)`，與 `RoomCampaignPage` 同 pattern。
- **測試**：`npm test -- --run` 95 files／564 passed；`npm run build` exit 0（指揮者本機重跑）。
- **未解問題／下一步**：`statusLabel` 在 `AdventureList`／editor 仍各留一個 lambda 包裝 `adventureStatusLabel`，可直接 inline，未動。下一步 A5。
