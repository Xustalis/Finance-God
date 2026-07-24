"""Decision inbox aggregation for the trading overview (T01).

The decision inbox merges two authoritative fact sources into a single,
priority-ordered list of things the user must look at:

* execution order anomalies, derived from :class:`StoredOrderView` (unknown
  status, rejection, partial fill, cancelling, expiry, execution error);
* unread workspace notifications (authorization, risk, data quality, ...).

It never fabricates todos: every item is backed by a real order or a real
notification, and the AI layer may only summarize what is listed here. Order
market value / unrealized P&L are out of scope — this view is about *state and
action*, not valuation.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from finance_god.domain import (
    Notification,
    NotificationCategory,
    NotificationSeverity,
)
from finance_god.execution import StoredOrderView

# Priority buckets, most urgent first.
P0 = "P0"  # blocking: trading unavailable (auth/account/data/unknown order)
P1 = "P1"  # needs handling: user must confirm or dispose
P2 = "P2"  # needs attention: may affect the portfolio, no immediate action
P3 = "P3"  # informational: completed or general reminder

_PRIORITY_ORDER = {P0: 0, P1: 1, P2: 2, P3: 3}


class Clock(Protocol):
    def now(self) -> datetime: ...


class OrderViewSource(Protocol):
    async def list_order_views(
        self, *, owner_id: str
    ) -> Sequence[StoredOrderView]: ...


class NotificationSource(Protocol):
    async def list_unread(self, owner_id: str) -> Sequence[Notification]: ...


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DecisionInboxItem(StrictModel):
    item_id: str = Field(min_length=1, max_length=200)
    priority: str = Field(pattern=r"^P[0-3]$")
    kind: str = Field(pattern=r"^(order|notification)$")
    category: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(min_length=1, max_length=1000)
    source_object_type: str = Field(min_length=1, max_length=80)
    source_object_id: str = Field(min_length=1, max_length=160)
    occurred_at: AwareDatetime
    required: bool = False
    action_route: str | None = Field(default=None, max_length=40)


class DecisionInboxCounts(StrictModel):
    p0: int = Field(ge=0)
    p1: int = Field(ge=0)
    p2: int = Field(ge=0)
    p3: int = Field(ge=0)
    total: int = Field(ge=0)


class DecisionInboxView(StrictModel):
    owner_id: str = Field(min_length=1, max_length=160)
    as_of: AwareDatetime
    counts: DecisionInboxCounts
    items: tuple[DecisionInboxItem, ...] = ()


class DecisionInboxService:
    """Aggregate order anomalies and unread notifications into a todo list."""

    def __init__(
        self,
        *,
        orders: OrderViewSource,
        notifications: NotificationSource,
        clock: Clock,
    ) -> None:
        self._orders = orders
        self._notifications = notifications
        self._clock = clock

    async def inbox(self, *, owner_id: str) -> DecisionInboxView:
        order_views = await self._orders.list_order_views(owner_id=owner_id)
        unread = await self._notifications.list_unread(owner_id)
        items: list[DecisionInboxItem] = []
        for view in order_views:
            item = _order_item(view)
            if item is not None:
                items.append(item)
        for notification in unread:
            items.append(_notification_item(notification))
        items.sort(
            key=lambda item: (_PRIORITY_ORDER[item.priority], _negated(item.occurred_at))
        )
        return DecisionInboxView(
            owner_id=owner_id,
            as_of=self._clock.now(),
            counts=_count(items),
            items=tuple(items),
        )


def _negated(value: datetime) -> float:
    # Sort most recent first within a priority bucket.
    return -value.timestamp()


def _count(items: Sequence[DecisionInboxItem]) -> DecisionInboxCounts:
    tally = {P0: 0, P1: 0, P2: 0, P3: 0}
    for item in items:
        tally[item.priority] += 1
    return DecisionInboxCounts(
        p0=tally[P0],
        p1=tally[P1],
        p2=tally[P2],
        p3=tally[P3],
        total=len(items),
    )


def _order_item(view: StoredOrderView) -> DecisionInboxItem | None:
    priority, title, detail = _order_classification(view)
    if priority is None:
        return None
    if view.execution_error:
        detail = f"{detail}；执行异常：{view.execution_error}"
        if _PRIORITY_ORDER[priority] > _PRIORITY_ORDER[P1]:
            priority = P1
    return DecisionInboxItem(
        item_id=f"order:{view.order_id}",
        priority=priority,
        kind="order",
        category="order",
        title=title,
        detail=detail,
        source_object_type="OrderDraft",
        source_object_id=view.draft_reference.object_id,
        occurred_at=view.updated_at,
        required=priority in {P0, P1},
        action_route="orders",
    )


def _order_classification(
    view: StoredOrderView,
) -> tuple[str | None, str, str]:
    status = view.status
    filled = f"已成交 {view.cumulative_filled}/{view.quantity}"
    if status == "unknown":
        return P0, "订单状态未知", "需在执行中心对账确认最终状态"
    if status == "rejected":
        return P1, "订单被拒绝", "查看拒绝原因并决定是否重新下单"
    if status == "partially_filled":
        return P1, "订单部分成交", f"{filled}，需决定是否继续或撤单"
    if status == "cancelling":
        return P2, "撤单处理中", "确认撤单是否成功"
    if status == "expired":
        return P2, "订单已过期", "订单未在有效期内成交"
    if status == "filled":
        return P3, "订单已成交", filled
    # submitting / accepted / cancelled are normal in-flight or clean states.
    return None, "", ""


def _notification_item(notification: Notification) -> DecisionInboxItem:
    priority = _notification_priority(notification)
    return DecisionInboxItem(
        item_id=f"notification:{notification.notification_id}",
        priority=priority,
        kind="notification",
        category=notification.category.value,
        title=notification.title,
        detail=notification.message,
        source_object_type=notification.source_object_type,
        source_object_id=notification.source_object_id,
        occurred_at=notification.created_at,
        required=notification.required or priority == P0,
        action_route=_notification_route(notification.category),
    )


def _notification_priority(notification: Notification) -> str:
    severity = notification.severity
    if severity in {NotificationSeverity.REQUIRED, NotificationSeverity.HARD_RISK}:
        return P0
    if notification.category is NotificationCategory.AUTHORIZATION and severity in {
        NotificationSeverity.ERROR,
        NotificationSeverity.WARNING,
    }:
        return P0
    if severity is NotificationSeverity.ERROR:
        return P1
    if severity is NotificationSeverity.WARNING:
        return P2
    return P3


def _notification_route(category: NotificationCategory) -> str:
    if category in {NotificationCategory.ORDER, NotificationCategory.FILL}:
        return "orders"
    if category in {NotificationCategory.RISK, NotificationCategory.DATA_QUALITY}:
        return "portfolio"
    return "overview"
