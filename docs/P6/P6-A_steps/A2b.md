# A2b — Adventure routes 與 lifecycle

## Scope

- `AdventureService` 追加：`finalize`（draft→finalized）、`archive`（任何→archived）、`delete`（只允許 draft 或未被任何 Campaign attach 的 finalized；被 attach → `AdventureAttachedError` 409 `adventure_attached_use_archive`）、`attach_asset(entry_id, asset_id, role)`／`detach_asset`（asset 須同 Room，否則 404；role `image | map | source | attachment`）。
- `app/api/rooms/adventures.py`：`/api/rooms/{room_id}/adventures` GET／POST；`/{adventure_id}` GET／PATCH／DELETE；`/{adventure_id}/finalize` POST；`/{adventure_id}/archive` POST；`/{adventure_id}/entries` GET／POST；`/entries/{entry_id}` PATCH／DELETE；`/entries/reorder` POST；`/entries/{entry_id}/assets` POST／DELETE。錯誤對映集中在 `_map_adventure_error`。註冊到 `main.py`／`dependencies.py`。
- `tests/test_p6a_adventure_api.py`（TestClient）：owner 全流程 201／200；dm 可寫；member 任何路由 404；cross-Room 404；draft finalize 200 且 status 變更；archive 後 entry POST 409；finalized 後 PATCH name 200；delete draft 204；delete 被 attach 的 finalized 409（attach route 在 A3 才有，此步用 repository 直接插 link 模擬）；entry asset 連結 cross-Room asset 404；response 不含 asset `storage_key`。

## 對應契約

實作規格 P6-A lifecycle 條目；設計 §A.3、「REST / UI surface」；測試 A.1。

## 前置

A2a service；A1b `RoomAssetRepository`。

## 驗收

- `pytest tests/test_p6a_adventure_api.py tests/test_p6a_adventure_authoring.py tests/test_code_quality_gate.py`（cwd `apps/server`）全綠。

## 紀錄

（派工後補）
