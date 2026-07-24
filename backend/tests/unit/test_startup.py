from __future__ import annotations

import socket
from pathlib import Path

import pytest

from app import startup


def test_preflight_rejects_legacy_backend_env(tmp_path: Path) -> None:
    legacy_env = tmp_path / "backend" / ".env"
    legacy_env.parent.mkdir()
    legacy_env.touch()

    with pytest.raises(RuntimeError, match="app.env_migration"):
        startup.ensure_no_legacy_env(legacy_env=legacy_env)


def test_port_preflight_fails_without_stopping_existing_listener() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]

        with pytest.raises(RuntimeError, match="already in use"):
            startup.ensure_port_available(host="127.0.0.1", port=port)

        assert listener.getsockname()[1] == port


def test_launcher_executes_only_supported_asgi_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(startup, "ensure_no_legacy_env", lambda: None)
    monkeypatch.setattr(startup, "ensure_port_available", lambda **_: None)
    monkeypatch.setattr(
        startup.os,
        "execv",
        lambda executable, arguments: executed.append(
            (executable, arguments)
        ),
    )

    assert startup.main() == 0
    assert len(executed) == 1
    assert "app.main:app" in executed[0][1]
    assert "server:app" not in executed[0][1]
