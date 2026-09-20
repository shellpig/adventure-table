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

（派工後補）
