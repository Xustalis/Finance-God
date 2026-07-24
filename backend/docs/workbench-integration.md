# Workbench and API integration

The machine-readable contract is served at `/openapi.json`. All `/api/v1`
operations have concrete request and response schemas. Authenticated requests
use `Authorization: Bearer <access_token>`.

## Response envelope

Successful responses use:

```json
{"success": true, "data": {}, "error": null, "meta": {}}
```

Errors use:

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "HTTP_409",
    "message": "Session is not accepting messages",
    "details": {}
  },
  "meta": {"request_id": "request UUID"}
}
```

`ErrorCode` values are `VALIDATION_ERROR`, `HTTP_400`, `HTTP_401`, `HTTP_403`,
`HTTP_404`, `HTTP_409`, `HTTP_500`, `HTTP_502`, `HTTP_503`, and
`INTERNAL_ERROR`. Both request-model and manual 422 validation failures use
`VALIDATION_ERROR`; `HTTP_422` is never emitted. A 502 means an AI provider
returned an invalid structured result. A 503 means it timed out and the session
was not advanced. All operations document typed 400, 401, 403, 404, 409, 422,
500, 502, and 503 envelopes in OpenAPI. A failed provider call does not change
confirmed profile evidence or permanently consume a provider-call allowance.

## Endpoint fields

| Endpoint | Request data | Success data |
| --- | --- | --- |
| `POST /auth/register` | `email`, `password`, optional `display_name`, `base_currency`, `region` | `access_token`, `token_type`, `user` |
| `POST /auth/login` | `email`, `password` | `access_token`, `token_type`, `user` |
| `GET /auth/me` | none | current `user` |
| `POST /onboarding/sessions` | none | resumable `SessionResponse` |
| `GET /onboarding/sessions/current` | none | active or ready `SessionResponse` |
| `PUT /onboarding/sessions/{id}/objective-profile` | all objective profile fields below | updated `SessionResponse` |
| `POST /onboarding/sessions/{id}/messages` | optional `request_id`, `content`, `input_mode`, optional `confirm_pending` | AI turn or evidence-confirmation result |
| `POST /onboarding/sessions/{id}/skip` | current sensitive `dimension` | updated `SessionResponse` |
| `POST /onboarding/sessions/{id}/complete` | none | versioned profile and five ranked recommendations |
| `GET /profiles/me/latest` | none | latest profile and recommendations |
| `POST /profiles/{id}/direction-selection` | `selected_direction` | selected recommendation |
| `GET /admin/ai-settings` | admin only | text, STT, and TTS configurations with key values redacted |
| `PUT /admin/ai-settings` | provider configuration and optional Prompt content | redacted versioned configuration |
| `POST /admin/ai-settings/test` | `capability`, `provider`, `model_name` | adapter probe result without credentials |

Objective profile fields are `gender`, `age_range`, `asset_level`,
`employment_status`, `income_range`, `debt_pressure`,
`emergency_fund_months`, `investment_experience`, `fund_horizon`, and
`loss_reaction`. `asset_level` is `A1` through `A10`.

## Enums

- `gender`: `male`, `female`, `nonbinary`, `prefer_not_to_say`
- `age_range`: `minor`, `18-25`, `26-35`, `36-45`, `46-55`, `56-65`, `65+`
- `asset_level`: `A1` through `A10`
- `employment_status`: `employed`, `self_employed`, `unemployed`, `student`, `retired`, `other`
- `income_range`: `I1` through `I10`
- `debt_pressure`: `none`, `low`, `moderate`, `high`
- `investment_experience`: `none`, `beginner`, `intermediate`, `advanced`
- `fund_horizon`: `under_1_year`, `1_3_years`, `3_5_years`, `5_plus_years`
- `loss_reaction`: `sell_all`, `reduce`, `hold`, `buy_more`
- `input_mode`: `text`, `voice`
- `capability`: `text`, `stt`, `tts`
- `profile dimension`: `risk_tolerance`, `liquidity_need`, `investment_goal`,
  `loss_behavior`, `investment_knowledge`, `income_stability`
- `selected_direction`: `cash_fixed_income`, `public_funds`, `equities`,
  `alternatives`, `long_term_insurance`
- session `status`: `active`, `ready`, `completed`
- profile `risk_level`: `conservative`, `moderate`, `growth`

Only `income_stability` is sensitive in v1. It can be skipped only while it is
the current dimension of an active conversation. Refusal is stored separately,
does not create a dimension score, and does not reduce completeness.

## Onboarding example

```http
PUT /api/v1/onboarding/sessions/SESSION_ID/objective-profile
Authorization: Bearer TOKEN
Content-Type: application/json

{
  "gender": "prefer_not_to_say",
  "age_range": "36-45",
  "asset_level": "A6",
  "employment_status": "employed",
  "income_range": "I5",
  "debt_pressure": "low",
  "emergency_fund_months": 8,
  "investment_experience": "intermediate",
  "fund_horizon": "5_plus_years",
  "loss_reaction": "hold"
}
```

The AI message response includes a validated turn:

```json
{
  "reply": "Thank you. Let us continue with the next dimension.",
  "target_dimension": "risk_tolerance",
  "sensitive": false,
  "profile_delta": {"risk_tolerance": 0.8},
  "confidence": 0.72,
  "should_continue": true,
  "end_reason": null
}
```

`profile_delta` values are in `[-1, 1]`. Provider output is first stored in
`pending_profile_evidence`; it cannot affect scoring or progress. The pending
object includes `dimension`, `value`, `confidence`, `proposed_followup_count`,
`proposed_round_count`, `should_continue`, and `end_reason`. Before sending another
answer, the client must send a standalone confirmation request with
`"confirm_pending": true` to merge it into `profile_evidence`, or `false` to
discard it:

```json
{
  "request_id": "4bc499b7-cd41-4c4f-8954-60dcdde74641",
  "confirm_pending": true
}
```

The confirmation response contains `accepted`, `confirmed_evidence`, and the
updated session. Repeating the same confirmation `request_id` returns the
original result. A confirmation without `request_id`, or a request combining
`confirm_pending` with nonblank `content`, returns typed 422. After confirmation
succeeds, send the next content as a separate request. Confirmation atomically
applies confidence, followup count, round count, completeness, current
dimension, and terminal consequences. Rejection applies none of them and
recomputes progress from confirmed state. Completion and skipping are blocked
while evidence is pending.
The server, not the provider, controls the current dimension, two-followup cap,
completeness, and terminal state. A session becomes `ready` only after at least
six interactions and a terminal condition. AI turns are rejected after that
point, while a final pending-evidence confirmation remains available.

Clients should send a UUID `request_id` with every content message. Repeating a
completed request ID returns the original response without another provider
call. A duplicate request still being processed returns 409. The server writes
a leased request claim and reserves one `turn_count` slot before provider I/O,
then applies the validated result in a short optimistic write transaction.
Timeouts, provider exceptions, invalid output, and write conflicts remove the
claim and return the reserved slot transactionally. A claim abandoned by a
crashed worker expires after two minutes and is recovered by the next request.
`turn_count` is therefore the absolute successful provider-turn counter and
cannot exceed `max_rounds`; `round_count` counts only confirmed evidence and
does not advance when evidence is rejected.

Deterministic rules consume every confirmed dimension. Risk tolerance and loss
behavior affect drawdown capacity; liquidity need reduces illiquid and volatile
allocations; investment goal changes growth weighting; investment knowledge
changes direct-equity and alternatives weighting; income stability changes the
capacity for long-horizon risk. Identical confirmed inputs always produce the
same archetype and five-direction ordering.

## Admin configuration example

```json
{
  "capability": "text",
  "provider": "mock",
  "model_name": "mock-structured-v2",
  "api_key_ref": "FINANCE_GOD_TEXT_API_KEY",
  "prompt_version": "v2",
  "prompt_content": "Versioned server-side onboarding policy text...",
  "min_rounds": 6,
  "max_rounds": 10,
  "enabled": true
}
```

`api_key_ref` names a server environment variable. Neither the reference nor
its value is returned or written to audit snapshots. Browser STT/TTS adapters
are reserved server-side interfaces; v1 speech runs in the browser. Unsupported
text providers are rejected. The mock text provider can be enabled only when
`APP_ENV=development`.

Prompt versions are immutable. Reusing a version with different content returns
409; create a new version instead. Existing sessions retain their stored Prompt
version, immutable Prompt ID (when database-backed), SHA-256 hash, and server-side
content snapshot. Runtime never re-reads mutable external Prompt state. Enabling
a non-built-in text Prompt version that does not exist returns 409. Prompt
creation writes a separate `prompt_version.create` audit record
containing only version/active metadata, never Prompt content or credentials.

## Workbench handoff

Only after direction selection succeeds, the browser shell sends:

```ts
type ProfileCompletedMessage = {
  type: "FINANCE_GOD_PROFILE_COMPLETED";
  schemaVersion: "1.0";
  payload: {
    profileId: string;
    sessionId: string;
    selectedDirection:
      | "cash_fixed_income"
      | "public_funds"
      | "equities"
      | "alternatives"
      | "long_term_insurance";
    archetypeCode: string;
    riskLevel: "conservative" | "moderate" | "growth";
    completeness: number;
  };
};
```

Send only to configured `WORKBENCH_ORIGIN`; never use `"*"`. Do not include
messages, objective answers, profile evidence, key references, or other
sensitive fields in `postMessage`.

## Development database reset

The reset command is intentionally guarded and accepts only a local PostgreSQL
database named `finance_god` or `finance_god_dev` while
`APP_ENV=development`:

```bash
APP_ENV=development \
DATABASE_URL_SYNC=postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/finance_god_dev \
./scripts/reset_dev_db.sh --check

APP_ENV=development \
DATABASE_URL_SYNC=postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/finance_god_dev \
make reset-dev-db
```

`--check` performs validation only. The reset command drops and recreates the
validated database through the `postgres` maintenance database, then runs
`alembic upgrade head`.

The PostgreSQL migration round-trip test is opt-in and accepts only a dedicated
database named exactly `finance_god_test`:

```bash
FINANCE_GOD_POSTGRES_TEST_URL=postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/finance_god_test \
.venv/bin/pytest tests/integration/test_postgres_migrations.py -q
```

It runs upgrade, schema assertions, downgrade, and a final upgrade. Without the
environment variable, the test is skipped and the SQLite test suite remains
self-contained.
