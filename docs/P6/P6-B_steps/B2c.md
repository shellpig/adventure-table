# B2c — Runtime CRUD service、authority、revision／idempotency、event

## Scope

- 建立 Human Room owner/dm 的 pre-session management write 與 active Session current DM write，共用同一 application service。
- Player 不可建立／修改 world truth；active Session authority 沿用 `TableActorContext`，不得 AI-specific bypass。
- Campaign-scoped idempotency record 保存 command/result identity；active Session 成功寫入同 transaction 追加安全的 `world.*` event 並 notifier，session 外不得造假 event。
- create/update/archive/list/get 套用 Server projection；拒絕與 revision conflict 零副作用。

## 契約與輸入

- 依賴 B2a/B2b；P6 設計「Architecture」「Shared authority / projection」「Events」「Concurrency / idempotency」。

## 驗收

- service tests 覆蓋 owner/dm、current Human DM、Player／非 participant 拒絕、stale actor、retry、revision conflict、event secrecy 與 notifier。
- mutation/event/target row 必須原子；錯誤時三者皆不留下半筆。

## 完成紀錄

- 待補。
