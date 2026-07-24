from __future__ import annotations

from decimal import Decimal

from finance_god.application.journal_rules import (
    expected_posting_rows,
    semantic_posting_rows,
)
from finance_god.application.ports import UnitOfWork
from finance_god.application.reversal_rules import validate_reversal_history
from finance_god.domain import (
    AccountEventEnvelope,
    AccountEventType,
    CashProjection,
    DomainInvariantViolation,
    Money,
    PositionProjection,
    Reservation,
    projection_checksum,
)
from finance_god.domain.ledger import (
    AccountOpenedPayload,
    CashReleasedPayload,
    CashReservedPayload,
    FundAction,
    FundFillPayload,
    PositionReservedPayload,
    ReservationKind,
    ReversalPayload,
    TradeFillPayload,
    TradeSide,
)
from finance_god.domain.simulation_rules import (
    derived_money,
    proportional_consumption,
    proportional_remaining,
    require_rule_version,
)

ZERO = Decimal("0")
FINANCIAL_EVENTS = frozenset(
    {
        AccountEventType.ACCOUNT_OPENED,
        AccountEventType.CASH_RESERVED,
        AccountEventType.CASH_RELEASED,
        AccountEventType.BUY_FILL_RECORDED,
        AccountEventType.SELL_FILL_RECORDED,
        AccountEventType.SHORT_FILL_RECORDED,
        AccountEventType.COVER_FILL_RECORDED,
        AccountEventType.FUND_SUBSCRIPTION_CONFIRMED,
        AccountEventType.FUND_REDEMPTION_CONFIRMED,
        AccountEventType.REVERSAL_RECORDED,
    }
)
FILL_EVENTS = frozenset(
    {
        AccountEventType.BUY_FILL_RECORDED,
        AccountEventType.SELL_FILL_RECORDED,
        AccountEventType.SHORT_FILL_RECORDED,
        AccountEventType.COVER_FILL_RECORDED,
        AccountEventType.FUND_SUBSCRIPTION_CONFIRMED,
        AccountEventType.FUND_REDEMPTION_CONFIRMED,
    }
)


async def rebuild_projections(uow: UnitOfWork, account_id: str) -> str:
    await uow.locks.account(account_id)
    account = await uow.accounts.get(account_id)
    if account is None:
        raise DomainInvariantViolation("account not found")
    events = await uow.events.list(account_id)
    await _verify_facts(uow, events)
    cash, positions, reservations = project_event_stream(events)
    await replace_projections(uow, account_id, cash, positions, reservations)
    anchor = events[-1].event_hash if events else "0" * 64
    rebuild_revision = await uow.audits.count_action(
        account_id, "projection_rebuild"
    ) + 1
    await uow.audits.append(
        audit_id=f"rebuild-{account_id}-{rebuild_revision}-{anchor[:12]}",
        owner_user_id=account.owner_user_id,
        account_id=account_id,
        event_id=None,
        event_hash=anchor,
        journal_hash=None,
        action="projection_rebuild",
        correlation_id=f"projection-rebuild-{anchor[:16]}",
        occurred_at=events[-1].occurred_at if events else account.created_at,
    )
    await uow.flush()
    await uow.commit()
    return projection_checksum(
        tuple(cash[key] for key in sorted(cash)),
        tuple(positions[key] for key in sorted(positions)),
        tuple(reservations[key] for key in sorted(reservations)),
    )


async def replace_projections(
    uow: UnitOfWork,
    account_id: str,
    cash: dict[str, CashProjection],
    positions: dict[str, PositionProjection],
    reservations: dict[str, Reservation],
) -> None:
    await uow.account_projections.clear(account_id)
    await uow.position_projections.clear(account_id)
    await uow.reservations.clear(account_id)
    await uow.flush()
    for cash_projection in cash.values():
        await uow.account_projections.add(cash_projection)
    for position_projection in positions.values():
        await uow.position_projections.add(position_projection)
    for reservation in reservations.values():
        await uow.reservations.add(reservation)


async def _verify_facts(
    uow: UnitOfWork, events: tuple[AccountEventEnvelope, ...]
) -> None:
    validate_reversal_history(events)
    previous: AccountEventEnvelope | None = None
    by_id: dict[str, AccountEventEnvelope] = {}
    for expected_sequence, event in enumerate(events, start=1):
        require_rule_version(event.rule_version)
        if event.sequence != expected_sequence:
            raise DomainInvariantViolation("event sequence is not contiguous")
        if previous is None and event.previous_hash is not None:
            raise DomainInvariantViolation("first event previous_hash must be null")
        if previous is not None and event.previous_hash != previous.event_hash:
            raise DomainInvariantViolation("event hash chain is broken")
        audits = await uow.audits.list_for_event(event.event_id)
        if len(audits) != 1 or getattr(audits[0], "event_hash", None) != event.event_hash:
            raise DomainInvariantViolation("event audit anchor is missing or inconsistent")
        outbox = await uow.outbox.get_by_event(event.event_id)
        if outbox is None or getattr(outbox, "event_hash", None) != event.event_hash:
            raise DomainInvariantViolation("event outbox anchor is missing or inconsistent")
        journal = await uow.journals.get_by_event(event.event_id)
        if event.event_type in FINANCIAL_EVENTS and journal is None:
            raise DomainInvariantViolation("financial event journal is missing")
        if event.event_type not in FINANCIAL_EVENTS and journal is not None:
            raise DomainInvariantViolation("non-financial event has a journal")
        if journal is not None and (
            journal.account_id != event.account_id
            or journal.event_id != event.event_id
            or journal.rule_version != event.rule_version
            or journal.occurred_at != event.occurred_at
        ):
            raise DomainInvariantViolation("journal fact does not match event")
        original_journal = None
        if isinstance(event.payload, ReversalPayload):
            original = by_id.get(event.payload.original_event_id)
            if original is None:
                raise DomainInvariantViolation("reversal target does not exist")
            original_journal = await uow.journals.get_by_event(original.event_id)
            if (
                journal is None
                or original_journal is None
                or journal.reversal_of_journal_id
                != original_journal.journal_id
            ):
                raise DomainInvariantViolation("reversal journal link is invalid")
        expected_rows = expected_posting_rows(
            event, reversed_journal=original_journal
        )
        if journal is not None and (
            expected_rows is None
            or semantic_posting_rows(journal) != expected_rows
        ):
            raise DomainInvariantViolation(
                "journal postings do not match event semantics"
            )
        expected_journal_hash = journal.journal_hash if journal else None
        if getattr(audits[0], "journal_hash", None) != expected_journal_hash:
            raise DomainInvariantViolation(
                "event audit journal anchor is inconsistent"
            )
        fill = await uow.fills.get_by_event(event.event_id)
        if event.event_type in FILL_EVENTS and fill is None:
            raise DomainInvariantViolation("fill fact is missing")
        if event.event_type not in FILL_EVENTS and fill is not None:
            raise DomainInvariantViolation("non-fill event has a fill fact")
        if fill is not None:
            _verify_fill_fact(event, fill)
        if isinstance(event.payload, FundFillPayload):
            expected_gross = derived_money(
                event.payload.units * event.payload.nav.amount,
                rule_version=event.rule_version,
                label="fund gross",
            )
            if event.payload.native_gross.amount != expected_gross:
                raise DomainInvariantViolation(
                    "fund gross does not match versioned rules"
                )
        by_id[event.event_id] = event
        previous = event


def _verify_fill_fact(event: AccountEventEnvelope, fill: object) -> None:
    payload = event.payload
    if isinstance(payload, TradeFillPayload):
        expected_transaction_type = payload.side.value
        expected_quantity = payload.quantity
        expected_native_borrow_fee = payload.native_borrow_fee
        expected_rmb_borrow_fee = payload.rmb_borrow_fee.amount
        expected_margin = payload.margin_change_rmb.amount
    elif isinstance(payload, FundFillPayload):
        expected_transaction_type = f"fund_{payload.action.value}"
        expected_quantity = payload.units
        expected_native_borrow_fee = _zero_money(payload.native_gross.currency)
        expected_rmb_borrow_fee = ZERO
        expected_margin = ZERO
    else:
        raise DomainInvariantViolation("fill fact is attached to a non-fill payload")
    expected = {
        "event_id": event.event_id,
        "account_id": event.account_id,
        "order_id": payload.order_id,
        "reservation_id": payload.reservation_id,
        "instrument_id": payload.instrument_id,
        "transaction_type": expected_transaction_type,
        "quantity": expected_quantity,
        "native_gross": payload.native_gross,
        "native_fee": payload.native_fee,
        "native_borrow_fee": expected_native_borrow_fee,
        "rmb_gross": payload.rmb_gross.amount,
        "rmb_fee": payload.rmb_fee.amount,
        "rmb_borrow_fee": expected_rmb_borrow_fee,
        "margin_change_rmb": expected_margin,
        "exchange_rate": payload.exchange_rate,
        "market_evidence": payload.market_evidence,
        "model_version": payload.model_version,
        "rule_version": event.rule_version,
        "occurred_at": event.occurred_at,
    }
    for field_name, expected_value in expected.items():
        if getattr(fill, field_name, None) != expected_value:
            raise DomainInvariantViolation(
                f"fill fact field {field_name} does not match event"
            )
    if isinstance(payload, TradeFillPayload) and (
        getattr(fill, "slippage_bps", None) != payload.slippage_bps
    ):
        raise DomainInvariantViolation("fill slippage does not match event")


def project_event_stream(
    events: tuple[AccountEventEnvelope, ...],
) -> tuple[
    dict[str, CashProjection],
    dict[str, PositionProjection],
    dict[str, Reservation],
]:
    reversed_ids = {
        event.payload.original_event_id
        for event in events
        if isinstance(event.payload, ReversalPayload)
    }
    cash: dict[str, CashProjection] = {}
    positions: dict[str, PositionProjection] = {}
    reservations: dict[str, Reservation] = {}
    for event in events:
        payload = event.payload
        if event.event_id in reversed_ids or isinstance(payload, ReversalPayload):
            continue
        if isinstance(payload, AccountOpenedPayload):
            cash["CNY"] = CashProjection(
                account_id=event.account_id,
                currency="CNY",
                total=payload.initial_cash.amount,
                rmb_total=payload.initial_cash.amount,
                revision=1,
            )
        elif isinstance(payload, CashReservedPayload):
            _project_cash_reserve(event, payload, cash, reservations)
        elif isinstance(payload, CashReleasedPayload):
            reservation = _reservation(payload.reservation_id, reservations)
            reservations[reservation.reservation_id] = reservation.release()
            cny = _cash("CNY", cash)
            cash["CNY"] = _cash_replace(
                cny,
                frozen=cny.frozen - payload.rmb_amount.amount,
                rmb_frozen=cny.rmb_frozen - payload.rmb_amount.amount,
            )
        elif isinstance(payload, PositionReservedPayload):
            position = _position(payload.instrument_id, positions)
            positions[payload.instrument_id] = _position_replace(
                position,
                frozen_quantity=position.frozen_quantity + payload.quantity,
            )
            reservations[payload.reservation_id] = Reservation(
                reservation_id=payload.reservation_id,
                account_id=event.account_id,
                order_id=payload.order_id,
                instrument_id=payload.instrument_id,
                kind=ReservationKind.FUND_REDEMPTION,
                native_amount=_zero_money(position.currency),
                rmb_amount=ZERO,
                quantity=payload.quantity,
            )
        elif isinstance(payload, TradeFillPayload):
            _project_trade(event, payload, cash, positions, reservations)
        elif isinstance(payload, FundFillPayload):
            _project_fund(event, payload, cash, positions, reservations)
    return cash, positions, reservations


def _project_cash_reserve(
    event: AccountEventEnvelope,
    payload: CashReservedPayload,
    cash: dict[str, CashProjection],
    reservations: dict[str, Reservation],
) -> None:
    cny = _cash("CNY", cash)
    cash["CNY"] = _cash_replace(
        cny,
        frozen=cny.frozen + payload.rmb_amount.amount,
        rmb_frozen=cny.rmb_frozen + payload.rmb_amount.amount,
    )
    reservations[payload.reservation_id] = Reservation(
        reservation_id=payload.reservation_id,
        account_id=event.account_id,
        order_id=payload.order_id,
        instrument_id=payload.instrument_id,
        kind=payload.reservation_kind,
        native_amount=payload.native_amount,
        rmb_amount=payload.rmb_amount.amount,
    )


def _project_trade(
    event: AccountEventEnvelope,
    payload: TradeFillPayload,
    cash: dict[str, CashProjection],
    positions: dict[str, PositionProjection],
    reservations: dict[str, Reservation],
) -> None:
    position = positions.get(payload.instrument_id) or PositionProjection(
        account_id=event.account_id,
        instrument_id=payload.instrument_id,
        currency=payload.native_gross.currency,
    )
    total_native = (
        payload.native_gross.amount
        + payload.native_fee.amount
        + payload.native_borrow_fee.amount
    )
    total_rmb = (
        payload.rmb_gross.amount
        + payload.rmb_fee.amount
        + payload.rmb_borrow_fee.amount
    )
    if payload.side in {TradeSide.BUY, TradeSide.COVER}:
        reservation = _reservation(payload.reservation_id, reservations)
        reservations[reservation.reservation_id] = reservation.consume_cash(
            order_id=payload.order_id,
            instrument_id=payload.instrument_id,
            expected_kind={
                TradeSide.BUY: ReservationKind.CASH_BUY,
                TradeSide.COVER: ReservationKind.CASH_COVER,
            }[payload.side],
            native_amount=total_native,
            rmb_amount=total_rmb,
        )
        cny = _cash("CNY", cash)
        cash["CNY"] = _cash_replace(
            cny,
            total=cny.total - total_rmb,
            frozen=cny.frozen - total_rmb,
            rmb_total=cny.rmb_total - total_rmb,
            rmb_frozen=cny.rmb_frozen - total_rmb,
        )
    if payload.side in {TradeSide.SELL, TradeSide.SHORT}:
        currency = payload.native_gross.currency
        proceeds = cash.get(currency) or CashProjection(
            account_id=event.account_id, currency=currency
        )
        cash[currency] = _cash_replace(
            proceeds,
            total=proceeds.total
            + payload.native_gross.amount
            - payload.native_fee.amount
            - payload.native_borrow_fee.amount,
            rmb_total=proceeds.rmb_total
            + payload.rmb_gross.amount
            - payload.rmb_fee.amount
            - payload.rmb_borrow_fee.amount,
        )
    if payload.side is TradeSide.BUY:
        position = _position_replace(
            position,
            long_quantity=position.long_quantity + payload.quantity,
            settled_quantity=position.settled_quantity + payload.quantity,
            long_cost_native=position.long_cost_native + payload.native_gross.amount,
            long_cost_rmb=position.long_cost_rmb + payload.rmb_gross.amount,
        )
    elif payload.side is TradeSide.SELL:
        position = _position_replace(
            position,
            long_quantity=position.long_quantity - payload.quantity,
            settled_quantity=position.settled_quantity - payload.quantity,
            long_cost_native=proportional_remaining(
                position.long_cost_native,
                consumed=payload.quantity,
                total=position.long_quantity,
                rule_version=event.rule_version,
                label="remaining native cost",
            ),
            long_cost_rmb=proportional_remaining(
                position.long_cost_rmb,
                consumed=payload.quantity,
                total=position.long_quantity,
                rule_version=event.rule_version,
                label="remaining RMB cost",
            ),
        )
    elif payload.side is TradeSide.SHORT:
        reservation = _reservation(payload.reservation_id, reservations)
        margin = payload.margin_change_rmb.amount
        reservations[reservation.reservation_id] = reservation.consume_cash(
            order_id=payload.order_id,
            instrument_id=payload.instrument_id,
            expected_kind=ReservationKind.SHORT_MARGIN,
            native_amount=margin,
            rmb_amount=margin,
        )
        cny = _cash("CNY", cash)
        cash["CNY"] = _cash_replace(
            cny,
            frozen=cny.frozen - margin,
            margin=cny.margin + margin,
            rmb_frozen=cny.rmb_frozen - margin,
            rmb_margin=cny.rmb_margin + margin,
        )
        position = _position_replace(
            position,
            short_quantity=position.short_quantity + payload.quantity,
            short_proceeds_native=position.short_proceeds_native
            + payload.native_gross.amount,
            short_proceeds_rmb=position.short_proceeds_rmb
            + payload.rmb_gross.amount,
            margin_rmb=position.margin_rmb + margin,
            borrow_fee_rmb=position.borrow_fee_rmb
            + payload.rmb_borrow_fee.amount,
        )
    else:
        released = -payload.margin_change_rmb.amount
        expected_release = proportional_consumption(
            position.margin_rmb,
            consumed=payload.quantity,
            total=position.short_quantity,
            rule_version=event.rule_version,
            label="cover margin release",
        )
        if released != expected_release:
            raise DomainInvariantViolation("cover margin release does not match rules")
        cny = _cash("CNY", cash)
        cash["CNY"] = _cash_replace(
            cny,
            margin=cny.margin - released,
            rmb_margin=cny.rmb_margin - released,
        )
        position = _position_replace(
            position,
            short_quantity=position.short_quantity - payload.quantity,
            short_proceeds_native=proportional_remaining(
                position.short_proceeds_native,
                consumed=payload.quantity,
                total=position.short_quantity,
                rule_version=event.rule_version,
                label="remaining short proceeds",
            ),
            short_proceeds_rmb=proportional_remaining(
                position.short_proceeds_rmb,
                consumed=payload.quantity,
                total=position.short_quantity,
                rule_version=event.rule_version,
                label="remaining short RMB proceeds",
            ),
            margin_rmb=position.margin_rmb - released,
            borrow_fee_rmb=proportional_remaining(
                position.borrow_fee_rmb + payload.rmb_borrow_fee.amount,
                consumed=payload.quantity,
                total=position.short_quantity,
                rule_version=event.rule_version,
                label="remaining short borrow fee",
            ),
        )
    positions[payload.instrument_id] = position


def _project_fund(
    event: AccountEventEnvelope,
    payload: FundFillPayload,
    cash: dict[str, CashProjection],
    positions: dict[str, PositionProjection],
    reservations: dict[str, Reservation],
) -> None:
    position = positions.get(payload.instrument_id) or PositionProjection(
        account_id=event.account_id,
        instrument_id=payload.instrument_id,
        currency=payload.native_gross.currency,
    )
    reservation = _reservation(payload.reservation_id, reservations)
    if payload.action is FundAction.SUBSCRIBE:
        native_total = payload.native_gross.amount + payload.native_fee.amount
        rmb_total = payload.rmb_gross.amount + payload.rmb_fee.amount
        reservations[reservation.reservation_id] = reservation.consume_cash(
            order_id=payload.order_id,
            instrument_id=payload.instrument_id,
            expected_kind=ReservationKind.FUND_SUBSCRIPTION,
            native_amount=native_total,
            rmb_amount=rmb_total,
        )
        cny = _cash("CNY", cash)
        cash["CNY"] = _cash_replace(
            cny,
            total=cny.total - rmb_total,
            frozen=cny.frozen - rmb_total,
            rmb_total=cny.rmb_total - rmb_total,
            rmb_frozen=cny.rmb_frozen - rmb_total,
        )
        positions[payload.instrument_id] = _position_replace(
            position,
            long_quantity=position.long_quantity + payload.units,
            settled_quantity=position.settled_quantity
            + (payload.units if payload.settled else ZERO),
            long_cost_native=position.long_cost_native + payload.native_gross.amount,
            long_cost_rmb=position.long_cost_rmb + payload.rmb_gross.amount,
        )
        return
    reservations[reservation.reservation_id] = reservation.consume_position(
        payload.units,
        order_id=payload.order_id,
        instrument_id=payload.instrument_id,
        expected_kind=ReservationKind.FUND_REDEMPTION,
    )
    positions[payload.instrument_id] = _position_replace(
        position,
        long_quantity=position.long_quantity - payload.units,
        settled_quantity=position.settled_quantity - payload.units,
        frozen_quantity=position.frozen_quantity - payload.units,
        long_cost_native=proportional_remaining(
            position.long_cost_native,
            consumed=payload.units,
            total=position.long_quantity,
            rule_version=event.rule_version,
            label="remaining fund cost",
        ),
        long_cost_rmb=proportional_remaining(
            position.long_cost_rmb,
            consumed=payload.units,
            total=position.long_quantity,
            rule_version=event.rule_version,
            label="remaining fund RMB cost",
        ),
    )
    currency = payload.native_gross.currency
    proceeds = cash.get(currency) or CashProjection(
        account_id=event.account_id, currency=currency
    )
    cash[currency] = _cash_replace(
        proceeds,
        total=proceeds.total + payload.native_gross.amount - payload.native_fee.amount,
        rmb_total=proceeds.rmb_total
        + payload.rmb_gross.amount
        - payload.rmb_fee.amount,
    )


def _cash(currency: str, cash: dict[str, CashProjection]) -> CashProjection:
    if currency not in cash:
        raise DomainInvariantViolation(f"{currency} cash projection missing")
    return cash[currency]


def _position(
    instrument_id: str, positions: dict[str, PositionProjection]
) -> PositionProjection:
    if instrument_id not in positions:
        raise DomainInvariantViolation("position projection missing")
    return positions[instrument_id]


def _reservation(
    reservation_id: str | None, reservations: dict[str, Reservation]
) -> Reservation:
    if reservation_id is None or reservation_id not in reservations:
        raise DomainInvariantViolation("reservation projection missing")
    return reservations[reservation_id]


def _cash_replace(item: CashProjection, **updates: object) -> CashProjection:
    return CashProjection.model_validate(
        {
            **item.model_dump(mode="python"),
            **updates,
            "revision": item.revision + 1,
        }
    )


def _position_replace(
    item: PositionProjection, **updates: object
) -> PositionProjection:
    return PositionProjection.model_validate(
        {
            **item.model_dump(mode="python"),
            **updates,
            "revision": item.revision + 1,
        }
    )


def _zero_money(currency: str) -> Money:
    return Money(currency=currency, amount=ZERO)
