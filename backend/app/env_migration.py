"""Explicit one-time migration from legacy backend/.env to root .env."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from dotenv import dotenv_values

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_ENV_FILE = BACKEND_DIR.parent / ".env"
LEGACY_ENV_FILE = BACKEND_DIR / ".env"
ARCHIVE_ENV_FILE = BACKEND_DIR / ".env.migrated"
DEPRECATED_KEYS = frozenset({"FINANCE_GOD_WORKSPACE_OWNER_ID"})


def _quoted(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError("multiline env values require manual migration")
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def migrate_legacy_env(
    *,
    root_env: Path = ROOT_ENV_FILE,
    legacy_env: Path = LEGACY_ENV_FILE,
    archive_env: Path | None = None,
) -> Path:
    """Merge missing non-empty keys and archive the legacy source."""
    archive = archive_env or legacy_env.with_name(".env.migrated")
    if not legacy_env.is_file():
        raise FileNotFoundError(f"legacy env not found: {legacy_env}")
    if archive.exists():
        raise FileExistsError(f"legacy env archive already exists: {archive}")

    root_values = (
        dotenv_values(root_env, interpolate=False)
        if root_env.is_file()
        else {}
    )
    legacy_values = dotenv_values(legacy_env, interpolate=False)
    additions = {
        key: value
        for key, value in legacy_values.items()
        if key not in root_values
        and key not in DEPRECATED_KEYS
        and value is not None
        and value.strip()
    }

    existing = root_env.read_text() if root_env.is_file() else ""
    separator = "" if not existing or existing.endswith("\n") else "\n"
    appended = "".join(
        f"{key}={_quoted(value)}\n"
        for key, value in additions.items()
    )
    root_env.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=root_env.parent,
        prefix=".env.migration-",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(existing)
            handle.write(separator)
            handle.write(appended)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, root_env)
    finally:
        if temporary.exists():
            temporary.unlink()

    legacy_env.replace(archive)
    archive.chmod(0o600)
    return archive


def main() -> int:
    archive = migrate_legacy_env()
    print(
        "Legacy environment migrated without overwriting root keys. "
        f"Original archived at {archive}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
