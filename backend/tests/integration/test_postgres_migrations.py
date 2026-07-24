import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, inspect


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def postgres_test_url() -> str:
    database_url = os.getenv("FINANCE_GOD_POSTGRES_TEST_URL", "")
    if not database_url:
        pytest.skip("FINANCE_GOD_POSTGRES_TEST_URL is not configured")
    parsed = urlsplit(database_url)
    if parsed.path.lstrip("/") != "finance_god_test":
        pytest.fail("PostgreSQL smoke test requires the dedicated finance_god_test database")
    if parsed.scheme not in {"postgresql", "postgresql+psycopg2"}:
        pytest.fail("PostgreSQL smoke test requires a synchronous psycopg2 URL")
    return database_url


def run_alembic(database_url: str, *args: str) -> None:
    subprocess.run(
        [str(BACKEND_ROOT / ".venv/bin/alembic"), *args],
        cwd=BACKEND_ROOT,
        env=os.environ
        | {
            "APP_ENV": "development",
            "DATABASE_URL_SYNC": database_url,
        },
        check=True,
        capture_output=True,
        text=True,
    )


def test_postgres_migration_round_trip() -> None:
    database_url = postgres_test_url()

    run_alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)
    try:
        schema = inspect(engine)
        assert {
            "users",
            "onboarding_sessions",
            "profile_messages",
            "investment_profiles",
            "direction_recommendations",
            "ai_model_configs",
            "prompt_versions",
        } <= set(schema.get_table_names())
        profile_uniques = {
            tuple(item["column_names"])
            for item in schema.get_unique_constraints("investment_profiles")
        }
        assert ("user_id", "version") in profile_uniques
    finally:
        engine.dispose()

    run_alembic(database_url, "check")
    run_alembic(database_url, "downgrade", "base")
    run_alembic(database_url, "upgrade", "head")
