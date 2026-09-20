# A1a — schema：五張表、migration 0031、Settings、compose volume、boundary 擴充

## Scope

- `app/persistence/room_assets/tables.py`：`room_assets`（設計 §A.1 欄位；`kind` 只允許 `image | source_document`，`visibility` 只允許 `room | dm_only`，以 CHECK 限制；`(room_id, sha256)` 不設 unique——同 Room 可重複上傳同檔）。
- `app/persistence/adventures/tables.py`：`adventure_definitions`、`adventure_entries`、`adventure_entry_assets`、`campaign_adventure_links`（設計 §A.2 欄位；`campaign_adventure_links` PK `(campaign_id, adventure_id)`，**不得**對 `campaign_id` 單獨 unique）。FK：`adventure_entries.parent_entry_id` → 同表；`adventure_entry_assets.asset_id` → `room_assets.id`；`campaign_adventure_links.adventure_id` → `adventure_definitions.id`（RESTRICT，不 cascade delete）。
- `alembic/versions/0031_p6a_room_assets_adventures.py`：`down_revision="0030_p4f_entry_dodging"`，web track；downgrade 反向 drop。
- `app/config.py`：`asset_root: str | None`（env `ADVENTURE_TABLE_ASSET_ROOT`）、`asset_max_image_bytes`／`asset_max_source_document_bytes`（20 MiB）。
- `docker-compose.yml`：server／server-e2e 加 `ADVENTURE_TABLE_ASSET_ROOT=/data/adventure-table/assets` 與 named volume `asset_data`（e2e 用獨立 `asset_data_e2e`）。
- `tests/test_m03_import_boundary.py`：`FORBIDDEN_MODULE_RE` 加 `room_assets?`／`adventures?` 段；`test_forbidden_regex_matches_module_segments_not_substrings` 加對應斷言。
- `tests/test_m03d_schema_parity.py`：`FORBIDDEN_MULTIPLAYER_TABLES` 加五張表。
- `tests/test_p6a_postgres_migration.py`：沿用 `test_p4f_postgres_migration.py` 形狀（`P4_POSTGRES_URL` skipif、xdist group）：upgrade head 後五張表存在、`campaign_adventure_links` 可對同一 Campaign 插入兩筆不同 Adventure、downgrade 到 `0030` 後五張表消失。
- `tests/test_migration_heads.py` 若有寫死 head，更新。

## 對應契約

設計 §A.1（欄位）、§A.2（欄位、多 link）、「Migration / PostgreSQL / Standalone」；測試 A.5。

## 前置

無。

## 驗收

- `pytest tests/test_p6a_postgres_migration.py tests/test_m03_import_boundary.py tests/test_m03d_schema_parity.py tests/test_migration_heads.py tests/test_p2a_migration_tracks.py tests/test_code_quality_gate.py`（cwd `apps/server`；PG 測試需 `P4_POSTGRES_URL`，指揮者以 docker db 提供）全綠。
- `docker compose config` 通過。
- Standalone `character@head` schema 不含五張表（parity test 證明）。

## 紀錄

- **起始**：2026-09-20，worker agy（`Gemini 3.8 Flash (High)`），1 回合 2 分 23 秒，prompt `C:/_work/AI_Work/Tools/agy-runs/agy-p6a-A1a.prompt.txt`，conversation `0b166a93-3c25-4510-b545-7bd411396b4c`。agy 在寫完全部檔案後、pytest 跑完前就結束回合（final report 只有一句「Running pytest…」），檔案齊全，指揮者自行跑 gate。
- **交付**：`persistence/room_assets/tables.py`（`room_assets`，CHECK `ck_room_assets_kind`／`ck_room_assets_visibility`，`storage_key` unique）；`persistence/adventures/tables.py`（`adventure_definitions`／`adventure_entries`／`adventure_entry_assets`／`campaign_adventure_links`，CHECK status／kind／visibility／role，`campaign_adventure_links` PK `(campaign_id, adventure_id)`、`adventure_id` RESTRICT）；兩模組由 `persistence/rooms/__init__.py` import 註冊到 metadata；`alembic/versions/0031_p6a_room_assets_adventures.py`（web track，parent `0030`）；`Settings.asset_root`／`asset_max_image_bytes`／`asset_max_source_document_bytes`；compose：server／server-e2e `ADVENTURE_TABLE_ASSET_ROOT` 與 `asset_data`／`asset_data_e2e` volume；`test_m03_import_boundary.py` regex 加 `room_assets?|adventures?` 與正／反斷言；`test_m03d_schema_parity.py` forbidden 加五表；`tests/test_p6a_postgres_migration.py` 3 個測試（reuse `test_p4f_postgres_migration._seed_room_and_campaign`）。
- **指揮者審核修正**：兩處 CHECK `kind IN (...)` 字串超過 140 字元，拆成兩行字串常數；其餘零修正。`test_p6a_source_document_visibility_check_constraint` 名稱是 prompt 給的，實際驗的是 invalid kind／visibility 被 CHECK 擋、`source_document+room` 在 DB 層合法（dm_only 是 A1b service 規則）。
- **測試**：`P4_POSTGRES_URL=…/adventure_table_p4` 下 `pytest tests/test_p6a_postgres_migration.py tests/test_p4f_postgres_migration.py tests/test_m03_import_boundary.py tests/test_m03d_schema_parity.py tests/test_migration_heads.py tests/test_p2a_migration_tracks.py tests/test_p3b_migration_contract.py tests/test_code_quality_gate.py` 34 passed；PG 三測試單跑 3 passed（非 skip）；全套 backend pytest 全綠（1 既有 skip）；`docker compose config` exit 0。
- **未解問題／下一步**：無；A1b。
