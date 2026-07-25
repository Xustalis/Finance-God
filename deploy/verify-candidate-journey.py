#!/usr/bin/env python3
"""Exercise the production candidate-research journey with a temporary user."""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class JourneyVerificationError(RuntimeError):
    """A required user-journey contract did not hold."""


TERMINAL_STATUSES = {
    "completed",
    "failed",
    "timed_out",
    "cancelled",
    "attention_required",
    "blocked",
}

PROFILE_ANSWERS = {
    "risk_tolerance": "我能接受约百分之二十的阶段性回撤，会依据长期计划复核而不是恐慌卖出。",
    "liquidity_need": "未来五年以上没有大额资金用途，已准备十二个月应急资金。",
    "investment_goal": "目标是十年以上参与权益市场增长，重视长期复利而不是短期预测。",
    "loss_behavior": "下跌时先检查基本面和组合集中度，投资逻辑未变时继续持有并定期再平衡。",
    "investment_knowledge": "我理解股票估值、分散化、波动和最大回撤，也清楚历史收益不代表未来。",
    "income_stability": "收入稳定、负债压力低，投资资金与日常支出相互隔离。",
}


class JsonClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token: str | None = None

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "Finance-God-Journey-Verification",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode()
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=45) as response:
                status = response.status
                raw = response.read()
        except HTTPError as error:
            status = error.code
            raw = error.read()
        except (TimeoutError, URLError) as error:
            raise JourneyVerificationError(f"{method} {path} request failed: {error}") from error
        if status not in expected:
            detail = raw[:600].decode("utf-8", errors="replace")
            raise JourneyVerificationError(
                f"{method} {path} returned HTTP {status}, expected {expected}: {detail}"
            )
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise JourneyVerificationError(f"{method} {path} did not return JSON") from error
        if not isinstance(payload, dict):
            raise JourneyVerificationError(f"{method} {path} did not return an object")
        return payload


def api_data(payload: dict[str, Any], label: str) -> dict[str, Any]:
    value = payload.get("data")
    if not isinstance(value, dict):
        raise JourneyVerificationError(f"{label} response is missing data")
    return value


def require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JourneyVerificationError(f"{label} must be a non-empty string")
    return value.strip()


def complete_profile(client: JsonClient) -> tuple[dict[str, Any], str]:
    session = api_data(
        client.request("POST", "/api/v1/onboarding/sessions", expected=(200, 201)),
        "create onboarding session",
    )
    session_id = require_text(session.get("id"), "session.id")
    session = api_data(
        client.request(
            "PUT",
            f"/api/v1/onboarding/sessions/{quote(session_id)}/objective-profile",
            body={
                "gender": "prefer_not_to_say",
                "age_range": "36-45",
                "asset_level": "A6",
                "employment_status": "employed",
                "income_range": "I7",
                "debt_pressure": "low",
                "emergency_fund_months": 12,
                "investment_experience": "advanced",
                "fund_horizon": "5_plus_years",
                "loss_reaction": "hold",
            },
        ),
        "objective profile",
    )
    for _ in range(12):
        if session.get("status") == "ready":
            break
        dimension = require_text(session.get("current_dimension"), "current_dimension")
        answer = PROFILE_ANSWERS.get(
            dimension,
            "我的选择以长期目标、风险承受能力和真实数据为依据，并保留充分应急资金。",
        )
        turn = api_data(
            client.request(
                "POST",
                f"/api/v1/onboarding/sessions/{quote(session_id)}/messages",
                body={
                    "request_id": str(uuid.uuid4()),
                    "content": answer,
                    "input_mode": "text",
                },
            ),
            "onboarding message",
        )
        next_session = turn.get("session")
        if not isinstance(next_session, dict):
            raise JourneyVerificationError("onboarding turn is missing session")
        session = next_session
    if session.get("status") != "ready":
        raise JourneyVerificationError(
            f"onboarding did not become ready after 12 turns: {session.get('status')}"
        )
    completed = api_data(
        client.request(
            "POST",
            f"/api/v1/onboarding/sessions/{quote(session_id)}/complete",
        ),
        "complete profile",
    )
    profile = completed.get("profile")
    recommendations = completed.get("recommendations")
    if not isinstance(profile, dict) or not isinstance(recommendations, list):
        raise JourneyVerificationError("completed profile response is incomplete")
    profile_id = require_text(profile.get("id"), "profile.id")
    equity = next(
        (
            item
            for item in recommendations
            if isinstance(item, dict) and item.get("direction") == "equities"
        ),
        None,
    )
    if equity is None:
        raise JourneyVerificationError("test persona did not receive an equities direction")
    client.request(
        "POST",
        f"/api/v1/profiles/{quote(profile_id)}/direction-selection",
        body={"selected_direction": "equities"},
    )
    return profile, session_id


def verify_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise JourneyVerificationError(
            f"candidate list is empty: {payload.get('unavailable_reason')}"
        )
    verified: list[dict[str, Any]] = []
    for index, item in enumerate(candidates):
        if not isinstance(item, dict):
            raise JourneyVerificationError(f"candidates[{index}] is not an object")
        if item.get("provider") != "PandaData":
            raise JourneyVerificationError(
                f"candidates[{index}].provider must be PandaData"
            )
        require_text(item.get("as_of"), f"candidates[{index}].as_of")
        dimensions = item.get("dimensions")
        if not isinstance(dimensions, list) or not dimensions:
            raise JourneyVerificationError(
                f"candidates[{index}] is missing explanation dimensions"
            )
        verified.append(item)
    return verified


def run(base_url: str, timeout_seconds: int) -> dict[str, Any]:
    client = JsonClient(base_url)
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    email = f"codex-journey-{timestamp}-{secrets.token_hex(3)}@example.com"
    password = f"Fg!{secrets.token_urlsafe(18)}"
    auth = api_data(
        client.request(
            "POST",
            "/api/v1/auth/register",
            body={
                "email": email,
                "password": password,
                "display_name": f"候选旅程测试 {timestamp}",
            },
            expected=(201,),
        ),
        "register",
    )
    client.token = require_text(auth.get("access_token"), "access_token")
    user = auth.get("user")
    if not isinstance(user, dict):
        raise JourneyVerificationError("register response is missing user")
    user_id = require_text(user.get("id"), "user.id")

    profile, session_id = complete_profile(client)
    bootstrap = client.request(
        "GET",
        "/api/desk/bootstrap?" + urlencode(
            {"section": "watchlist", "symbol": "000001.SZ"}
        ),
    )
    profile_projection = bootstrap.get("profile_projection")
    capabilities = bootstrap.get("capabilities")
    if not isinstance(profile_projection, dict) or not profile_projection.get("available"):
        raise JourneyVerificationError("desk bootstrap has no available profile projection")
    if profile_projection.get("selected_direction") != "equities":
        raise JourneyVerificationError("desk bootstrap did not retain equities selection")
    if not isinstance(capabilities, dict):
        raise JourneyVerificationError("desk bootstrap is missing capabilities")
    for capability in ("market_data", "workflow_create", "workflow_worker"):
        if capabilities.get(capability) is not True:
            raise JourneyVerificationError(f"desk capability {capability} is not available")
    context_version = require_text(bootstrap.get("context_version"), "context_version")

    created = client.request(
        "POST",
        "/api/workflows/desk",
        body={
            "request_intent": "结合画像生成可研究候选",
            "section": "watchlist",
            "symbol": "000001.SZ",
            "context_version": context_version,
        },
        expected=(200, 201),
        idempotency_key=f"candidate-journey-{timestamp}",
    )
    run_id = require_text(created.get("run_id"), "workflow.run_id")
    deadline = time.monotonic() + timeout_seconds
    run = created
    while run.get("status") not in TERMINAL_STATUSES and time.monotonic() < deadline:
        revision = int(run.get("revision") or 0)
        progress = client.request(
            "GET",
            f"/api/workflows/{quote(run_id)}/progress?"
            + urlencode({"after_revision": revision, "wait_seconds": 20}),
        )
        run = client.request("GET", f"/api/workflows/{quote(run_id)}")
        if progress.get("status") in TERMINAL_STATUSES:
            break
    if run.get("status") != "completed":
        raise JourneyVerificationError(
            f"workflow ended as {run.get('status')}: {run.get('errors')}"
        )
    artifact = run.get("final_artifact")
    if not isinstance(artifact, dict):
        raise JourneyVerificationError("completed workflow has no final artifact")
    if artifact.get("object_type") != "ResearchCandidateSet":
        raise JourneyVerificationError(
            f"unexpected artifact type: {artifact.get('object_type')}"
        )
    artifact_id = require_text(artifact.get("object_id"), "artifact.object_id")
    artifact_version = require_text(artifact.get("version"), "artifact.version")
    evidence = client.request(
        "GET",
        f"/api/evidence/{quote('ResearchCandidateSet')}/{quote(artifact_id)}?"
        + urlencode({"version": artifact_version}),
    )
    require_text(evidence.get("conclusion"), "evidence.conclusion")
    candidates = verify_candidates(
        client.request("GET", "/api/workspace/candidates")
    )
    return {
        "status": "passed",
        "base_url": base_url.rstrip("/"),
        "tested_at": datetime.now(UTC).isoformat(),
        "test_identity": {
            "email": email,
            "user_id": user_id,
            "session_id": session_id,
            "profile_id": profile.get("id"),
        },
        "workflow": {
            "run_id": run_id,
            "status": run.get("status"),
            "revision": run.get("revision"),
            "artifact": artifact,
        },
        "evidence": {
            "provider": evidence.get("provider"),
            "generated_at": evidence.get("generated_at"),
            "conclusion": evidence.get("conclusion"),
        },
        "candidates": [
            {
                "symbol": item.get("symbol"),
                "provider": item.get("provider"),
                "as_of": item.get("as_of"),
                "dimension_count": len(item.get("dimensions") or []),
            }
            for item in candidates
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", help="Deployment origin, for example http://127.0.0.1")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if args.timeout < 30:
        parser.error("--timeout must be at least 30 seconds")
    try:
        report = run(args.base_url, args.timeout)
    except JourneyVerificationError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
