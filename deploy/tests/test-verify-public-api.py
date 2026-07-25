#!/usr/bin/env python3
"""Self-test the post-deployment public API contract verifier."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

VERIFY_SCRIPT = Path(__file__).parents[1] / "verify-public-api.py"


class ContractHandler(BaseHTTPRequestHandler):
    news_provider = "Finance-God crawler"
    news_data_mode = "real"
    market_order_status = 201

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path in {"/", "/desk/trading"}:
            self._html('<!doctype html><html><body><div id="app"></div></body></html>')
            return
        if parsed.path == "/api/simulation/accounts/current":
            if self.headers.get("Authorization") != "Bearer smoke-token":
                self._json(401, {"error": {"code": "UNAUTHORIZED"}})
                return
            self._json(
                200,
                {
                    "account_id": "smoke-account",
                    "owner_id": "smoke-user",
                    "status": "active",
                    "cash_available_rmb": "1000000.00",
                },
            )
            return
        if parsed.path == "/api/market/bars" and query.get("frequency") == ["daily"]:
            self._json(
                200,
                {
                    "provider": "PandaData",
                    "symbol": "000001.SZ",
                    "frequency": "日频",
                    "bars": [{"trade_date": "2026-07-24", "close": 11.1}],
                },
            )
            return
        if parsed.path == "/api/market/bars" and query.get("frequency") == ["1m"]:
            self._json(
                502,
                {
                    "error": {
                        "code": "MARKET_DATA_CAPABILITY_UNAVAILABLE",
                        "message": "not enabled",
                    }
                },
            )
            return
        if parsed.path == "/api/market/news":
            self._json(
                200,
                {
                    "provider": self.news_provider,
                    "data_mode": self.news_data_mode,
                    "requested_at": "2026-07-25T15:00:01+08:00",
                    "fetched_at": "2026-07-25T15:00:00+08:00",
                    "freshness": {
                        "status": "fresh",
                        "age_seconds": 1,
                        "ttl_seconds": 300,
                        "cached": True,
                    },
                    "trade_eligible": False,
                    "warnings": [],
                    "items": [
                        {
                            "source": "证券时报",
                            "url": "https://example.com/news/1",
                            "publish_time": "2026-07-25T15:00:00+08:00",
                        }
                    ],
                },
            )
            return
        self._json(404, {"error": {"code": "NOT_FOUND"}})

    def do_POST(self) -> None:
        payload = self._read_json()
        if self.path == "/api/v1/auth/login":
            if payload != {
                "email": "smoke@example.com",
                "password": "correct-horse-battery",
            }:
                self._json(401, {"detail": "邮箱或密码错误"})
                return
            self._json(
                200,
                {
                    "success": True,
                    "data": {
                        "access_token": "smoke-token",
                        "token_type": "bearer",
                        "user": {"id": "smoke-user", "email": "smoke@example.com"},
                    },
                },
            )
            return
        if self.path == "/api/simulation/market-orders":
            if self.market_order_status != 201:
                self._json(
                    self.market_order_status,
                    {
                        "error": {
                            "code": "SERVICE_UNAVAILABLE",
                            "message": "real market reference unavailable",
                        }
                    },
                )
                return
            if (
                self.headers.get("Authorization") != "Bearer smoke-token"
                or self.headers.get("Idempotency-Key")
                != "production-smoke-test-sha"
                or payload.get("account_id") != "smoke-account"
                or payload.get("instrument_id") != "000001.SZ"
                or "decision_context" in payload
            ):
                self._json(400, {"error": {"code": "INVALID_REQUEST"}})
                return
            self._json(
                201,
                {
                    "order_id": "smoke-order",
                    "owner_id": "smoke-user",
                    "status": "filled",
                },
            )
            return
        self._json(404, {"error": {"code": "NOT_FOUND"}})

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        return payload if isinstance(payload, dict) else {}

    def _json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, document: str) -> None:
        body = document.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _run(
    handler: type[ContractHandler],
    *,
    authenticated_smoke: bool = False,
    missing_smoke_password: bool = False,
) -> subprocess.CompletedProcess[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        command = [
            sys.executable,
            str(VERIFY_SCRIPT),
            f"http://127.0.0.1:{server.server_port}",
            "--attempts",
            "1",
            "--retry-delay",
            "0",
        ]
        environment = os.environ.copy()
        if authenticated_smoke:
            command.append("--authenticated-smoke")
            environment |= {
                "FINANCE_GOD_SMOKE_EMAIL": "smoke@example.com",
                "FINANCE_GOD_SMOKE_PASSWORD": "correct-horse-battery",
                "FINANCE_GOD_SMOKE_SYMBOL": "000001.SZ",
                "FINANCE_GOD_SMOKE_QUANTITY": "100",
                "FINANCE_GOD_SMOKE_IDEMPOTENCY_KEY": "production-smoke-test-sha",
            }
            if missing_smoke_password:
                environment.pop("FINANCE_GOD_SMOKE_PASSWORD")
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            env=environment,
            text=True,
            timeout=10,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main() -> int:
    success = _run(ContractHandler, authenticated_smoke=True)
    if success.returncode != 0:
        print(success.stdout, success.stderr, file=sys.stderr)
        return 1

    class MockNewsHandler(ContractHandler):
        news_data_mode = "mock"

    rejected = _run(MockNewsHandler)
    if rejected.returncode == 0 or "data_mode=real" not in rejected.stderr:
        print(
            "Verifier did not reject mock crawler news:\n"
            f"stdout={rejected.stdout}\nstderr={rejected.stderr}",
            file=sys.stderr,
        )
        return 1

    class MarketFailureHandler(ContractHandler):
        market_order_status = 503

    market_failure = _run(MarketFailureHandler, authenticated_smoke=True)
    if (
        market_failure.returncode == 0
        or "returned HTTP 503, expected 201" not in market_failure.stderr
    ):
        print(
            "Verifier did not fail closed when the real market reference failed:\n"
            f"stdout={market_failure.stdout}\nstderr={market_failure.stderr}",
            file=sys.stderr,
        )
        return 1

    missing_credentials = _run(
        ContractHandler,
        authenticated_smoke=True,
        missing_smoke_password=True,
    )
    if (
        missing_credentials.returncode == 0
        or "FINANCE_GOD_SMOKE_PASSWORD is missing"
        not in missing_credentials.stderr
    ):
        print(
            "Verifier did not reject missing production smoke credentials:\n"
            f"stdout={missing_credentials.stdout}\n"
            f"stderr={missing_credentials.stderr}",
            file=sys.stderr,
        )
        return 1

    print("PASS: production API verifier self-test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
