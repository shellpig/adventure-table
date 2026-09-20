# B3b — Current Scene／Situation context 與 concurrency

## Scope

- 實作 Campaign runtime context get/update/clear；Adventure scene 與 Runtime scene 最多一個非 null，兩者皆 null 合法，Situation 可單獨存在。
- 驗證 Adventure 已 attach、Runtime scene 同 Campaign 且 kind=scene。
- expected revision + campaign mutation idempotency；active Session 成功時安全發布 `world.context_changed`，session 外不造 event。

## 契約與輸入

- 依賴 B2c；P6 設計 B.3、Events、Concurrency；測試 B.3、B.5。

## 驗收

- null/situation-only/Adventure scene/Runtime scene/互斥/clear 全覆蓋。
- 同 revision 競爭只能一方成功，失敗方無 target／mutation／event 半筆。

## 完成紀錄

- 待補。
