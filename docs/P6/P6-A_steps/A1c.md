# A1c — Room hard delete cascade 與 filesystem cleanup

## Scope

- `app/persistence/rooms/workspace.py::hard_delete_room`：同一 transaction 內先刪 `campaign_adventure_links`、`adventure_entry_assets`、`adventure_entries`、`adventure_definitions`，收集該 Room 全部 `room_assets.storage_key` 後刪 metadata；transaction commit 後逐一刪檔。
- 檔案刪除失敗：不 rollback DB；每個失敗以結構化 log 記 `(room_id, asset_id, storage_key, error)` 並繼續刪其餘檔案；回傳值擴充 `assets_deleted`／`assets_cleanup_failed` 與失敗 `storage_key` 清單，讓呼叫端可重試。以 A1a 實際 schema 為準，不新增表。
- `tests/test_p6a_room_assets.py` 追加：hard delete 後 row 與檔案皆消失；以 monkeypatch 讓 `storage.delete` 對其中一檔拋錯 → DB row 仍消失、其他檔案已刪、失敗定位資訊可查、回傳計數正確。

## 對應契約

設計 §A.1「Room Hard Delete 必須 cascade…」；測試 A.4。

## 前置

A1b storage／repository。

## 驗收

- `pytest tests/test_p6a_room_assets.py tests/test_code_quality_gate.py`＋既有 Room hard delete 測試（cwd `apps/server`）全綠；既有測試零修改。

## 紀錄

（派工後補）
