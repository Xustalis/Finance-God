from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from finance_god.agents.catalog import AgentGovernanceCatalog
from finance_god.agents.contracts import OrderReviewMode, WorkflowKey
from finance_god.domain.models import VersionReference, WorkflowBlockReason
from finance_god.orchestration.task_plans import TaskPlanFactory
from finance_god.orchestration.workflow_commands import (
    DataQualityWorkflowCreationPort,
    WorkflowCommandService,
    WorkflowCreateCommand,
)
from finance_god.orchestration.workflow_registry import FormalWorkflowRegistry
from finance_god.orchestration.workflow_selection import (
    WorkflowRoutingContext,
    WorkflowSelector,
)
from tests.workflows.support import (
    AsyncMemoryWorkflowRepository,
    SequenceRunIds,
)


INPUT = (
    VersionReference(
        object_type="market_snapshot",
        object_id="XNAS:AAPL",
        version="2026-07-24T03:00:00Z",
    ),
)
NOW = datetime(2026, 7, 24, tzinfo=timezone.utc)


def routing(**changes: object) -> WorkflowRoutingContext:
    values: dict[str, object] = {
        "requested_workflow": WorkflowKey.COMPANY_RESEARCH,
        "request_intent": "Research a versioned input.",
        "owner_id": "user-1",
        "scope": {"account_id": "sim-1"},
        "input_versions": INPUT,
    }
    values.update(changes)
    return WorkflowRoutingContext(**values)


class WorkflowSelectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.selector = WorkflowSelector()

    def test_priority_is_pause_hard_cooldown_data_auth_normal(self) -> None:
        paused = self.selector.select(
            routing(
                user_paused=True,
                hard_risk_blocked=True,
                cooldown_active=True,
                data_usable=False,
                authorization_active=False,
            ),
            notice_id="notice-1",
        )
        self.assertEqual(
            paused.block_notice.reason,
            WorkflowBlockReason.USER_PAUSED,
        )
        self.assertEqual(paused.block_notice.agent_calls, 0)

        hard = self.selector.select(
            routing(
                hard_risk_blocked=True,
                cooldown_active=True,
                data_usable=False,
                authorization_active=False,
            ),
            notice_id="notice-2",
        )
        self.assertEqual(hard.block_notice.reason, WorkflowBlockReason.HARD_RISK)

        cooldown = self.selector.select(
            routing(cooldown_active=True, data_usable=False),
            notice_id="notice-3",
        )
        self.assertEqual(cooldown.selected_workflow, WorkflowKey.REVIEW_ONLY)

        quality = self.selector.select(
            routing(data_usable=False, authorization_active=False),
            notice_id="notice-4",
        )
        self.assertEqual(
            quality.selected_workflow,
            WorkflowKey.DATA_QUALITY_REVIEW,
        )

        unauthorized = self.selector.select(
            routing(authorization_active=False),
            notice_id="notice-5",
        )
        self.assertEqual(
            unauthorized.selected_workflow,
            WorkflowKey.REVIEW_ONLY,
        )

    def test_manual_order_remains_legal_when_agents_are_paused(self) -> None:
        selection = self.selector.select(
            routing(
                requested_workflow=WorkflowKey.ORDER_REVIEW,
                order_review_mode=OrderReviewMode.MANUAL,
                user_paused=True,
            ),
            notice_id="manual-paused",
        )
        self.assertEqual(selection.selected_workflow, WorkflowKey.ORDER_REVIEW)
        self.assertTrue(selection.suppress_agent_nodes)
        self.assertIsNone(selection.block_notice)

    def test_hard_risk_always_blocks_manual_order(self) -> None:
        selection = self.selector.select(
            routing(
                requested_workflow=WorkflowKey.ORDER_REVIEW,
                order_review_mode=OrderReviewMode.MANUAL,
                user_paused=True,
                hard_risk_blocked=True,
            ),
            notice_id="manual-hard",
        )
        self.assertEqual(
            selection.block_notice.reason,
            WorkflowBlockReason.HARD_RISK,
        )

    def test_paused_manual_order_still_passes_lower_priority_gates(self) -> None:
        cooldown = self.selector.select(
            routing(
                requested_workflow=WorkflowKey.ORDER_REVIEW,
                order_review_mode=OrderReviewMode.MANUAL,
                user_paused=True,
                cooldown_active=True,
            ),
            notice_id="paused-cooldown",
        )
        self.assertEqual(cooldown.selected_workflow, WorkflowKey.REVIEW_ONLY)
        self.assertTrue(cooldown.suppress_agent_nodes)

        bad_data = self.selector.select(
            routing(
                requested_workflow=WorkflowKey.ORDER_REVIEW,
                order_review_mode=OrderReviewMode.MANUAL,
                user_paused=True,
                data_usable=False,
            ),
            notice_id="paused-data",
        )
        self.assertEqual(
            bad_data.selected_workflow,
            WorkflowKey.DATA_QUALITY_REVIEW,
        )
        self.assertTrue(bad_data.suppress_agent_nodes)

        unauthorized = self.selector.select(
            routing(
                requested_workflow=WorkflowKey.ORDER_REVIEW,
                order_review_mode=OrderReviewMode.MANUAL,
                user_paused=True,
                authorization_active=False,
            ),
            notice_id="paused-auth",
        )
        self.assertEqual(
            unauthorized.selected_workflow,
            WorkflowKey.REVIEW_ONLY,
        )
        self.assertTrue(unauthorized.suppress_agent_nodes)

    def test_cooldown_only_allows_risk_reducing_manual_order(self) -> None:
        allowed = self.selector.select(
            routing(
                requested_workflow=WorkflowKey.ORDER_REVIEW,
                order_review_mode=OrderReviewMode.MANUAL,
                cooldown_active=True,
                manual_risk_reducing=True,
            ),
            notice_id="manual-reduce",
        )
        self.assertEqual(allowed.selected_workflow, WorkflowKey.ORDER_REVIEW)
        self.assertTrue(allowed.suppress_agent_nodes)
        denied = self.selector.select(
            routing(
                requested_workflow=WorkflowKey.ORDER_REVIEW,
                order_review_mode=OrderReviewMode.MANUAL,
                cooldown_active=True,
            ),
            notice_id="manual-increase",
        )
        self.assertEqual(denied.selected_workflow, WorkflowKey.REVIEW_ONLY)

    def test_manual_normal_path_keeps_nonblocking_explanation_agents(self) -> None:
        catalog = AgentGovernanceCatalog()
        registry = FormalWorkflowRegistry.build_default(catalog)
        plan = TaskPlanFactory(catalog, registry).formal(
            plan_id="manual-normal",
            owner_id="user-1",
            workflow_key=WorkflowKey.ORDER_REVIEW,
            input_versions=(
                VersionReference(
                    object_type="order_draft",
                    object_id="order-1",
                    version="7",
                ),
            ),
            route_reason="manual order review",
            order_review_mode=OrderReviewMode.MANUAL,
        )
        agent_nodes = [node for node in plan.nodes if node.agent_ids]
        self.assertTrue(agent_nodes)
        self.assertTrue(
            all(node.requirement.value == "non_blocking" for node in agent_nodes)
        )

    def test_paused_manual_data_fallback_is_deterministic_only(self) -> None:
        catalog = AgentGovernanceCatalog()
        registry = FormalWorkflowRegistry.build_default(catalog)
        plan = TaskPlanFactory(catalog, registry).formal(
            plan_id="paused-manual-dq",
            owner_id="user-1",
            workflow_key=WorkflowKey.DATA_QUALITY_REVIEW,
            input_versions=INPUT,
            route_reason="paused manual order has unusable data",
            suppress_agents=True,
            paused_manual_fallback=True,
        )
        self.assertTrue(plan.agent_pause_exempt)
        self.assertTrue(all(not node.agent_ids for node in plan.nodes))


class WorkflowCommandTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.registry = FormalWorkflowRegistry.build_default()
        self.repository = AsyncMemoryWorkflowRepository()
        self.commands = WorkflowCommandService(
            registry=self.registry,
            repository=self.repository,
            run_ids=SequenceRunIds(),
        )

    def command(self, **changes: object) -> WorkflowCreateCommand:
        values: dict[str, object] = {
            "idempotency_key": "request-0001",
            "workflow_key": WorkflowKey.COMPANY_RESEARCH,
            "request_intent": "Create a durable research run.",
            "owner_id": "user-1",
            "scope": {"workspace_id": "desk-1"},
            "input_versions": INPUT,
            "requested_at": NOW,
        }
        values.update(changes)
        return WorkflowCreateCommand(**values)

    async def test_create_is_queued_versioned_and_idempotent(self) -> None:
        first = await self.commands.create(self.command())
        second = await self.commands.create(
            self.command(requested_at=NOW + timedelta(minutes=5))
        )
        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.run.run_id, second.run.run_id)
        self.assertEqual(first.run.status.value, "queued")
        self.assertEqual(
            first.run.workflow_version,
            self.registry.version,
        )

    async def test_same_key_different_payload_conflicts(self) -> None:
        await self.commands.create(self.command())
        with self.assertRaisesRegex(ValueError, "different request"):
            await self.commands.create(
                self.command(request_intent="A materially different request.")
            )

    async def test_same_key_with_different_scope_or_input_conflicts(self) -> None:
        await self.commands.create(self.command())
        for change in (
            {"scope": {"workspace_id": "desk-2"}},
            {
                "input_versions": (
                    VersionReference(
                        object_type="market_snapshot",
                        object_id="XNAS:AAPL",
                        version="2026-07-24T03:01:00Z",
                    ),
                )
            },
        ):
            with self.subTest(change=change):
                with self.assertRaisesRegex(ValueError, "different request"):
                    await self.commands.create(self.command(**change))

    def test_scope_rejects_non_string_external_values(self) -> None:
        with self.assertRaisesRegex(
            ValidationError,
            "keys and values must be strings",
        ):
            self.command(scope={"account_id": 42})

    async def test_data_quality_port_creates_queryable_real_run(self) -> None:
        port = DataQualityWorkflowCreationPort(
            commands=self.commands,
            owner_id="pandadata-system",
        )
        receipt = await port.create(
            workflow_key=WorkflowKey.DATA_QUALITY_REVIEW,
            stable_trigger_key="dq-trigger-0001",
            input_versions=INPUT,
            scope={"instrument": "XNAS:AAPL"},
            requested_at=NOW,
        )
        queried = await self.commands.get(receipt.run.run_id)
        self.assertEqual(queried, receipt.run)
        self.assertEqual(
            receipt.run.workflow_key,
            WorkflowKey.DATA_QUALITY_REVIEW.value,
        )


if __name__ == "__main__":
    unittest.main()
