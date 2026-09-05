# Adventure Table

![Python](https://img.shields.io/badge/PYTHON-3.13-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FASTAPI-0.128-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/POSTGRESQL-17-4169E1?logo=postgresql&logoColor=white)
![React](https://img.shields.io/badge/REACT-19.2-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TYPESCRIPT-5.9-3178C6?logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/VITE-8.2-646CFF?logo=vite&logoColor=white)
![Ruleset](https://img.shields.io/badge/RULESET-D%26D%205E%202014-purple)
![Status](https://img.shields.io/badge/STATUS-CHARACTER%20LAYER%20USABLE-orange)

Adventure Table 是一個**輕量、桌上跑團優先的 D&D 5e 2014 Web VTT**。真人 DM 像實體跑團一樣主要靠口頭敘事，網站只管需要共享、同步、計算、保存、權限與 AI 接入的東西。外部 AI 未來可透過 MCP / Site Tools 正式進桌擔任 DM 或 Player，與真人共用同一套 Game State、規則與權限。

朋友間私人使用，非商品化平台。介面為 `zh-TW` / `en` 雙語。

**目前進度以 [`PROJECT_BRIEF.md`](PROJECT_BRIEF.md) 為單一事實來源**——本檔不複述 Phase 狀態。概略地說：角色端（Character Workshop / Builder / Sheet / Level Up / Version History）可用，Room / Campaign / Session / Combat 尚未實作。

文件入口：

| 檔案 | 內容 |
|---|---|
| [`PROJECT_BRIEF.md`](PROJECT_BRIEF.md) | 當前 Phase、Roadmap、Subphase 進度、文件索引 |
| [`規格企劃.md`](規格企劃.md) | 產品與玩法的單一事實來源 |
| [`AGENTS.md`](AGENTS.md) | 開發與 AI agent 的工作規則 |
| [`已知問題.md`](已知問題.md) | 已確認但決定暫不處理的問題 |
| `docs/P0/`、`docs/P1/`、`docs/M01/`、`docs/M02/`、`docs/M03/` | 各 Phase 的實作規格、開發設計方針、測試指南與 closeout |

## 快速啟動

需求：Docker + Docker Compose。

```bash
cp .env.example .env
docker compose up --build
```

啟動後：

- Web app: http://localhost:5173
- Backend health: http://localhost:8000/health
- Backend readiness: http://localhost:8000/ready

`/health` 只表示 FastAPI process 可回應；`/ready` 會實際檢查 PostgreSQL，資料庫不可用時回傳 HTTP 503。Server 啟動時會載入並驗證全部 enabled content packs；schema、stable key 或 cross-reference 錯誤一律 fail-fast，應用程式不會帶著壞資料啟動。

## Content packs

規則內容住在 `data/<pack>/`，全部是 version-controlled 的 normalized JSON。每筆 entry 使用不依賴顯示名稱的 stable key，例如 `srd5.1:spell:fireball`、`tce:class:artificer`。

目前 enabled 的 9 個 pack 共 3,186 筆 entry：

| Pack | 來源 | Entries |
|---|---|---|
| `srd5.1` | System Reference Document 5.1（CC BY 4.0） | 1,944 |
| `phb2014` | Player's Handbook 2014 | 384 |
| `tce` | Tasha's Cauldron of Everything | 401 |
| `xge` | Xanathar's Guide to Everything | 266 |
| `scag` | Sword Coast Adventurer's Guide | 78 |
| `vgm` | Volo's Guide to Monsters | 64 |
| `mtf` | Mordenkainen's Tome of Foes | 40 |
| `vrgr` | Van Richten's Guide to Ravenloft | 5 |
| `gos` | Ghosts of Saltmarsh | 4 |

啟用清單的單一事實來源是 `Settings.enabled_content_packs`，可用環境變數覆寫。`data/localization/` 放 locale policy 與術語表，各 pack 的 `zh-TW` 呈現字串放在該 pack 的 `locales/` 之下。

`data/srd5.1/NOTICE.md` 保存 SRD 5.1 的 attribution 與繁中翻譯聲明。`scripts/vendor_srd.py` 是 maintainer 用的可重現 vendor 工具，runtime 不會連外下載規則資料。**網站本身不接 LLM API。**

## Database migration

Server container 啟動前會自動執行 `alembic upgrade head`。也可手動驗證：

```bash
docker compose up -d db
docker compose run --rm server alembic upgrade head
```

## Backend 本機開發

Python 3.12+。venv 建在**專案根目錄**，讓所有人與 agent 看到一致結果：

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
cd apps/server
pip install -e ".[dev]"
```

在可連線的 PostgreSQL 已啟動後：

```bash
# PowerShell: $env:DATABASE_URL="postgresql+psycopg://adventure:adventure@localhost:5432/adventure_table"
export DATABASE_URL="postgresql+psycopg://adventure:adventure@localhost:5432/adventure_table"
cd apps/server
alembic upgrade head
uvicorn app.main:app --reload
```

Backend tests：

```bash
cd apps/server && pytest
```

## Frontend 本機開發

需求：Node.js 24。先固定 npm 11.6.0，避開 npm 10.9.8 的 dependency resolver bug。

```bash
cd apps/web
npm install --global npm@11.6.0
npm install
npm run dev
```

單元測試與 build：

```bash
npm test -- --run
npm run build          # tsc --noEmit + vite build
```

## E2E 測試

**整套 Playwright 一律走容器裡的 Linux dev server：**

```bash
cd apps/web && npm run test:e2e:docker
```

該 script 會自己 `docker compose up -d --build web`、等埠開、再以容器的 5173 當 base URL 執行。`--build` 不可省——`web` service 沒有掛 bind mount，略過重建會靜默測到上一版 frontend。

Windows 上不要讓 Playwright 自己託管 vite：dev server 會在跑測試途中停止接受連線，造成數十個 `net::ERR_CONNECTION_REFUSED`。`playwright.config.ts` 會直接擋下這條路徑。根因與量測見 [`已知問題.md`](已知問題.md) 的 KI-ENV-001。

第一次執行前先安裝 Chromium：

```bash
npx playwright install chromium
```

## Standalone 發版相依版本

Windows standalone 發版的套件版本固定在 [`apps/server/constraints-standalone-win.txt`](apps/server/constraints-standalone-win.txt)，本機與 CI 共用同一份。`pyproject.toml` 只宣告需要哪些套件與相容範圍；實際版本號只住這份清單。

`scripts/build-standalone.cmd` 會在建立 venv 後檢查直譯器版本，安裝時帶 `-c` 套用清單，裝完再比對一次實際安裝結果。環境與清單不符時 build 直接失敗，錯誤訊息會列出差在哪個套件。

發版用的 Python 固定為 3.13（與 M03 CI 契約一致）。若本機預設 `python` 不是 3.13，用 `STANDALONE_PYTHON` 指向 3.13 直譯器：

```bat
set "STANDALONE_PYTHON=C:\path\to\python3.13\python.exe"
scripts\build-standalone.cmd --version v0.1.0
```

平常改遊戲邏輯、UI 或翻譯都不必動這份清單。新增 Python 套件、升級既有套件，或更換發版 Python 版本時才更新：

```bat
rmdir /s /q .pin-venv
"%STANDALONE_PYTHON%" -m venv .pin-venv
.pin-venv\Scripts\python.exe -m pip install --upgrade pip
.pin-venv\Scripts\python.exe -m pip install -e "apps\server[standalone]"
.pin-venv\Scripts\python.exe -m pip freeze --exclude-editable --all
```

把輸出接在清單既有的註解標頭後面覆蓋原本的版本列表——標頭裡的 `# python-version:` 與說明要保留。**一定要帶 `--exclude-editable`**，否則 `adventure-table-server` 自己會被寫進清單，下次安裝就會壞。

更新後必須跑過完整 standalone build 與 frozen smoke 才提交：

```bat
scripts\build-standalone.cmd --version pin-check
.standalone-venv\Scripts\python.exe scripts\smoke_standalone.py dist\adventure-table-standalone --timeout 30
```

這份清單只適用 Windows，內含 win32 專用 wheel，不要拿去餵 Linux 或 Docker。重建某個舊版發行時，用當時 commit 的清單。

## 授權

本 repo 的規則內容取自 System Reference Document 5.1，依 CC BY 4.0 使用；attribution 見 `data/srd5.1/NOTICE.md`。非 SRD 內容依私人專案需求逐步加入，不對外散布。
