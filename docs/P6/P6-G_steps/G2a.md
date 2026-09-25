# G2a — Adventure journey：Adventure 至 Stage

## Scope

- 新增可單跑的 Adventure-driven browser journey：以既有 manual／Importer authoring 建 Adventure、finalize、attach Campaign、選 Current Scene、將 Adventure／Runtime image 設 Stage。
- UI／API 證明 Adventure baseline 與 Campaign Runtime 分開；Player 只看到 DM 放上的 Stage，不直讀 Adventure 或 secret asset。
- Explore／Check／Combat／write-back／next Session 留 G2b。

## 契約與驗收

- 規格 P6-G G.2；測試指南 G.2 前半、G.5。參考 `p6a-adventures.spec.ts`、`p6d-stage-and-review.spec.ts`、`p6f-import-review.spec.ts`。
- 新 spec 單跑通過；原 P6-A／D／F 相關 E2E 與 unit／build 通過。

## 完成紀錄

- **起始與 worker**：2026-09-24，agy（Gemini 3.8 Flash High）1 回合，CLI 回報約 575 秒；只新增 `apps/web/e2e/p6g-adventure-journey.spec.ts`，未改 production code／docs。
- **交付**：手動建立 Adventure 的 public Scene、DM-only Secret／Note 與 Scene／Secret image，finalize 並 attach；建 DM／Player Seat／Character，UI Start；DM UI 設 Current Scene／Situation 與 Stage image，雙方經 authenticated blob 顯示；核對 persisted context、Adventure baseline 未被 Runtime 改寫。Player 不見 world／Stage 控制、Adventure direct-read／secret asset API 回 404，頁面不含 secret 或 asset id。
- **指揮者審核修正**：無；核對 source／asset route、UI waiter、Player credential 與 server projection，未發現 test-only bypass。
- **測試與證據**：指揮者於獨立 Docker E2E DB 跑 `p6g-adventure-journey.spec.ts`＋`p6d-stage-and-review.spec.ts` **2 passed**；全套 frontend Vitest **103 files／775 tests passed**、`npm run build` 通過；`apps/server` 專案 venv `test_code_quality_gate.py` **2 passed**；`git diff --cached --check` 通過。驗證 code commit：`78bfc0b5`。
- **未解與下一步**：本步無未解。G2b 已按指揮者手冊步長拆為 G2b-1 Exploration／Check、G2b-2 Quick Combat、G2b-3 write-back／next Session truth。
