# P6-D — AI DM Write-back & Exploration Integration 實作紀錄

## 接手摘要

- **更新日期**：2026-09-22
- **目標與邊界**：D0 已完成拆檔；D1 已交付八個 world intent；D2 已交付 atomic world＋narration；D3 已交付 asset／entry image → P3 Main Stage bridge與 Human DM REST route；D4 已交付十個 DM-only MCP write tool（facade 只轉 intent）並抽出共用 `require_active_table_actor`。D5 接 Session DM UI＋E2E；不做 P5 geometry／P7 GameTransaction。
- **Branch**：`feat/p6d-ai-dm-write-back`（自 `main@10565217`）
- **最近已驗證 commit**：`c55e692e`（D4）；指揮者獨立 gate 為 P3-B、P3-E、P4-C／P4-E MCP、M04、P6 全部、code quality、M03 boundary 共 611 passed／22 skipped，`import app.main` 與 `git diff --check` 通過。
- **下一步**：D5（Session DM UI set Stage／`needs_review` toggle＋E2E）。使用者 2026-09-22 拍板 D1～D5 為既定完整步驟，不再拆分；全 gate／closeout 由指揮者收。
- **阻礙／未審**：無。
- **派工約束**：沿 P6-C 派工約束 1／3（parametrize、測試不展開矩陣）；D0 兩步 **只搬不改**——函式本體逐字保留（僅允許移除跨模組後的 leading underscore 與對應 import 調整），指揮者以 AST 逐函式比對前後本體驗證。
- **派工決策（2026-09-22 拍板）**：(1) 既有 P6-B REST route **不改接** `CampaignWorldService`——REST 與 world service 都委派同一個 `CampaignRuntimeService`，已是同一份 backend logic，改接線只是 churn；(2) `resolve_world_action` **只開 MCP**，不開 Human REST route；D5 可玩 loop 若發現需要再補；(3) D4 tool input 的 `idempotency_key` 一律 required，`CampaignContextDmView` 補 `current_context_revision` 供 `world_set_current_context` 取得 expected_revision。
- **正式契約入口**：`docs/P6/實作規格.md`「P6 共用產品邊界」「P6-D」；`docs/P6/開發設計方針.md`「Architecture」「Shared authority / projection」「P6-D」（D.1～D.4）「Subphase implementation boundary」；`docs/P6/測試指南.md`「P6 核心風險」「執行環境」「P6-D」（D.1～D.8）。
- **跨步依賴**：D0a → D0b → D1 → D2 → D3 → D4 → D5（D1 是 D2／D4 前置；D3 是 D4／D5 前置；D2 內含 `append_in_transaction` 抽取）。P6-B／P6-C 技術決策見各自 closeout；共用測試 fixture 住 `tests/p6_active_fixture.py`。

## 步驟進度

| Step | 標題 | 狀態 | 依賴 | 紀錄 |
|---|---|---|---|---|
| D0a | 拆 `service.py`：errors／conversion／adventure_overlay／events leaf module | 完成（`fbf49f5a`） | — | [D0a](P6-D_steps/D0a.md) |
| D0b | 拆 `service.py`：entry／override／context mutation module，`service.py` 只留 `CampaignRuntimeService` | 完成（`34b8061b`） | D0a | [D0b](P6-D_steps/D0b.md) |
| D1 | `CampaignWorldService` 八個 intent（management／active 雙路徑） | 完成（`500d9b3e`） | D0b | [D1](P6-D_steps/D1.md) |
| D2 | `resolve_world_action` atomic world＋narration（含 `append_in_transaction` 抽取） | 完成（`f8622b69`） | D1 | [D2](P6-D_steps/D2.md) |
| D3 | Stage bridge：asset／entry image → P3 Stage，REST route | 完成（`a0cae16a`） | D0b | [D3](P6-D_steps/D3.md) |
| D4 | MCP 十個 write tool | 完成（`c55e692e`） | D1、D2、D3 | [D4](P6-D_steps/D4.md) |
| D5 | Session DM UI（set Stage、`needs_review`）＋E2E | 待做 | D3 | [D5](P6-D_steps/D5.md) |
