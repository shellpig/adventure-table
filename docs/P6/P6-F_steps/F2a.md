# F2a — Adventure authoring 的共用 transaction 接線

## Scope

- 讓既有 `AdventureService.create_definition`、`create_entry`、`link_entry_asset`、`finalize` 可在呼叫端提供的**同一個 SQLAlchemy `Connection`／transaction** 內執行；未提供時沿用目前公開 API 行為。F2b 會在 Import transaction 中依序呼叫這四個既有 authoring intent。
- 只把上述 intent 實際用到的 Adventure／Room Asset repository 讀寫接到傳入 connection。`_definition_or_404`、`_writable_definition`、parent 驗證、asset 解析等內部讀取也必須看見同一 transaction 的未提交資料；不可以另開 engine connection／commit。
- 不複製 P6-A authoring 的驗證與建立邏輯，不新增另一套 raw row authoring facade。既有 route／其他 caller 不傳 connection 時行為與簽名相容。跨 Room asset、parent、權限檢查維持原本語意。
- 本步不改 `AdventureImportService`、不做 finalize orchestration／idempotency／blocking gate（F2b），不改 route、MCP、UI 或 migration。

## 契約與輸入

- 原 F2 契約仍由 `docs/P6/實作規格.md`「P6-F」、`開發設計方針.md`「P6-F／Finalize transaction」、`測試指南.md`「P6-F／F.4」承擔；F2a 只交付其共用 transaction 前置能力。前置 F1。
- 修改前核對 `app/domain/adventures/service.py` 四個 public method 與所呼叫 private helper、`app/persistence/adventures/repository.py`、`app/persistence/room_assets/repository.py` 最新簽名；測試沿用 P6-A authoring fixture 模式。F2b 將利用此步 API，勿提前建立 Import 專用分支。

## 驗收

- `tests/test_p6f_authoring_transaction.py`：同一外部 transaction 中建立 Definition → parent／child entries → link asset → finalize，所有中途讀取可見未提交資料；commit 後可由新 connection 讀回。
- 在上述順序中途故意拋錯，外部 transaction rollback 後沒有 Definition、entries、links；跨 Room／不存在的 asset 也拒絕並 rollback。
- 未傳 connection 的既有 P6-A authoring 測試仍通過；MEMBER／跨 Room authoring 拒絕、零副作用。使用 real repository／service，不用 test-only 假實作。

## 完成紀錄

- **起始與 worker**：2026-09-23，agy（Gemini 3.8 Flash High），同一對話 2 回合；CLI 回報約 417 秒與 944 秒（第二回合只精簡測試）。
- **交付**：`AdventureService.create_definition`／`create_entry`／`link_entry_asset`／`finalize` 新增 keyword-only `connection: Connection | None = None`，並傳入 `_definition_or_404`、`_writable_definition`、`_validate_parent`、`_resolve_entry_assets`。`AdventureRepository` 的 `insert_definition`、`get_definition`、`set_status`、`insert_entry`、`get_entry`、`next_sort_order`、`insert_entry_asset`、`list_entry_assets`、`next_entry_asset_sort_order`，以及 `RoomAssetRepository.get`／`list_for_room` 同樣接受 optional connection；有傳時只在該 connection 執行，不另開 connection、不 commit。未傳時行為不變。新增 `tests/test_p6f_authoring_transaction.py`（6 個 test function、9 cases）。
- **指揮者審核修正**：第一回合後，`test_p6a_adventure_api.py::test_entry_list_embeds_assets_without_n_plus_one` 的 counting monkeypatch 不接受 `connection` keyword 而失敗；並移除 agy 對 `RoomAssetRepository.insert` 多加的 connection 參數（F2a 不需要）。先前為此在 `_resolve_entry_assets` 加的「`connection is None` 時省略 keyword」分支是 production 遷就測試替身，已改為讓 monkeypatch 轉傳 `connection`，production 無條件呼叫 `list_for_room(room_id, connection=connection)`。要求 agy 把測試從 540 行精簡到 366 行（parametrize owner／dm 與 cross-room／missing）。
- **觀察（未修）**：兩個 repository 的 11 個 method 都是「有 connection 直接用，否則自開」同一套分支，query 各寫一次；`RoomAssetRepository` 另有既存的 `insert_in_transaction(connection, stored)` 慣例，兩種並存。code quality gate 未擋，F2b 若需再加 connection-aware method 時再評估收斂。
- **測試與證據**：指揮者在 `apps/server` 用專案 venv 執行 `pytest tests/test_p6f_authoring_transaction.py tests/test_p6a_adventure_authoring.py tests/test_p6a_adventure_api.py tests/test_p6a_room_assets.py tests/test_p6f_review_state.py tests/test_p6e_import_service.py tests/test_p6e_import_persistence.py tests/test_m03_import_boundary.py tests/test_code_quality_gate.py`，**135 passed**；全部 `tests/test_p6*.py` 577 個 0 failed（16 skipped）；`git diff --check` 通過。驗證 code commit：`6f50cfcd`。
- **未解與下一步**：本步無未解問題。F2b 以這四個 intent 的 `connection=` 在 Import transaction 內組合 finalize。
