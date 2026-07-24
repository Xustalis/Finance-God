from __future__ import annotations

from decimal import Decimal

from finance_god.domain import (
    AccountEventEnvelope,
    DomainInvariantViolation,
    JournalEntry,
    Money,
)
from finance_god.domain.ledger import (
    AccountOpenedPayload,
    CashReleasedPayload,
    CashReservedPayload,
    FundAction,
    FundFillPayload,
    ReversalPayload,
    TradeFillPayload,
    TradeSide,
)

CNY = "CNY"
ZERO = Decimal("0")
PostingRow = tuple[str, str, Decimal, Decimal]


def expected_posting_rows(
    event: AccountEventEnvelope,
    *,
    reversed_journal: JournalEntry | None = None,
) -> tuple[PostingRow, ...] | None:
    payload = event.payload
    if isinstance(payload, AccountOpenedPayload):
        amount = payload.initial_cash.amount
        return (
            ("cash:available", CNY, amount, amount),
            ("equity:opening", CNY, -amount, -amount),
        )
    if isinstance(payload, CashReservedPayload):
        amount = payload.rmb_amount.amount
        return (
            ("cash:frozen", CNY, amount, amount),
            ("cash:available", CNY, -amount, -amount),
        )
    if isinstance(payload, CashReleasedPayload):
        amount = payload.rmb_amount.amount
        return (
            ("cash:available", CNY, amount, amount),
            ("cash:frozen", CNY, -amount, -amount),
        )
    if isinstance(payload, TradeFillPayload):
        return _trade_rows(payload)
    if isinstance(payload, FundFillPayload):
        return _fund_rows(payload)
    if isinstance(payload, ReversalPayload):
        if reversed_journal is None:
            raise DomainInvariantViolation("reversal requires original journal")
        return tuple(
            (
                posting.account_code,
                posting.original.currency,
                -posting.original.amount,
                -posting.rmb_amount,
            )
            for posting in reversed_journal.postings
        )
    return None


def semantic_posting_rows(journal: JournalEntry) -> tuple[PostingRow, ...]:
    return tuple(
        (
            posting.account_code,
            posting.original.currency,
            posting.original.amount,
            posting.rmb_amount,
        )
        for posting in journal.postings
    )


def _fund_rows(payload: FundFillPayload) -> tuple[PostingRow, ...]:
    side = (
        TradeSide.BUY
        if payload.action is FundAction.SUBSCRIBE
        else TradeSide.SELL
    )
    trade = TradeFillPayload(
        side=side,
        reservation_id=(
            payload.reservation_id if side is TradeSide.BUY else None
        ),
        order_id=payload.order_id,
        instrument_id=payload.instrument_id,
        quantity=payload.units,
        native_gross=payload.native_gross,
        native_fee=payload.native_fee,
        native_borrow_fee=Money(
            currency=payload.native_gross.currency, amount=ZERO
        ),
        rmb_gross=payload.rmb_gross,
        rmb_fee=payload.rmb_fee,
        rmb_borrow_fee=Money(currency=CNY, amount=ZERO),
        margin_change_rmb=Money(currency=CNY, amount=ZERO),
        exchange_rate=payload.exchange_rate,
        slippage_bps=ZERO,
        market_evidence=payload.market_evidence,
        model_version=payload.model_version,
    )
    return _trade_rows(trade)


def _trade_rows(payload: TradeFillPayload) -> tuple[PostingRow, ...]:
    currency = payload.native_gross.currency
    gross = payload.native_gross.amount
    fee = payload.native_fee.amount + payload.native_borrow_fee.amount
    rmb_gross = payload.rmb_gross.amount
    rmb_fee = payload.rmb_fee.amount + payload.rmb_borrow_fee.amount
    if payload.side in {TradeSide.BUY, TradeSide.COVER}:
        rows: list[PostingRow] = [
            (
                "asset:position"
                if payload.side is TradeSide.BUY
                else "liability:short",
                currency,
                gross,
                rmb_gross,
            ),
            ("expense:fees", currency, fee, rmb_fee),
            (
                "cash:fx-clearing" if currency != CNY else "cash:frozen",
                currency,
                -(gross + fee),
                -(rmb_gross + rmb_fee),
            ),
        ]
        if currency != CNY:
            total = rmb_gross + rmb_fee
            rows.extend(
                [
                    ("fx:clearing", CNY, total, total),
                    ("cash:frozen", CNY, -total, -total),
                ]
            )
    else:
        rows = [
            (
                "cash:proceeds",
                currency,
                gross - fee,
                rmb_gross - rmb_fee,
            ),
            ("expense:fees", currency, fee, rmb_fee),
            (
                "asset:position"
                if payload.side is TradeSide.SELL
                else "liability:short",
                currency,
                -gross,
                -rmb_gross,
            ),
        ]
    margin = payload.margin_change_rmb.amount
    if margin > ZERO:
        rows.extend(
            [
                ("cash:margin", CNY, margin, margin),
                ("cash:frozen", CNY, -margin, -margin),
            ]
        )
    elif margin < ZERO:
        release = -margin
        rows.extend(
            [
                ("cash:available", CNY, release, release),
                ("cash:margin", CNY, -release, -release),
            ]
        )
    return tuple(rows)
