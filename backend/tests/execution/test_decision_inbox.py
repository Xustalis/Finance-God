from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from finance_god.application.decision_inbox import DecisionInboxService
from finance_god.domain import (
    AuditReference,
    Notification,
    NotificationCategory,
    NotificationSeverity,
    NotificationStatus,
    VersionReference,
)
from finance_god.execution import StoredOrderView

NOW = datetime(2026, 7, 24, 2, tzinfo=UTC)
DRAFT_REF = VersionReference(
    object_type="order_draft",
    object_id="draft-1",
    version="1",
)


def order_view(
    *,
    order_id: str = "order-1",
    status: str = "partially_filled",
    execution_error: str | None = None,
    updated_at: datetime = NOW,
    cumulative_filled: Decimal = Decimal("50"),
) -> StoredOrderView:
    return StoredOrderView(
        order_id=order_id,
        owner_id="owner-1",
        order_kind="exchange",
        status=status,
        instrument_id="600519.SSE",
        side="buy",
        order_type="market",
        time_in_force="day",
        quantity=Decimal("100"),
        cumulative_filled=cumulative_filled,
        remaining_quantity=Decimal("100") - cumulative_filled,
        total_fee_rmb=Decimal("1"),
        filled_notional_rmb=Decimal("5000"),
        revision=2,
        updated_at=updated_at,
        draft_reference=DRAFT_REF,
        execution_error=execution_error,
    )


def notification(
    *,
    notification_id: str = "notif-1",
    category: NotificationCategory = NotificationCategory.RISK,
    severity: NotificationSeverity = NotificationSeverity.WARNING,
    required: bool = False,
    created_at: datetime = NOW,
) -> Notification:
    return Notification(
        notification_id=notification_id,
        owner_user_id="owner-1",
        category=category,
        severity=severity,
        title="标题",
        message="消息内容",
        source_object_type="WorkflowRun",
        source_object_id="run-1",
        source_version="1",
        required=required,
        status=NotificationStatus.UNREAD,
        created_at=created_at,
        audit_reference=AuditReference(
            audit_id="audit-1",
            actor_id="system",
            recorded_at=created_at,
        ),
    )


class FakeOrders:
    def __init__(self, views: tuple[StoredOrderView, ...]) -> None:
        self._views = views

    async def list_order_views(
        self, *, owner_id: str
    ) -> tuple[StoredOrderView, ...]:
        del owner_id
        return self._views


class FakeNotifications:
    def __init__(self, items: tuple[Notification, ...]) -> None:
        self._items = items

    async def list_unread(self, owner_id: str) -> tuple[Notification, ...]:
        del owner_id
        return self._items


class Clock:
    def now(self) -> datetime:
        return NOW


class DecisionInboxTest(unittest.IsolatedAsyncioTestCase):
    def _service(
        self,
        *,
        views: tuple[StoredOrderView, ...] = (),
        notifications: tuple[Notification, ...] = (),
    ) -> DecisionInboxService:
        return DecisionInboxService(
            orders=FakeOrders(views),
            notifications=FakeNotifications(notifications),
            clock=Clock(),
        )

    async def test_empty_inbox_has_zero_counts(self) -> None:
        view = await self._service().inbox(owner_id="owner-1")
        self.assertEqual(view.counts.total, 0)
        self.assertEqual(view.items, ())

    async def test_unknown_order_is_p0(self) -> None:
        service = self._service(views=(order_view(status="unknown"),))
        view = await service.inbox(owner_id="owner-1")
        self.assertEqual(len(view.items), 1)
        item = view.items[0]
        self.assertEqual(item.priority, "P0")
        self.assertEqual(item.kind, "order")
        self.assertTrue(item.required)
        self.assertEqual(item.action_route, "orders")
        self.assertEqual(item.source_object_id, "draft-1")

    async def test_filled_order_is_p3_and_cancelled_excluded(self) -> None:
        service = self._service(
            views=(
                order_view(order_id="o-filled", status="filled"),
                order_view(order_id="o-cancelled", status="cancelled"),
                order_view(order_id="o-submitting", status="submitting"),
            )
        )
        view = await service.inbox(owner_id="owner-1")
        self.assertEqual(len(view.items), 1)
        self.assertEqual(view.items[0].priority, "P3")

    async def test_execution_error_escalates_to_p1(self) -> None:
        service = self._service(
            views=(order_view(status="filled", execution_error="broker rejected"),)
        )
        view = await service.inbox(owner_id="owner-1")
        self.assertEqual(view.items[0].priority, "P1")
        self.assertIn("broker rejected", view.items[0].detail)

    async def test_required_notification_is_p0(self) -> None:
        service = self._service(
            notifications=(
                notification(
                    severity=NotificationSeverity.REQUIRED,
                    category=NotificationCategory.AUTHORIZATION,
                    required=True,
                ),
            )
        )
        view = await service.inbox(owner_id="owner-1")
        self.assertEqual(view.items[0].priority, "P0")
        self.assertEqual(view.items[0].kind, "notification")

    async def test_authorization_error_is_p0(self) -> None:
        service = self._service(
            notifications=(
                notification(
                    category=NotificationCategory.AUTHORIZATION,
                    severity=NotificationSeverity.ERROR,
                ),
            )
        )
        view = await service.inbox(owner_id="owner-1")
        self.assertEqual(view.items[0].priority, "P0")

    async def test_items_sorted_by_priority_then_recency(self) -> None:
        service = self._service(
            views=(
                order_view(order_id="o-unknown", status="unknown"),
                order_view(order_id="o-partial", status="partially_filled"),
            ),
            notifications=(
                notification(
                    notification_id="n-info",
                    severity=NotificationSeverity.INFO,
                    category=NotificationCategory.FILL,
                ),
                notification(
                    notification_id="n-warn-old",
                    severity=NotificationSeverity.WARNING,
                    created_at=NOW - timedelta(hours=2),
                ),
                notification(
                    notification_id="n-warn-new",
                    severity=NotificationSeverity.WARNING,
                    created_at=NOW,
                ),
            ),
        )
        view = await service.inbox(owner_id="owner-1")
        priorities = [item.priority for item in view.items]
        self.assertEqual(priorities, ["P0", "P1", "P2", "P2", "P3"])
        self.assertEqual(view.counts.p0, 1)
        self.assertEqual(view.counts.p1, 1)
        self.assertEqual(view.counts.p2, 2)
        self.assertEqual(view.counts.p3, 1)
        self.assertEqual(view.counts.total, 5)
        # Within P2, the most recent warning comes first.
        p2_ids = [item.item_id for item in view.items if item.priority == "P2"]
        self.assertEqual(
            p2_ids, ["notification:n-warn-new", "notification:n-warn-old"]
        )


if __name__ == "__main__":
    unittest.main()
