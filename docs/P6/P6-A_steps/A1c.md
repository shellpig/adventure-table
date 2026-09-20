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

- **起始**：2026-09-20，worker agy（`Gemini 3.8 Flash (High)`），1 回合 4 分 50 秒，prompt `C:/_work/AI_Work/Tools/agy-runs/agy-p6a-A1c.prompt.txt`，conversation `1ec66e88-0648-4546-a876-a51366912a0b`。
- **交付**：`workspace.hard_delete_room` 同一 transaction 內先收集 `room_assets.storage_key`，再依 RESTRICT 方向刪 `campaign_adventure_links` → `adventure_entry_assets` → `adventure_entries` → `adventure_definitions` → `room_assets`，其餘順序不變；`LegacyWorkspaceCounts.asset_storage_keys`（預設空 tuple，既有建構不受影響）；persistence 不碰檔案。`RoomAssetService.purge_storage_keys(room_id, keys) -> RoomAssetCleanupReport(deleted, failed)`：逐檔刪、`OSError` 記一行 ERROR log（含 room_id／storage_key／錯誤）後繼續；`access.hard_delete_room` route 於 transaction commit 後呼叫 purge，仍回 204（DB 為真值，失敗由 log＋report 定位）。`test_p6a_room_assets.py` 追加 3 個測試。
- **指揮者審核修正**：
  - 三個新測試各自手動設定／還原 `app.state.character_engine`／`adventure_service`／`room_workspace_service`（`try/finally` ＋ `except AttributeError` 吞 `KeyError`），單模組過、全套時被其他模組留下的 stale `room_workspace_service`（指向已 dispose 的 engine）打爆 → 改由 fixture 統一 pin 三個 state 並在 teardown 還原先前值，三個測試扁平化。
  - caplog 在全套中抓不到 log：alembic migration 測試在同一 worker 執行 `fileConfig` 會 disable 既有 logger → 測試前顯式 `logger.disabled = False` 並註解原因；log 斷言收斂為訊息含 room_id 與 storage_key（我先移除了 `extra=` 重複欄位）。
  - `hard_delete_room` 兩段 `if adventure_ids:` 被 storage_key select 切開 → 合併成一段並加註解；四行從 prompt 貼進來的超長註解改短。
- **測試**：focused＋P2 hard delete regression 31 passed；全套 backend 1892 passed／65 skipped，連跑兩次順序穩定。
- **未解問題／下一步**：無；A4a。
