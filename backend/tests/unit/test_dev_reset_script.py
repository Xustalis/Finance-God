import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "reset_dev_db.sh"


def run_check(*, app_env: str, url: str) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"APP_ENV": app_env, "DATABASE_URL_SYNC": url}
    return subprocess.run(
        ["bash", str(SCRIPT), "--check"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_reset_script_accepts_only_local_finance_god_development_database() -> None:
    valid = run_check(
        app_env="development",
        url="postgresql://postgres:postgres@127.0.0.1:5432/finance_god",
    )
    production = run_check(
        app_env="production",
        url="postgresql://postgres:postgres@127.0.0.1:5432/finance_god",
    )
    remote = run_check(
        app_env="development",
        url="postgresql://postgres:postgres@db.example.com:5432/finance_god",
    )
    wrong_database = run_check(
        app_env="development",
        url="postgresql://postgres:postgres@127.0.0.1:5432/postgres",
    )

    assert valid.returncode == 0
    assert "Validated development database" in valid.stdout
    assert production.returncode != 0
    assert remote.returncode != 0
    assert wrong_database.returncode != 0


def test_reset_script_uses_postgres_maintenance_connection(
    tmp_path: Path,
) -> None:
    command_log = tmp_path / "commands.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    command = fake_bin / "postgres-command"
    command.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$COMMAND_LOG"\n'
        'case "$0" in *createdb) exit 42 ;; esac\n',
        encoding="utf-8",
    )
    command.chmod(0o755)
    (fake_bin / "dropdb").symlink_to(command)
    (fake_bin / "createdb").symlink_to(command)
    env = os.environ | {
        "APP_ENV": "development",
        "DATABASE_URL_SYNC": "postgresql+psycopg2://postgres:secret@127.0.0.1:5432/finance_god_dev",
        "COMMAND_LOG": str(command_log),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 42
    commands = command_log.read_text(encoding="utf-8")
    assert (
        "dropdb --if-exists --force "
        "--maintenance-db=postgresql://postgres:secret@127.0.0.1:5432/postgres "
        "finance_god_dev"
    ) in commands
    assert (
        "createdb --maintenance-db=postgresql://postgres:secret@127.0.0.1:5432/postgres "
        "finance_god_dev"
    ) in commands
