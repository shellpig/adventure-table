# G3a — PostgreSQL restart／reconnect continuity

## Scope

- 在真 PostgreSQL 的 active Session 建 Runtime、Current Context、Import Draft；重啟 `server-e2e` 後 reconnect，驗證資料、revision、visibility 與 next Session continuity。
- 只重啟 E2E service、只重置獨立 `adventure_table_e2e`；不碰 daily DB 或使用者服務。

## 契約與驗收

- 測試指南 G.3；Windows E2E Docker／`serial-restart` project 規則見 `docs/others/local-tools.md`，參考 `p4f-full-combat-journey.spec.ts`。
- Docker restart spec 通過，P6 migration／concurrency regression 與 schema parity 通過。

## 完成紀錄

- **起始與 worker**：2026-09-24，agy（Gemini 3.8 Flash High）1 回合，CLI 回報約 807 秒；新增 `p6g-restart-continuity.spec.ts`，在 `playwright.config.ts` 的 `RESTART_SPECS` 列入新 spec（完整 E2E 走 serial-restart）。
- **交付**：獨立 Docker PostgreSQL 的 active Session 建 public Fact／Scene、DM-only Secret、Current Context，以及有 entry／warning／question 的 mutable Import Draft；只重啟 `server-e2e`，重新載入 DM／Player 後核對 IDs／revisions／內容／visibility 不變，並用 expected revision 更新 Draft。End／Start next Session 後 Runtime 與 Situation／Scene 延續；Player Journal 只見 public Fact，不能直讀 Importer draft／source／chunk 或 DM context。
- **指揮者審核修正**：post-restart Draft 改為與重啟前完整 deep equality（含 entry payload、warning、question）；補 Player 讀 source chunk 403，避免只驗 source list。
- **測試與證據**：指揮者以 `ADVENTURE_TABLE_E2E_ALLOW_DESTRUCTIVE_RESET=1` 在獨立 `adventure_table_e2e` 跑 `p6g-restart-continuity.spec.ts --project=serial-restart`，實際 Docker `server-e2e` restart **1 passed**；全套 frontend Vitest **103 files／775 tests passed**、`npm run build` 通過；專案 venv 的 P6-A／B／E PG migration＋migration heads＋M03 boundary／schema parity＋code quality focused **16 passed／18 skipped**（PG pytest URL 未設定，真 PG 由 Docker E2E 覆蓋）；`git diff --cached --check` 通過。驗證 code commit：`7d555a71`。
- **未解與下一步**：本步無未解。G3b 做跨 transport secrecy matrix 與 P5／Standalone 邊界。
