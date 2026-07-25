from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from bridge.domain.models import AccountSnapshot, MarketSnapshot, MarketStatus, RiskPolicy
from bridge.domain.risk import review_plan
from bridge.injective.client import SpotLimitOrderRequest
from bridge.persistence.repository import BridgeRepository, canonical_json_hash
from bridge.settings import Settings


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _model(value: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in value.__table__.columns:
        item = getattr(value, column.name)
        if isinstance(item, Decimal):
            item = format(item, "f")
        elif isinstance(item, datetime):
            item = _utc(item).isoformat()
        result[column.name] = item
    return result


class BridgeApplication:
    def __init__(self, settings: Settings, injective: Any, finance_god: Any | None = None) -> None:
        self.settings, self.injective, self.finance_god = settings, injective, finance_god

    async def source_snapshot(self, repo: BridgeRepository, plan_id: str) -> dict[str, Any]:
        if not self.settings.finance_god_sync_enabled or self.finance_god is None:
            raise RuntimeError("Finance-God sync is disabled")
        item = await self.finance_god.fetch_snapshot(plan_id)
        snapshot = await repo.create_source_snapshot(
            source_plan_id=item.plan_id,
            projection={
                "plan_id": item.plan_id,
                "draft_id": item.draft_id,
                "version": item.plan_version,
                "status": item.plan_status,
                "expires_at": item.expires_at.isoformat() if item.expires_at else None,
                "audit_reference": item.audit_reference,
                "draft_status": item.draft_status,
                "draft_confirmed": item.draft_confirmed,
            },
            source_draft_id=item.draft_id,
            source_plan_version=str(item.plan_version),
            source_plan_status=item.plan_status,
            source_expires_at=item.expires_at,
            audit_reference=item.audit_reference,
            draft_status=item.draft_status,
            draft_confirmed=item.draft_confirmed,
        )
        return _model(snapshot)

    async def create_plan(
        self,
        repo: BridgeRepository,
        *,
        side: str,
        price: Decimal,
        quantity: Decimal,
        source_snapshot_id: str | None,
    ) -> dict[str, Any]:
        market = await self.injective.resolve_market(self.settings.market_ticker)
        plan = await repo.create_plan(
            market_id=market.market_id,
            ticker=market.ticker,
            side=side,
            price=price,
            quantity=quantity,
            source_snapshot_id=source_snapshot_id,
            expires_at=datetime.now(UTC) + timedelta(seconds=self.settings.plan_ttl_seconds),
        )
        return _model(plan)

    async def review(self, repo: BridgeRepository, plan_id: str) -> dict[str, Any]:
        plan = await repo.get_plan(plan_id)
        market = await self.injective.resolve_market(self.settings.market_ticker)
        book = await self.injective.order_book(market.market_id)
        balances = await self.injective.balances(self.subaccount_id)
        available = {b.denom: b.available for b in balances}
        domain_plan = __import__(
            "bridge.domain.models", fromlist=["InjectivePlan"]
        ).InjectivePlan.model_validate(
            {
                "id": plan.id,
                "market_id": plan.market_id,
                "ticker": plan.ticker,
                "side": plan.side,
                "price": plan.price,
                "quantity": plan.quantity,
                "status": plan.status,
                "revision": plan.revision,
                "created_at": _utc(plan.created_at),
                "updated_at": _utc(plan.updated_at),
                "expires_at": _utc(plan.expires_at),
            }
        )
        report = review_plan(
            domain_plan,
            market=MarketSnapshot(
                market_id=market.market_id,
                ticker=market.ticker,
                status=MarketStatus(market.status),
                min_price_tick_size=market.min_price_tick_size,
                min_quantity_tick_size=market.min_quantity_tick_size,
                best_bid=book.best_bid,
                best_ask=book.best_ask,
            ),
            account=AccountSnapshot(
                subaccount_id=self.subaccount_id,
                quote_available_balance=available.get(market.quote_denom, Decimal("0")),
                base_available_balance=available.get(market.base_denom, Decimal("0")),
            ),
            active_order_count=await repo.count_active_orders(subaccount_id=self.subaccount_id),
            policy=RiskPolicy(
                allowed_market_id=market.market_id,
                allowed_ticker=market.ticker,
                max_notional=self.settings.max_notional,
                max_price_deviation_bps=self.settings.max_price_deviation_bps,
                max_active_orders=self.settings.max_active_orders,
            ),
        )
        stored = await repo.review_plan(
            plan_id,
            expected_revision=plan.revision,
            risk_report=report.model_dump(mode="json"),
            approved=report.passed,
            rejection_reason=None
            if report.passed
            else ",".join(code.value for code in report.violations),
        )
        return _model(stored)

    @property
    def subaccount_id(self) -> str:
        return getattr(self.injective, "subaccount_id", "default-subaccount")

    async def confirm(
        self, repo: BridgeRepository, plan_id: str, expected_revision: int
    ) -> dict[str, Any]:
        if not self.settings.execution_enabled:
            raise RuntimeError(
                "Testnet execution is unavailable until a dedicated private key is configured"
            )
        return _model(await repo.confirm_plan(plan_id, expected_revision=expected_revision))

    async def submit(self, repo: BridgeRepository, plan_id: str) -> dict[str, Any]:
        plan = await repo.get_plan(plan_id)
        market = await self.injective.resolve_market(self.settings.market_ticker)
        order, _ = await repo.begin_broadcast(
            plan_id,
            expected_revision=plan.revision,
            market_id=market.market_id,
            subaccount_id=self.subaccount_id,
            request_hash=canonical_json_hash({"plan_id": plan_id, "revision": plan.revision}),
            max_active_orders=self.settings.max_active_orders,
            allow_sqlite_test_noop=self.settings.database_url.startswith("sqlite"),
        )
        try:
            tx_hash = await asyncio.wait_for(
                self.injective.submit_limit_order(
                    SpotLimitOrderRequest(
                        market.market_id,
                        self.subaccount_id,
                        plan.side,
                        plan.price,
                        plan.quantity,
                        order.client_order_id,
                    )
                ),
                timeout=self.settings.broadcast_timeout_seconds,
            )
            return _model(await repo.complete_broadcast(order.id, tx_hash=tx_hash))
        except Exception as exc:
            indeterminate = isinstance(exc, TimeoutError)
            cause = exc.__cause__
            while cause is not None and not indeterminate:
                indeterminate = isinstance(cause, TimeoutError)
                cause = cause.__cause__
            await repo.fail_broadcast(
                order.id,
                error_code="SUBMISSION_FAILED",
                error_message=str(exc),
                indeterminate=indeterminate,
            )
            raise

    async def cancel(self, repo: BridgeRepository, order_id: str) -> dict[str, Any]:
        order = await repo.get_order(order_id)
        if not order.order_hash:
            raise RuntimeError("order has no chain order hash and cannot be cancelled")
        tx_hash = await asyncio.wait_for(
            self.injective.cancel_order(
                order.market_id,
                order.subaccount_id,
                order.order_hash,
            ),
            timeout=self.settings.broadcast_timeout_seconds,
        )
        updated, _, _ = await repo.apply_order_event(
            order.id,
            event_key=f"cancel:{tx_hash}",
            status=order.status,
            payload={
                "cancel_tx_hash": tx_hash,
                "order_hash": order.order_hash,
                "state": "cancel_requested",
            },
            occurred_at=datetime.now(UTC),
            order_hash=order.order_hash,
        )
        return {
            "order": _model(updated),
            "cancel_tx_hash": tx_hash,
            "status": "cancel_requested",
        }

    async def reconcile(self, repo: BridgeRepository, order_id: str) -> dict[str, Any]:
        order = await repo.get_order(order_id)
        chain_orders = await self.injective.orders(
            order.market_id,
            order.subaccount_id,
        )
        chain_order = next(
            (
                item
                for item in chain_orders
                if (order.order_hash and item.order_hash == order.order_hash)
                or item.client_order_id == order.client_order_id
            ),
            None,
        )
        if chain_order is None:
            return _model(order)
        status_map = {
            "booked": "open",
            "active": "open",
            "unfilled": "open",
            "open": "open",
            "partial_filled": "partially_filled",
            "partially_filled": "partially_filled",
            "filled": "filled",
            "canceled": "cancelled",
            "cancelled": "cancelled",
            "rejected": "rejected",
        }
        target = status_map.get(chain_order.status)
        if target is None:
            return _model(order)
        updated, _, _ = await repo.apply_order_event(
            order.id,
            event_key=(
                f"indexer:{chain_order.order_hash}:{target}:"
                f"{format(chain_order.filled_quantity, 'f')}"
            ),
            status=target,
            payload={
                "order_hash": chain_order.order_hash,
                "status": target,
                "filled_quantity": format(chain_order.filled_quantity, "f"),
                "client_order_id": chain_order.client_order_id,
            },
            occurred_at=datetime.now(UTC),
            filled_quantity=chain_order.filled_quantity,
            tx_hash=chain_order.tx_hash or order.tx_hash,
            order_hash=chain_order.order_hash,
        )
        return _model(updated)

    async def ready(self) -> dict[str, Any]:
        if self.settings.network != "testnet":
            raise RuntimeError("only Testnet is permitted")
        market = await self.injective.resolve_market(self.settings.market_ticker)
        return {
            "network": "testnet",
            "market_id": market.market_id,
            "ticker": market.ticker,
            "execution_ready": self.settings.execution_enabled,
            "account_address": getattr(self.injective, "account_address", None),
            "subaccount_id": (self.subaccount_id if self.settings.execution_enabled else None),
        }
