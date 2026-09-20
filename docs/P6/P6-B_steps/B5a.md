# B5a — Web API／types、雙語 copy、Campaign Changes 骨架

## Scope

- 新增與 B4 精確對齊的 web API client/types、machine error mapping 與 tests。
- Campaign page 增加 Campaign Changes 入口／頁面骨架，載入 Runtime entries、overrides、context；支援 loading/empty/fatal 狀態。
- 所有首次 expose copy 同步 zh-TW/en，沿用既有 auth/session helpers 與 form/layout pattern。

## 契約與輸入

- 依賴 B4；P6 REST/UI surface；既有 `RoomCampaignPage`、Adventure API/client/copy patterns。

## 驗收

- API contract tests、component empty/load/error tests、locale parity、`npm test -- --run`、`npm run build`。

## 完成紀錄

- 待補。
