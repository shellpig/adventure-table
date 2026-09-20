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

- **起始**：2026-09-20，worker agy（`Gemini 3.8 Flash (High)`），1 回合 6 分 19 秒，prompt `C:/_work/AI_Work/Tools/agy-runs/agy-p6a-A2b.prompt.txt`，conversation `a39e0246-2487-4e2c-afc6-dbca54ba8418`。
- **交付**：repository `delete_definition`／`is_attached`（EXISTS `campaign_adventure_links`）／`StoredAdventureEntryAsset`＋`insert_entry_asset`／`delete_entry_asset`／`list_entry_assets`（join 一次取整個 Adventure）／`next_entry_asset_sort_order`；schemas `AdventureEntryAssetRole`／`AdventureEntryAsset`／`AdventureEntryAssetLink`、`AdventureEntry.assets`、`AdventureAttachedError`／`AdventureStatusError`／`AdventureEntryAssetNotFoundError`；service `finalize`（只 draft）／`archive`（idempotent）／`delete_definition`（attached → 409 零副作用）／`link_entry_asset`（同 Room、role↔kind 檢查、重複拒絕）／`unlink_entry_asset`／`_resolve_entry_assets`（每次 get／list 各一個 query，無 N+1）；`AdventureService` 改為 `(repository, asset_repository)`，`test_p6a_adventure_authoring.py` 只改 fixture 一行＋import；`api/rooms/adventures.py` 17 條 route（reorder 宣告在 `/{entry_id}` 之前；**Forbidden 對映 404 `adventure_not_found`**，不回 403）；`dependencies.get_adventure_service`；`tests/test_p6a_adventure_api.py` 10 個測試。
- **指揮者審核修正**：
  - `_resolve_entry_assets` 內逐欄重建 `RoomAsset`，複製了 A1b `room_assets/service.py::_to_view` → 把後者改為公開 `room_asset_view()` 並重用；FK 為 RESTRICT，去掉「asset 找不到就略過」的防禦分支。
  - `link_entry_asset` 的 `elif role == "attachment": pass` 死分支 → 收斂為兩條 guard。
  - `next_entry_asset_sort_order`／`next_sort_order` 的 `int(val if val is not None else 0)`——`coalesce` 已保證非 None → `int(val)`。
  - `dependencies.py` import 排序（`app.config`、`app.persistence.adventures`）。
- **測試**：`pytest tests/test_p6a_adventure_api.py tests/test_p6a_adventure_authoring.py tests/test_p6a_room_assets.py tests/test_m03_import_boundary.py tests/test_code_quality_gate.py` 59 passed；全套 backend 1880 passed／65 skipped（PG 測試未帶 env）。
- **未解問題／下一步**：A2a 留下的 `KNOWN_ENTRY_KINDS` 重複列舉未動（本步未碰 payloads.py）；A3。
