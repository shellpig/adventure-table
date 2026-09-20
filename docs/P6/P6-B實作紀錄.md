# P6-B — Campaign Runtime World State 實作紀錄

## 接手摘要

- **更新日期**：2026-09-20
- **目標與邊界**：建立 Campaign mutable world layer：Runtime Scene／NPC／Item／Quest／Fact／Secret、角色知識、Adventure Override、optional Current Scene／Situation、revision／idempotency 與 Server-side projection。支援空 Campaign、跨 Session persistence、Human DM quick add；不做 P6-C AI retrieval、P6-D MCP write-back／Stage bridge、P6-E/F Importer。
- **Branch**：`codex/p6b-campaign-runtime`（自 `main@8db7d851`）
- **最近已驗證 commit**：`5505160d`（B3b Current Scene／Situation context 與 concurrency）
- **Worker**：B1～B5e 由 agy 實作；每步由指揮者審 diff、跑 focused/regression gate、修小錯、commit＋push。B2c 因實際 event transaction API 邊界拆為 B2c-1／B2c-2；B6 E2E／完整 gate／closeout／合併由指揮者處理。
- **下一步**：B3 已完成；下一步為 B4 — REST routes、stable errors、完整 secrecy matrix，尚未開工
- **阻礙／未審**：無
- **正式契約入口**：`docs/P6/實作規格.md`「P6 共用產品邊界」「P6-B」；`docs/P6/開發設計方針.md`「Architecture」「P6-B」「Shared authority / projection」「REST / UI surface」「Events」「Migration / PostgreSQL / Standalone」「Concurrency / idempotency」「Subphase implementation boundary」；`docs/P6/測試指南.md`「P6 核心風險」「執行環境」「P6-B」。
- **跨步依賴**：B2a→B2b→B2c-1→B2c-2；B3a 依賴 B2c-2，B3b 依賴 B2c-2；B4 整合 B2c-2/B3a/B3b；所有 Web 步依賴 B4；B5d/B5e 依賴 B5a；B6 依賴全部。

## 步驟進度

| Step | 標題 | 狀態 | 依賴 | 紀錄 |
|---|---|---|---|---|
| B1 | 五張 Runtime table、migration、Standalone boundary／parity | 完成 | — | [B1](P6-B_steps/B1.md) |
| B2a | Typed payload、command／view DTO、projection 基礎 | 完成 | B1 | [B2a](P6-B_steps/B2a.md) |
| B2b | Runtime entry repository 與 character recipients | 完成 | B1、B2a | [B2b](P6-B_steps/B2b.md) |
| B2c-1 | Mutation repository、Session 外管理 CRUD／projection | 完成 | B2a、B2b | [B2c-1](P6-B_steps/B2c-1.md) |
| B2c-2 | Active Session actor、world event／notifier 原子接線 | 完成 | B2c-1 | [B2c-2](P6-B_steps/B2c-2.md) |
| B3a | Adventure override 與 detach blocker | 完成 | B2c-2 | [B3a](P6-B_steps/B3a.md) |
| B3b | Current Scene／Situation context 與 concurrency | 完成 | B2c-2 | [B3b](P6-B_steps/B3b.md) |
| B4 | REST routes、stable errors、完整 secrecy matrix | 待做 | B2c-2、B3a、B3b | [B4](P6-B_steps/B4.md) |
| B5a | Web API／types、雙語 copy、Campaign Changes 骨架 | 待做 | B4 | [B5a](P6-B_steps/B5a.md) |
| B5b | Runtime CRUD 與 Quick Add UI | 待做 | B5a | [B5b](P6-B_steps/B5b.md) |
| B5c | Overrides、needs_review、Current Context UI | 待做 | B5a、B3a、B3b | [B5c](P6-B_steps/B5c.md) |
| B5d | Session DM Current Context 與 Quick Add 接線 | 待做 | B5a、B5b、B5c | [B5d](P6-B_steps/B5d.md) |
| B5e | Player Journal public／own-character projection | 待做 | B5a、B4 | [B5e](P6-B_steps/B5e.md) |
| B6 | E2E、完整 gate、closeout、合併 | 待做 | B1～B5e | [B6](P6-B_steps/B6.md) |
