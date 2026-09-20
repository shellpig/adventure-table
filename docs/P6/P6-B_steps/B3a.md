# B3a — Adventure override 與 detach blocker

## Scope

- 實作 attached Adventure entry 的 Campaign override create/get/list/update/clear、revision、needs_review、idempotency 與 authority。
- Runtime view overlay 不回寫 Adventure Definition；未 attach、wrong Campaign／Room、stale revision 拒絕且零副作用。
- 擴充 detach：只有 active override 或 current Adventure scene 兩種 blocker；Runtime provenance reference 不阻擋，清除後可 detach。

## 契約與輸入

- 依賴 B2c；P6 設計 B.2、concurrency；測試 B.1、B.6。

## 驗收

- neutral Adventure + hostile override 後 template 不變、Campaign view 改變。
- detach blocker matrix、競爭與 rollback 測試完整。

## 完成紀錄

- **起始**：2026-09-20；agy 三回合實作／修正，conversation `d20a95e8-f498-43d0-bdf1-3781f527acf3`。
- **交付**：Adventure override management／active DM create、get、list、update、clear；Campaign overlay view；campaign-scoped idempotency、revision＋override identity CAS；active Session `world.override.*` dm-only event／notifier；detach active override／current Adventure scene blocker與 409 雙語呈現。
- **指揮者審核修正**：要求補上 create→clear→recreate 的 ABA identity 防護、source／override payload kind 驗證、public domain exception mapping、stale Human／AI authority與跨 Session replay、post-write rollback、真 PostgreSQL detach race；收斂重複 event／overlay helper並移除未使用 wrapper。首輪 gate 發現兩處 persistence exception 洩漏與四個測試 scope／exception 契約錯誤，退回同一對話修正；另移除測試檔 EOF 多餘空行。
- **測試**：B3a＋既有 P6-B／P6-A Campaign Adventure／quality gate `79 passed, 8 skipped`；前端全套 `95 files / 564 passed`、build 通過；Docker 專用 `adventure_table_p6b_b3a_test` 真 PostgreSQL concurrency `1 passed`，測後已刪除。`git diff --check` 通過。
- **驗證 commit**：`7a024321`。
- **未解問題／下一步**：無；接 B3b Current Scene／Situation，不提前做 B4 routes。
