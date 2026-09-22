# P6-E — Adventure Source & Import Draft 實作紀錄

## 接手摘要

- **更新日期**：2026-09-22
- **目標與邊界**：建立 Importer 的 Source → Draft substrate：`adventure_imports` 三張表、`AdventureImportService`（paste／txt／markdown／url source、bounded chunk 讀取、Draft revision）、PDF／DOCX deterministic extraction、DM-only REST 與最小 Human UI（Source 區＋Draft editor）。**不做** Review 動作（Accept／Ignore／Mark uncertain）、warning 分級、Finalize、六個 Importer MCP tool——全部留 P6-F。Backend 不對 URL 做任何 fetch；importer module 不得含 LLM client。
- **Branch**：`feat/p6e-adventure-import`（自 `main@4c4943f5`）
- **最近已驗證 commit**：`74b30920`（E3）；62 focused／boundary／quality、514 passed＋16 skipped（P6-A～E regression），standalone build＋frozen smoke通過。
- **下一步**：派工 E4。
- **阻礙／未審**：無。
- **派工約束**：沿 P6-C 派工約束 1／3（parametrize、前端測試不超過元件兩倍）。E3 若新增 Python 套件，只進 `[project.optional-dependencies].web`、extractor lazy import；`constraints-standalone-win.txt` 重產、standalone build 與 frozen smoke 由指揮者在 E3 驗證時執行，不派給 worker。
- **派工決策（2026-09-22 拍板）**：(1) 六個 Importer MCP tool **全放 P6-F**，P6-E 只以 service／REST 驗測試指南 E.3 的 URL boundary；(2) E5 Draft editor 為**最小表單編 entry**，Human 建立的 entry provenance 固定 `user_explicit`，Review 動作留 F；(3) PDF／DOCX 套件採 `pypdf` + `python-docx`。
- **正式契約入口**：`docs/P6/實作規格.md`「P6 共用產品邊界」「P6-E」；`docs/P6/開發設計方針.md`「Architecture」「P6-A」（asset substrate、raw-body upload、media type）「P6-E」（E.1 Source、E.2 Extraction）「REST / UI surface」「Subphase implementation boundary」；`docs/P6/測試指南.md`「P6 核心風險」「執行環境」「P6-E」（E.1～E.5）。
- **跨步依賴**：E1 → E2 → E3 → E4 → E5（E3 依賴 E2 的 source pipeline；E4 需 E2＋E3 的 service 介面；E5 需 E4 route）。P6-A asset 上傳模式、DM-only authority（`RoomAccessContext`）與 P6-D 共用 fixture 見各自 closeout／`tests/p6_active_fixture.py`。

## 步驟進度

| Step | 標題 | 狀態 | 依賴 | 紀錄 |
|---|---|---|---|---|
| E1 | migration `0033`＋persistence＋Draft schema v1＋boundary gate | 完成（`1b878669`） | — | [E1](P6-E_steps/E1.md) |
| E2 | `AdventureImportService`：paste／txt／markdown／url source、chunk 讀取、Draft revision | 完成（`ad13898f`） | E1 | [E2](P6-E_steps/E2.md) |
| E3 | PDF／DOCX extractor（`web` extra、lazy import、locator、empty warning）＋從 room asset 建 source | 完成（`74b30920`） | E2 | [E3](P6-E_steps/E3.md) |
| E4 | REST `/api/rooms/{room}/adventure-imports/...`（DM-only） | 待做 | E2、E3 | [E4](P6-E_steps/E4.md) |
| E5 | Web UI：Importer Source 區＋最小 Draft editor、zh-TW／en、E2E | 待做 | E4 | [E5](P6-E_steps/E5.md) |
