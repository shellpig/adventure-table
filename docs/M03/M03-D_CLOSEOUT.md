# M03-D Closeout Checklist

M03-D — SQLite Migration Chain Gate & FK PRAGMA closeout scope：

- [x] **D.1 SQLite migration 綠燈**：整條 Alembic 鏈（`0001` ～ `0008_m03c_import_records`）在乾淨的空 SQLite 檔上 `upgrade head` → `downgrade base` → 再 `upgrade head` 全綠，涵蓋 M03-B 的 `builder_provenance` 與 M03-C 的 `character_import_records`。downgrade 後只剩 `alembic_version` 且 row 數為 0——`alembic_version` 由 Alembic 自身管理、downgrade 不會 drop 它，因此契約寫的是「除它以外無殘留」而非「tables 全空」。證據：`tests/test_m03d_migration_sqlite.py::test_sqlite_alembic_upgrade_downgrade_upgrade`。
- [x] **D.2 Schema 一致性**：`alembic upgrade head` 與 `metadata.create_all()` 兩條路徑產出的 SQLite schema 在表列、欄位型別、nullable、索引與 unique 約束上完全相等，**沒有任何白名單讓步**。比對前自兩側排除 `alembic_version`（migration 路徑會建、`create_all()` 不會，屬結構性預期差異）。證據：`tests/test_m03d_schema_parity.py::test_sqlite_migration_schema_matches_metadata`。
- [x] **D.3 SQLite FK PRAGMA**：`app/db.py` 以 `@event.listens_for(Engine, "connect")` 對每條新連線執行 `PRAGMA foreign_keys=ON`，並以 `isinstance(dbapi_connection, sqlite3.Connection)` 過濾，Postgres 連線不受影響。掛在 `Engine` 類別而非單一 engine 實例，因此涵蓋 `create_database_engine()` 建的 runtime engine、測試 engine，以及 M03-E launcher 之後呼叫的 migration engine。回歸證據：`tests/test_m03d_sqlite_fk.py::test_sqlite_connections_enable_foreign_keys_and_set_null_import_targets` 驗 `PRAGMA foreign_keys` 為 1，且刪除 character / draft 後 `character_import_records` 對應欄位確實被設為 NULL（`ON DELETE SET NULL` 真的生效，該列也因兩欄皆 NULL 而未被 M03-C 的 CheckConstraint 擋下）。
- [x] **D.3.1 Engine 建立收斂為單一入口**：新增 `app.db.create_database_engine()`，預設經 `resolve_database_url()` 取 URL。`api/dependencies.py` 不再自行 `create_engine(resolve_database_url(), ...)`，`database_is_ready()` 也改走同一個 factory，`connect_timeout` 僅在 URL 為 postgresql 時附加。M03-A 的 dependency 契約測試同步改為斷言「經共用 factory 建立」（`tests/test_m03a_dependencies_uses_resolver.py::test_database_dependency_uses_shared_engine_factory`）。
- [x] **D.4 Postgres 行為不變**：M03-B 與 M03-C 的 migration round-trip 對真 PostgreSQL 17 各自綠燈（`M03B_POSTGRES_URL` / `M03C_POSTGRES_URL` 指向獨立資料庫）；後端全量 `pytest` 綠；前端 112 條 Vitest、`tsc --noEmit` 與 `vite build` 綠；`docker compose config` 通過。
- [x] **D.5 `psycopg` 相依可選**：`psycopg[binary]` 移出 `[project.dependencies]`，改列於 `[project.optional-dependencies].web`（`dev` extra 亦保留一份，供本機／CI 測試安裝）。`apps/server/Dockerfile` 改裝 `.[web]`，M03-B / M03-C / M03-D 三個 workflow 的後端安裝步驟改為 `.[web,dev]`。證據：`tests/test_m03d_dependency_extras.py::test_psycopg_is_optional_and_postgres_workflows_install_web_extra`，該測試會掃過 `.github/workflows/*.yml`，凡含 `postgres:` service 的 workflow 都必須裝 web extra，新增 workflow 忘了裝即紅燈。
- [x] **CI gate**：新增 `.github/workflows/m03d-non-e2e.yml`（backend + frontend + compose-config 三個 job），沿用既有的 `.github/m03d-non-e2e.trigger` 觸發模式，內容由 `tests/test_m03d_ci_contract.py` 靜態鎖住。

## 交付內容

| 檔案 | 內容 |
|---|---|
| `apps/server/app/db.py` | `create_database_engine()` factory 與全域 SQLite FK PRAGMA listener |
| `apps/server/app/api/dependencies.py` | 改用共用 engine factory |
| `apps/server/pyproject.toml` | `psycopg[binary]` 移入 `web` / `dev` extras |
| `apps/server/Dockerfile` | `pip install ".[web]"` |
| `.github/workflows/m03d-non-e2e.yml`、`.github/m03d-non-e2e.trigger` | M03-D non-E2E gate |
| `.github/workflows/m03b-non-e2e.yml`、`m03c-non-e2e.yml` | 後端安裝改 `.[web,dev]` |
| `apps/server/tests/test_m03d_migration_sqlite.py` | D.1 |
| `apps/server/tests/test_m03d_schema_parity.py` | D.2 |
| `apps/server/tests/test_m03d_sqlite_fk.py` | D.3 |
| `apps/server/tests/test_m03d_dependency_extras.py` | D.5 |
| `apps/server/tests/test_m03d_ci_contract.py` | CI workflow 靜態契約 |
| `apps/server/tests/test_m03a_dependencies_uses_resolver.py` | 契約改為共用 engine factory |

## M03-D 未涵蓋（依實作規格「本 Subphase 不要求」）

- 不引入 standalone launcher（M03-E）。
- 不修改任何角色 JSON 匯出／匯入邏輯。
- 不改變 Postgres migration 行為。

## 驗收方式與分層 gate

M03-D 的 diff 只動 backend / DB / 打包相依，完全沒有碰 `apps/web`，依 `AGENTS.md`「測試分層 gate」屬 backend-only，Subphase 關門不要求全套 E2E。本次仍依使用者指示跑了一輪完整 Playwright（96 passed / 1 failed / 3 skipped），唯一失敗為既有的 P1-D ASI flaky spec，見 `已知問題.md` KI-P1D-001，與 M03-D 無關。因為第一輪失敗，`e2e-docker.mjs` 拿掉 `xge` 的第二輪（M03-C import 子集）本次未執行。

## 已知的覆蓋缺口與待決建議（留給後續 Subphase）

以下三點於本 Subphase 的 code review 發現，均不影響 M03-D 的契約成立，尚未處理：

1. **`Settings()` 的 import-time 快照會跨測試污染**（既有問題，非 M03-D 引入）。`app/config.py` 在 import 當下建立 `settings`；若 `app.config` 的首次 import 發生在某個已 `monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", ...)` 的測試中，`settings.database_path` 會被永久釘在那個 tmp 路徑，之後即使環境變數已還原，`resolve_database_url()` 仍回該 SQLite 檔。實測：同一個 pytest process 內先跑 `test_m03b_migration.py` 再跑 `test_m03c_migration.py`，m03c 必失敗。CI 因兩個 job 分開跑、且不會同時提供兩個 `M03*_POSTGRES_URL` 而照不到；production 也不受影響（`resolve_database_path()` 先讀環境變數，執行時環境變數一定在）。建議修法為在 `tests/conftest.py` 加 session autouse fixture 把 `settings.database_path` 釘成 `None`，不動 runtime。
2. **`app/scripts/seed_p0_fighter_wizard.py` 仍直接 `create_engine(settings.database_url)`**，繞過 `resolve_database_url()` 與 `create_database_engine()`。只影響該 dev seed 腳本，不進 web runtime 也不進 standalone bundle。
3. **`create_database_engine()` 預設走 `resolve_database_url()` 這條 SSOT 沒有測試**。M03-A 原本在 dependency 層斷言 URL 來源，本 Subphase 改為斷言「有呼叫共用 factory」後，這條連結只剩讀 code 保證。M03-E launcher 依賴它把 engine 指向 SQLite，建議於 M03-E 補上斷言。
