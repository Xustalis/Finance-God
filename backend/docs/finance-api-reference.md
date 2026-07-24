# Finance API reference

The FastAPI process (`app.main:app`) is the only public backend entry point.
Its generated OpenAPI document is available at `/openapi.json` and interactive
documentation at `/docs`. Onboarding endpoints use `/api/v1`; the trading
simulation sub-application uses `/api/finance`.

## Service and market data

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/finance/live` | Liveness probe; no external dependency is required. |
| `GET` | `/api/finance/ready` | Readiness probe for the workflow runtime and PandaData. Returns `503` when configuration is incomplete. |
| `GET` | `/api/finance/health` | Combined service state; identifies PandaData and simulation mode. |
| `GET` | `/api/finance/market/quotes?symbols=000001.SZ,...` | Normalized PandaData quotes. |
| `GET` | `/api/finance/market/bars?symbol=000001.SZ&limit=80` | Normalized bars with freshness and quality metadata. |
| `GET` | `/api/finance/market/catalog` | Audited PandaData capability catalog. |

Market requests never return fabricated values. A failed upstream request has a
non-2xx status and an `error.code`; clients must display this state rather than
reusing stale values as current data.

## Persisted simulation APIs

`/api/finance/workspace/*` provides server-owned watchlists, notifications and
notification preferences. It uses the shared `DATABASE_URL`; the unique owner
comes from the verified Bearer JWT `sub`, and the browser cannot override it.

`/api/finance/simulation/*` provides simulation-only accounts, order drafts,
risk confirmation, order submission, reconciliation, cancellation and fills.
It uses the same verified Bearer JWT `sub` as the owner. Mutating calls require
`idempotency-key`; client-supplied owner headers are ignored.
The account, order and fill data is simulation data, not broker execution data.

## Running and verifying

```bash
cd backend
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/uvicorn app.main:app --reload

curl http://127.0.0.1:8000/api/finance/live
curl http://127.0.0.1:8000/openapi.json
```

The repository verifies the mount and route behavior in
`tests/integration/test_finance_api_mount.py`, and validates generated OpenAPI
contracts in `tests/integration/test_openapi.py`.
