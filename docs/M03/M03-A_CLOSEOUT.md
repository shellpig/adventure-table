# M03-A Closeout Checklist

M03-A — Content Root Path Abstraction & Enabled-Pack SSOT closeout scope：

- [x] Content root 解析順序固定為 `env` → `frozen-exe-dir` → `frozen-meipass` → `repo-relative`，四段各自可觀察；解析失敗的錯誤訊息同時帶出實際路徑與解析階段標籤。
- [x] Rules JSON、localization root、SPA root、database URL 一律自 content root 推導或走同一組 resolver，沒有第二處硬編路徑。
- [x] 未設 `ADVENTURE_TABLE_CONTENT_ROOT` 且非凍結環境時，解析結果與 M03-A start baseline 一致：9 個 pack、3,186 個 entry，逐 pack 數量與 manifest 宣告的 `total_entries` 相符。
- [x] `Settings.enabled_content_packs` 成為 enabled pack 的單一事實來源。`NoDecode` + `field_validator(mode="before")` 兩者齊備，comma string、含空白、空字串 fallback 均正確；`app/content/__init__.py` 對 `_registry.DEFAULT_CONTENT_PACKS` 的 monkey-patch 已移除。
- [x] Repo-wide sweep 一次到位：`app/` 全樹不再有 `REPOSITORY_ROOT` / `CONTENT_PACKS_ROOT` / `DEFAULT_CONTENT_ROOT` / `DEFAULT_SRD_CONTENT_ROOT` / `DEFAULT_CONTENT_PACKS` / `RULES_PATH`；`Path(__file__).resolve().parents[N≥3]` 只剩 `app/paths.py` 一處。`api/dependencies.py`、`alembic/env.py`、`domain/character_builder/rules.py`，以及 `m01j_overrides` / `m01j_inventory` / `m01l_inventory` / `m01m_inventory` / `m01m_overrides` / `background_roleplay` 全部改為呼叫時解析，import time 不再綁定 filesystem 位置。
- [x] 靜態 sweep test 具備反例自檢：重新引入常數、對已移除常數 monkey-patch、legacy registry import、`parents[3]` 推導，四類反例都會被抓到。
- [x] Subset registry 的 unresolved 語意收窄至「已安裝但未啟用」（實作規格 A.5.1）：source 未安裝、目標 pack 已啟用卻缺 entry、kind 不符，三者一律維持 `ContentValidationError`。完整 9 pack 的網頁版設定下 installed == enabled，等於沒有任何放行，M01-J / M01-L / M01-M 的 registry load 身分守門不受影響。
- [x] 測試以 settings 注入 subset 模擬缺 pack，全程不刪 pack 目錄；缺目錄仍以 `enabled content pack directory is missing` 明確失敗。
- [x] Settings 環境變數相容性維持：未啟用 `env_prefix`，Docker Compose 的 `DATABASE_URL` 語意不變；四個新欄位各自以 `AliasChoices` 明列 `ADVENTURE_TABLE_*`。
- [x] M03-A start baseline 凍結於 `docs/M03/baseline/m03a-start.json`，測試一律經 `apps/server/tests/m03_baseline.py` 讀取，測試碼內不再重複抄寫 pack 清單或 entry 數。
- [x] Docker Compose 啟動不需要任何新環境變數；`docker compose config` 於 CI 驗證。
- [x] P0 / P1 / M01 / M02 regression 保持 green。

## A.1～A.8 證據對應

| 契約 | 測試位置 | 測試數 |
|---|---|---|
| A.1 Path resolver unit test | `apps/server/tests/test_m03a_paths.py` | 13 |
| A.2 Registry loads via new resolver | `apps/server/tests/test_m03a_registry_uses_resolver.py` | 6 |
| A.3 Rules module 使用 resolver | `apps/server/tests/test_m03a_rules_uses_resolver.py` | 4 |
| A.4 `api.dependencies` 使用 resolver | `apps/server/tests/test_m03a_dependencies_uses_resolver.py` | 2 |
| A.5 Repo-wide constant sweep static test | `apps/server/tests/test_m03a_no_legacy_path_constants.py` | 5 |
| A.6 Enabled pack SSOT | `apps/server/tests/test_m03a_enabled_packs.py` | 14 |
| A.6.1 Subset unresolved 語意 | `apps/server/tests/test_m03a_enabled_packs.py`、`apps/server/tests/test_m01a_content_packs.py` | 3 + 2 |
| A.7 Settings 環境變數相容性 | `apps/server/tests/test_m03a_settings_env_compat.py` | 6 |
| A.8 網頁版無回歸 | 後端 pytest 全量、前端 Vitest / tsc / build、Playwright 全量 | 見下 |

M03-A 專屬後端覆蓋為 7 個測試檔共 50 個測試。A.6.1 的 5 條分屬 `test_m03a_enabled_packs.py`（3）與 `test_m01a_content_packs.py`（2），後者取代原 `test_cross_pack_dependency_must_be_enabled`。

## Verification evidence

2026-09-04，分支 `claude/project-progress-gkyref` HEAD `bb340e2`：

```text
cd apps/server
python -m pytest
786 passed（exit 0，339s）

python -m pytest tests/test_m03a_*.py
50 passed
```

後端全量由本 session 於 Linux / Python 3.13 執行。

前端 Vitest / `tsc --noEmit` / `vite build` 與 Playwright E2E 由專案 owner 於本機（Windows，codex）執行並回報通過；**本 session 未執行 E2E**——remote container 沒有 docker daemon，而 `apps/web/scripts/e2e-global-setup.mjs` 以 `docker compose exec` 清庫與 re-seed，globalSetup 因此無法起動。M03-A 未改動 `apps/web/`，前端無 diff。

`.github/workflows/m03a-non-e2e.yml` 涵蓋後端 pytest、M03-A focused pytest、localization authoring unit tests、以 resolver 跑的全新 SQLite `alembic upgrade head`、前端測試與 build、`docker compose config`；目前僅於 `m03-a-paths-enabled-pack-ssot` 分支的 push 觸發。

## 關門過程中修復的既有缺陷

1. **Disabled-pack 放行過寬（主缺陷）**：`_validate_cross_references()` 原本對「目標 pack 未啟用」全類放行，連 source 段打錯字或指向未出貨 pack 的 StableKey 也一併靜默通過，且在正式 9 pack 設定下同樣失效。已收窄為只放行「已安裝但未啟用」，並把同一判準套進 `builder_content_validation` 與 `background_roleplay`。`ContentRegistry` 因此新增 `installed_pack_ids`。
2. **M01-A 契約測試未同步**：`test_cross_pack_dependency_must_be_enabled` 斷言的是 subset 載入必然推翻的那一半，於全量 suite 紅燈。已改寫成兩條分別守住收窄後的兩半，理由記於實作規格 A.5.1。
3. **`_require_installed_pool(field: str)` 收到 1-tuple**：`builder_content_validation.py` 的 retraining pool 分支多了一個逗號，錯誤訊息會印成 tuple。正常路徑不受影響，故原測試抓不到。已修。
4. **Baseline 三處重複**：pack 清單與 entry 數同時寫死在 `conftest.py`、`test_m03a_enabled_packs.py`、`test_m03a_registry_uses_resolver.py`。已收斂為 `docs/M03/baseline/m03a-start.json` 單一來源。
5. **Baseline 命名名實不符**：測試指南原訂 `m01-full-closeout.json`，但 M01 依使用者決定保持 open。已改名為 `m03a-start.json`，三份 M03 文件的「M01 Full Closeout snapshot」術語一併改為「M03-A start baseline」。

## M03-A 未涵蓋（依實作規格「本 Subphase 不要求」）

- 未建立 standalone entry point 或 launcher（M03-E）。
- 未新增 Character JSON 匯出／匯入（M03-B / M03-C）。
- 未修改 Alembic migration，未引入 SQLite runtime 程式碼（M03-D）。
- 未新增 `/api/meta/capabilities` router（M03-E）。
- `app/paths.py` 已備妥 `mark_launcher_mode()` 與 frozen / SPA / SQLite 解析，但於 M03-A 尚無呼叫端；這是刻意為 M03-E 預留的 resolver 形狀，不是未接線的死碼。
