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

（派工後補）
