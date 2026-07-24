from __future__ import annotations

import asyncio
import io
import os
import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

POSTGRES_URL = os.getenv("FINANCE_GOD_TEST_POSTGRES_URL")
BACKEND = Path(__file__).resolve().parents[2]
LEDGER_TABLES = (
    "account_activities",
    "outbox_messages",
    "audit_records",
    "idempotency_records",
    "fills",
    "reservations",
    "position_projections",
    "account_projections",
    "ledger_postings",
    "journal_entries",
    "account_events",
    "simulation_accounts",
    "alembic_version",
)


class MigrationSmokeTest(unittest.TestCase):
    def test_initial_migration_upgrades_empty_sqlite_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "ledger.db"
            config = Config(str(BACKEND / "alembic.ini"))
            config.set_main_option(
                "sqlalchemy.url", f"sqlite+aiosqlite:///{database}"
            )
            command.upgrade(config, "head")
            command.check(config)

            engine = create_engine(f"sqlite:///{database}")
            try:
                tables = set(inspect(engine).get_table_names())
            finally:
                engine.dispose()
            self.assertTrue(
                {
                    "simulation_accounts",
                    "account_events",
                    "journal_entries",
                    "ledger_postings",
                    "account_projections",
                    "position_projections",
                    "reservations",
                    "account_activities",
                    "fills",
                    "idempotency_records",
                    "audit_records",
                    "outbox_messages",
                    "alembic_version",
                }.issubset(tables)
            )

    def test_initial_migration_upgrades_empty_postgres_database(self) -> None:
        if POSTGRES_URL is None:
            self.skipTest("FINANCE_GOD_TEST_POSTGRES_URL is not configured")
        _require_test_database(POSTGRES_URL)
        asyncio.run(_clear_ledger_schema(POSTGRES_URL))
        config = Config(str(BACKEND / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", POSTGRES_URL)
        command.upgrade(config, "head")
        command.check(config)
        self.assertTrue(asyncio.run(_postgres_has_fact_triggers()))

    def test_offline_sql_is_renderable(self) -> None:
        output = io.StringIO()
        config = Config(str(BACKEND / "alembic.ini"), output_buffer=output)
        config.set_main_option("sqlalchemy.url", "sqlite+aiosqlite:///:memory:")
        command.upgrade(config, "head", sql=True)
        rendered = output.getvalue()
        self.assertIn("CREATE TABLE account_events", rendered)
        self.assertIn("account_events_no_update", rendered)


def _require_test_database(database_url: str) -> None:
    database = make_url(database_url).database or ""
    if "test" not in database.lower() or database.lower() in {
        "postgres",
        "template0",
        "template1",
    }:
        raise RuntimeError(
            "FINANCE_GOD_TEST_POSTGRES_URL must target a dedicated test database"
        )


async def _clear_ledger_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "DROP TABLE IF EXISTS "
                    + ", ".join(LEDGER_TABLES)
                    + " CASCADE"
                )
            )
            await connection.execute(
                text(
                    "DROP FUNCTION IF EXISTS "
                    "finance_god_prevent_fact_mutation()"
                )
            )
    finally:
        await engine.dispose()


async def _postgres_has_fact_triggers() -> bool:
    assert POSTGRES_URL is not None
    engine = create_async_engine(POSTGRES_URL)
    try:
        async with engine.connect() as connection:
            count = await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_trigger "
                    "WHERE tgname LIKE '%_no_mutation' AND NOT tgisinternal"
                )
            )
            return bool(count == 5)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    unittest.main()
