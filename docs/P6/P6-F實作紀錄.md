# P6-F — Import Review, Finalization & Importer MCP 實作紀錄

## 接手摘要

- **更新日期**：2026-09-23
- **目標與邊界**：完成 Importer 的 Review → Finalize：Draft entry 的 Accept／Edit／Ignore／Mark uncertain／View source、warning 三級（Info／Warning／Blocking）與 question 回答、Finalize 建立新的 Adventure Definition baseline（retry 不重複）、DM-only REST、六個 Importer MCP tool、Review／Finalize UI 與 E2E。**不做** P7 package import／export，也不放寬 P3-D pre-session grant 的工具集合。Backend 仍不對 URL fetch、不含 LLM client。
- **Branch**：`feat/p6f-import-review-finalize`（自 `main@6028d6c9`）
- **最近已驗證 commit**：`931c08ff`（F4a code；指揮者完成 P6 全部 backend regression 與 diff 審核）。
- **下一步**：F4b 六個 Importer MCP tool（直接用 F4a authority）。F5 須補 `adventure_import_blocking_warnings` 的 zh-TW／en 文案（見 [F3](P6-F_steps/F3.md)）。
- **阻礙／未審**：無。
- **派工約束**：沿 P6-C 派工約束 1／3（parametrize、前端測試不超過元件兩倍）。F5 開工前先評估是否順手拆 `AdventureImporterPanel.tsx`（P6-E closeout 觀察 1：1,241 行單一元件）；拆與不拆都要在 F5 紀錄說明。
- **派工決策（2026-09-22 拍板）**：(1) Review state 存進 `draft_json` 的 entry／warning 欄位，**schema 維持 `schema_version=1`**，新欄位一律 optional 帶預設；(2) Finalize 的 idempotency 鍵就是 **`adventure_imports.target_adventure_id`**——已設即回同一 Adventure，不新增欄位、不新增 migration；(3) 六個 importer MCP tool **全開給 active Session 的 current AI DM**（AI Player／stale／revoked 一律拒絕，pre-session grant 工具集不變）；(4) Finalize 的 entry asset 走 **`DraftEntry.asset_ids`（room asset id，optional）**＋既有 `link_entry_asset`，`source_ref` 維持 draft-only 稽核；(5)（2026-09-23）AI DM 可 finalize，但 table actor 只能 author draft Adventure，P6-A A.1 測試相應收斂（見 [F4a](P6-F_steps/F4a.md)）。
- **正式契約入口**：`docs/P6/實作規格.md`「P6 共用產品邊界」「P6-F」；`docs/P6/開發設計方針.md`「Architecture」「P6-A」（Adventure authoring API）「P6-E」（E.1 Source）「P6-F」「REST / UI surface」「Subphase implementation boundary」；`docs/P6/測試指南.md`「P6 核心風險」「執行環境」「P6-F」（F.1～F.6）。
- **跨步依賴**：F1 → F2a → F2b → F3 → F4a → F4b／F5（F4b 依賴 F4a，F5 只依賴 F3，可並行但本排程照序）。P6-E 交付面（`AdventureImportService`、`ImportDraft` schema、REST router、web API client）見 [P6-E closeout](P6-E_CLOSEOUT.md)；MCP facade 模式與 `require_active_table_actor` 見 [P6-D closeout](P6-D_CLOSEOUT.md)。

## 步驟進度

| Step | 標題 | 狀態 | 依賴 | 紀錄 |
|---|---|---|---|---|
| F1 | Review state：entry review status、warning 三級與 resolve、question answer | 完成 | — | [F1](P6-F_steps/F1.md) |
| F2a | Adventure authoring 共用 transaction 接線 | 完成 | F1 | [F2a](P6-F_steps/F2a.md) |
| F2b | Import Finalize transaction／blocking gate／idempotency | 完成 | F2a | [F2b](P6-F_steps/F2b.md) |
| F3 | REST：review／resolve／answer／finalize route | 完成 | F2b | [F3](P6-F_steps/F3.md) |
| F4a | Importer 的 current AI DM authority 接線 | 完成 | F3 | [F4a](P6-F_steps/F4a.md) |
| F4b | 六個 Importer MCP tool＋catalog／guide parity | 待做 | F4a | [F4b](P6-F_steps/F4b.md) |
| F5 | UI：Draft Review 面板、Finalize、zh-TW／en、E2E | 待做 | F3 | [F5](P6-F_steps/F5.md) |
