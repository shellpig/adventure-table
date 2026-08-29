# Adventure Table

Adventure Table 是一個桌上跑團優先的 D&D 5e 2014 Web VTT。**P0-A — Project Foundation** 與 **P0-B — Character-Relevant SRD Foundation** 已完成；目前已有可重現的 Web / API / DB 地基，以及角色系統會使用的 SRD 5.1 normalized reference content。Character persistence、Character Sheet、Combat 等後續功能尚未實作。

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

`/health` 只表示 FastAPI process 可回應；`/ready` 會實際檢查 PostgreSQL，資料庫不可用時回傳 HTTP 503。Server 啟動時也會先載入並驗證 P0-B 的 SRD content；mandatory schema / reference 錯誤會 fail-fast，應用程式不會帶著壞資料啟動。

## Database migration

Server container 啟動前會自動執行 `alembic upgrade head`。也可手動驗證：

```bash
docker compose up -d db
docker compose run --rm server alembic upgrade head
```

目前 baseline migration 刻意不建立 Character 等 P0-C 之後才需要的 table。

## Backend 本機開發

在可連線的 PostgreSQL 已啟動後：

```bash
cd apps/server
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
# Windows cmd
set "DATABASE_URL=postgresql+psycopg://adventure:adventure@localhost:5432/adventure_table"
# PowerShell: $env:DATABASE_URL="postgresql+psycopg://adventure:adventure@localhost:5432/adventure_table"
alembic upgrade head
uvicorn app.main:app --reload
```

Backend tests：

```bash
cd apps/server
pytest
```

## Frontend 本機開發

需求：Node.js 24。先固定 npm 11.6.0，避開 npm 10.9.8 的 dependency resolver bug。

```bash
cd apps/web
npm install --global npm@11.6.0
npm install
npm run dev
```

Vitest baseline：

```bash
npm test -- --run
```

Playwright baseline 第一次執行前先安裝 Chromium：

```bash
npx playwright install chromium
npm run test:e2e
```

## P0-A — Project Foundation

包含：React + TypeScript + Vite app shell、TanStack Query provider、FastAPI、PostgreSQL connection/readiness、SQLAlchemy/Alembic baseline、Docker Compose、pytest、Vitest 與 Playwright smoke tests。

## P0-B — Character-Relevant SRD Foundation

P0-B 已建立：

- `data/srd5.1/` 作為 version-controlled normalized SRD reference content Source of Truth。
- 22 個 character-relevant categories，共 1,944 筆 normalized entries。
- 每筆 reference 使用不依賴顯示名稱的 stable key，例如 `srd5.1:spell:fireball`、`srd5.1:class:fighter`。
- Pydantic category schemas、manifest validation、stable-key uniqueness 與 cross-reference validation。
- `ContentRegistry` 啟動載入與 query 能力。
- duplicate key、missing required field、malformed value、dangling reference 等負向測試。
- P0 scope guard：**不包含 Monster / Beast stat blocks**；這部分明確延後 P4-A。
- SRD 來源、ruleset、license / attribution 與 pinned extraction source metadata。

`data/srd5.1/manifest.json` 是資料集合與數量的 manifest；`data/srd5.1/NOTICE.md` 保存 attribution。`scripts/vendor_srd.py` 是 maintainer 用的可重現 vendor 工具，runtime 不會連外下載規則資料。

下一個 Subphase 是 **P0-C — Character Core & Persistence**；未獲明確指示前不自行開始。
