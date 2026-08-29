# Adventure Table

Adventure Table 是一個桌上跑團優先的 D&D 5e 2014 Web VTT。P0-A 只建立可重現啟動與測試的專案地基；Character / SRD / Combat 等功能尚未在此階段實作。

## P0-A 快速啟動

需求：Docker + Docker Compose。

```bash
cp .env.example .env
docker compose up --build
```

啟動後：

- Web app: http://localhost:5173
- Backend health: http://localhost:8000/health
- Backend readiness: http://localhost:8000/ready

`/health` 只表示 FastAPI process 可回應；`/ready` 會實際檢查 PostgreSQL，資料庫不可用時回傳 HTTP 503。

## Database migration

Server container 啟動前會自動執行 `alembic upgrade head`。也可手動驗證：

```bash
docker compose up -d db
docker compose run --rm server alembic upgrade head
```

P0-A 的 baseline migration 刻意不建立 Character 等後續 Phase table。

## Backend 本機開發

在可連線的 PostgreSQL 已啟動後：

```bash
cd apps/server
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
set DATABASE_URL=postgresql+psycopg://adventure:adventure@localhost:5432/adventure_table  # Windows cmd
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

```bash
cd apps/web
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

## P0-A 範圍

目前只包含：React + TypeScript + Vite app shell、TanStack Query provider、FastAPI、PostgreSQL connection/readiness、SQLAlchemy/Alembic baseline、Docker Compose、pytest、Vitest 與 Playwright smoke tests。

下一個 Subphase 是 P0-B — Character-Relevant SRD Foundation。
