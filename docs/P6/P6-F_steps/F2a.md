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

（待填）
