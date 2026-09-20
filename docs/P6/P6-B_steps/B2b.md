# B2b — Runtime entry repository 與 character recipients

## Scope

- 實作 Campaign-scoped Runtime entry create/get/list/update/archive 與 character recipient replace/read。
- 所有 lookup 同時約束 Campaign/Room ownership；禁止 cross-Campaign／cross-Room ID 混用。
- expected revision 以單一條件 update 保證競爭只一方成功；archive 保留 durable truth。
- repository 回傳明確 stored model，不把 raw row／JSON 洩漏到 route。

## 契約與輸入

- 依賴 B1、B2a；P6 設計 B.1、B.4 與 concurrency。

## 驗收

- repository tests：CRUD、recipient、archive、wrong campaign、stale revision、空 Campaign persistence。
- NPC update 不改 Monster；Item holder update 不改 Character inventory。

## 完成紀錄

- 待補。
