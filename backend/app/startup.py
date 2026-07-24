"""Local backend launcher with a fail-fast port ownership check."""

from __future__ import annotations

import errno
import os
import socket
import sys
from pathlib import Path

HOST = "0.0.0.0"
PORT = 8000
ASGI_TARGET = "app.main:app"
BACKEND_DIR = Path(__file__).resolve().parents[1]
LEGACY_ENV_FILE = BACKEND_DIR / ".env"


def ensure_no_legacy_env(*, legacy_env: Path = LEGACY_ENV_FILE) -> None:
    """Require an explicit one-time migration instead of hidden fallback."""
    if legacy_env.is_file():
        raise RuntimeError(
            "legacy backend/.env detected; it is not loaded. Run "
            "`.venv/bin/python -m app.env_migration` from backend/ once, "
            "then retry"
        )


def ensure_port_available(*, host: str = HOST, port: int = PORT) -> None:
    """Refuse to start while another process owns the backend port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError as error:
            if error.errno == errno.EADDRINUSE:
                raise RuntimeError(
                    f"port {port} is already in use; refusing to start a second "
                    "Finance-God backend"
                ) from error
            raise


def main() -> int:
    try:
        ensure_no_legacy_env()
        ensure_port_available()
    except RuntimeError as error:
        print(f"Backend preflight failed: {error}", file=sys.stderr)
        return 2
    arguments = [
        sys.executable,
        "-m",
        "uvicorn",
        ASGI_TARGET,
        "--reload",
        "--host",
        HOST,
        "--port",
        str(PORT),
    ]
    os.execv(sys.executable, arguments)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
