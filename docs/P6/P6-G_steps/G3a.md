# G3a — PostgreSQL restart／reconnect continuity

## Scope

- 在真 PostgreSQL 的 active Session 建 Runtime、Current Context、Import Draft；重啟 `server-e2e` 後 reconnect，驗證資料、revision、visibility 與 next Session continuity。
- 只重啟 E2E service、只重置獨立 `adventure_table_e2e`；不碰 daily DB 或使用者服務。

## 契約與驗收

- 測試指南 G.3；Windows E2E Docker／`serial-restart` project 規則見 `docs/others/local-tools.md`，參考 `p4f-full-combat-journey.spec.ts`。
- Docker restart spec 通過，P6 migration／concurrency regression 與 schema parity 通過。

## 完成紀錄

（待填）
