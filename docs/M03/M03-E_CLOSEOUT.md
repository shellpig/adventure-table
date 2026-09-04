# M03-E Closeout Checklist

M03-E — Standalone Packaging & Launcher closeout scope：

- [x] **E.0 Minimal frozen smoke gate**：真的 freeze 出 exe 才驗，沒有以 `python -m app.launcher` 代替。CI 的 `frozen-smoke` job 於 `windows-latest` 用 `standalone.spec` 產出 one-folder 產物後跑 `scripts/smoke_standalone.py`；本機亦以 `scripts/build-standalone.cmd --version verify-local --skip-frontend` 產出完整產物再跑同一支腳本，結果為 `Standalone smoke passed.`。腳本斷言：exe 同層出現 `adventure-table.sqlite3`、`alembic_version` 等於當時 head（`_migration_head()` 由 `alembic/versions/*.py` 的 revision 圖推得，非硬編）、`GET /api/meta/capabilities` 回 200 且 `channel="standalone"`、`GET /api/characters` 回空清單、stdout / stderr 全程不含 `postgresql` 或 `psycopg`、process 可正常收掉。最小 spec 未另存一份，直接就是 E.7 的正式 spec。
- [x] **E.1 Neutral shared modules**：`app/api/error_handlers.py` 提供 `register_exception_handlers(app)`，`app.main` 與 `app.standalone` 各自呼叫；`app/api/meta.py` 只有 `create_meta_router(channel)` factory，module scope 沒有 `router` / `meta_router` global；`app/api/spa.py` 的 catch-all 明確排除 `/api/` prefix。`app.standalone` 不 import `app.main`。證據：`tests/test_m03e_error_handlers_shared.py`、`tests/test_m03e_meta_router_factory.py`。
- [x] **E.2 單機版 entry point**：`app/standalone.py` 以 `docs_url=None` / `redoc_url=None` / `openapi_url=None` 組裝，只掛 reference / content_presentation / characters / character_builder / `create_meta_router("standalone")` 五個 router，掛 `/assets` StaticFiles 與 SPA history fallback，startup 不呼叫 alembic。啟動硬守衛 `_require_sqlite()` 於組裝時檢查 `resolve_database_url()`，非 SQLite 即以帶實際 URL 與環境變數名的 `RuntimeError` 中止，且該守衛不需 freeze、不需 CI 就測得到。證據：`tests/test_m03e_standalone_composition.py`、`tests/test_m03e_database_path.py::test_standalone_guard_rejects_postgres_before_connection_attempt`。
- [x] **E.3 Capability endpoint**：`GET /api/meta/capabilities` 於 web 回 `channel="web"`、standalone 回 `channel="standalone"`，capability flag 於 M03 期間 `character_builder` / `character_import_export` 為 true、其餘為 false。證據：`tests/test_m03e_capabilities.py`。
- [x] **E.4 / E.5 Launcher 與資料檔路徑**：`app/launcher.py` 依序做 pin database path → 決定 content / SPA root → `alembic upgrade head` → 選 8000–8100 第一個可用 port → 起 uvicorn 載 `app.standalone:app` → 等 ready → 開瀏覽器 → 印 banner；Alembic Config 手動指向 bundle 內 `alembic.ini`，`_alembic_script_location()` 明確區分 repo（`apps/server/alembic/`）與 frozen（`_MEIPASS/alembic/`）兩種 layout，不倚賴 CWD。解析順序 env → `settings.database_path` → frozen `<exe_dir>` → launcher `<cwd>` 全部由 `paths.resolve_database_path()` 一手實作。證據：`tests/test_m03e_launcher_headless.py`、`tests/test_m03e_database_path.py`、`tests/test_m03e_alembic_bundle_ready.py`。
- [x] **E.6 Content root / SPA root**：`resolve_spa_root()` 順序與 content root 一致（env → `<exe_dir>/web` → frozen fallback `_MEIPASS/web` → dev `None`）。`data/` 與 `web/` 由 build 腳本複製到執行檔同層，bundle 內不放第二份。
- [x] **E.7 PyInstaller spec**：`apps/server/pyinstaller/standalone.spec` 為 one-folder、`console=True`、`excludes` 含 `psycopg` / `psycopg_binary` / `psycopg_c`，`datas` 含 `alembic/alembic.ini`、`alembic/env.py`、`alembic/script.py.mako` 與 `alembic/versions/*.py`，且不含 `data/` 或 `web/`；`hiddenimports` 明列 `app.standalone`（uvicorn 以字串載入）與 alembic / pydantic submodules。證據：`tests/test_m03e_pyinstaller_spec.py`。
- [x] **E.8 Build 腳本**：`scripts/build-standalone.cmd` 建臨時 venv、只裝 `standalone` extra（不裝 `web`）、build 前端、跑 spec、複製 `data/` 與 `apps/web/dist/`、複製 `LICENSE.txt` 與雙語 README、寫 `build-id.txt`、`Compress-Archive` 成 zip；`--dry-run` / `--skip-frontend` / `--version <tag>` 皆可用，且冪等（每次先清 venv / build / dist）。證據：`tests/test_m03e_build_script.py`，CI `windows-build-contract` job 跑 `--dry-run`。
- [x] **E.9 前端 build 一致性與 capability 呈現**：standalone 掛的是與網頁版同一份 `npm run build` 產物，沒有 feature flag、沒有 build-time 分支。SPA boot 讀 `/api/meta/capabilities`（`CapabilityProvider`），capability 為 false 的 route 由 `protectedCapabilityForPath()` 攔下並 render `CapabilityDisabledPage`，`zh-TW` / `en` 兩語文案同批交付。證據：`apps/web/src/features/capabilities/*.test.{ts,tsx}`、`apps/web/src/App.test.tsx`。
- [x] **E.10 啟動可觀察行為（開發機 frozen 執行）**：console 保持開啟並顯示 build id、資料檔 / content root / SPA root 三條實際絕對路徑、監聽 URL 與結束方式；Landing SPA 於 `channel="standalone"` 且 `database_path` 非 null 時顯示同一條絕對路徑。手動打 `/characters/<uuid>` 回 index.html、`/api/nope` 回 404，`/api/rules/content/races?locale=zh-TW` 由 exe 同層 `data/` 正常供應。
- [ ] **測試指南 E.9 手動冷啟動（乾淨 Windows 11）尚未執行**。該條要求在一台未裝 Python / Node / Docker 的機器上解壓 zip、雙擊 exe 並逐項確認（含建立 Lv1 Fighter、匯出 JSON、關分頁不停 server、Ctrl+C 停止）。本次是在開發機上對 frozen 產物做等價的 HTTP / 路徑 / banner 驗證，**不能取代該條**。這是 M03-E 唯一未取得的驗收證據。

## 交付內容

| 檔案 | 內容 |
|---|---|
| `apps/server/app/standalone.py` | 單機版 FastAPI 組裝與 SQLite 啟動守衛 |
| `apps/server/app/launcher.py` | PyInstaller entry：pin DB path、migration、free port、uvicorn、browser、banner |
| `apps/server/app/api/meta.py` | `create_meta_router(channel)` factory 與 capability model |
| `apps/server/app/api/error_handlers.py` | 由 web / standalone 共用的 exception handler 註冊 |
| `apps/server/app/api/spa.py` | `/assets` 掛載與排除 `/api/` 的 SPA history fallback |
| `apps/server/app/api/__init__.py` | `characters_router` 組合 core + export + import |
| `apps/server/app/main.py` | 改用 neutral shared modules 與 `create_meta_router("web")` |
| `apps/server/pyinstaller/standalone.spec` | one-folder spec、alembic datas、psycopg excludes |
| `apps/server/pyproject.toml` | 新增 `standalone` extra（`pyinstaller`） |
| `scripts/build-standalone.cmd` | Windows 打包腳本 |
| `scripts/smoke_standalone.py` | frozen 產物 smoke（E.0，M03-F 沿用） |
| `LICENSE.txt`、`README-standalone.en.txt`、`README-standalone.zh-TW.txt` | 發行附帶文件（含 SRD 5.1 CC BY 4.0 attribution） |
| `apps/web/src/features/capabilities/*` | `CapabilityProvider`、`CapabilityDisabledPage`、capability API / routes / 雙語 copy |
| `apps/web/src/App.tsx`、`main.tsx` | capability 邊界接線與 Landing 資料檔路徑提示 |
| `.github/workflows/m03e-non-e2e.yml`、`.github/m03e-non-e2e.trigger` | backend / frontend / frozen-smoke / build-contract / compose-config 五個 job |
| `apps/server/tests/test_m03e_*.py`、`tests/m03e_support.py` | E.1～E.8 契約測試 |

## 兩項超出實作規格文字、刻意採用的實作決定

1. **`characters_router` 改為組合 router**（`app/api/__init__.py`）。E.2 只列 `characters_router`，但 M03-B / M03-C 的 export / import 原本是 `app.main` 另外掛的兩個 router；若照字面只掛五個，standalone 就沒有匯入匯出，與 `character_import_export: true` 直接矛盾。因此把 core + export + import 併入單一 `characters_router`，web 與 standalone 掛到的角色 surface 完全相同，router 數也仍是五個。舊的 `character_export_router` / `character_import_router` 名稱保留為 public alias。
2. **capability payload 多一個 `database_path`**（`app/api/meta.py`）。E.3 列的 JSON 沒有這個 key，但 E.10 要求 Landing SPA 顯示資料檔絕對路徑，而 SPA 沒有其他管道拿到它。web channel 一律回 `null`，只有 standalone 回實際路徑。此為 E.3「只新增 key、不改變舊 key 語意」允許的擴充。

## 驗收方式與分層 gate

M03-E 的 diff 同時動到 backend 與 `apps/web`（capability 呈現改了 Landing 與 route 攔截），依 `AGENTS.md` 分層 gate 屬「動到 `apps/web`」，Subphase 關門需跑對應 E2E。實際執行：

- 全套 backend `pytest`：綠。
- 前端 Vitest 26 files / 124 tests、`npm run build`：綠。
- `docker compose config`：通過。
- 全套 E2E（`npm run test:e2e:docker`）：**97 passed (6.4m)**，含 `app-shell`、`m02a` / `m02b` / `m02h` 等 Landing 相關 spec 與 `m03b-character-export` / `m03c-character-import`；`e2e-docker.mjs` 拿掉 `xge` 的第二輪 M03-C import 子集另 **7 passed**。無失敗、無 flaky。
- E.0 frozen smoke：本機真實 freeze 後綠（詳見上方 E.0）。

## 驗證過程中修正的兩個問題

1. **`launcher._prepare_database_path()` 原本先 `os.environ.setdefault()` 再解析**，會讓透過 `.env` 設定的 `settings.database_path` 被自己塞進去的預設值蓋掉，繞過 E.5 解析順序的第二順位。改為「先 `resolve_database_path()`、再把解析出的絕對路徑寫回環境變數釘死」，並移除因此變成孤兒的 `_resolve_default_database_path()`。回歸鎖：`tests/test_m03e_launcher_headless.py::test_launcher_keeps_settings_database_path_when_env_var_is_absent`。`docs/M03/開發設計方針.md` 的 launcher 範例與環境變數表原本寫的正是這個有問題的順序，已一併更正。
2. **`test_m03e_build_script.py` 的 dry-run 副作用斷言用 `not (REPO_ROOT / ".standalone-venv").exists()`**，任何跑過一次真實 build 又沒清乾淨的開發機都會紅，而且抓不到真正危險的回歸——build 腳本的 `rmdir /s /q` 就排在 dry-run 分支之後，一旦順序被改動，dry-run 會刪掉既有 build。改為對 `.standalone-venv`、`build/standalone`、`dist/adventure-table-standalone` 三條路徑做前後快照比對，同時涵蓋「不建立」與「不刪除」。

## M03-E 未涵蓋（依實作規格「本 Subphase 不要求」）

- 不做 code signing、Windows installer、自動更新、system tray、隱藏 console。
- 不做 macOS / Linux build。
- 不做 shutdown / heartbeat：關閉瀏覽器分頁不停 server 是刻意行為，已寫入雙語 README。
- CI 上的正式 release build 與 import boundary test 屬 M03-F。

## 已知的覆蓋缺口與待決建議（留給後續 Subphase）

1. **測試指南 E.9 乾淨 Windows 11 冷啟動未執行**（見上方未打勾項）。M03-F 會在 CI 產出正式 release artifact，屆時一併補這份人工證據最自然。
2. **`/docs` / `/redoc` / `/openapi.json` 只由 `*_url is None` 與 openapi paths 白名單間接保證**。測試指南 E.3 寫的是「斷言中對這三個路徑明確不存在」，目前沒有對它們實際發 request 驗 404。建議 M03-F 的 import boundary test 一併補上。
3. **Launcher 的 `KeyboardInterrupt` 回收路徑沒有測試**。測試指南 E.5 列了「Ctrl+C 訊號可讓 launcher 回收」，headless test 只覆蓋 `server.should_exit` 這條正常關閉路徑。
4. **`Settings()` 的 import-time 快照仍會跨測試污染**（M03-D 已記錄，尚未處理）。`app/config.py` 於 import 當下建立 `settings`；若首次 import 發生在已 `monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", ...)` 的測試中，`settings.database_path` 會被永久釘在該 tmp 路徑。建議於 `tests/conftest.py` 加 session autouse fixture 把它釘成 `None`，不動 runtime。
5. **M03-D 遺留建議第 3 點已於本 Subphase 處理**：`create_database_engine()` 預設走 `resolve_database_url()` 這條 SSOT 現在有 `tests/test_m03e_database_path.py::test_shared_engine_factory_defaults_to_database_resolver` 直接斷言。第 2 點（`seed_p0_fighter_wizard.py` 仍直接 `create_engine(settings.database_url)`）維持未處理，只影響 dev seed 腳本。
