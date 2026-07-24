from __future__ import annotations

import io
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

BACKEND = Path(__file__).resolve().parents[2]
WORKFLOW_TABLES = {
    "workflow_runs",
    "workflow_events",
    "workflow_audit_records",
    "workflow_execution_audit_records",
    "workflow_outbox_messages",
}


def test_sqlite_upgrade_and_metadata_check(tmp_path: Path) -> None:
    database = tmp_path / "workflow-migration.db"
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")

    command.upgrade(config, "head")
    command.check(config)

    engine = create_engine(f"sqlite:///{database}")
    try:
        assert WORKFLOW_TABLES.issubset(inspect(engine).get_table_names())
        with engine.connect() as connection:
            triggers = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'trigger' AND name LIKE 'workflow_%'"
                    )
                )
            }
    finally:
        engine.dispose()
    assert {
        "workflow_events_no_update",
        "workflow_events_no_delete",
        "workflow_audit_records_no_update",
        "workflow_audit_records_no_delete",
        "workflow_execution_audit_records_no_update",
        "workflow_execution_audit_records_no_delete",
    }.issubset(triggers)


def test_offline_postgres_sql_contains_workflow_contract() -> None:
    output = io.StringIO()
    config = Config(str(BACKEND / "alembic.ini"), output_buffer=output)
    config.set_main_option(
        "sqlalchemy.url",
        "postgresql+asyncpg://workflow:workflow@localhost/workflow_test",
    )

    command.upgrade(config, "head", sql=True)

    rendered = output.getvalue()
    assert "CREATE TABLE workflow_runs" in rendered
    assert "CREATE TABLE workflow_events" in rendered
    assert "uq_workflow_run_owner_idempotency" in rendered
    assert "ck_workflow_run_trade_eligible" in rendered
    assert "finance_god_prevent_workflow_fact_mutation" in rendered
    assert "workflow_events_no_mutation" in rendered
    assert "workflow_audit_records_no_mutation" in rendered
    assert "workflow_execution_audit_records_no_mutation" in rendered
