# B4c — Active Session Runtime entry routes 與 Player secrecy

## Scope

- 新增 active Session Human router：`/api/rooms/{room_id}/campaigns/{campaign_id}/sessions/{session_id}/runtime/entries`。
- 暴露 list/get 給 current participant；create/update/archive 僅 current DM，全部解析既有 `TableActorContext` 後呼叫 active service methods。
- 直接以 serialized response 驗證 Current DM 全量、Human Player public + own active Character knowledge；不得出現 other-character、dm-only、`dm_notes` 或 `?` 佔位。
- stale/revoked/nonparticipant/wrong scope/inactive Session 拒絕且零副作用；不做 override/context/overlay active routes、Web UI 或 MCP。

## 契約與輸入

- 依賴 B4a；讀 Shared authority Human／AI projection、測試 B.4／B.5。Human route 重用 `TableEventService.resolve_human_actor` 與 `CampaignRuntimeService` active methods。

## 驗收

- Current Human DM CRUD 與 event/notifier 維持 service 契約；Human Player只可 read。
- Player serialized list/get secrecy matrix完整；非 participant、stale actor、wrong Room/Campaign/Session 與 Player write 有 stable error。

## 完成紀錄

- 待補。
