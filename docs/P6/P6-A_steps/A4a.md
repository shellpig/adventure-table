# A4a — web：API clients 與 Adventures workspace page

## Scope

- `apps/web/src/api/adventures.ts`：型別（`AdventureDefinition`、`AdventureEntry`、`AdventureEntryKind`、`AttachedAdventure`）與 A2b／A3 全部 route 的 client；`apps/web/src/api/roomAssets.ts`：`uploadRoomAsset(roomId, token, {kind, filename, visibility, file})`（raw body）、`listRoomAssets`、`roomAssetContentUrl`。欄位一律對照 server Pydantic model，不自創 optional。
- `apps/web/src/features/rooms/RoomAdventuresPage.tsx`：列表（name／status／updated）、建立（只需 Name）、finalize／archive／delete（delete 對 attached finalized 顯示 server 409 訊息）、開啟 editor 連結 `/rooms/{roomId}/adventures/{adventureId}`；member（非 owner／dm）進入顯示無權限訊息，不呼叫 list。
- `App.tsx` 加 `/rooms/{roomId}/adventures` 與 `/rooms/{roomId}/adventures/{adventureId}` 路由（後者先指向 placeholder，A4b 換成 editor）；`RoomWorkspacePage` 加 Adventures 入口按鈕（對照既有 `campaignsAction`）。
- `adventuresCopy.ts`：兩 locale 全部 copy（含 status label、kind label 供 A4b 共用、錯誤碼訊息 `adventure_attached_use_archive`／`adventure_not_finalized`／`adventure_already_attached`／`asset_visibility_not_allowed`／`asset_in_use`）。
- Vitest：`RoomAdventuresPage.test.tsx`（list／create／finalize／archive／409 訊息／member 無權限）、`adventures.test.ts` client 路徑與 method、copy parity。

## 對應契約

實作規格 P6-A「Human UI 有最小 Adventures workspace」；設計「REST / UI surface」；工程守則 7（雙語）。

## 前置

A2b、A3 route 已 commit。

## 驗收

- `npm test -- --run`、`npm run build`（cwd `apps/web`）通過。

## 紀錄

- **起始**：2026-09-20，worker agy（`Gemini 3.8 Flash (High)`），1 回合 3 分 44 秒，prompt `C:/_work/AI_Work/Tools/agy-runs/agy-p6a-A4a.prompt.txt`，conversation `331ccfe5-fec6-4678-867f-f93e138c11bb`。
- **交付**：`api/adventures.ts`（型別鏡射 server：12 kind payload union、`AdventureDefinition`／`AdventureEntry`／`AttachedAdventure` 等；18 個 route function 含 campaign attach／detach；`AdventureApiError`）；`api/roomAssets.ts`（`uploadRoomAsset` raw Blob body＋query params、`listRoomAssets`／`getRoomAsset`／`deleteRoomAsset`／`roomAssetContentUrl`）；`adventuresCopy.ts` 兩 locale 全部 key（含 12 kind label、10 個錯誤碼訊息）＋`adventureErrorMessage()`；`RoomAdventuresPage.tsx`（`roomAdventuresRouteFromPath`、`adventurePermissions`、`adventureActions`、`AdventureList` presentational、list／create／finalize／archive／delete、member 顯示 `noAuthority` 不呼叫 list、detail 路由先放 placeholder 供 A4b 換）；`copy.ts` `adventuresAction`、`RoomWorkspacePage` 第三顆按鈕、`App.tsx` 路由、`rooms.css` `/* P6-A Adventures */` 區；Vitest 三個測試檔。
- **指揮者審核修正**：
  - `useEffect` deps 放了 `recent`（`recentRoomForId` 每次 render 重新解析 storage，物件身分不同）→ effect 每次 render 重跑、setState 再 render → 無限 fetch。改為 `[adventureId, canAuthor, roomId, token]` 並沿用 `RoomCampaignPage` 的 eslint-disable 註解。
  - create form 手寫一份 pending／error／reload 流程，與 `runMutation` 重複 → 改走 `runMutation`。
- **測試**：`npm test -- --run` 93 files／543 passed；`npm run build` exit 0。
- **未解問題／下一步**：`AdventureList` 直接顯示 `updated_at` ISO 字串（與 Campaign 列表一致，未格式化）；`roomAssetContentUrl` 用於 `<img src>` 時瀏覽器不帶 Authorization——A4b 顯示縮圖時需改為 fetch＋blob URL 或另訂方案，已在 client 註解。A4b 待使用者指示。
