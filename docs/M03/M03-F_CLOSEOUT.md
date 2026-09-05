# M03-F Closeout Checklist

M03-F — Windows CI Build, Release & Import Boundary Test closeout scope：

- [x] **F.1 Windows CI job**：`.github/workflows/m03-standalone.yml` 於 `windows-latest` 上 checkout → Python 3.13 / Node 24 → `scripts\build-standalone.cmd --version <version>` → 在乾淨產物資料夾跑 `scripts\smoke_standalone.py` → 上傳 `.zip` 為 workflow artifact（`if-no-files-found: error`）。Job 內未出現 `ADVENTURE_TABLE_DATABASE_PATH`，由 `test_m03f_workflow_contract.py` 靜態守住，預設 exe 同層路徑因此是被測對象本身。觸發為 `main` push、PR label `standalone-build`、`workflow_dispatch`，三者走同一個 `standalone-build` job。證據：run `33933833357`（PR label 觸發）全綠，artifact `adventure-table-standalone-m03f-26016636ff77`（23,042,996 bytes）可下載；`m03f-non-e2e.yml` 的 `windows-standalone` job 亦以同一組命令在 `windows-latest` 上綠。
- [x] **F.2 Release 產物（契約已改：本機發版，CI 不建立 GitHub Release）**：發版一律跑本機 `scripts\build-standalone.cmd --version <版本>` 取 `dist\adventure-table-standalone-<版本>.zip`；CI artifact 僅為「乾淨環境能建置」的證據，有保存期限，不作為版本存檔。Workflow 不含 `release` job、不含 tag `v*` 觸發、`permissions` 維持 `contents: read`。`docs/M03/release-notes-template.md` 為本機發版時的 release notes 範本，明文標示 JSON schema `unstable`。防回流由 `test_m03f_workflow_contract.py::test_m03f_workflow_never_publishes_a_github_release` 靜態鎖住（斷言 workflow 不含 `gh release` / `refs/tags/v` / `tags:` / `contents: write`）。決策理由見下方「一項與原實作規格不同的契約變更」。
- [x] **F.3 Import boundary test**：`apps/server/tests/test_m03_import_boundary.py` 以 `ast.parse` 遞迴建可達 import graph（不呼叫 `importlib.import_module`），對 `app.content.*`、`app.domain.character*` 與 `EXACT_PROTECTED_MODULES` 十個模組為 seed，斷言 graph 內無命中 forbidden regex 的 `app.*` module。`_protected_seeds()` 另外斷言每個 guarded module 都真的存在於 source tree，避免模組改名後 gate 靜默失效。`app.standalone` 不得可達 `app.main` 為獨立一條。
- [x] **F.4 Standalone composition test**：`apps/server/tests/test_m03_standalone_composition.py` 以 AST 比對 `create_standalone_app()` 的 `include_router` 呼叫恰為五個（reference / content_presentation / characters / character_builder / `create_meta_router('standalone')`），並斷言 `/assets` 與 `/{full_path:path}` 已掛載、client route 回 200 而未知 `/api/*` 回 404、`standalone.py` 全文不含 `alembic`、standalone 的 `/api/meta/capabilities` 回 `channel="standalone"` 與 `room=false`、`app.main` 同 endpoint 回 `channel="web"`。
- [x] **F.5 網頁版行為不變**：本 Subphase 未新增任何產品程式碼，diff 僅涵蓋 `.github/`、`apps/server/tests/` 與 `docs/M03/`。未動 `Dockerfile`、`pyproject.toml`、`compose.yaml` 或任何 runtime module，因此 Docker image 大小與啟動時間結構上不變（測試指南 F.6 的「差異 < 5%」由 diff 本身滿足）。既有 workflow 全綠。
- [ ] **M03-E 遺留的測試指南 E.9 乾淨 Windows 11 冷啟動仍未執行**。M03-E closeout 原本規劃「M03-F 產出正式 release artifact 時一併補」；artifact 現已存在（見 F.1 證據），但冷啟動人工驗收需要一台未裝 Python / Node / Docker 的機器，本 Subphase 沒有取得。順延至 M03-G。

## 交付內容

| 檔案 | 內容 |
|---|---|
| `.github/workflows/m03-standalone.yml` | Windows standalone build + frozen smoke + artifact upload（無 release job） |
| `.github/workflows/m03f-non-e2e.yml`、`.github/m03f-non-e2e.trigger` | backend / frontend / windows-standalone / compose-config 四個 job 的 review-gated 回歸 |
| `apps/server/tests/test_m03_import_boundary.py` | F.3 static import graph gate、反例 fixture 與 regex 邊界測試 |
| `apps/server/tests/test_m03_standalone_composition.py` | F.4 standalone 組裝契約 |
| `apps/server/tests/test_m03f_workflow_contract.py` | workflow 觸發、Windows toolchain、artifact 命名、無 GitHub Release、非 E2E gate 的靜態契約 |
| `docs/M03/release-notes-template.md` | 本機發版用 release notes 範本（含 JSON schema `unstable` 說明） |

## 一項與原實作規格不同的契約變更

**F.2 由「CI 於 tag `v*` 建立 GitHub Release」改為「本機發版，CI 不建立 Release」。**

原因：本專案為朋友間私人使用，repo 將轉為 private。Private repo 的 Release 頁面與 asset 都需要 repo 讀取權限，`browser_download_url` 對沒有權限者回 404，因此 GitHub Release 無法達成「把 zip 連結給朋友」這個唯一目的，只會多一條要維護與驗證的通路。本機 `build-standalone.cmd` 早在 M03-E 就能產出同一份 zip，發版能力並未因此減少。

同步更新的文件：`docs/M03/實作規格.md` F.1 / F.2、`docs/M03/測試指南.md` F.1 / F.3、`docs/M03/開發設計方針.md` 10.1。移除的驗收項是原測試指南 F.3 的「於 pre-release tag 上手動觸發 release job」，改以靜態防回流斷言取代。

## 驗證過程中修正的兩個問題

1. **release job 缺少 repository context**。初版 `release` job 在 `ubuntu-latest` 上只有 `download-artifact`，沒有 `actions/checkout`、也沒有 `GH_REPO`；`gh` 只能從 cwd 的 git remote 推斷 repo，在空的 workspace 會以 "could not determine base repository" 失敗，而 `gh release view ... || gh release create ...` 的 `||` 會把第一次失敗吃掉，讓 job 直到 `create` 才紅。當時的修法是補上 `GH_REPO: ${{ github.repository }}` 與 `checkout`，並加測試斷言 checkout 排在 `gh release view` 之前。此問題隨後因 F.2 契約變更、整個 release job 被移除而不再適用，記錄於此以免同樣寫法回流。
2. **forbidden regex 收窄後抓不到複數 module 名**。為對齊測試指南字面，regex 一度改為 `(?:^|\.)(?:room|session|seat|campaign|party_roster)(?:\.|$)`，實測 `app.api.rooms`、`app.persistence.sessions`、`app.api.seats`、`app.domain.campaigns` 全部不命中——而複數 resource module 名正是 P2 較可能的寫法，等於 gate 會靜默放行。改為每個 segment 允許可選的結尾 `s`：`(?:^|\.)(?:rooms?|sessions?|seats?|campaigns?|party_rosters?)(?:\.|$)`，同時保留 `session_scope` / `roommate` 為非命中。回歸鎖：`test_forbidden_regex_matches_plural_resource_module_names`，反例 fixture 亦補上複數 `app.api.rooms`。測試指南與開發設計方針的 regex 字面已同步。

## 驗收方式與分層 gate

M03-F 的 diff 只動 `.github/`、`apps/server/tests/` 與 `docs/M03/`，未觸及 `apps/web`、未觸及 server 送給前端的 DTO / machine code / locale 字串，依 `AGENTS.md` 分層 gate 屬 backend-only，Subphase 關門不需跑 E2E。實際執行：

- 全套 backend `pytest`：綠（exit 0）。
- 前端 Vitest 與 `npm run build`：綠（`m03f-non-e2e.yml` 的 `frontend` job，run `33931831167`）。
- `docker compose config`：通過（同上 run 的 `compose-config` job）。
- `windows-latest` frozen build + smoke：綠（run `33933833357` 與 `33931831167` 的 `windows-standalone` job）。
- PostgreSQL migration round trip：綠（同上 run 的 backend job）。

## M03-F 未涵蓋（依實作規格「本 Subphase 不要求」）

- 不做 code signing。
- 不做 Linux / macOS CI build。
- 不做 SmartScreen reputation build。

## 已知的覆蓋缺口與待決建議（留給 M03-G）

1. **測試指南 E.9 乾淨 Windows 11 冷啟動未執行**（見上方未打勾項）。需要一台未裝 Python / Node / Docker 的機器或 VM；artifact 已備妥。
2. **`m03-standalone.yml` 尚未由 `main` push 路徑實跑過**。目前綠燈來自 PR label 觸發；三種觸發走同一個 job，差異只在 `if` 條件，風險低，但 M03-F 合併進 `main` 後會自然跑到一次，屆時確認即可。
3. **M03-E 遺留第 2 點仍未處理**：`/docs` / `/redoc` / `/openapi.json` 只由 `*_url is None` 間接保證，沒有實際發 request 驗 404。M03-E closeout 建議由 M03-F 補，本 Subphase 未做。
4. **M03-E 遺留第 3、4 點仍未處理**：launcher 的 `KeyboardInterrupt` 回收路徑無測試；`Settings()` import-time 快照跨測試污染。
5. **forbidden regex 的維護責任**：P2 開工引入多人模組時，若命名不落在 `room` / `session` / `seat` / `campaign` / `party_roster`（含複數）這組字根內，boundary gate 會失效。P2 的第一個 Subphase 應同步擴充該 regex 與 `EXACT_PROTECTED_MODULES`。
