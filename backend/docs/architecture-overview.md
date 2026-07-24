# Backend architecture overview

The backend is a single Python process that composes two ASGI applications.

## Two applications, one process

| Application | Code location | Framework | Responsibilities |
| --- | --- | --- | --- |
| `app` | `app/` (`app/main.py`) | FastAPI | Authentication, onboarding, investment profiling, direction recommendations, admin AI settings. Serves `/api/v1/*` with typed schemas and the response envelope documented in `workbench-integration.md`. |
| `finance_app` | `finance_god/` + `server.py` | Starlette | Normalized PandaData market data (`/market/*`), persisted workspace (`/workspace/*`), simulation trading (`/simulation/*`), and the `/live`, `/ready`, `/health` probes. |

`server.py` builds `finance_app` from the `finance_god` packages (market data,
workspace routes, simulation wiring, workflow runtime). It also defines a
standalone Starlette `app` that mounts `finance_app` under `/api` and serves
the `prototype/` static directory; that standalone app is a reusable component
and is not deployed on its own.

## Production entry point

`uvicorn app.main:app` is the only production entry point. `app/main.py`
imports `finance_app` and `lifespan` from `server.py`; the FastAPI lifespan
delegates to the Starlette lifespan, so the workflow runtime, database engine
and market-data services are initialized and disposed by the single process.

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

The two sub-systems inside `finance_app` resolve identity differently:

- Simulation APIs (`/simulation/*`): every mutating call must send the
  `x-finance-god-owner-id` request header, plus `idempotency-key`. The header
  is defined in `finance_god/api/simulation.py` and scopes accounts, orders
  and fills to one owner.
- Workspace APIs (`/workspace/*`): the owner is fixed by the
  `FINANCE_GOD_WORKSPACE_OWNER_ID` environment variable, resolved by
  `_workspace_owner` in `server.py`. The browser cannot choose the owner;
  any client-sent owner header is ignored for workspace routes.

`/api/v1/*` uses `Authorization: Bearer <access_token>` as described in
`workbench-integration.md`.

## Related documents

- `finance-api-reference.md` — endpoint-level reference for `finance_app`.
- `workbench-integration.md` — `/api/v1` contract, response envelope and
  error codes.
