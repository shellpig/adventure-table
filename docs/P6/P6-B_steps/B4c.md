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

- **起始**：2026-09-20；agy 一回合實作，conversation `23f59939-8c24-4f38-b157-1dc4ea56136b`，約 9 分 21 秒。
- **交付**：active Session Runtime entry list/get/create/update/archive routes；Human actor resolution；TableEvent authority error mapping；Current DM full view與Player public／own-character serialized projection tests；world event／notifier與拒絕零副作用 tests。
- **指揮者審核修正**：直接核對 FastAPI union response raw JSON key集合，確認 Player無 `dm_notes`、recipient、provenance、actor audit等欄位且 invisible item為404；移除未使用 import、關閉測試暫時 connection並清除 EOF whitespace。
- **測試**：B4 API＋active/runtime/override/context service regression＋Exploration route＋quality gate，`78 passed, 2 skipped`；`git diff --check` 通過。
- **驗證 commit**：`26a50fd8`。
- **未解問題／下一步**：無；接 B4d active Override／Context／Overlay與完整 stable-error／Human-AI projection matrix。
