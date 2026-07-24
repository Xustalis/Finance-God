# Finance-God

Finance-God is a Chinese-first educational investment profiling application.
The current release covers authentication, objective information collection,
AI-assisted text/voice onboarding, a deterministic profile report, investment
direction selection, and administrator AI settings. It does not execute trades
or recommend specific funds.

## Stack

- Frontend: Vue 3, TypeScript, Vite, Pinia, Vue Router
- Backend: FastAPI, SQLAlchemy 2, Pydantic, Alembic
- Database: PostgreSQL 16
- Development AI: deterministic mock text adapter and browser speech APIs

## Setup

Requirements: Python 3.11+, Node.js 20+, and PostgreSQL 16 (local or Docker).

```bash
cp .env.example .env

cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cd ../frontend
npm install
```

Start PostgreSQL and apply the existing schema:

```bash
docker compose up -d db
cd backend
.venv/bin/alembic upgrade head
```

Start the services in separate terminals:

```bash
cd backend
.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

cd frontend
npm run dev
```

- Frontend: `http://localhost:5173`
- API: `http://localhost:8000`
- OpenAPI UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

## Existing Workspace Database

On 2026-07-23, the local `finance_god` development database in this checkout
was deliberately dropped, recreated, and migrated to the clean onboarding
schema.

Choose the migration path based on the workspace state:

- A fresh database or a database already created from the current onboarding
  migration can run `alembic upgrade head`.
- A legacy workspace stamped with the old `20260723_0001` revision must use the
  guarded reset below. The revision identifier was retained while its schema
  was replaced, so `alembic upgrade head` alone reports success without
  replacing legacy trading tables.

The legacy reset destroys local data. Always run `--check` first and inspect the
validated database name before proceeding.

The reset workflow is guarded. It runs only with `APP_ENV=development`, accepts
only a local PostgreSQL host, and accepts only the database names `finance_god`
or `finance_god_dev`. Validate the target without changing data first:

```bash
cd backend
APP_ENV=development \
DATABASE_URL_SYNC=postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/finance_god \
./scripts/reset_dev_db.sh --check
```

To erase and rebuild that validated legacy development database:

```bash
cd backend
APP_ENV=development \
DATABASE_URL_SYNC=postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/finance_god \
make reset-dev-db
```

The script uses the `postgres` maintenance database, recreates only the
validated target, and runs `alembic upgrade head`. It refuses production mode,
remote hosts, other database names, and missing URLs.

## Configuration

Important environment variables:

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | `development` enables the mock text provider; other environments require a supported non-mock provider |
| `DATABASE_URL` | Async application database URL |
| `DATABASE_URL_SYNC` | Synchronous Alembic and guarded reset URL |
| `SECRET_KEY` | JWT signing secret; the development default is rejected outside development |
| `CORS_ORIGINS` | Comma-separated allowed frontend origins |
| `VITE_WORKBENCH_ORIGIN` | Browser build variable containing the exact target origin for the profile completion handoff |
| `WORKBENCH_ORIGIN` | Compatible alias used by Vite when `VITE_WORKBENCH_ORIGIN` is absent |

The frontend resolves `VITE_WORKBENCH_ORIGIN` first and falls back to
`WORKBENCH_ORIGIN`. Vite embeds this value into browser code, so set it before
starting the development server or creating a production build. Docker Compose
passes the root `.env` file to the frontend service.

API keys are read only from server environment variables referenced by admin
configuration. They are never returned by the API or stored in audit snapshots.

## Tests

```bash
cd backend
.venv/bin/pytest -q
.venv/bin/alembic upgrade head --sql
```

The PostgreSQL migration round-trip test is opt-in and destructive only to a
database named exactly `finance_god_test`:

```bash
FINANCE_GOD_POSTGRES_TEST_URL=postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/finance_god_test \
.venv/bin/pytest tests/integration/test_postgres_migrations.py -q
```

See [backend/docs/workbench-integration.md](backend/docs/workbench-integration.md)
for API fields, enums, error codes, idempotency behavior, and the workbench
`postMessage` contract.
