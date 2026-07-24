# Admin DeepSeek Auto Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build independent user/admin browser sessions, a real DeepSeek OpenAI-compatible adapter, and an automatic novice-friendly profile interview that stores analysis and advances after each answer.

**Architecture:** Keep backend JWT/RBAC authoritative while splitting frontend storage and HTTP clients by audience. Add a fixed-origin DeepSeek provider whose structured output is validated before the existing deterministic onboarding constraints apply. Collapse message analysis and evidence confirmation into one idempotent transaction, then simplify the Vue conversation UI around the server-owned next question.

**Tech Stack:** FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, httpx, pytest, Vue 3, Pinia, Vue Router, Axios, Vitest, Playwright CLI.

---

## File Map

- `backend/app/api/v1/auth.py`: shared credential verification and the admin-only login endpoint.
- `backend/scripts/seed_dev_admin.py`: idempotent, development-only admin creation/update command.
- `backend/app/config.py`: server-only DeepSeek credential access without exposing secrets.
- `backend/app/schemas/admin.py`: controlled provider/model configuration contracts.
- `backend/app/services/ai_orchestrator.py`: DeepSeek HTTP adapter, structured parsing, novice prompt context, and provider registry.
- `backend/app/api/v1/admin.py`: safe configuration responses, validation, and real connection probe.
- `backend/app/schemas/onboarding.py`: message/session contracts without pending confirmation.
- `backend/app/models/onboarding.py`: persistent session shape after pending evidence removal.
- `backend/app/api/v1/onboarding.py`: one-request automatic evidence merge and next-question transition.
- `backend/alembic/versions/20260724_0003_auto_profile.py`: removal of the obsolete pending evidence column.
- `frontend/src/api/client.ts`: audience-specific Axios clients and 401 handling.
- `frontend/src/api/index.ts`: normal auth, admin auth, user API, and admin API bindings.
- `frontend/src/stores/adminAuth.ts`: independent admin token/user state.
- `frontend/src/router.ts`: `/admin/login` and independent route guards.
- `frontend/src/bootstrap.ts`, `frontend/src/main.ts`: hydrate user and admin sessions before routing.
- `frontend/src/views/AdminLoginView.vue`: dedicated administrator login.
- `frontend/src/views/AdminSettingsView.vue`: controlled DeepSeek settings, connection test, and admin logout.
- `frontend/src/stores/onboarding.ts`: direct answer flow and idempotent retry without confirmation state.
- `frontend/src/views/OnboardingView.vue`: no evidence panel, mock disclosure, and automatic latest-question scrolling.
- Backend and frontend test files named below: regression and contract coverage.

## Task 1: Admin-only login and development account

**Files:**
- Modify: `backend/app/api/v1/auth.py`
- Create: `backend/scripts/seed_dev_admin.py`
- Modify: `backend/tests/integration/test_auth_api.py`
- Create: `backend/tests/unit/test_seed_dev_admin.py`

- [x] **Step 1: Write failing admin login tests**

Add tests proving an active admin receives a token, a normal user gets a non-enumerating 403, and inactive/wrong credentials fail without revealing account state:

```python
response = client.post(
    "/api/v1/auth/admin/login",
    json={"email": "admin@example.com", "password": "correct-horse-123"},
)
assert response.status_code == 200
assert response.json()["data"]["user"]["role"] == "admin"

denied = client.post(
    "/api/v1/auth/admin/login",
    json={"email": "reader@example.com", "password": "correct-horse-123"},
)
assert denied.status_code == 403
assert denied.json()["error"]["message"] == "管理员邮箱或密码错误"
```

- [x] **Step 2: Verify the new endpoint test is red**

Run: `cd backend && .venv/bin/pytest tests/integration/test_auth_api.py -q`

Expected: admin login tests fail with HTTP 404 because `/auth/admin/login` does not exist.

- [x] **Step 3: Implement shared login verification and admin endpoint**

Extract credential lookup into a private helper and add:

```python
@router.post("/admin/login", response_model=ApiResponse[AuthData])
async def admin_login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await _authenticated_user(body, db)
    if user is None or user.role != "admin":
        raise HTTPException(status_code=403, detail="管理员邮箱或密码错误")
    return _auth_response(user)
```

Keep ordinary login behavior unchanged and update `last_login_at` only after the role check succeeds.

- [x] **Step 4: Write red tests for the seed command guard and idempotency**

Test that production is rejected, missing/weak passwords are rejected, and two development runs leave one active admin with a newly verified password.

- [x] **Step 5: Implement the seed command**

Implement `main()` around an async `seed_dev_admin(session, email, password)` function. Read `APP_ENV`, `DEV_ADMIN_EMAIL`, and `DEV_ADMIN_PASSWORD`; require development and a password of at least 12 characters; create or update `role="admin"`, `status="active"`, and `hashed_password=hash_password(password)`.

- [x] **Step 6: Run focused auth and seed tests**

Run: `cd backend && .venv/bin/pytest tests/integration/test_auth_api.py tests/unit/test_seed_dev_admin.py -q`

Expected: all focused tests pass.

## Task 2: Controlled DeepSeek configuration and adapter

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/schemas/admin.py`
- Modify: `backend/app/services/ai_orchestrator.py`
- Modify: `backend/app/api/v1/admin.py`
- Modify: `backend/tests/unit/test_ai_adapters.py`
- Modify: `backend/tests/integration/test_admin_api.py`
- Modify: `backend/tests/integration/test_runtime_ai_config.py`

- [x] **Step 1: Write failing schema and safe-config tests**

Assert that text accepts only `mock`/`deepseek`, DeepSeek accepts only the two approved model names, non-development mock is rejected, the response contains `base_url`, and `api_key_configured` uses `settings.deepseek_api_key` rather than `os.getenv`.

```python
with pytest.raises(ValidationError):
    AISettingsUpdate(capability="text", provider="deepseek", model_name="arbitrary")
```

- [x] **Step 2: Run schema/admin tests and verify red**

Run: `cd backend && .venv/bin/pytest tests/integration/test_admin_api.py tests/unit/test_config_validation.py -q`

Expected: failures for unrestricted provider/model values and missing `base_url`.

- [x] **Step 3: Implement controlled configuration contracts**

Add `deepseek_api_key: SecretStr | None` to `Settings`, fixed constants:

```python
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODELS = {"deepseek-v4-flash", "deepseek-v4-pro"}
```

Validate capability/provider/model combinations in `AISettingsUpdate` and `AIConnectionTest`. Return the fixed base URL for text settings and never serialize the secret.

- [x] **Step 4: Write failing DeepSeek adapter tests with `httpx.MockTransport`**

Cover Authorization header presence without logging it, `/chat/completions`, selected model, JSON response parsing, 401, 429, 5xx, timeout, invalid JSON, unknown dimension, and out-of-range confidence.

```python
transport = httpx.MockTransport(handler)
provider = DeepSeekTextProvider(api_key="secret", transport=transport)
result = await provider.create(model_name="deepseek-v4-flash", system_prompt="prompt").respond(...)
assert result.target_dimension is ProfileDimension.RISK_TOLERANCE
```

- [x] **Step 5: Implement DeepSeek provider and structured response parsing**

Create a Pydantic wire model for the provider JSON, an error type with stable codes, and an async orchestrator that calls the fixed HTTPS origin with explicit timeouts and `response_format={"type":"json_object"}`. Convert only validated output into `AITurnResult`.

- [x] **Step 6: Register DeepSeek and implement real probe**

Build the registry from current settings so `deepseek` is registered only when a key is configured. `probe()` must execute a minimal real completion and report `credential_status="configured"`; do not fall back to mock.

- [x] **Step 7: Add novice prompt context tests and implementation**

Assert `investment_experience="none"` produces a prompt instruction containing “生活化场景”“一次只问一个概念”“不把不懂视为低风险”, while advanced experience permits detail without requiring jargon. Pass objective profile context from onboarding to `respond()`.

- [x] **Step 8: Run adapter and admin suites**

Run: `cd backend && .venv/bin/pytest tests/unit/test_ai_adapters.py tests/integration/test_admin_api.py tests/integration/test_runtime_ai_config.py -q`

Expected: all focused tests pass without secrets in captured logs.

## Task 3: Automatic profile state transition

**Files:**
- Modify: `backend/app/schemas/onboarding.py`
- Modify: `backend/app/models/onboarding.py`
- Modify: `backend/app/api/v1/onboarding.py`
- Create: `backend/alembic/versions/20260724_0003_auto_profile.py`
- Modify: `backend/tests/integration/test_evidence_confirmation.py`
- Modify: `backend/tests/integration/test_onboarding_api.py`
- Modify: `backend/tests/integration/test_ai_failures.py`
- Modify: `backend/tests/integration/test_idempotency.py`
- Modify: `backend/tests/integration/test_openapi.py`
- Modify: `backend/tests/unit/test_migration_contract.py`

- [ ] **Step 1: Replace confirmation tests with failing automatic-merge tests**

After one message, assert `profile_evidence`, `dimension_scores`, `followup_counts`, `round_count`, assistant message, and `current_question` are updated in the returned session. Assert `pending_profile_evidence` and `confirm_pending` are absent from response and OpenAPI schemas.

```python
turn = client.post(url, headers=headers, json={"request_id": str(uuid.uuid4()), "content": "我可以长期持有并接受波动", "input_mode": "text"})
state = turn.json()["data"]["session"]
assert state["profile_evidence"]["risk_tolerance"] == 0.8
assert state["round_count"] == 1
assert "pending_profile_evidence" not in state
```

- [ ] **Step 2: Run focused onboarding tests and verify red**

Run: `cd backend && .venv/bin/pytest tests/integration/test_evidence_confirmation.py tests/integration/test_idempotency.py tests/integration/test_openapi.py -q`

Expected: failures because evidence remains pending and confirmation fields still exist.

- [ ] **Step 3: Simplify schemas and model**

Remove `confirm_pending`, `PendingProfileEvidence`, and the public/session model pending field. Keep content/input mode validation and request UUID idempotency.

- [ ] **Step 4: Implement one-request automatic merge**

In the content branch, validate `AITurnResult`, merge the current dimension value into `session.profile_evidence`, update scores/counts/rounds/completeness, persist both messages, and set `current_dimension/current_question` or ready state before flushing. Remove confirmation/rejection branches.

- [ ] **Step 5: Preserve failure and idempotency semantics**

Tests must prove adapter/validation failures leave round count, evidence, and current question unchanged, and a repeated successful `request_id` returns the original result without duplicate messages or increments.

- [ ] **Step 6: Add the Alembic migration**

Create revision `20260724_0003`, down revision `20260724_0002`, with upgrade dropping `pending_profile_evidence` and downgrade recreating it as non-null JSON with server default `{}` before removing the default.

- [ ] **Step 7: Run all onboarding, failure, OpenAPI, and migration tests**

Run: `cd backend && .venv/bin/pytest tests/integration/test_onboarding_api.py tests/integration/test_evidence_confirmation.py tests/integration/test_ai_failures.py tests/integration/test_idempotency.py tests/integration/test_openapi.py tests/unit/test_migration_contract.py -q`

Expected: all focused tests pass.

## Task 4: Independent frontend admin session

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/index.ts`
- Create: `frontend/src/stores/adminAuth.ts`
- Modify: `frontend/src/router.ts`
- Modify: `frontend/src/bootstrap.ts`
- Modify: `frontend/src/main.ts`
- Create: `frontend/src/views/AdminLoginView.vue`
- Modify: `frontend/src/tests/core-behavior.spec.ts`
- Modify: `frontend/src/tests/views.spec.ts`

- [ ] **Step 1: Write failing storage/client/route tests**

Assert user and admin stores use distinct keys, `adminApi` sends the admin token, each 401 clears only its own keys, `/admin/ai-settings` redirects to `/admin/login` without an admin session, and a normal user session remains intact.

```ts
localStorage.setItem('finance-god-token', 'user-token')
await router.push('/admin/ai-settings')
expect(router.currentRoute.value.path).toBe('/admin/login')
expect(localStorage.getItem('finance-god-token')).toBe('user-token')
```

- [ ] **Step 2: Run frontend core tests and verify red**

Run: `cd frontend && npm test -- --run src/tests/core-behavior.spec.ts src/tests/views.spec.ts`

Expected: failures because no admin store/login route or audience-specific client exists.

- [ ] **Step 3: Create audience-specific clients**

Factor client creation into `createApiClient({tokenKey, userKey, loginPath})`; export normal `api` and `adminHttpApi`. Bind auth/register/onboarding/profile to normal API and admin login/settings to admin API.

- [ ] **Step 4: Implement the admin auth store**

Use `finance-god-admin-token` and `finance-god-admin-user`; `login()` calls `/auth/admin/login`, rejects non-admin responses defensively, `hydrate()` calls `/auth/me` through the admin client, and `logout()` clears only admin keys.

- [ ] **Step 5: Implement independent routes and bootstrap hydration**

Add `/admin/login`; guard management routes using admin storage only. Bootstrap both existing user and admin sessions before mount without letting one hydrate failure block the other.

- [ ] **Step 6: Build the admin login view**

Provide email/password inputs, password visibility control, loading/error states, redirect to `/admin/ai-settings`, and no registration option. Keep headings compact and use existing icon/button patterns.

- [ ] **Step 7: Run frontend auth/view tests**

Run: `cd frontend && npm test -- --run src/tests/core-behavior.spec.ts src/tests/views.spec.ts`

Expected: independent session and login view tests pass.

## Task 5: Controlled admin AI settings UI

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/services/admin.ts`
- Modify: `frontend/src/views/AdminSettingsView.vue`
- Modify: `frontend/src/tests/core-behavior.spec.ts`
- Modify: `frontend/src/tests/views.spec.ts`

- [ ] **Step 1: Write failing controlled-settings tests**

Assert provider/model are selects, DeepSeek models are the only production text choices, Base URL is read-only, no API key input exists, configured status renders, and admin logout does not remove `finance-god-token`.

- [ ] **Step 2: Verify UI tests are red**

Run: `cd frontend && npm test -- --run src/tests/core-behavior.spec.ts src/tests/views.spec.ts`

Expected: failures because current settings use free-text provider/model/key-reference inputs.

- [ ] **Step 3: Update TypeScript contracts and payload mapping**

Add `base_url`, controlled provider/model unions, and remove editable key reference/clear fields. Send `api_key_ref: "DEEPSEEK_API_KEY"` only for DeepSeek text configuration; never accept a secret value.

- [ ] **Step 4: Implement the controlled settings form**

Use select controls for provider/model, reset model when provider changes, display fixed Base URL and credential status, preserve prompt/round controls, add admin logout, and show “模拟 AI” when mock is active.

- [ ] **Step 5: Run UI tests, type-check, and build**

Run: `cd frontend && npm test -- --run src/tests/core-behavior.spec.ts src/tests/views.spec.ts && npm run type-check && npm run build`

Expected: tests, type-check, and production build pass.

## Task 6: Direct conversation UI and latest-message behavior

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/stores/onboarding.ts`
- Modify: `frontend/src/views/OnboardingView.vue`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/tests/core-behavior.spec.ts`
- Modify: `frontend/src/tests/views.spec.ts`

- [ ] **Step 1: Write failing direct-flow tests**

Assert session types contain no pending evidence, sending content never sends `confirm_pending`, no evidence panel renders, a failure restores the textarea value and reuses the request ID, and a successful turn scrolls the message stream to its `scrollHeight`.

- [ ] **Step 2: Run conversation tests and verify red**

Run: `cd frontend && npm test -- --run src/tests/core-behavior.spec.ts src/tests/views.spec.ts`

Expected: failures for pending confirmation logic and missing auto-scroll.

- [ ] **Step 3: Simplify API types and onboarding store**

Remove `PendingEvidence`, `EvidenceConfirmation`, `confirmEvidence`, and `pendingConfirmation`. Keep the existing `pendingContent` tuple so retries reuse the same UUID; assign the returned session and append messages immediately on success.

- [ ] **Step 4: Simplify the conversation view**

Remove evidence UI and confirm handlers. Always show the composer while the session is in conversation, preserve the draft on error, show a visible mock badge when `provider_name === "mock"`, and use a template ref plus `nextTick()` to scroll after messages/current question change.

- [ ] **Step 5: Run frontend full verification**

Run: `cd frontend && npm test && npm run type-check && npm run build`

Expected: all frontend tests, type-check, and build pass with no Vue warnings.

## Task 7: Environment, migration, and local development setup

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `backend/Makefile`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add non-secret configuration documentation**

Document `DEEPSEEK_API_KEY`, `DEV_ADMIN_EMAIL`, and `DEV_ADMIN_PASSWORD` without placing real values in tracked files. Add `make seed-dev-admin` and explain the development-only guard.

- [ ] **Step 2: Put local secrets only in ignored `.env`**

Set the user-provided DeepSeek Key and a generated strong development admin password in local `.env`. Do not print either value during commands or tests.

- [ ] **Step 3: Apply migration and seed the test admin**

Run: `cd backend && .venv/bin/alembic upgrade head`

Run: `cd backend && .venv/bin/python scripts/seed_dev_admin.py`

Expected: database reaches `20260724_0003`; exactly one active `admin@finance-god.local` account exists.

- [ ] **Step 4: Configure DeepSeek through the admin API**

Use the local admin session to save text provider `deepseek`, model `deepseek-v4-flash`, key reference `DEEPSEEK_API_KEY`, and the approved prompt version. Do not include the Key in the request.

- [ ] **Step 5: Run the real connection probe**

Expected: probe returns `ok=true`, adapter identifies the DeepSeek implementation, selected model is Flash, and the response contains no secret.

## Task 8: Full regression and browser acceptance

**Files:**
- Update only if verification exposes a tested defect in files already listed above.

- [ ] **Step 1: Run complete backend verification**

Run: `cd backend && .venv/bin/pytest -q`

Run: `cd backend && .venv/bin/alembic check`

Run: `cd backend && .venv/bin/alembic upgrade head --sql >/tmp/finance-god-auto-profile-migration.sql`

Expected: tests pass, Alembic reports no new upgrade operations, and offline SQL generation exits 0.

- [ ] **Step 2: Run complete frontend verification**

Run: `cd frontend && npm test && npm run type-check && npm run build`

Expected: all tests pass and production build exits 0.

- [ ] **Step 3: Restart backend and frontend with the migrated schema**

Verify `/health`, `/openapi.json`, `/admin/login`, and `/login` return successful responses.

- [ ] **Step 4: Verify simultaneous sessions in a real browser**

Log in as a normal user, then log in as `admin@finance-god.local` at `/admin/login` in the same browser context. Confirm both `/app/exe` and `/admin/ai-settings` remain usable and each logout affects only its own area.

- [ ] **Step 5: Verify real DeepSeek onboarding**

Complete objective questions as a novice user, submit at least one conversational answer, and confirm the response advances directly to a new life-scenario question with no confirmation panel. Inspect the API response to verify evidence was stored and pending evidence is absent.

- [ ] **Step 6: Verify responsive and secret-safe behavior**

Capture desktop and 375px mobile screenshots; verify latest-question scroll position, no overlap, and no console errors. Search captured console/backend logs and response bodies for key prefixes and ensure none are present.

- [ ] **Step 7: Report credentials and security follow-up**

Provide the local development admin email/password to the user through the final response, state that they exist only in ignored local configuration/database, and remind them to rotate the DeepSeek Key before production use.

## Execution Notes

- The current branch contains a large pre-existing dirty refactor. Do not reset, clean, or stage unrelated files.
- Do not make intermediate Git commits from modified/untracked implementation files unless the user explicitly approves a precise staging scope; many target files already contain user work relative to HEAD.
- Every production change follows red-green-refactor: add the narrow failing test, observe the expected failure, implement the minimum behavior, then rerun focused and broader suites.
