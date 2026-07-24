# Finance-God

Finance-God is a Chinese-first educational investment profiling application.
The current release covers authentication, objective information collection,
AI-assisted text/voice onboarding, a deterministic profile report, investment
direction selection, administrator AI settings, PandaData-backed market views,
and simulation-only trading services. It does not execute broker trades or
recommend specific funds.

## Documentation

- [文档中心](docs/README.md)：现行规范、参考资料与历史记录的统一入口
- [项目索引](docs/项目索引.md)：代码结构、路由、API、迁移与验证入口
- [Backend architecture](backend/docs/architecture-overview.md)：后端组合与路径约定
- [Finance API reference](backend/docs/finance-api-reference.md)：行情、工作区与仿真 API

## Stack

- Frontend: Vue 3, TypeScript, Vite, Pinia, Vue Router
- Backend: FastAPI, SQLAlchemy 2, Pydantic, Alembic
- Database: PostgreSQL 16
- AI: DeepSeek OpenAI-compatible text adapter, development mock, and browser speech APIs

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
make seed-dev-admin
```

Start the services in separate terminals:

```bash
make backend

cd frontend
npm run dev
```

- Frontend: `http://localhost:3000`
- API: `http://localhost:8000`
- OpenAPI UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

`app.main:app` is the only supported ASGI application. `make backend` runs a
port preflight before starting it and fails explicitly if port 8000 is already
owned by another process; it never stops that process or starts a second
backend. The former `server:app` static-prototype entry point no longer exists.

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

Copy only the repository-root example:

```bash
cp .env.example .env
```

The root `.env` is the sole implicit local configuration file. Both typed
settings and adapters that read `os.getenv` receive values from it.
`backend/.env` is not loaded and must not be used.

Existing checkouts that still contain `backend/.env` fail startup explicitly
instead of silently losing those settings or restoring a second source.
Run `make migrate-legacy-env` once: it adds only non-empty keys missing from the
root `.env`, never overwrites existing root keys or prints values, and preserves
the original as `backend/.env.migrated`.

Important environment variables:

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | `development` enables the mock text provider; other environments require a supported non-mock provider |
| `DATABASE_URL` | Async application database URL |
| `DATABASE_URL_SYNC` | Synchronous Alembic and guarded reset URL |
| `SECRET_KEY` | JWT signing secret; the development default is rejected outside development |
| `CORS_ORIGINS` | Comma-separated allowed frontend origins |
| `DEEPSEEK_API_KEY` | Server-only DeepSeek credential; never exposed to the frontend or admin API |
| `STEPFUN_API_KEY` | Server-only StepFun credential for the controlled `step-3.5-flash-2603` profile model |
| `ARK_API_KEY` / `ARK_MODEL` | Server-only ARK credential and required model identifier |
| `PANDA_DATA_USERNAME` / `PANDA_DATA_PASSWORD` | Server-only PandaData credentials required by production readiness |
| `DEV_ADMIN_EMAIL` | Development administrator email, default `admin@finance-god.local` |
| `DEV_ADMIN_PASSWORD` | Development-only seed password; required by `make seed-dev-admin`, minimum 12 characters |
| `VITE_WORKBENCH_ORIGIN` | Browser build variable containing the exact target origin for the profile completion handoff |
| `WORKBENCH_ORIGIN` | Compatible alias used by Vite when `VITE_WORKBENCH_ORIGIN` is absent |

The frontend resolves `VITE_WORKBENCH_ORIGIN` first and falls back to
`WORKBENCH_ORIGIN`. Vite embeds this value into browser code, so set it before
starting the development server or creating a production build. Docker Compose
passes the root `.env` file to the frontend service.

API keys are read only from server environment variables referenced by admin
configuration. They are never returned by the API or stored in audit snapshots.
The DeepSeek origin is fixed to `https://api.deepseek.com`; administrators may
select only `deepseek-v4-flash` or `deepseek-v4-pro`. User and administrator
browser sessions use separate credentials, so both areas can stay signed in in
the same browser.

The development admin seed command refuses to run outside `APP_ENV=development`.
Keep its password in the ignored local `.env`, then open `/admin/login`.

## Production deployment

Production deployment does not create an environment file automatically. Copy
`deploy/production.env.example` to `deploy/.env.production`, provide a strong
database password and JWT secret, both PandaData credentials, and at least one
real text provider. DeepSeek uses `DEEPSEEK_API_KEY` with its model selected
through the existing administrator whitelist; StepFun uses `STEPFUN_API_KEY`
with the fixed `step-3.5-flash-2603` profile model; ARK requires both
`ARK_API_KEY` and `ARK_MODEL`.

Validate the file before deploying:

```bash
deploy/check-production-config.sh deploy/.env.production
docker compose --env-file deploy/.env.production \
  -f deploy/docker-compose.prod.yml config --quiet
```

Container health and the final deployment probe both use `/api/ready`.
Readiness failures therefore fail the deployment instead of being replaced by
the shallow application `/health` response.

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

## Trading simulation API

The FastAPI application is the single backend entry point. It keeps the
onboarding API under `/api/v1/*` and mounts the trading simulation API under
`/api/finance/*`, including `/live`, `/market/*`, `/workspace/*`, and
`/simulation/*`. The market endpoints use PandaData; account and execution
facts are explicitly simulation-only.

Install both dependency sets before starting the backend because the trading
runtime uses the bundled research framework:

```bash
cd backend
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e ".[dev]"
cd ..
make backend
```

`DATABASE_URL` enables the persisted workspace and simulation APIs. Their
unique owner is the `sub` claim from the verified Bearer JWT; clients cannot
select an owner through headers or configuration. PandaData credentials enable
live market requests. Missing configuration produces explicit readiness or
service errors; it never substitutes fabricated market data.
