# A1b — Room Asset：storage、repository、service、routes

## Scope

- `app/persistence/room_assets/storage.py`：`FilesystemAssetStorage(root: Path)`：`write(storage_key, data)`（先寫 temp 再 rename）、`open(storage_key)`、`delete(storage_key)`；`storage_key = f"{room_id}/{asset_id}{ext}"`；不做 public static mount。
- `app/persistence/room_assets/repository.py`：`RoomAssetRepository`：`insert`、`get(room_id, asset_id)`、`list(room_id, kind?)`、`delete`；stored dataclass。
- `app/domain/room_assets/schemas.py`／`service.py`：`RoomAsset` view（**不含** `storage_key`／實體路徑）；`RoomAssetService.create(room_id, *, kind, filename, mime_type, data, visibility, context)`：owner／dm 才可建立；MIME 白名單（image：png／jpeg／webp；source_document：text/plain、text/markdown、application/pdf、DOCX）；size 上限來自 Settings；`kind=source_document` 強制 `visibility=dm_only`，傳 `room` 拒絕（`400 asset_visibility_not_allowed`）；sha256；DB insert 與檔案寫入失敗任一方回滾另一方（零 orphan）。`get`／`list` 依 visibility 過濾：member 只看 `room`；`open_content` 同規則。`delete` owner／dm；若被 `adventure_entry_assets` 引用回 `409 asset_in_use`。
- `app/api/rooms/room_assets.py`：`POST /api/rooms/{room_id}/assets?kind=&filename=&visibility=`（raw body，`Content-Type` 為 MIME）、`GET /assets`、`GET /assets/{asset_id}`、`GET /assets/{asset_id}/content`（StreamingResponse，`Content-Disposition` 用 `original_filename`）、`DELETE /assets/{asset_id}`；註冊到 `app/main.py` 與 `api/rooms/dependencies.py`（`get_room_asset_service`）。
- `tests/test_p6a_room_assets.py`：owner 上傳 image 201＋metadata 正確；member 上傳 403；member 讀 `room` image 200、讀 `dm_only` image 404；dm 讀 `dm_only` 200；`source_document` 帶 `visibility=room` 400 且無 row、無檔案；invalid MIME 400 零 orphan；oversize 413 零 orphan；cross-Room 讀 404；response JSON 不含 `storage_key`／絕對路徑；delete 後檔案與 row 皆消失。

## 對應契約

實作規格 P6-A「Room 可保存 P6 reusable assets…」；設計 §A.1；測試 A.4（hard delete 部分留 A1c）。

## 前置

A1a 五張表與 Settings。

## 驗收

- `pytest tests/test_p6a_room_assets.py tests/test_code_quality_gate.py`＋既有 Room API 測試（cwd `apps/server`）全綠；測試用 `tmp_path` 作 asset root。

## 紀錄

- **起始**：2026-09-20，worker agy（`Gemini 3.8 Flash (High)`），1 回合 4 分 47 秒，prompt `C:/_work/AI_Work/Tools/agy-runs/agy-p6a-A1b.prompt.txt`，conversation `a530827b-360e-4a31-8f79-ac552dfbeef5`。
- **交付**：`paths.resolve_asset_root()`（env → Settings → `apps/server/.data/assets`；`.gitignore` 加 `.data/`）；`persistence/room_assets/storage.py::FilesystemAssetStorage`（tmp＋`os.replace`、`..`／絕對路徑拒絕、root 逃逸拒絕）；`repository.py::StoredRoomAsset`／`RoomAssetRepository`（`insert_in_transaction`、`get`、`list_for_room`、`delete` 回傳 row、`is_referenced` EXISTS `adventure_entry_assets`）；`domain/room_assets/schemas.py`（`RoomAsset` view 無 storage_key、7 個 domain error）；`service.py::RoomAssetService`（`create`／`get`／`list`／`open_content`／`delete`，單一 `_visible`，MIME→ext 常數，insert＋write 同 transaction、失敗清檔）；`api/rooms/room_assets.py`（POST raw body／GET list／GET one／GET content StreamingResponse／DELETE；錯誤碼 `room_asset_not_found` 404、`room_asset_authority_required` 403、`asset_media_type_not_supported` 400、`asset_too_large` 413、`asset_empty` 400、`asset_visibility_not_allowed` 400、`asset_in_use` 409）；`dependencies.get_room_asset_service`；router 註冊；`tests/test_p6a_room_assets.py` 10 個測試。
- **指揮者審核修正**：
  - `Content-Disposition` 原本把 `quote()` 百分比編碼塞進 `filename="…"`（瀏覽器不解碼）→ 改為 RFC 6266／5987：ASCII fallback `filename=` ＋ `filename*=UTF-8''<quote>`；測試斷言同步改為驗兩段。
  - `get_asset_content` 同時用 generator `finally: close` 與 `BackgroundTask(handle.close)` 雙重關閉 → 移除 BackgroundTask。
  - `get_room_asset_service` 多餘的 `if service is not None` 與 import 亂序（`app.config` 插在 combat import 中間）→ 整理；保留 `try/except AttributeError` 作為 Starlette State 的 membership test（既有 `getattr` 形式會突破 quality gate baseline）。
  - `storage.write` 失敗清理的 nested try/except → `unlink(missing_ok=True)`。
  - fixture teardown 沒清 `app.state.room_asset_service`，會漏到其他測試模組 → 加 `del`。
- **測試**：`pytest tests/test_p6a_room_assets.py tests/test_p2a_room_access.py tests/test_p2b_room_character_api.py tests/test_p2b_legacy_and_room_delete.py tests/test_m03_import_boundary.py tests/test_code_quality_gate.py` 34 passed；全套 backend pytest 全綠（1 既有 skip）。
- **未解問題／下一步**：`create()` 內 `else: raise Unsupported kind` 是 Literal 已排除的不可能分支，留待 A1c 若改到同檔順手收；A2a。
