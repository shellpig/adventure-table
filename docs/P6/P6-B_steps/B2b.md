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

- **起始**：2026-09-20；agy 1 回合，283 秒；conversation `9e22b211-0d81-475c-86e5-1d3278f1dcaf`。
- **交付**：connection-aware＋engine wrapper repository、Stored aggregate/update types、campaign-scoped CRUD、batched recipient load、expected-revision update／soft archive、typed not-found/conflict/archive errors與 focused tests。
- **指揮者審核修正**：移除 repository 的 `dict.fromkeys` recipient 靜默去重，以及 Stored aggregate/update 將非 tuple 偷轉 tuple 的 `__post_init__`；persistence 現在不掩蓋上游 invariant 違約。補 duplicate recipient 觸發 join PK 且整筆 create rollback 的 regression。
- **測試**：repository＋schemas＋code-quality＋P6-A authoring regression 共 59 tests 全綠（pytest exit 0）；list recipient query-count 證明固定 2 queries，空清單 1 query。
- **驗證 commit**：待本次 B2b commit。
- **未解問題**：repository 不做 actor／projection；B2c 必須用 in-transaction methods 組合 mutation record與 active-session event，不可退回 nested transaction。
