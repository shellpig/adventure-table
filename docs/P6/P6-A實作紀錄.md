# P6-A — Adventure Definition & Campaign Attachment 實作紀錄

## 接手摘要

- **更新日期**：2026-09-20
- **目標與邊界**：Room-scoped asset substrate（PostgreSQL metadata＋Server filesystem）、Adventure Definition／Entry authoring 與 draft→finalized→archived lifecycle、Campaign 對 finalized Adventure 的多重 attach／detach、最小 Adventures workspace UI。**不做** Runtime／override／AI context／Importer（P6-B～F）。Human Player／AI Player 對 Adventure entry 任何 visibility 一律不可讀；`source_document` asset 固定 `dm_only`。契約：`docs/P6/實作規格.md` P6-A 與「P6 共用產品邊界」、`docs/P6/開發設計方針.md` §A.1～A.3 與「Shared authority」「REST / UI surface」「Migration」「Subphase implementation boundary」、`docs/P6/測試指南.md` A.1～A.5 與「執行環境」。
- **Branch**：`feat/p6a-adventure-definition`（自 `main@f2822270` 開出）
- **最近已驗證 commit**：A4b-1（Adventure editor；hash 見 git log）。Backend 全部完成
- **Worker**：agy 做 backend（A1a～A3）與 web（A4a～A4c；A4b 拆 A4b-1／A4b-2）；E2E、關門由指揮者做。每步 prompt 存 `C:\_work\AI_Work\Tools\agy-runs\agy-p6a-<step>.prompt.txt`
- **下一步**：A4b-2 進行中（agy）；之後 A4c → A5，使用者 2026-09-20 指示連續做到 P6-A 完成
- **阻礙／未審**：無
- **本 Subphase 技術決策（契約未指定，指揮者拍板，verifier 可同步回設計文件）**：
  1. 模組位置：`app/persistence/room_assets/`（tables、storage、repository）、`app/persistence/adventures/`（tables、repository）、`app/domain/room_assets/`、`app/domain/adventures/`、`app/api/rooms/room_assets.py`、`app/api/rooms/adventures.py`、`app/api/rooms/campaign_adventures.py`。M03 boundary regex 同 commit 加 `room_assets?`／`adventures?`。
  2. Asset upload 走 **raw request body**（`Content-Type` 為 MIME、`filename` query param），不用 multipart，避免新增 `python-multipart` 相依觸發發版清單重產；size 上限由 Settings 固定（image 20 MiB、source_document 20 MiB）。
  3. Migration 單檔 `0031_p6a_room_assets_adventures` 含五張表（`room_assets`、`adventure_definitions`、`adventure_entries`、`adventure_entry_assets`、`campaign_adventure_links`），由 A1a 一次建立；後續步驟不再改 schema。
  4. duplicate attach 契約：同一 Campaign 重複 attach 同一 Adventure 回 **409 `adventure_already_attached`**，零副作用（不採 idempotent 200，避免掩蓋 UI 重送）。
- **跨步依賴**：A1b／A2a 依賴 A1a schema；A1c 依賴 A1b storage；A2b 依賴 A2a＋A1b（entry asset 連結）；A3 依賴 A2b；A4a 依賴 A2b＋A3 route；A4b-1 依賴 A4a；A4b-2 依賴 A4b-1＋A1b；A4c 依賴 A4a＋A3；A5 依賴全部

## 步驟進度

| Step | 標題 | 狀態 | 依賴 | 紀錄 |
|---|---|---|---|---|
| A1a | schema：五張表＋migration `0031`、Settings `asset_root`、compose volume、M03 boundary／parity 擴充、PG migration test | 完成 | — | [A1a](P6-A_steps/A1a.md) |
| A1b | Room Asset：filesystem storage、repository、service、routes、`test_p6a_room_assets.py`（A.4 除 hard delete） | 完成 | A1a | [A1b](P6-A_steps/A1b.md) |
| A1c | Room hard delete cascade＋filesystem cleanup 失敗可重試定位（A.4 後半） | 完成 | A1b | [A1c](P6-A_steps/A1c.md) |
| A2a | Adventure domain：typed entry payloads、repository、service（definition／entry CRUD、owner／dm authority、Player 拒讀）、`test_p6a_adventure_authoring.py` | 完成 | A1a | [A2a](P6-A_steps/A2a.md) |
| A2b | Adventure routes＋lifecycle：finalize／archive／delete 規則、entry asset 連結、cross-Room 拒絕、`test_p6a_adventure_api.py` | 完成 | A2a、A1b | [A2b](P6-A_steps/A2b.md) |
| A3 | Campaign attachment：links repository／service／routes、finalized-only、409 duplicate、detach、空 Campaign regression、`test_p6a_campaign_adventures.py` | 完成 | A2b | [A3](P6-A_steps/A3.md) |
| A4a | web：`api/adventures.ts`／`api/roomAssets.ts`、`RoomAdventuresPage`（list／create／finalize／archive）、routing、workspace 入口、copy 兩 locale | 完成 | A2b、A3 | [A4a](P6-A_steps/A4a.md) |
| A4b-1 | web：`AdventureEditorPage`（definition 編輯、entries CRUD／kind 欄位／reorder、archived 唯讀）、copy 兩 locale | 完成 | A4a | [A4b-1](P6-A_steps/A4b-1.md) |
| A4b-2 | web：entry 圖片上傳→連結、縮圖（fetch＋blob URL）、unlink、copy 兩 locale | 進行中 | A4b-1、A1b | [A4b-2](P6-A_steps/A4b-2.md) |
| A4c | web：Campaign page「Attached Adventures」（attach picker／detach）、copy 兩 locale | 待做 | A4a、A3 | [A4c](P6-A_steps/A4c.md) |
| A5 | E2E `p6a-adventures.spec.ts`、關門 gate、closeout、合併 `main` | 待做 | A1a～A4c | [A5](P6-A_steps/A5.md) |
