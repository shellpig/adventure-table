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

- 待補。
