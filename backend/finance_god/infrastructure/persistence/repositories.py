from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, TypeVar, cast

from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from finance_god.domain import (
    AccountEventEnvelope,
    AccountEventType,
    AccountStatus,
    CashProjection,
    ConcurrentCommandConflict,
    DomainInvariantViolation,
    ExchangeRateEvidence,
    Fill,
    JournalEntry,
    LedgerPosting,
    Money,
    PositionProjection,
    Reservation,
    ReservationKind,
    ReservationStatus,
    SimulationAccount,
    VersionReference,
)
from finance_god.domain.ledger import (
    AccountOpenedPayload,
    AccountResetClosedPayload,
    CashReleasedPayload,
    CashReservedPayload,
    EventPayload,
    FundAction,
    FundFillPayload,
    PositionReservedPayload,
    ReversalPayload,
    TradeFillPayload,
    TradeSide,
)

from .models import (
    AccountActivityRow,
    AccountEventRow,
    AccountProjectionRow,
    AccountRow,
    AuditRow,
    FillRow,
    IdempotencyRow,
    JournalRow,
    LedgerPostingRow,
    OutboxRow,
    PositionProjectionRow,
    ReservationRow,
)

ZERO = Decimal("0")
T = TypeVar("T")


def _required(value: T | None, field_name: str) -> T:
    if value is None:
        raise DomainInvariantViolation(f"persisted {field_name} is missing")
    return value


def _require_one(result: object, message: str) -> None:
    if cast(CursorResult[Any], result).rowcount != 1:
        raise ConcurrentCommandConflict(message)


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, account_id: str) -> SimulationAccount | None:
        row = await self._session.get(AccountRow, account_id)
        return _account(row) if row else None

    async def get_current(self, owner_user_id: str) -> SimulationAccount | None:
        row = await self._session.scalar(
            select(AccountRow).where(
                AccountRow.owner_user_id == owner_user_id,
                AccountRow.current.is_(True),
            )
        )
        return _account(row) if row else None

    async def add(self, account: SimulationAccount) -> None:
        self._session.add(_account_row(account))

    async def save(
        self, account: SimulationAccount, *, expected_revision: int
    ) -> None:
        result = await self._session.execute(
            update(AccountRow)
            .where(
                AccountRow.account_id == account.account_id,
                AccountRow.revision == expected_revision,
            )
            .values(
                status=account.status.value,
                current=account.current,
                revision=account.revision,
                closed_at=account.closed_at,
            )
        )
        _require_one(result, "account revision changed")


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, account_id: str) -> tuple[AccountEventEnvelope, ...]:
        rows = (
            await self._session.scalars(
                select(AccountEventRow)
                .where(AccountEventRow.account_id == account_id)
                .order_by(AccountEventRow.sequence)
            )
        ).all()
        return tuple(_event(row) for row in rows)

    async def last(self, account_id: str) -> AccountEventEnvelope | None:
        row = await self._session.scalar(
            select(AccountEventRow)
            .where(AccountEventRow.account_id == account_id)
            .order_by(AccountEventRow.sequence.desc())
            .limit(1)
        )
        return _event(row) if row else None

    async def append(self, event: AccountEventEnvelope) -> None:
        self._session.add(_event_row(event))


class JournalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, entry: JournalEntry) -> None:
        self._session.add(
            JournalRow(
                journal_id=entry.journal_id,
                account_id=entry.account_id,
                event_id=entry.event_id,
                occurred_at=entry.occurred_at,
                rule_version=entry.rule_version,
                reversal_of_journal_id=entry.reversal_of_journal_id,
                journal_hash=entry.journal_hash,
            )
        )
        self._session.add_all(
            [
                LedgerPostingRow(
                    posting_id=posting.posting_id,
                    journal_id=entry.journal_id,
                    sequence=sequence,
                    account_code=posting.account_code,
                    original_currency=posting.original.currency,
                    original_amount=posting.original.amount,
                    rmb_amount=posting.rmb_amount,
                    posting_hash=posting.posting_hash,
                )
                for sequence, posting in enumerate(entry.postings, start=1)
            ]
        )

    async def get_by_event(self, event_id: str) -> JournalEntry | None:
        row = await self._session.scalar(
            select(JournalRow).where(JournalRow.event_id == event_id)
        )
        return await self._entry(row) if row else None

    async def list(self, account_id: str) -> tuple[JournalEntry, ...]:
        rows = (
            await self._session.scalars(
                select(JournalRow)
                .where(JournalRow.account_id == account_id)
                .order_by(JournalRow.occurred_at, JournalRow.journal_id)
            )
        ).all()
        return tuple([await self._entry(row) for row in rows])

    async def _entry(self, row: JournalRow) -> JournalEntry:
        postings = (
            await self._session.scalars(
                select(LedgerPostingRow)
                .where(LedgerPostingRow.journal_id == row.journal_id)
                .order_by(LedgerPostingRow.sequence)
            )
        ).all()
        return JournalEntry(
            journal_id=row.journal_id,
            account_id=row.account_id,
            event_id=row.event_id,
            occurred_at=row.occurred_at,
            rule_version=row.rule_version,
            reversal_of_journal_id=row.reversal_of_journal_id,
            journal_hash=row.journal_hash,
            postings=tuple(
                LedgerPosting(
                    posting_id=item.posting_id,
                    sequence=item.sequence,
                    account_code=item.account_code,
                    original=Money(
                        currency=item.original_currency,
                        amount=item.original_amount,
                    ),
                    rmb_amount=item.rmb_amount,
                    posting_hash=item.posting_hash,
                )
                for item in postings
            ),
        )


class AccountProjectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, account_id: str, currency: str
    ) -> CashProjection | None:
        row = await self._session.get(AccountProjectionRow, (account_id, currency))
        return _cash(row) if row else None

    async def add(self, projection: CashProjection) -> None:
        self._session.add(_cash_row(projection))

    async def save(
        self, projection: CashProjection, *, expected_revision: int
    ) -> None:
        result = await self._session.execute(
            update(AccountProjectionRow)
            .where(
                AccountProjectionRow.account_id == projection.account_id,
                AccountProjectionRow.currency == projection.currency,
                AccountProjectionRow.revision == expected_revision,
            )
            .values(
                total=projection.total,
                frozen=projection.frozen,
                margin=projection.margin,
                rmb_total=projection.rmb_total,
                rmb_frozen=projection.rmb_frozen,
                rmb_margin=projection.rmb_margin,
                revision=projection.revision,
            )
        )
        _require_one(result, "cash projection revision changed")

    async def list(self, account_id: str) -> tuple[CashProjection, ...]:
        rows = (
            await self._session.scalars(
                select(AccountProjectionRow)
                .where(AccountProjectionRow.account_id == account_id)
                .order_by(AccountProjectionRow.currency)
            )
        ).all()
        return tuple(_cash(row) for row in rows)

    async def clear(self, account_id: str) -> None:
        await self._session.execute(
            delete(AccountProjectionRow).where(
                AccountProjectionRow.account_id == account_id
            )
        )


class PositionProjectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, account_id: str, instrument_id: str
    ) -> PositionProjection | None:
        row = await self._session.get(
            PositionProjectionRow, (account_id, instrument_id)
        )
        return _position(row) if row else None

    async def add(self, projection: PositionProjection) -> None:
        self._session.add(_position_row(projection))

    async def save(
        self, projection: PositionProjection, *, expected_revision: int
    ) -> None:
        result = await self._session.execute(
            update(PositionProjectionRow)
            .where(
                PositionProjectionRow.account_id == projection.account_id,
                PositionProjectionRow.instrument_id == projection.instrument_id,
                PositionProjectionRow.revision == expected_revision,
            )
            .values(**_position_values(projection))
        )
        _require_one(result, "position projection revision changed")

    async def list(self, account_id: str) -> tuple[PositionProjection, ...]:
        rows = (
            await self._session.scalars(
                select(PositionProjectionRow)
                .where(PositionProjectionRow.account_id == account_id)
                .order_by(PositionProjectionRow.instrument_id)
            )
        ).all()
        return tuple(_position(row) for row in rows)

    async def clear(self, account_id: str) -> None:
        await self._session.execute(
            delete(PositionProjectionRow).where(
                PositionProjectionRow.account_id == account_id
            )
        )


class ReservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, reservation_id: str) -> Reservation | None:
        row = await self._session.get(ReservationRow, reservation_id)
        return _reservation(row) if row else None

    async def add(self, reservation: Reservation) -> None:
        self._session.add(_reservation_row(reservation))

    async def save(
        self, reservation: Reservation, *, expected_revision: int
    ) -> None:
        result = await self._session.execute(
            update(ReservationRow)
            .where(
                ReservationRow.reservation_id == reservation.reservation_id,
                ReservationRow.revision == expected_revision,
            )
            .values(
                consumed_native=reservation.consumed_native,
                consumed_rmb=reservation.consumed_rmb,
                consumed_quantity=reservation.consumed_quantity,
                status=reservation.status.value,
                revision=reservation.revision,
            )
        )
        _require_one(result, "reservation revision changed")

    async def list(self, account_id: str) -> tuple[Reservation, ...]:
        rows = (
            await self._session.scalars(
                select(ReservationRow)
                .where(ReservationRow.account_id == account_id)
                .order_by(ReservationRow.reservation_id)
            )
        ).all()
        return tuple(_reservation(row) for row in rows)

    async def clear(self, account_id: str) -> None:
        await self._session.execute(
            delete(ReservationRow).where(ReservationRow.account_id == account_id)
        )


class FillRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, fill: Fill) -> None:
        self._session.add(_fill_row(fill))

    async def get_by_event(self, event_id: str) -> Fill | None:
        row = await self._session.scalar(
            select(FillRow).where(FillRow.event_id == event_id)
        )
        return _fill(row) if row else None

    async def list(self, account_id: str) -> tuple[Fill, ...]:
        rows = (
            await self._session.scalars(
                select(FillRow)
                .where(FillRow.account_id == account_id)
                .order_by(FillRow.occurred_at, FillRow.fill_id)
            )
        ).all()
        return tuple(_fill(row) for row in rows)


class IdempotencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, scope: str, owner_user_id: str, key: str
    ) -> IdempotencyRow | None:
        row: IdempotencyRow | None = await self._session.scalar(
            select(IdempotencyRow).where(
                IdempotencyRow.scope == scope,
                IdempotencyRow.owner_user_id == owner_user_id,
                IdempotencyRow.key == key,
            )
        )
        return row

    async def add(
        self,
        *,
        scope: str,
        owner_user_id: str,
        key: str,
        request_hash: str,
        result_reference: str,
        created_at: datetime,
    ) -> None:
        self._session.add(
            IdempotencyRow(
                scope=scope,
                owner_user_id=owner_user_id,
                key=key,
                request_hash=request_hash,
                result_reference=result_reference,
                created_at=created_at,
            )
        )


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        *,
        audit_id: str,
        owner_user_id: str,
        account_id: str,
        event_id: str | None,
        event_hash: str,
        journal_hash: str | None,
        action: str,
        correlation_id: str,
        occurred_at: datetime,
    ) -> None:
        self._session.add(
            AuditRow(
                audit_id=audit_id,
                owner_user_id=owner_user_id,
                account_id=account_id,
                event_id=event_id,
                event_hash=event_hash,
                journal_hash=journal_hash,
                action=action,
                correlation_id=correlation_id,
                occurred_at=occurred_at,
            )
        )

    async def list_for_event(self, event_id: str) -> tuple[AuditRow, ...]:
        return tuple(
            (
                await self._session.scalars(
                    select(AuditRow).where(AuditRow.event_id == event_id)
                )
            ).all()
        )

    async def count_action(self, account_id: str, action: str) -> int:
        return int(
            await self._session.scalar(
                select(func.count(AuditRow.audit_id)).where(
                    AuditRow.account_id == account_id,
                    AuditRow.action == action,
                )
            )
            or 0
        )


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        *,
        message_id: str,
        topic: str,
        aggregate_id: str,
        event_id: str,
        event_hash: str,
        occurred_at: datetime,
    ) -> None:
        self._session.add(
            OutboxRow(
                message_id=message_id,
                topic=topic,
                aggregate_id=aggregate_id,
                event_id=event_id,
                event_hash=event_hash,
                occurred_at=occurred_at,
            )
        )

    async def get_by_event(self, event_id: str) -> OutboxRow | None:
        row: OutboxRow | None = await self._session.scalar(
            select(OutboxRow).where(OutboxRow.event_id == event_id)
        )
        return row


class ActivityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def has_open(self, account_id: str) -> bool:
        return (
            await self._session.scalar(
                select(AccountActivityRow.activity_id)
                .where(
                    AccountActivityRow.account_id == account_id,
                    AccountActivityRow.status == "open",
                )
                .limit(1)
            )
            is not None
        )

    async def open(
        self,
        *,
        activity_id: str,
        account_id: str,
        activity_type: str,
        reference_id: str,
        occurred_at: datetime,
    ) -> None:
        self._session.add(
            AccountActivityRow(
                activity_id=activity_id,
                account_id=account_id,
                activity_type=activity_type,
                reference_id=reference_id,
                status="open",
                opened_at=occurred_at,
            )
        )

    async def complete(
        self, reference_id: str, *, occurred_at: datetime
    ) -> None:
        result = await self._session.execute(
            update(AccountActivityRow)
            .where(
                AccountActivityRow.reference_id == reference_id,
                AccountActivityRow.status == "open",
            )
            .values(status="completed", completed_at=occurred_at)
        )
        _require_one(result, "activity is no longer open")

    async def reopen(self, reference_id: str) -> None:
        result = await self._session.execute(
            update(AccountActivityRow)
            .where(
                AccountActivityRow.reference_id == reference_id,
                AccountActivityRow.status == "completed",
            )
            .values(status="open", completed_at=None)
        )
        _require_one(result, "activity cannot be reopened")


def _account(row: AccountRow) -> SimulationAccount:
    return SimulationAccount(
        account_id=row.account_id,
        owner_user_id=row.owner_user_id,
        initial_cash_rmb=row.initial_cash_rmb,
        status=AccountStatus(row.status),
        current=row.current,
        revision=row.revision,
        created_at=row.created_at,
        closed_at=row.closed_at,
        reset_from_account_id=row.reset_from_account_id,
    )


def _account_row(account: SimulationAccount) -> AccountRow:
    return AccountRow(
        account_id=account.account_id,
        owner_user_id=account.owner_user_id,
        initial_cash_rmb=account.initial_cash_rmb,
        status=account.status.value,
        current=account.current,
        revision=account.revision,
        created_at=account.created_at,
        closed_at=account.closed_at,
        reset_from_account_id=account.reset_from_account_id,
    )


def _event(row: AccountEventRow) -> AccountEventEnvelope:
    return AccountEventEnvelope(
        event_id=row.event_id,
        account_id=row.account_id,
        owner_user_id=row.owner_user_id,
        sequence=row.sequence,
        event_type=AccountEventType(row.event_type),
        occurred_at=row.occurred_at,
        correlation_id=row.correlation_id,
        causation_id=row.causation_id,
        source=VersionReference(
            object_type=row.source_object_type,
            object_id=row.source_object_id,
            version=row.source_version,
        ),
        rule_version=row.rule_version,
        previous_hash=row.previous_hash,
        payload=_payload(row),
        event_hash=row.event_hash,
    )


def _event_row(event: AccountEventEnvelope) -> AccountEventRow:
    values: dict[str, object] = {
        "event_id": event.event_id,
        "account_id": event.account_id,
        "owner_user_id": event.owner_user_id,
        "sequence": event.sequence,
        "event_type": event.event_type.value,
        "occurred_at": event.occurred_at,
        "correlation_id": event.correlation_id,
        "causation_id": event.causation_id,
        "source_object_type": event.source.object_type,
        "source_object_id": event.source.object_id,
        "source_version": event.source.version,
        "rule_version": event.rule_version,
        "previous_hash": event.previous_hash,
        "event_hash": event.event_hash,
        "payload_kind": event.payload.kind,
    }
    payload = event.payload
    if isinstance(payload, AccountOpenedPayload):
        values.update(
            native_currency=payload.initial_cash.currency,
            native_amount=payload.initial_cash.amount,
            rmb_amount=payload.initial_cash.amount,
        )
    elif isinstance(payload, AccountResetClosedPayload):
        values["new_account_id"] = payload.new_account_id
    elif isinstance(payload, CashReservedPayload):
        values.update(
            reservation_id=payload.reservation_id,
            order_id=payload.order_id,
            instrument_id=payload.instrument_id,
            reservation_kind=payload.reservation_kind.value,
            native_currency=payload.native_amount.currency,
            native_amount=payload.native_amount.amount,
            rmb_amount=payload.rmb_amount.amount,
        )
        _put_fx(values, payload.exchange_rate)
    elif isinstance(payload, CashReleasedPayload):
        values.update(
            reservation_id=payload.reservation_id,
            order_id=payload.order_id,
            native_currency=payload.native_amount.currency,
            native_amount=payload.native_amount.amount,
            rmb_amount=payload.rmb_amount.amount,
        )
    elif isinstance(payload, PositionReservedPayload):
        values.update(
            reservation_id=payload.reservation_id,
            order_id=payload.order_id,
            instrument_id=payload.instrument_id,
            quantity=payload.quantity,
        )
    elif isinstance(payload, TradeFillPayload):
        _put_trade(values, payload)
    elif isinstance(payload, FundFillPayload):
        _put_fund(values, payload)
    elif isinstance(payload, ReversalPayload):
        values.update(
            original_event_id=payload.original_event_id,
            original_event_hash=payload.original_event_hash,
            correction_reason=payload.reason,
        )
    return AccountEventRow(**values)


def _payload(row: AccountEventRow) -> EventPayload:
    fx = _fx(row)
    if row.payload_kind == "account_opened":
        return AccountOpenedPayload(
            initial_cash=Money(
                currency=_required(row.native_currency, "opening currency"),
                amount=_required(row.native_amount, "opening amount"),
            )
        )
    if row.payload_kind == "account_reset_closed":
        return AccountResetClosedPayload(
            new_account_id=_required(row.new_account_id, "reset new account")
        )
    if row.payload_kind == "cash_reserved":
        return CashReservedPayload(
            reservation_id=_required(row.reservation_id, "reservation id"),
            order_id=_required(row.order_id, "reservation order id"),
            instrument_id=_required(
                row.instrument_id, "reservation instrument id"
            ),
            reservation_kind=ReservationKind(
                _required(row.reservation_kind, "reservation kind")
            ),
            native_amount=Money(
                currency=_required(row.native_currency, "reservation currency"),
                amount=_required(row.native_amount, "reservation native amount"),
            ),
            rmb_amount=Money(
                currency="CNY",
                amount=_required(row.rmb_amount, "reservation RMB amount"),
            ),
            exchange_rate=fx,
        )
    if row.payload_kind == "cash_released":
        return CashReleasedPayload(
            reservation_id=_required(row.reservation_id, "release reservation id"),
            order_id=_required(row.order_id, "release order id"),
            native_amount=Money(
                currency=_required(row.native_currency, "release currency"),
                amount=_required(row.native_amount, "release native amount"),
            ),
            rmb_amount=Money(
                currency="CNY", amount=_required(row.rmb_amount, "release RMB amount")
            ),
        )
    if row.payload_kind == "position_reserved":
        return PositionReservedPayload(
            reservation_id=_required(row.reservation_id, "position reservation id"),
            order_id=_required(row.order_id, "position reservation order id"),
            instrument_id=_required(
                row.instrument_id, "position reservation instrument"
            ),
            quantity=_required(row.quantity, "position reservation quantity"),
        )
    if row.payload_kind == "trade_fill":
        market = _market(row)
        currency = _required(row.native_currency, "trade currency")
        return TradeFillPayload(
            side=TradeSide(_required(row.trade_side, "trade side")),
            reservation_id=row.reservation_id,
            order_id=_required(row.order_id, "trade order id"),
            instrument_id=_required(row.instrument_id, "trade instrument"),
            quantity=_required(row.quantity, "trade quantity"),
            native_gross=Money(
                currency=currency,
                amount=_required(row.native_gross, "trade native gross"),
            ),
            native_fee=Money(
                currency=currency,
                amount=_required(row.native_fee, "trade native fee"),
            ),
            native_borrow_fee=Money(
                currency=currency,
                amount=_required(row.native_borrow_fee, "trade native borrow fee"),
            ),
            rmb_gross=Money(
                currency="CNY", amount=_required(row.rmb_gross, "trade RMB gross")
            ),
            rmb_fee=Money(
                currency="CNY", amount=_required(row.rmb_fee, "trade RMB fee")
            ),
            rmb_borrow_fee=Money(
                currency="CNY",
                amount=_required(row.rmb_borrow_fee, "trade RMB borrow fee"),
            ),
            margin_change_rmb=Money(
                currency="CNY",
                amount=_required(row.margin_change_rmb, "trade margin change"),
            ),
            exchange_rate=fx,
            slippage_bps=_required(row.slippage_bps, "trade slippage"),
            market_evidence=market,
            model_version=_required(row.model_version, "trade model version"),
        )
    if row.payload_kind == "fund_fill":
        market = _market(row)
        currency = _required(row.native_currency, "fund currency")
        return FundFillPayload(
            action=FundAction(_required(row.fund_action, "fund action")),
            reservation_id=_required(row.reservation_id, "fund reservation id"),
            order_id=_required(row.order_id, "fund order id"),
            instrument_id=_required(row.instrument_id, "fund instrument"),
            units=_required(row.quantity, "fund units"),
            nav=Money(currency=currency, amount=_required(row.nav, "fund NAV")),
            native_gross=Money(
                currency=currency,
                amount=_required(row.native_gross, "fund native gross"),
            ),
            native_fee=Money(
                currency=currency,
                amount=_required(row.native_fee, "fund native fee"),
            ),
            rmb_gross=Money(
                currency="CNY", amount=_required(row.rmb_gross, "fund RMB gross")
            ),
            rmb_fee=Money(
                currency="CNY", amount=_required(row.rmb_fee, "fund RMB fee")
            ),
            exchange_rate=fx,
            market_evidence=market,
            model_version=_required(row.model_version, "fund model version"),
            settled=_required(row.settled, "fund settlement status"),
        )
    if row.payload_kind == "reversal":
        return ReversalPayload(
            original_event_id=_required(
                row.original_event_id, "reversal original event"
            ),
            original_event_hash=_required(
                row.original_event_hash, "reversal original hash"
            ),
            reason=_required(row.correction_reason, "reversal reason"),
        )
    raise DomainInvariantViolation(f"unknown persisted payload kind: {row.payload_kind}")


def _put_trade(values: dict[str, object], payload: TradeFillPayload) -> None:
    values.update(
        trade_side=payload.side.value,
        reservation_id=payload.reservation_id,
        order_id=payload.order_id,
        instrument_id=payload.instrument_id,
        quantity=payload.quantity,
        native_currency=payload.native_gross.currency,
        native_gross=payload.native_gross.amount,
        native_fee=payload.native_fee.amount,
        native_borrow_fee=payload.native_borrow_fee.amount,
        rmb_gross=payload.rmb_gross.amount,
        rmb_fee=payload.rmb_fee.amount,
        rmb_borrow_fee=payload.rmb_borrow_fee.amount,
        margin_change_rmb=payload.margin_change_rmb.amount,
        slippage_bps=payload.slippage_bps,
        market_object_type=payload.market_evidence.object_type,
        market_object_id=payload.market_evidence.object_id,
        market_version=payload.market_evidence.version,
        model_version=payload.model_version,
    )
    _put_fx(values, payload.exchange_rate)


def _put_fund(values: dict[str, object], payload: FundFillPayload) -> None:
    values.update(
        fund_action=payload.action.value,
        reservation_id=payload.reservation_id,
        order_id=payload.order_id,
        instrument_id=payload.instrument_id,
        quantity=payload.units,
        nav=payload.nav.amount,
        native_currency=payload.native_gross.currency,
        native_gross=payload.native_gross.amount,
        native_fee=payload.native_fee.amount,
        rmb_gross=payload.rmb_gross.amount,
        rmb_fee=payload.rmb_fee.amount,
        market_object_type=payload.market_evidence.object_type,
        market_object_id=payload.market_evidence.object_id,
        market_version=payload.market_evidence.version,
        model_version=payload.model_version,
        settled=payload.settled,
    )
    _put_fx(values, payload.exchange_rate)


def _put_fx(
    values: dict[str, object], evidence: ExchangeRateEvidence | None
) -> None:
    if evidence is None:
        return
    values.update(
        fx_base_currency=evidence.base_currency,
        fx_quote_currency=evidence.quote_currency,
        fx_rate=evidence.rate,
        fx_observed_at=evidence.observed_at,
        fx_source_object_type=evidence.source.object_type,
        fx_source_object_id=evidence.source.object_id,
        fx_source_version=evidence.source.version,
    )


def _fx(row: AccountEventRow | FillRow) -> ExchangeRateEvidence | None:
    if row.fx_rate is None:
        return None
    return ExchangeRateEvidence(
        base_currency=_required(row.fx_base_currency, "FX base currency"),
        quote_currency=_required(row.fx_quote_currency, "FX quote currency"),
        rate=row.fx_rate,
        observed_at=_required(row.fx_observed_at, "FX observed time"),
        source=VersionReference(
            object_type=_required(row.fx_source_object_type, "FX source type"),
            object_id=_required(row.fx_source_object_id, "FX source id"),
            version=_required(row.fx_source_version, "FX source version"),
        ),
    )


def _market(row: AccountEventRow | FillRow) -> VersionReference:
    return VersionReference(
        object_type=_required(row.market_object_type, "market source type"),
        object_id=_required(row.market_object_id, "market source id"),
        version=_required(row.market_version, "market source version"),
    )


def _cash(row: AccountProjectionRow) -> CashProjection:
    return CashProjection(
        account_id=row.account_id,
        currency=row.currency,
        total=row.total,
        frozen=row.frozen,
        margin=row.margin,
        rmb_total=row.rmb_total,
        rmb_frozen=row.rmb_frozen,
        rmb_margin=row.rmb_margin,
        revision=row.revision,
    )


def _cash_row(item: CashProjection) -> AccountProjectionRow:
    return AccountProjectionRow(
        account_id=item.account_id,
        currency=item.currency,
        total=item.total,
        frozen=item.frozen,
        margin=item.margin,
        rmb_total=item.rmb_total,
        rmb_frozen=item.rmb_frozen,
        rmb_margin=item.rmb_margin,
        revision=item.revision,
    )


def _position(row: PositionProjectionRow) -> PositionProjection:
    return PositionProjection(
        account_id=row.account_id,
        instrument_id=row.instrument_id,
        currency=row.currency,
        long_quantity=row.long_quantity,
        short_quantity=row.short_quantity,
        settled_quantity=row.settled_quantity,
        frozen_quantity=row.frozen_quantity,
        long_cost_native=row.long_cost_native,
        long_cost_rmb=row.long_cost_rmb,
        short_proceeds_native=row.short_proceeds_native,
        short_proceeds_rmb=row.short_proceeds_rmb,
        margin_rmb=row.margin_rmb,
        borrow_fee_rmb=row.borrow_fee_rmb,
        revision=row.revision,
    )


def _position_values(item: PositionProjection) -> dict[str, object]:
    return {
        "currency": item.currency,
        "long_quantity": item.long_quantity,
        "short_quantity": item.short_quantity,
        "settled_quantity": item.settled_quantity,
        "frozen_quantity": item.frozen_quantity,
        "long_cost_native": item.long_cost_native,
        "long_cost_rmb": item.long_cost_rmb,
        "short_proceeds_native": item.short_proceeds_native,
        "short_proceeds_rmb": item.short_proceeds_rmb,
        "margin_rmb": item.margin_rmb,
        "borrow_fee_rmb": item.borrow_fee_rmb,
        "revision": item.revision,
    }


def _position_row(item: PositionProjection) -> PositionProjectionRow:
    return PositionProjectionRow(
        account_id=item.account_id,
        instrument_id=item.instrument_id,
        **_position_values(item),
    )


def _reservation(row: ReservationRow) -> Reservation:
    return Reservation(
        reservation_id=row.reservation_id,
        account_id=row.account_id,
        order_id=row.order_id,
        instrument_id=row.instrument_id,
        kind=ReservationKind(row.kind),
        native_amount=Money(currency=row.native_currency, amount=row.native_amount),
        rmb_amount=row.rmb_amount,
        quantity=row.quantity,
        consumed_native=row.consumed_native,
        consumed_rmb=row.consumed_rmb,
        consumed_quantity=row.consumed_quantity,
        status=ReservationStatus(row.status),
        revision=row.revision,
    )


def _reservation_row(item: Reservation) -> ReservationRow:
    return ReservationRow(
        reservation_id=item.reservation_id,
        account_id=item.account_id,
        order_id=item.order_id,
        instrument_id=item.instrument_id,
        kind=item.kind.value,
        native_currency=item.native_amount.currency,
        native_amount=item.native_amount.amount,
        rmb_amount=item.rmb_amount,
        quantity=item.quantity,
        consumed_native=item.consumed_native,
        consumed_rmb=item.consumed_rmb,
        consumed_quantity=item.consumed_quantity,
        status=item.status.value,
        revision=item.revision,
    )


def _fill_row(item: Fill) -> FillRow:
    values: dict[str, object] = {
        "fill_id": item.fill_id,
        "event_id": item.event_id,
        "account_id": item.account_id,
        "order_id": item.order_id,
        "reservation_id": item.reservation_id,
        "instrument_id": item.instrument_id,
        "transaction_type": item.transaction_type,
        "quantity": item.quantity,
        "native_currency": item.native_gross.currency,
        "native_gross": item.native_gross.amount,
        "native_fee": item.native_fee.amount,
        "native_borrow_fee": item.native_borrow_fee.amount,
        "rmb_gross": item.rmb_gross,
        "rmb_fee": item.rmb_fee,
        "rmb_borrow_fee": item.rmb_borrow_fee,
        "margin_change_rmb": item.margin_change_rmb,
        "slippage_bps": item.slippage_bps,
        "market_object_type": item.market_evidence.object_type,
        "market_object_id": item.market_evidence.object_id,
        "market_version": item.market_evidence.version,
        "model_version": item.model_version,
        "rule_version": item.rule_version,
        "occurred_at": item.occurred_at,
    }
    _put_fx(values, item.exchange_rate)
    return FillRow(**values)


def _fill(row: FillRow) -> Fill:
    return Fill(
        fill_id=row.fill_id,
        event_id=row.event_id,
        account_id=row.account_id,
        order_id=row.order_id,
        reservation_id=row.reservation_id,
        instrument_id=row.instrument_id,
        transaction_type=row.transaction_type,
        quantity=row.quantity,
        native_gross=Money(currency=row.native_currency, amount=row.native_gross),
        native_fee=Money(currency=row.native_currency, amount=row.native_fee),
        native_borrow_fee=Money(
            currency=row.native_currency, amount=row.native_borrow_fee
        ),
        rmb_gross=row.rmb_gross,
        rmb_fee=row.rmb_fee,
        rmb_borrow_fee=row.rmb_borrow_fee,
        margin_change_rmb=row.margin_change_rmb,
        slippage_bps=row.slippage_bps,
        exchange_rate=_fx(row),
        market_evidence=_market(row),
        model_version=row.model_version,
        rule_version=row.rule_version,
        occurred_at=row.occurred_at,
    )
