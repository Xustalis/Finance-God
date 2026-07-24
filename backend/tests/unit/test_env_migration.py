from __future__ import annotations

import stat
from pathlib import Path

import pytest
from dotenv import dotenv_values

from app.env_migration import migrate_legacy_env


def test_migration_merges_missing_keys_without_overwriting_root(
    tmp_path: Path,
) -> None:
    root_env = tmp_path / ".env"
    legacy_env = tmp_path / "backend" / ".env"
    legacy_env.parent.mkdir()
    root_env.write_text("SHARED=root-value\nROOT_ONLY=keep\n")
    legacy_env.write_text(
        "SHARED=legacy-value\nPANDA_DATA_USERNAME=legacy-market-user\n"
        "EMPTY_OPTIONAL=\nFINANCE_GOD_WORKSPACE_OWNER_ID=legacy-owner\n"
    )

    archive = migrate_legacy_env(
        root_env=root_env,
        legacy_env=legacy_env,
    )

    migrated = dotenv_values(root_env)
    assert migrated["SHARED"] == "root-value"
    assert migrated["ROOT_ONLY"] == "keep"
    assert migrated["PANDA_DATA_USERNAME"] == "legacy-market-user"
    assert "EMPTY_OPTIONAL" not in migrated
    assert "FINANCE_GOD_WORKSPACE_OWNER_ID" not in migrated
    assert not legacy_env.exists()
    assert archive.exists()
    assert stat.S_IMODE(root_env.stat().st_mode) == 0o600
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600


def test_migration_refuses_to_replace_existing_archive(tmp_path: Path) -> None:
    root_env = tmp_path / ".env"
    legacy_env = tmp_path / "backend" / ".env"
    archive = legacy_env.with_name(".env.migrated")
    legacy_env.parent.mkdir()
    root_env.touch()
    legacy_env.touch()
    archive.touch()

    with pytest.raises(FileExistsError, match="archive"):
        migrate_legacy_env(root_env=root_env, legacy_env=legacy_env)

    assert legacy_env.exists()
