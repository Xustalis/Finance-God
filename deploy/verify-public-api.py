#!/usr/bin/env python3
"""Verify production API contracts that must hold after every deployment."""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class VerificationError(RuntimeError):
    """A production contract did not hold."""


def _request_json(
    base_url: str,
    path: str,
    *,
    expected_status: int,
    attempts: int,
    retry_delay: float,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        status: int | None = None
        body = b""
        try:
            request = Request(
                url,
                headers={"Accept": "application/json", "User-Agent": "Finance-God-CI"},
            )
            with urlopen(request, timeout=20) as response:
                status = response.status
                body = response.read()
        except HTTPError as error:
            status = error.code
            body = error.read()
        except (TimeoutError, URLError, socket.timeout) as error:
            last_error = error
        if status is not None:
            if status == expected_status:
                try:
                    payload = json.loads(body)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise VerificationError(f"{path} did not return valid JSON") from error
                if not isinstance(payload, dict):
                    raise VerificationError(f"{path} did not return a JSON object")
                return payload
            last_error = VerificationError(
                f"{path} returned HTTP {status}, expected {expected_status}: "
                f"{body[:300].decode('utf-8', errors='replace')}"
            )

        if attempt < attempts:
            time.sleep(retry_delay)

    if isinstance(last_error, VerificationError):
        raise last_error
    raise VerificationError(f"{path} request failed after {attempts} attempts: {last_error}")


def _require_non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VerificationError(f"{field} must be a non-empty string")
    return value.strip()


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", help="Public deployment origin, e.g. http://127.0.0.1")
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument("--retry-delay", type=float, default=5.0)
    args = parser.parse_args()
    if args.attempts < 1:
        parser.error("--attempts must be at least 1")

    checks = (
        ("stock daily bars", _verify_stock_daily_bars),
        ("index minute capability", _verify_index_minute_capability),
        ("crawler news", _verify_crawler_news),
    )
    try:
        for label, check in checks:
            check(args.base_url, args.attempts, args.retry_delay)
            print(f"PASS: {label}")
    except VerificationError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
