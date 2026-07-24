# Backend architecture overview

The backend is a single Python process that composes two ASGI applications.

## One public application, one mounted sub-application

| Application | Code location | Framework | Responsibilities |
| --- | --- | --- | --- |
| `app` | `app/` (`app/main.py`) | FastAPI | Authentication, onboarding, investment profiling, direction recommendations, admin AI settings. Serves `/api/v1/*` with typed schemas and the response envelope documented in `workbench-integration.md`. |
| `finance_app` | `finance_god/` + `server.py` | Starlette | Normalized PandaData market data (`/market/*`), persisted workspace (`/workspace/*`), simulation trading (`/simulation/*`), and the `/live`, `/ready`, `/health` probes. |

`server.py` builds `finance_app` from the `finance_god` packages (market data,
workspace routes, simulation wiring, workflow runtime). It does not expose a
module-level `app` or serve a static prototype; only `app.main:app` is a
supported ASGI entry point.

## Production entry point

`uvicorn app.main:app` is the only production entry point. `app/main.py`
imports `finance_app` and `lifespan` from `server.py`; the FastAPI lifespan
delegates to the Starlette lifespan, so the workflow runtime and market-data
services are initialized by the single process. All HTTP modules use the
`DATABASE_URL` setting and the shared engine/session factory in
`app/db/session.py`; the outer FastAPI lifespan owns and disposes that pool.
Local development uses `python -m app.startup` (via `make backend`) so an
existing listener on port 8000 fails preflight instead of allowing a second
Finance-God process to start.

The repository-root `.env` is the only implicit local configuration file.
`app.config` loads it before composing `finance_app`, making the same values
available to typed settings and direct `os.getenv` adapters.

## Route mounting and path families

`app/main.py` registers routes in this order:

1. `include_router(api_router, prefix="/api/v1")` — FastAPI routes.
2. `app.mount("/api/finance", finance_app)` — canonical prefix, used by
   `finance-api-reference.md`.
3. `app.mount("/api", finance_app)` — compatibility prefix for the frontend
   desk client, which calls `/api/market/*`, `/api/simulation/*` and
   `/api/workspace/*` with `baseURL='/api'`.

The same `finance_app` instance is mounted twice, so both path families serve
identical behavior. Ordering matters:

- `/api/finance` must be mounted before `/api`; otherwise the `/api` mount
  would capture `/api/finance/*` requests and resolve them against
  `finance_app` with a leftover `finance/` path segment, returning 404.
- `/api/v1/*` requests match the FastAPI router before either mount because
  `include_router` registers plain routes, and Starlette evaluates routes in
  registration order.

Mount behavior is verified by `tests/integration/test_route_mounting.py` and
`tests/integration/test_finance_api_mount.py`.

## Identity conventions

Simulation and workspace APIs both derive their owner from the signed Bearer
token subject. Client-supplied owner headers are ignored and cannot select
another user's data.

`/api/v1/*` uses `Authorization: Bearer <access_token>` as described in
`workbench-integration.md`.

## Related documents

- `finance-api-reference.md` — endpoint-level reference for `finance_app`.
- `workbench-integration.md` — `/api/v1` contract, response envelope and
  error codes.
