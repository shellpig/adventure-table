# B5c — Overrides、needs_review、Current Context UI

## Scope

- Campaign Changes 顯示 attached Adventure entries 的 override 編輯／清除與 detach blocker 指引。
- 集中顯示／處理 `needs_review`；不得把提醒變成 mandatory approval。
- Current Context 支援無 Scene、Situation-only、Adventure Scene 或 Runtime Scene，兩種 scene selector 互斥並可 clear。

## 契約與輸入

- 依賴 B5a/B3a/B3b；P6 設計 B.2/B.3；測試 B.3/B.6。

## 驗收

- component tests 覆蓋 override 不改 template、兩種 blocker、context 合法狀態、revision conflict。
- zh-TW/en、全 web unit、build 通過。

## 完成紀錄

- 待補。
