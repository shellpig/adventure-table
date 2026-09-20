# B4a — Session 外 Runtime entry REST routes

## Scope

- 新增 Room-first management router：`/api/rooms/{room_id}/campaigns/{campaign_id}/runtime/entries`。
- 暴露 list/get/create/update/archive；route 只轉 intent到既有 `CampaignRuntimeService` management methods，不直碰 repository。
- mutation request 明確攜帶 `idempotency_key`；update/archive 沿用 domain expected revision contract。
- 共用 stable mapping：authority 403、not found 404、active Session／revision／idempotency／archived conflict 409、validation 422。
- 註冊 router 與 service dependency；不做 active Session routes、override/context/overlay routes、Web UI 或 MCP。

## 契約與輸入

- 依賴 B2c-2；讀 P6 規格「P6-B」、設計「Shared authority / projection」「REST / UI surface」「Concurrency / idempotency」、測試 B.1／B.2／B.4／B.5。
- 重用 `CampaignRuntimeService.create_management`、`update_management`、`archive_management`、`get_management`、`list_management`；request DTO 只補 HTTP transport 所需的 idempotency wrapper，不複製 domain invariant。

## 驗收

- Owner／DM 在無 active Session 時可 CRUD；Player／wrong Room／wrong Campaign 被拒。
- active Session 時 management mutation 回 stable conflict，讀取仍遵循 management authority。
- stale revision、idempotency reuse、archived/not found、invalid payload 均有 stable `{code, message}`；拒絕零副作用。

## 完成紀錄

- 待補。
