from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from alembic import command
from alembic.config import Config

from finance_god.agents.contracts import WorkflowKey
from finance_god.domain.models import VersionReference
from finance_god.orchestration import (
    WorkflowCommandService,
    WorkflowCreateCommand,
    create_workflow_command_runtime_from_environment,
)

BACKEND = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 7, 24, tzinfo=timezone.utc)


def workflow_command() -> WorkflowCreateCommand:
    return WorkflowCreateCommand(
        idempotency_key="runtime-request-0001",
        workflow_key=WorkflowKey.DATA_QUALITY_REVIEW,
        request_intent="Persist a real data-quality workflow.",
        owner_id="pandadata-system",
        scope={"instrument": "XNAS:AAPL"},
        input_versions=(
            VersionReference(
                object_type="market_snapshot",
                object_id="XNAS:AAPL",
                version="v1",
            ),
        ),
        requested_at=NOW,
    )


class WorkflowRuntimeConfigurationTest(unittest.TestCase):
    def test_missing_database_url_fails_without_fallback(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                RuntimeError,
                "FINANCE_GOD_DATABASE_URL is required",
            ):
                create_workflow_command_runtime_from_environment()


class WorkflowRuntimeLifecycleTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        database = Path(self.temporary.name) / "runtime.db"
        self.database_url = f"sqlite+aiosqlite:///{database}"
        config = Config(str(BACKEND / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", self.database_url)
        command.upgrade(config, "head")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    async def test_command_commits_and_runtime_closes_with_context(self) -> None:
        runtime = create_workflow_command_runtime_from_environment(
            database_url=self.database_url
        )
        async with runtime:
            receipt = await runtime.create(workflow_command())
            queried = await runtime.get(receipt.run.run_id)
            self.assertEqual(queried, receipt.run)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            await runtime.create(workflow_command())

    async def test_exception_after_flush_rolls_back_command_transaction(self) -> None:
        runtime = create_workflow_command_runtime_from_environment(
            database_url=self.database_url
        )
        original = WorkflowCommandService.create

        async def fail_after_flush(
            service: WorkflowCommandService,
            command_value: WorkflowCreateCommand,
        ) -> object:
            await original(service, command_value)
            raise RuntimeError("injected application failure")

        try:
            with patch.object(
                WorkflowCommandService,
                "create",
                fail_after_flush,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "injected application failure",
                ):
                    await runtime.create(workflow_command())
            receipt = await runtime.create(workflow_command())
            self.assertTrue(receipt.created)
        finally:
            await runtime.close()


if __name__ == "__main__":
    unittest.main()
