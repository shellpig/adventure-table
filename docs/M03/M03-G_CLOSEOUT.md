# M03-G Closeout Checklist

M03-G — Full M03 Integration & Closeout closeout scope：

- [x] **G.1 End-to-end round trip**：實作規格列的六條路徑全部跑過並保留自動化證據。以 `tests/m03g_support.py` 的 `standalone_client()` 起真正的 `app.standalone`（先 `launcher.run_migrations()` 建 file-backed SQLite，再 `importlib.import_module("app.standalone")`），缺 pack 一律以 `Settings.enabled_content_packs` 注入 subset，不刪 pack 目錄。逐條對應見下方「G.1 六條路徑的證據對照」。
- [x] **G.2 網頁版功能不回歸**：全套 backend `pytest` exit 0；前端 Vitest 26 files / 124 tests 綠；`npm run build` 綠；全套 E2E `npm run test:e2e:docker` 第一輪 **97 passed / 3 skipped（6.8m）**、`e2e-docker.mjs` 拿掉 `xge` 的第二輪 **7 passed（5.8s）**，`apps/web/test-results/.last-run.json` 為 `{"status": "passed", "failedTests": []}`。3 個 skip 中兩個是 `m03c-character-import.spec.ts:74` / `:85`（設計上第一輪跳過、第二輪執行，第二輪皆通過），第三個是 `m01j-subclass-expansion.spec.ts:531` 的 `test.fixme()`，即已記錄的 KI-M01J-001。
- [x] **G.3 單機版可下載產物（zip 部分）**：本機 `scripts\build-standalone.cmd --version m03` 產出 `dist\adventure-table-standalone-m03.zip`（23,417,795 bytes），內含 `adventure-table.exe`（12,261,851 bytes）、`_internal\`、`data\`、`web\`、`LICENSE.txt`、`README-standalone.zh-TW.txt` / `.en.txt`、`build-id.txt = m03`。將 zip 解壓到一個全新空資料夾後跑 `scripts/smoke_standalone.py`：SQLite 建在 exe 同層、`alembic_version` 等於當時 Alembic head、`/api/meta/capabilities` 回 `channel="standalone"`、`/api/characters` 為空、stdout/stderr 全程不含 `postgresql` / `psycopg`。
- [ ] **G.3 的乾淨 Windows 11 冷啟動（吸收自測試指南 E.9）仍未執行**。本次是在開發機上以「乾淨解壓資料夾 + 清空 `ADVENTURE_TABLE_DATABASE_PATH` 的環境」做等價驗證，並非契約要求的未裝 Python / Node / Docker 的機器。zip 已備妥，這條隨時可補。詳見下方「未結清的驗收項」。
- [x] **G.4 M03 已知限制記錄**：見下方「M03 已知限制」。
- [x] **G.5 P2 依賴的界線正式生效**：`test_m03_import_boundary.py`（含 `app.standalone` 不可達 `app.main`）、`test_m03_standalone_composition.py`、`test_m03f_workflow_contract.py` 於全套 backend pytest 中綠；`.github/workflows/m03g-non-e2e.yml` 以 backend / frontend / windows-standalone / compose-config 四個 job 覆蓋同一組命令。capability endpoint 於 web 與 standalone 兩個 entry 上分別回 `channel="web"` / `channel="standalone"`，由 composition test 靜態與動態雙鎖。SSOT 更新見「交付內容」。
- [x] **G.6 Localization 同步**：本 Subphase 未新增任何 user-visible UI copy、rules presentation field 或 error message，因此無新增待譯字串。既有兩語資產維持完整：`README-standalone.zh-TW.txt` / `README-standalone.en.txt` 均隨 zip 出貨；匯出／匯入 UI、20 個 rejection code、`capability_disabled` 頁面的兩語覆蓋由 M03-B / C / E 交付，並由前端兩語 parity 與 hardcoded copy scan 測試、`m02h-bilingual-site-smoke.spec.ts`、`m03b-character-export.spec.ts` 的 `export labels are complete in English and zh-TW`、`m03c-character-import.spec.ts` 的 `import rejection messages are localized in English and zh-TW` 在本次全套 E2E 中一併驗過。
- [x] **G.7 已知問題**：M03 期間未發現需要新增條目的問題。既有 KI-P1D-001 / KI-M01J-001 / KI-ENV-001 狀態不變，本次全套 E2E 的兩個 M03-C skip 是設計行為而非缺陷，不入 `已知問題.md`。

## G.1 六條路徑的證據對照

| 實作規格路徑 | 測試 |
|---|---|
| 1. W → S 完整 | `tests/test_m03g_roundtrip.py::test_web_to_standalone_roundtrip_preserves_live_state_and_history` |
| 2. S → W 完整 | `tests/test_m03g_roundtrip.py::test_standalone_to_web_roundtrip_preserves_payload` |
| 3. W → S 缺 pack | `tests/test_m03g_import_edges.py::test_missing_xge_lands_as_persisted_builder_draft` |
| 4. State-only 缺 ref | `tests/test_m03g_import_edges.py::test_state_only_missing_ref_lands_as_history_loss_draft` |
| 5. 重複匯入偵測 | `tests/test_m03g_import_edges.py::test_duplicate_hint_does_not_block_second_character` |
| 6. Legacy character 缺 pack 拒絕 | `tests/test_m03g_import_edges.py::test_legacy_missing_pack_rejection_is_atomic_in_standalone_sqlite` |

第 1 條的斷言涵蓋 M03-G 想證明的完整往返：網頁版建 Lv5 Multiclass（`fixture_multiclass_mixed.json`）後先改動 live state（HP −3、prepared spell、新增一件不在 Starting Equipment 的 inventory item），匯出後於單機版 dry-run 得 `landing_mode="character"` 且 `unresolved_ref_count == 0`，commit 後由單機版再匯出一次，斷言 `payload` 與網頁版匯出**完全相等**、`envelope.source_app.channel` 各自為 `web` / `standalone`、version chain 為 `[1, 2]`。第 6 條在拒絕前後比對 `table_counts(engine)`，證明零副作用。

## 交付內容

| 檔案 | 內容 |
|---|---|
| `apps/server/tests/m03g_support.py` | 以真 launcher migration + file-backed SQLite 起 `app.standalone` 的 context manager，與 export / commit 輔助 |
| `apps/server/tests/test_m03g_roundtrip.py` | G.1 第 1、2 條：W ↔ S 完整往返與 payload 相等性 |
| `apps/server/tests/test_m03g_import_edges.py` | G.1 第 3～6 條：缺 pack、state-only 缺 ref、重複匯入、legacy 拒絕原子性 |
| `apps/server/tests/test_m03g_standalone_runtime.py` | frozen runtime 行為：`/docs` `/redoc` `/openapi.json` 落到 SPA fallback；launcher `KeyboardInterrupt` 回收路徑 |
| `.github/workflows/m03g-non-e2e.yml`、`.github/m03g-non-e2e.trigger` | backend / frontend / windows-standalone / compose-config 四個 job 的 review-gated 回歸 |
| `docs/M03/M03-G_CLOSEOUT.md` | 本檔 |
| `PROJECT_BRIEF.md` | M03 closeout 與 Subphase 進度更新 |
| `AGENTS.md` | 補上 M03 已交付與 standalone boundary 的常駐約束 |
| `規格企劃.md` 第五章 | Character Workshop 段補「單機版已出貨」現況 |

本 Subphase **未新增任何產品程式碼**，diff 僅涵蓋 `apps/server/tests/`、`.github/` 與文件。

## 順帶結清的 M03-E 遺留項

`docs/M03/M03-E_CLOSEOUT.md` 留下的四點中，第 2、3 點於本 Subphase 結清：

- **第 2 點**（`/docs` / `/redoc` / `/openapi.json` 只由 `*_url is None` 間接保證）→ `test_standalone_api_documentation_is_disabled_behind_spa_fallback` 對三個路徑實際發 request，斷言回 200 的 SPA HTML 且不含 `Swagger UI` / `ReDoc`。**注意這條的正確期望是「落到 SPA fallback」而非 404**：`/docs` 不帶 `/api/` prefix，依 M03-E 的 SPA history fallback 契約本來就該回 SPA。M03-E closeout 當時寫的「驗 404」是對契約的誤述，本次以實測修正。
- **第 3 點**（launcher `KeyboardInterrupt` 回收路徑無測試）→ `test_launcher_keyboard_interrupt_requests_shutdown_and_joins_server` 以 fake uvicorn Config / Server 與會在第一次 `join(0.5)` 丟 `KeyboardInterrupt` 的 fake thread，斷言 `server.should_exit` 被設為 `True`、thread 名稱為 `adventure-table-server`、join timeout 序列為 `[0.5, 10.0]`、最終 thread 不再 alive、`main()` 回 0。

第 1 點（E.9 冷啟動）與第 4 點（`Settings()` import-time 快照跨測試污染，`tests/conftest.py` 仍未加 session autouse fixture）維持未結清。

## M03 已知限制

1. **Character JSON schema 於 M03 期間仍是 `unstable`**，`schema_status` 鎖為 `"unstable"`，要到 P2 才 lock。這個版本匯出的 JSON 不保證未來版本讀得進去；可靠的原始資料是 SQLite 檔本身。
2. **Windows-only**，且是 portable zip 而非 installer；沒有自動更新、沒有 code signing、沒有 SmartScreen reputation。
3. **Draft 落地會捨棄舊版 chain**（見實作規格 3.3、C.6）。`landing_mode` 為 `draft` 或 `draft_with_history_loss` 時，補洞後 Confirm 產生的是新的 Version 1，原本的 version chain 與 Current State 不會進來。
4. **Legacy 角色（`builder_provenance = NULL`）於缺 pack 情境無法匯入**，一律回 400 `draft_reconstruction_unavailable`。這類角色只能在 pack 齊全的環境匯入。
5. **匯入不做合併**。同一份 export 匯入兩次會產生兩個獨立角色；`duplicate_hint` 只提示，不阻擋。
6. **單機版無帳號、無同步、無 Room / Campaign / Session / Seat / Combat / Timeline / AI Actor**。
7. **關閉瀏覽器分頁不會停 server**（刻意行為）。要整個關閉必須在 console 按 Ctrl+C 或關掉 console 視窗；`README-standalone` 兩語都寫明。
8. **port 每次啟動動態挑選**，重開後網址會變，以 console 印出的 listening URL 為準。
9. **`Settings()` 的 import-time 快照仍會跨測試污染**（M03-D 記錄、M03-E 重申，至今未處理）。只影響測試撰寫方式，不影響 runtime。
10. **standalone import boundary 的 forbidden regex 依賴字根命名**。P2 引入多人模組時若命名不落在 `room` / `session` / `seat` / `campaign` / `party_roster`（含複數）內，gate 會靜默失效；P2 第一個 Subphase 必須同步擴充該 regex 與 `EXACT_PROTECTED_MODULES`。

## 未結清的驗收項

**測試指南 E.9 / G.3 的乾淨 Windows 11 冷啟動。** 這條從 M03-E 順延到 M03-F 再順延到 M03-G，三次都因為沒有一台未裝 Python / Node / Docker 的機器而未取得。目前 `dist\adventure-table-standalone-m03.zip` 已備妥，補這條只需要把 zip 複製到那樣一台機器、解壓、雙擊，跑一次 G.1.a 的匯入即可。

**在此明確記錄：M03 於本 Subphase 關門時，這條驗收項是未取得證據的狀態**，不因 M03 宣告 closeout 而視為通過。取得後請直接補在本檔。

## G.1 人工 UI 流程以自動化取代的理由

測試指南 G.1 原本要求六條流程在「最新網頁版 + 最新單機版 zip」上人工執行並保留截圖／錄影。本次改以 API 層 pytest 取得等價證據，理由：

- 六條路徑要驗的是 import pipeline 的判定結果（`landing_mode`、unresolved 的 origin 與 pack、duplicate hint、拒絕碼與原子性）與往返後的 payload 相等性，這些都是 server-authoritative 的判定，UI 只是呈現層。
- 呈現層本身已有獨立覆蓋：`m03b-character-export.spec.ts`（6 條）與 `m03c-character-import.spec.ts`（7 條，含 xge-less 第二輪）在本次全套 E2E 中綠，涵蓋預覽數字、history-loss 二次確認、duplicate 顯示、兩語 rejection 訊息與真實下載檔名。
- 單機版 runtime 的真實性由 `standalone_client()` 起真正的 `app.standalone` + 真 migration + file-backed SQLite 保證，並非 mock。

**唯一沒有被這個取代涵蓋的是 frozen exe 上的人工操作**，也就是上面那條未結清的 E.9。

## 驗收方式與分層 gate

M03-G 是 Phase 關門，依 `AGENTS.md` 分層 gate 跑全套。實際執行：

- 全套 backend `pytest`（`.venv\Scripts\python.exe`）：綠（exit 0）。
- M03-G focused 加 M03 boundary / composition / workflow contract：**23 passed**。
- 前端 Vitest：**26 files / 124 tests passed**。
- `npm run build`：綠。
- `docker compose config`：通過。
- 全套 E2E `npm run test:e2e:docker`：第一輪 **97 passed / 3 skipped（6.8m）**，xge-less 第二輪 **7 passed（5.8s）**，script exit code 0。
- 本機 frozen build 加乾淨解壓資料夾 smoke：綠（見 G.3）。
- `.github/workflows/m03g-non-e2e.yml` 的 CI run 結果請於 GitHub 上確認；本機無 `gh` CLI，未於本檔記錄 run id。

## M03-G 未涵蓋（依實作規格「本 Subphase 不要求」）

- 不做 M01 之外的規則資料新增。
- 不做 P2 schema 決策。
- 不做 code signing / installer。
- 不做 macOS / Linux 平台擴充。

## 留給後續 Phase 的建議

1. **補 E.9 冷啟動**（見上）。
2. **`Settings()` import-time 快照污染**：建議於 `apps/server/tests/conftest.py` 加 session autouse fixture 把 `settings.database_path` 釘成 `None`，不動 runtime。
3. **P2 第一個 Subphase 必須擴充 import boundary 的 forbidden regex 與 `EXACT_PROTECTED_MODULES`**，否則新命名的多人模組會讓 gate 靜默放行。
4. **P2 lock JSON schema 時**，需一併決定既有 `unstable` 匯出檔的處置（拒絕、或提供一次性 upgrade path）。
5. **`seed_p0_fighter_wizard.py` 仍直接 `create_engine(settings.database_url)`**（M03-E 遺留），只影響 dev seed 腳本，未收斂到 `create_database_engine()`。
