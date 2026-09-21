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

- **起始**：2026-09-21；agy conversation `e346703d-bfaf-4fe2-8851-e8f48e7c2f96` 兩回合實作／退修，總計約 17 分鐘；prompt 位於 `C:/_work/AI_Work/Tools/agy-runs/agy-p6b-B5c*.prompt.txt`。
- **交付**：Campaign Changes 載入 attached Adventures 與 deterministic overlays，提供 override patch JSON／note／needs_review 建立、編輯、清除；集中但不阻塞跑團的 needs_review queue；Current Context 支援空值、Situation-only、Adventure Scene、Runtime Scene 與 clear-all，切換 scene 類型時同一 request 清除另一側 reference。每個 Adventure 顯示 active override／Current Adventure Scene 兩種 detach blocker 指引，不把 Runtime provenance 當 blocker。
- **指揮者審核修正**：退修空 Campaign 無法編輯 Context、唯讀 view 顯示無效操作、大量 optional callback、Adventure kind machine value／非安全 cast、conflict 後 stale form 可重送、needs_review 文案像 approval gate、主頁膨脹等問題；抽出完整 management hook 與 `null | actions` contract，將 mutation error 移至全域可見位置。指揮者另把 attachment 參數改為必填，並以 request body 斷言直接證明 Override 不含 Adventure template title／body／data mutation。
- **測試**（驗證 commit `0abc174d`）：`npm test -- --run` → 98 files／643 tests passed；`npm run build` → passed；`..\..\.venv\Scripts\python.exe -m pytest tests/test_code_quality_gate.py -q -n 0` → 2 passed；`git diff --check` 通過。既有 Vite dynamic-import／chunk-size warning 不影響輸出；正式 browser E2E 依步驟留在 B6。
- **未解問題／下一步**：B5c 無未解；下一步 B5d 接線 active Session DM Current Context 與 Quick Add，不在本步提前修改 Session UI。
