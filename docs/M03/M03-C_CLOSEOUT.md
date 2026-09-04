# M03-C Closeout Checklist

M03-C — Character JSON Import via Builder Draft closeout scope：

- [x] **C.1 匯入端點**：`POST /api/characters/import` 只收 `application/json`，非 JSON 的 `Content-Type` 回 415。端點手動讀 raw body（`await request.body()`），依序走 size gate → `json.loads` → `CharacterExport.model_validate` → 語意 pipeline，不使用 FastAPI typed body 綁定，因此 pydantic 失敗不會被全域 422 `validation_failed` 蓋掉，一律是 400 加對應 machine code。`dry_run=true` 回 200、commit 回 201。拒絕為原子操作，零殘留。
- [x] **C.2 Ref 收集器**：`collect_build_refs` / `collect_state_refs` 沿用 M03-B 的 `content_ref_walker`，明列 StableKey path、不做 reflection，遇到 inventory 未涵蓋的形狀 fail-fast。State walker 覆蓋 `conditions[].condition_ref`、`prepared_spells[].spell_key`、`inventory_state[].item_ref`、`active_infusions[].infusion_ref`、`spell_storing_item.spell_ref`。
- [x] **C.3 解析預檢**：preview 與 commit 走同一個 `_prepare()`，順序為 ruleset 支援檢查 → version chain 一致性 → lineage 完整性 → 逐 version `CharacterBuild.model_validate` → 非 null `builder_provenance` 過 `BuilderDraftPayload.model_validate` → `CharacterState.model_validate` → ruleset 三重 cross-check → build/state refs 收集與 `registry.get_optional` 分類 → landing_mode 判定 → `duplicate_hint` → `character_preview`。前端一律先 dry-run 再由使用者決定是否 commit，沒有預設門檻。
- [x] **C.3.1 lineage 檢查順序**：cycle 偵測排在 direction 檢查**之前**。反過來的話任何環都會先撞上「parent 必須早於自己」而回 `version_lineage_direction_invalid`，`version_lineage_cycle` 這個 code 將永遠無法到達。`fixture_bad_lineage_cycle.json`（v1↔v2 互指）就是這條順序的守門測試。
- [x] **C.4 落地邏輯**：`landing_mode="character"` 走**兩階段 insert**——第一 pass 每個 version 以 `parent_version_id=NULL` / `superseded_by_version_id=NULL` 寫入，第二 pass 依 `version_no → 新 UUID` dict UPDATE 補 lineage，避免 FK 於 INSERT 當下指向尚未存在的 row。`builder_provenance` 逐 row 保留原 JSON；`characters.current_version_id` 對應 `current_version_no`，不假定等於 max。`draft` / `draft_with_history_loss` 建立 fresh CREATE Draft（不綁 `base_version_id`），未解析 ref 對應的 choice 清空為未填，current state 不進 Draft。
- [x] **C.4.1 Draft 不得挾帶 state seed**：`_sanitize_draft_payload()` 一律把 `initial_state_seed` 清成空。provenance 可能來自歷史 create/version draft，不清就會把過期的 state 種進新的 Version 1。未解析的 class ref 會截斷該 level 之後的整條 rail（level row 不能沒有 class），未解析的 subclass ref 只清該欄位；starting equipment choice id 是 builder 決定性 id 而非 StableKey，沒有安全的反查，因此一旦有 equipment/item ref 未解析就整組重開。
- [x] **C.5 Identity 與重複偵測**：一律新 UUID 落地，不合併、不覆寫、不帶入 `archived_at`。`source_character_id` / `source_export_id` 進 `character_import_records`；dry-run 回 `duplicate_hint`（次數 + 最近一次時間），前端提示但不阻擋。
- [x] **C.6 歷史版本處理**：`character` 模式保留完整 chain 含 correction lineage；`draft` / `draft_with_history_loss` 只取 `current_version_no` 的 provenance，其餘 version 於本次匯入放棄，此犧牲已於 preview 明示。
- [x] **C.7 拒絕條件**：20 個 rejection code 各有一條 test，且各自斷言 `characters` / `character_versions` / `character_states` / `character_import_records` / `character_build_drafts` 均無新 row。`payload_too_large` 回 413 並帶 `params.max_bytes`；`Content-Length` 於讀 body 前先擋一次。
- [x] **C.7.1 Pydantic 階段的 code 映射**：`map_validation_error()` 先對 `exc.errors()` 依 `loc` 排序再取 `min`，因此 `schema_status` 與 `version_kind` 同時出錯時固定回 `loc` 排序最前者，不隨 pydantic 的 error 順序漂移。special case 優先於泛用 shape code；root location 為空（傳進來的是純量或 list）歸 `invalid_envelope_shape`。
- [x] **C.7.2 錯誤回應帶 `params`**：`APIError` / `CharacterImportError` / `_error_response()` 串起 optional `params`，rejection 訊息不再只有一句英文散文。
- [x] **C.8 Import records**：`0008_m03c_import_records` 建表，兩個 FK 皆 `ON DELETE SET NULL`，CheckConstraint 為 `character_id IS NULL OR draft_id IS NULL`。**刻意不是 XOR**：目標 character 被永久刪除後該列會變成兩欄皆 NULL，XOR 會當場擋下刪除。「建立當下恰好一欄非 NULL」由 service 層保證（commit 內有 `(character_id is None) == (draft_id is None)` 的 guard，違反即 rollback）。
- [x] **C.8.1 Revision id 長度**：Alembic 的 `alembic_version.version_num` 是 `VARCHAR(32)`。revision id 命名為 `0008_m03c_import_records`（24 字元）而非展開式的長名，否則 Postgres 會在 `UPDATE alembic_version` 當下丟 `StringDataRightTruncation`，server 直接起不來。`test_m03c_migration.py` 有 `len(revision) <= 32` 的斷言鎖住這件事。
- [x] **C.9 前端匯入入口**：Workshop hero、角色列表 header 與空狀態各有一顆「匯入角色」按鈕。Dialog 同時提供檔案選擇（`File.text()` 讀出後與貼上走同一條 JSON body 呼叫）與 textarea。Preview 顯示可解析 / 未解析數量與 landing_mode，未解析清單可展開並標示 `origin`（build / state）與 version_no。`draft_with_history_loss` 顯示 warning banner 並要求勾選二次確認才 enable commit。成功後導向新 Character Sheet 或新 Draft。
- [x] **C.9.1 Rejection message 雙語**：20 個 machine code 各有 `zh-TW` / `en` 文案，住在 `characterImportMessages.ts`。不做這件事的話 zh-TW 會全部退化成「要求失敗（HTTP 400）」、en 會直接吐 `str(ValidationError)` 的多行 dump。`characterImportMessages.test.ts` 鎖住 code 集合完整性，並斷言已知 code 不會漏出 pydantic dump。
- [x] **C.9.2 關閉鈕有自己的 accessible name**：dialog 的 × 原本沿用 `importCancel`，與 footer 的「取消 / Cancel」共用同一個 accessible name。已改為獨立的 `importClose`（`關閉匯入對話框` / `Close import dialog`）——兩顆功能不同的按鈕不該同名。
- [x] **C.10 不變性**：後端全量 `pytest` 與整套 E2E 綠；Landing / Workshop / Builder / Sheet / Level Up / Version History / Archive / Locale 切換行為與 M03-B closeout 一致。既有 Builder Draft 語意未變，只是多了一種建立來源。

## 交付內容

後端：

| 檔案 | 內容 |
|---|---|
| `apps/server/alembic/versions/0008_m03c_import_records.py` | C.8 migration |
| `apps/server/app/persistence/character_imports.py` | `character_import_records` table 與 `ImportLandingMode` |
| `apps/server/app/interop/character_import.py` | preview / commit pipeline、landing_mode 判定、draft sanitization |
| `apps/server/app/api/character_import.py` | `POST /api/characters/import`、raw body 解析、`map_validation_error()` |
| `apps/server/app/api/dependencies.py` | `get_character_import_service` |
| `apps/server/app/api/errors.py`、`app/main.py` | `APIError.params` 與錯誤回應中的 `params` |
| `apps/server/alembic/env.py` | 補進 builder_drafts / character_imports 的 metadata import |

前端：

| 檔案 | 內容 |
|---|---|
| `apps/web/src/features/character-io/ImportCharacterDialog.tsx` | 匯入 dialog（檔案 / 貼上、preview、history-loss 二次確認） |
| `apps/web/src/features/character-io/api.ts` | `previewCharacterImport` / `commitCharacterImport`，送出原始 JSON 字串不重建 |
| `apps/web/src/features/character-io/character-io.css` | dialog 樣式 |
| `apps/web/src/i18n/characterImportMessages.ts` | 20 個 rejection code 的雙語訊息 |
| `apps/web/src/i18n/copy/character-io.{zh-TW,en}.ts` | dialog copy |
| `apps/web/src/features/character-builder/CharacterWorkshopPage.tsx` | 三處匯入入口 |

測試基礎設施：

| 檔案 | 內容 |
|---|---|
| `apps/server/tests/m03c_support.py` | 共用 client / registry / subset 組裝 |
| `apps/server/tests/data/m03/fixture_state_only_missing_inventory.json` | build 全解、state 有未解 |
| `apps/server/tests/data/m03/fixture_bad_{ruleset_mismatch,lineage_cycle,builder_provenance}.json` | 三個拒絕情境 |
| `apps/web/scripts/e2e-docker.mjs` | 缺 pack 的第二輪 E2E |
| `docker-compose.yml` | server 透傳 `ADVENTURE_TABLE_ENABLED_CONTENT_PACKS` |

## Verification evidence

2026-09-04，分支 `m03-c-character-import`：

```text
cd apps/server
python -m pytest                       # 後端全量
exit 0（1 skipped：Postgres-gated migration test）

M03C_POSTGRES_URL=... python -m pytest tests/test_m03c_migration.py
1 passed（真 Postgres 上 upgrade → downgrade → upgrade）

cd apps/web
npm test -- --run
22 test files / 112 tests passed

npm run build                          # tsc --noEmit + vite build
exit 0

npm run test:e2e:docker
pass 1（完整 9 pack）：97 passed / 3 skipped / 0 failed
pass 2（srd5.1,phb2014,scag,gos,vgm,vrgr,tce,mtf）：7 passed
```

M03-C 專屬後端覆蓋為 8 個測試檔共 59 個測試：

| 檔案 | 測試數 | 對應測試指南 |
|---|---|---|
| `test_m03c_state_ref_walker.py` | 3 | C.1 |
| `test_m03c_import_pipeline.py` | 14 | C.2 |
| `test_m03c_commit.py` | 4 | C.3 |
| `test_m03c_import_rejections.py` | 21 | C.4 |
| `test_m03c_validation_error_mapping.py` | 7 | C.4.1 |
| `test_m03c_duplicate_hint.py` | 3 | C.5 |
| `test_m03c_import_api.py` | 6 | C.6 |
| `test_m03c_migration.py` | 1 | C.7 |

瀏覽器覆蓋為 `apps/web/e2e/m03c-character-import.spec.ts`，7 條真後端 flow：檔案選擇匯入到 Sheet、貼上路徑走同一 preview、state-only 未解析要求二次確認、duplicate hint 含次數與最近時間、rejection 訊息雙語、缺 pack 時 build ref 未解析落 Draft、缺 provenance 時 `draft_reconstruction_unavailable`。**最後兩條只有在 server 少一個 pack 時才有意義**，因此 `e2e-docker.mjs` 在全套跑完後會用不含 `xge` 的 pack 清單重啟 server 再跑一次該 spec，結束後還原。subset 清單向跑著的 server 讀回而非寫死在腳本裡，`app/config.py` 仍是 pack 清單的唯一來源。

CI：`.github/workflows/m03c-non-e2e.yml`（Postgres service、Postgres migration round trip、M03-C focused pytest、後端全量 pytest、localization authoring unit tests、前端測試與 build、`docker compose config`），僅於 `m03-c-character-import` 分支且該 workflow 檔被觸碰時執行。

## 關門過程中處理的既有缺口

1. **Alembic revision id 超過 `VARCHAR(32)`**：初版 revision id 為 `0008_m03c_character_import_records`（34 字元），Postgres 上 `UPDATE alembic_version` 直接丟 `StringDataRightTruncation`，`docker compose` 的 server container exit 1，整套 E2E 起不來。pytest 抓不到是因為測試 harness 走 `metadata.create_all()`，唯一跑 alembic 的 M03-B migration test 只跑 SQLite，而 SQLite 不強制 VARCHAR 長度。已縮短 id 並補上真 Postgres 的 round-trip 測試。
2. **M03-B fixture corpus guard 的精確集合**：`test_m03b_fixture_corpus_is_present` 用精確檔名集合鎖 `data/m03/`，過濾條件只排除 `_bad_`。M03-C 新增的 `fixture_state_only_missing_inventory.json` 不含 `_bad_`，於是後端全量 pytest 變紅。已把新檔名加進期望集合。
3. **匯入 dialog 的關閉鈕與取消鈕同名**：見 C.9.2。
4. **`m03b-character-export.spec.ts` 的 import-absence 守門測試**：該測試斷言 M03-C 之前不得出現 import 入口，M03-C 交付後已完成任務，隨本 Subphase 移除。

## M03-C 未涵蓋（依實作規格「本 Subphase 不要求」）

- 不做 Campaign / Party Roster 匯入。
- 不做 batch 匯入、undo import、diff 顯示。
- 不做 SQLite migration gate（M03-D）。
- 無 packaging test、無 capability endpoint test。

## 已知的驗收覆蓋缺口（留給後續 Subphase）

以下兩點測試指南 C.8 有列，本 Subphase 未做到，不影響產品行為但覆蓋不完整：

1. **Draft 落地後的導向與「未填 choice 呈現」沒有瀏覽器斷言**。缺 pack 的第二輪 E2E 驗到 preview 顯示 `landing_mode=draft` 與 rejection，但沒有走完 commit → 導向 Draft → 檢查該 choice 呈現為未填。後端 `test_m03c_commit.py` 有涵蓋 draft payload 的等價斷言。
2. **主流程只跑 `en` 一輪**。C.8 要求 `zh-TW` / `en` 各跑主流程一次，目前 zh-TW 只覆蓋一則 rejection 訊息。dialog copy 的雙語完整性由 `characterIoCopy.test.ts` 的 key parity 測試守住。
