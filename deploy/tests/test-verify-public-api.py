#!/usr/bin/env python3
"""Self-test the post-deployment public API contract verifier."""

from __future__ import annotations

import json
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

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
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

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def _json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _run(handler: type[ContractHandler]) -> subprocess.CompletedProcess[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        return subprocess.run(
            [
                sys.executable,
                str(VERIFY_SCRIPT),
                f"http://127.0.0.1:{server.server_port}",
                "--attempts",
                "1",
                "--retry-delay",
                "0",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main() -> int:
    success = _run(ContractHandler)
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

    print("PASS: production API verifier self-test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
