# M03-B Closeout Checklist

M03-B — Character JSON Schema, Export & Builder Provenance closeout scope：

- [x] **B.1 Migration**：`0007_m03b_builder_provenance` 在 `character_versions` 加 `builder_provenance`，Postgres 為 `JSONB NULL`、SQLite 走 `with_variant` 的 `JSON NULL`；既有 version rows 為 `NULL`，upgrade / downgrade 在 Postgres 綠。SQLite parity 依實作規格延至 M03-D。
- [x] **B.2 Confirm 寫入 provenance**：Create / Level Up / Build Edit / Correction 四條 Confirm 路徑都把當時的 `BuilderDraftPayload` snapshot 寫進該 version 的 `builder_provenance`；snapshot 不含 session 資訊、revision counter 或 UI-only 欄位。Migration 之前落地的 legacy version 維持 `NULL`，不 backfill、不假造。
- [x] **B.2.1 Versioned draft seeding SSOT**：`seed_version_draft_payload()` 收斂為單一 fallback 序列 `builder_provenance` → `character_build_drafts` → `legacy_payload_from_build`，Level Up / Build Edit / Correction 共用同一函式，不各自判斷。`builder_provenance` 內容無法通過 `BuilderDraftPayload.model_validate()` 時降級到下一層並留 warning，不讓壞資料炸掉 Level Up。舊 keyword `source_payload` 保留為 compatibility alias，與新的 `stored_draft_payload` 互斥。
- [x] **B.3 匯出端點**：`GET /api/characters/{id}/export` 回 `application/json` + `Content-Disposition: attachment`，同時給 ASCII fallback 檔名與 RFC 5987 的 `filename*=UTF-8''`，中文角色名不產生非法檔名。端點純讀，匯出前後 DB rows 與 `updated_at` 不動；不存在的 UUID 回 404。已 archive 的角色仍可匯出，archived 狀態走 `X-Adventure-Table-Character-Archived` header 而不進 payload。
- [x] **B.4 Envelope**：`schema_version` / `schema_status` 於 M03 期間鎖為 `"unstable"`（`Literal`，未來值不會靜默通過 validation）；`content_requirements` 由實際 refs 走訪產生，只列該角色真正引用到的 pack 與其 manifest version；另帶 `ruleset`、`stable_key_refs_summary`、`source_character_id`、`source_export_id`、`source_app`、`exported_at`。
- [x] **B.4.1 Pack manifest version 為必填授權值**：`ContentManifest.version` 不給 schema default——沒有 default 才不會讓未標版本的 pack 靜默宣稱一個版本。9 個 enabled pack 的 `manifest.json` 均已補上 `version`。
- [x] **B.5 Payload**：`character` 只帶 `name` / `ruleset`；`versions` 是完整 chain 依 `version_no` 遞增，`parent_version_id` / `superseded_by_version_id` 已映射為 chain 內的 `version_no`；`current_version_no` 為明寫欄位，不假定等於 max；`current_state` 綁定該 version。payload 不含 `id` / `current_version_id` / `archived_at` / `updated_at`，也不含 Builder Draft。
- [x] **B.5.1 Portability inventory 是 fail-fast 的**：`content_ref_walker` 只走訪 inventory 宣告過的欄位，因此它本身抓不到全新欄位。`test_m03b_schema_inventory.py` 反過來要求 `CharacterBuild` / `CharacterState` 可達的每個欄位，都被明確歸類為 StableKey portability path 或「不帶 content reference」；新增、改名或刪除持久化欄位會在此紅燈，逼開發者當場重新考慮 `content_requirements` 覆蓋範圍。
- [x] **B.6 前端匯出入口**：Character Workshop 角色卡片與 Character Sheet header 各有匯出按鈕，按下直接觸發瀏覽器下載，無 dialog。Sheet 的按鈕由 Sheet 自己擁有，不是外部注入。
- [x] **B.7 Localization**：`character-io` copy 以 typed `zh-TW` / `en` 資源交付，涵蓋 label / `aria-label` / tooltip / 進行中狀態 / 失敗訊息；`hardcodedUiCopy.test.ts` 的掃描範圍已納入 export UI 檔。
- [x] **B.8 匯出 fixture 進 repo 且不漂移**：4 份 fixture（`fixture_low_level_srd` / `fixture_multiclass_mixed` / `fixture_xge_dependent` / `fixture_legacy_no_provenance`）由 `generate_m03b_fixtures.py` 從真實 endpoint 產生並提交；`--check` 模式在 CI 比對，端點輸出一變就紅。另有 `fixture_bad_version_kind` 作為 strict enum 的反例。
- [x] **B.9 邊界維持**：本 Subphase 不做匯入、不 lock schema、不加 `/api/meta/capabilities`。`m03b-character-export.spec.ts` 有一條測試明確斷言 M03-B 的 UI 尚未出現任何 import 入口。
- [x] **B.10 既有功能無回歸**：`characters.py` 端點 signature 除新增 `/export` 外未變；Landing / Workshop / Builder / Sheet / Level Up / Version History / Archive / Locale 切換行為與 M03-A closeout 一致。

## 交付內容

後端：

| 檔案 | 內容 |
|---|---|
| `apps/server/alembic/versions/0007_m03b_builder_provenance.py` | B.1 migration |
| `apps/server/app/interop/json_schema.py` | Envelope / Payload strict models、`VersionKind` enum |
| `apps/server/app/interop/content_ref_walker.py` | build / state StableKey 走訪與 portability inventory |
| `apps/server/app/interop/character_export.py` | `build_character_export()` payload builder |
| `apps/server/app/api/character_export.py` | `GET /api/characters/{id}/export` |
| `apps/server/app/persistence/characters.py` | `builder_provenance` 欄位讀寫 |
| `apps/server/app/domain/character_builder/versions.py` | B.2.1 seeding SSOT |
| `apps/server/app/domain/character_builder/service.py` | 接線至新 seeding 序列 |
| `apps/server/app/content/schemas.py` | `ContentManifest.version` |

前端：

| 檔案 | 內容 |
|---|---|
| `apps/web/src/features/character-io/api.ts` | 匯出呼叫與下載觸發 |
| `apps/web/src/features/character-io/ExportCharacterButton.tsx` | 共用匯出按鈕 |
| `apps/web/src/i18n/copy/character-io.{zh-TW,en}.ts` | 雙語 copy |
| `apps/web/src/i18n/useCharacterIoCopy.ts` | locale hook |

## Verification evidence

2026-09-04，分支 `m03-b-character-export-provenance`：

```text
cd apps/server
python -m pytest tests/test_m03b_*.py
50 passed（exit 0）

python tests/generate_m03b_fixtures.py --check
fixture 無漂移（exit 0）

cd apps/web
npm test -- --run
21 test files / 107 tests passed

npm run build          # tsc --noEmit + vite build
exit 0
```

Postgres 走本機 `adventure-table-db-1` 容器上的獨立 `adventure_m03b` database，不動開發用的 `adventure_table`。

後端全量 `pytest` 與 `npm run test:e2e:docker` 由專案 owner 於本 session 之前執行並回報通過；**本 session 未重跑這兩項**。E2E 一律走容器化 dev server，理由見 `已知問題.md` 的 KI-ENV-001。

M03-B 專屬後端覆蓋為 8 個測試檔共 50 個測試：

| 檔案 | 測試數 | 對應測試指南 |
|---|---|---|
| `test_m03b_migration.py` | 2 | B.1 |
| `test_m03b_confirm_writes_provenance.py` | 3 | B.1 |
| `test_m03b_json_schema.py` | 12 | B.2 |
| `test_m03b_versioned_draft_seeding.py` | 5 | B.2.1 |
| `test_m03b_build_ref_walker.py` | 8 | B.3 |
| `test_m03b_schema_inventory.py` | 3 | B.3（延伸） |
| `test_m03b_export_payload.py` | 3 | B.4 |
| `test_m03b_export_api.py` | 3 | B.5 |

瀏覽器覆蓋為 `apps/web/e2e/m03b-character-export.spec.ts`，7 條真後端 flow：Workshop 匯出、Sheet header 匯出、雙語 label 完整性、archived 角色仍可匯出、ASCII + RFC 5987 雙檔名、真實下載檔名一致、M03-C 之前不得出現 import 入口。

CI：`.github/workflows/m03b-non-e2e.yml`（Postgres service、M03-B focused pytest、後端全量 pytest、localization authoring unit tests、全新 SQLite `alembic upgrade head`、fixture drift `--check`、前端測試與 build、`docker compose config`）與 `.github/workflows/m03b-e2e.yml`，目前僅於 `m03-b-character-export-provenance` 分支 push 觸發。

## 關門過程中處理的既有缺口

1. **Pack manifest 沒有版本欄位**：`content_requirements` 需要每個 pack 的版本，但 9 個 `manifest.json` 都沒有。已補 `version` 並在 schema 明確不給 default——給 default 等於讓未標版本的 pack 靜默宣稱版本。`data/srd5.1/manifest.json` 的 `categories` 一併改為單行物件排版，內容未變。
2. **`legacy_payload_from_build` 是唯一 seed 來源**：匯入落地的角色沒有對應的 `character_build_drafts` row，只靠 legacy 重建會遺失原始 Draft 選擇。B.2.1 的 fallback 序列把 `legacy_payload_from_build` 降級為最後手段，`builder_provenance` 成為 SSOT，這是 M03-C 匯入能安全走 Level Up 的前提。
3. **兩個檔案缺行尾換行**：`service.py` 與 `schemas.py` 原本沒有 trailing newline，順手補上。

## M03-B 未涵蓋（依實作規格「本 Subphase 不要求」）

- 不做匯入（M03-C）。
- 不做網頁版 JSON schema lock；`schema_status` 於整個 M03 期間維持 `"unstable"`，正式 semver 待 P2。
- 不做 `/api/meta/capabilities`（M03-E）。
- `content_requirements` 只列 pack 版本，不列 StableKey 名單。
- 不做排程匯出或批次匯出。
- SQLite 上的 migration 綠燈不在本 Subphase 保證，統一由 M03-D 處理。
