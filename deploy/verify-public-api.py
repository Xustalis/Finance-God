#!/usr/bin/env python3
"""Verify production API contracts that must hold after every deployment."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class VerificationError(RuntimeError):
    """A production contract did not hold."""


def _request_bytes(
    base_url: str,
    path: str,
    *,
    expected_status: int,
    attempts: int,
    retry_delay: float,
    method: str = "GET",
    accept: str = "application/json",
    headers: Mapping[str, str] | None = None,
    json_body: Mapping[str, Any] | None = None,
) -> tuple[bytes, str]:
    url = f"{base_url.rstrip('/')}{path}"
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        status: int | None = None
        body = b""
        content_type = ""
        try:
            request_headers = {
                "Accept": accept,
                "User-Agent": "Finance-God-CI",
                **dict(headers or {}),
            }
            data = None
            if json_body is not None:
                request_headers["Content-Type"] = "application/json"
                data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            request = Request(
                url,
                data=data,
                headers=request_headers,
                method=method,
            )
            with urlopen(request, timeout=20) as response:
                status = response.status
                body = response.read()
                content_type = response.headers.get("Content-Type", "")
        except HTTPError as error:
            status = error.code
            body = error.read()
            content_type = error.headers.get("Content-Type", "")
        except (TimeoutError, URLError) as error:
            last_error = error
        if status is not None:
            if status == expected_status:
                return body, content_type
            last_error = VerificationError(
                f"{method} {path} returned HTTP {status}, expected {expected_status}: "
                f"{body[:300].decode('utf-8', errors='replace')}"
            )

        if attempt < attempts:
            time.sleep(retry_delay)

    if isinstance(last_error, VerificationError):
        raise last_error
    raise VerificationError(
        f"{method} {path} request failed after {attempts} attempts: {last_error}"
    )


def _request_json(
    base_url: str,
    path: str,
    *,
    expected_status: int,
    attempts: int,
    retry_delay: float,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    json_body: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    body, _content_type = _request_bytes(
        base_url,
        path,
        expected_status=expected_status,
        attempts=attempts,
        retry_delay=retry_delay,
        method=method,
        headers=headers,
        json_body=json_body,
    )
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationError(f"{path} did not return valid JSON") from error
    if not isinstance(payload, dict):
        raise VerificationError(f"{path} did not return a JSON object")
    return payload


def _require_non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VerificationError(f"{field} must be a non-empty string")
    return value.strip()


def _required_environment(name: str, *, strip: bool = True) -> str:
    value = os.environ.get(name, "")
    if not value.strip():
        raise VerificationError(f"required environment variable {name} is missing")
    return value.strip() if strip else value


def _verify_spa_route(
    base_url: str,
    path: str,
    attempts: int,
    retry_delay: float,
) -> None:
    body, content_type = _request_bytes(
        base_url,
        path,
        expected_status=200,
        attempts=attempts,
        retry_delay=retry_delay,
        accept="text/html",
    )
    if "text/html" not in content_type.lower():
        raise VerificationError(f"{path} did not return HTML")
    try:
        document = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise VerificationError(f"{path} did not return UTF-8 HTML") from error
    if 'id="app"' not in document:
        raise VerificationError(f"{path} did not return the frontend application shell")


def _verify_stock_daily_bars(base_url: str, attempts: int, retry_delay: float) -> None:
    path = "/api/market/bars?" + urlencode(
        {"symbol": "000001.SZ", "frequency": "daily"}
    )
    payload = _request_json(
        base_url,
        path,
        expected_status=200,
        attempts=attempts,
        retry_delay=retry_delay,
    )
    if payload.get("provider") != "PandaData":
        raise VerificationError("stock daily bars must come from PandaData")
    if payload.get("symbol") != "000001.SZ":
        raise VerificationError("stock daily bars returned the wrong symbol")
    if payload.get("frequency") != "日频":
        raise VerificationError(
            f"stock daily bars returned unexpected frequency: {payload.get('frequency')!r}"
        )
    bars = payload.get("bars")
    if not isinstance(bars, list) or not bars:
        raise VerificationError("stock daily bars must contain at least one bar")


def _verify_index_minute_capability(
    base_url: str, attempts: int, retry_delay: float
) -> None:
    path = "/api/market/bars?" + urlencode(
        {"symbol": "000300.SH", "frequency": "1m"}
    )
    payload = _request_json(
        base_url,
        path,
        expected_status=502,
        attempts=attempts,
        retry_delay=retry_delay,
    )
    error = payload.get("error")
    if not isinstance(error, dict):
        raise VerificationError("index minute bars must return an explicit error envelope")
    if error.get("code") != "MARKET_DATA_CAPABILITY_UNAVAILABLE":
        raise VerificationError(
            "index minute bars must fail with MARKET_DATA_CAPABILITY_UNAVAILABLE"
        )
    if "bars" in payload:
        raise VerificationError("index minute capability failure must not contain mock bars")


def _extract_news_items(payload: dict[str, Any]) -> list[Any]:
    value = payload.get("items")
    if isinstance(value, list):
        return value
    raise VerificationError("crawler news envelope must contain an items list")


def _verify_crawler_news(base_url: str, attempts: int, retry_delay: float) -> None:
    payload = _request_json(
        base_url,
        "/api/market/news?limit=5",
        expected_status=200,
        attempts=attempts,
        retry_delay=retry_delay,
    )
    if payload.get("trade_eligible") is not False:
        raise VerificationError("crawler news must explicitly set trade_eligible=false")
    if payload.get("data_mode") != "real":
        raise VerificationError("crawler news must explicitly set data_mode=real")
    provider = _require_non_empty_string(payload.get("provider"), "provider")
    if provider != "Finance-God crawler":
        raise VerificationError("crawler news provider must be Finance-God crawler")
    for field in ("requested_at", "fetched_at"):
        value = _require_non_empty_string(payload.get(field), field)
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise VerificationError(f"{field} must be an ISO timestamp") from error
    freshness = payload.get("freshness")
    if not isinstance(freshness, dict):
        raise VerificationError("crawler news must contain a freshness object")
    if freshness.get("status") not in {"fresh", "stale"}:
        raise VerificationError("crawler news freshness.status must be fresh or stale")
    if not isinstance(freshness.get("cached"), bool):
        raise VerificationError("crawler news freshness.cached must be boolean")
    for field in ("age_seconds", "ttl_seconds"):
        value = freshness.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise VerificationError(f"crawler news freshness.{field} must be non-negative")
    if not isinstance(payload.get("warnings"), list):
        raise VerificationError("crawler news warnings must be a list")

    items = _extract_news_items(payload)
    if not items:
        raise VerificationError("crawler news must contain at least one real item")
    if len(items) > 5:
        raise VerificationError("crawler news exceeded the requested limit")

    valid_item_found = False
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        try:
            source = _require_non_empty_string(item.get("source"), f"items[{index}].source")
            url = _require_non_empty_string(item.get("url"), f"items[{index}].url")
            publish_time = _require_non_empty_string(
                item.get("publish_time"), f"items[{index}].publish_time"
            )
            if not url.startswith(("https://", "http://")):
                raise VerificationError(f"items[{index}].url must be an HTTP(S) URL")
            datetime.fromisoformat(publish_time.replace("Z", "+00:00"))
            valid_item_found = bool(source)
        except (VerificationError, ValueError):
            continue
        if valid_item_found:
            break
    if not valid_item_found:
        raise VerificationError(
            "crawler news needs at least one item with source, HTTP(S) url and ISO publish_time"
        )


def _verify_authenticated_simulation(
    base_url: str,
    attempts: int,
    retry_delay: float,
) -> None:
    email = _required_environment("FINANCE_GOD_SMOKE_EMAIL")
    password = _required_environment("FINANCE_GOD_SMOKE_PASSWORD", strip=False)
    symbol = _required_environment("FINANCE_GOD_SMOKE_SYMBOL").upper()
    quantity = _required_environment("FINANCE_GOD_SMOKE_QUANTITY")
    idempotency_key = _required_environment(
        "FINANCE_GOD_SMOKE_IDEMPOTENCY_KEY"
    )

    login = _request_json(
        base_url,
        "/api/v1/auth/login",
        expected_status=200,
        attempts=attempts,
        retry_delay=retry_delay,
        method="POST",
        json_body={"email": email, "password": password},
    )
    login_data = login.get("data")
    if not isinstance(login_data, dict):
        raise VerificationError("login response is missing data")
    token = _require_non_empty_string(login_data.get("access_token"), "access_token")
    user = login_data.get("user")
    if not isinstance(user, dict) or user.get("email") != email.strip().lower():
        raise VerificationError("login returned the wrong user")

    authorization = {"Authorization": f"Bearer {token}"}
    account = _request_json(
        base_url,
        "/api/simulation/accounts/current",
        expected_status=200,
        attempts=attempts,
        retry_delay=retry_delay,
        headers=authorization,
    )
    account_id = _require_non_empty_string(account.get("account_id"), "account_id")
    if account.get("status") != "active":
        raise VerificationError("production smoke account is not active")

    order = _request_json(
        base_url,
        "/api/simulation/market-orders",
        expected_status=201,
        attempts=attempts,
        retry_delay=retry_delay,
        method="POST",
        headers={
            **authorization,
            "Idempotency-Key": idempotency_key,
        },
        json_body={
            "account_id": account_id,
            "instrument_id": symbol,
            "side": "buy",
            "quantity": quantity,
            "decision_context": {
                "thesis": "生产部署烟测验证模拟交易链路与真实行情引用",
                "expected_return": "仅验证订单接收与执行契约",
                "primary_risks": "行情服务不可用或账户风控拒绝",
                "contrary_evidence": "本次请求不构成投资判断",
                "expected_holding_period": "自动化验证周期",
                "confidence": "仅用于系统契约验证",
            },
        },
    )
    _require_non_empty_string(order.get("order_id"), "order_id")
    if order.get("status") not in {"accepted", "partially_filled", "filled"}:
        raise VerificationError(
            f"simulation order returned unexpected status: {order.get('status')!r}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", help="Public deployment origin, e.g. http://127.0.0.1")
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument("--retry-delay", type=float, default=5.0)
    parser.add_argument(
        "--authenticated-smoke",
        action="store_true",
        help="also verify login and a real-market-backed simulation order",
    )
    args = parser.parse_args()
    if args.attempts < 1:
        parser.error("--attempts must be at least 1")

    checks = (
        ("homepage", lambda url, attempts, delay: _verify_spa_route(url, "/", attempts, delay)),
        (
            "trading workspace",
            lambda url, attempts, delay: _verify_spa_route(
                url, "/desk/trading", attempts, delay
            ),
        ),
        ("stock daily bars", _verify_stock_daily_bars),
        ("index minute capability", _verify_index_minute_capability),
        ("crawler news", _verify_crawler_news),
    )
    try:
        for label, check in checks:
            check(args.base_url, args.attempts, args.retry_delay)
            print(f"PASS: {label}")
        if args.authenticated_smoke:
            _verify_authenticated_simulation(
                args.base_url,
                args.attempts,
                args.retry_delay,
            )
            print("PASS: authenticated simulation order")
    except VerificationError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
