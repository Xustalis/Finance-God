from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field, field_validator, model_validator

from finance_god.application.journal_rules import expected_posting_rows
from finance_god.application.ports import (
    Clock,
    IdGenerator,
    RuleCatalog,
    UnitOfWork,
    UnitOfWorkFactory,
)
from finance_god.application.projections import (
    project_event_stream,
    replace_projections,
)
from finance_god.application.reversal_rules import validate_reversal_request
from finance_god.domain import (
    AccountEventEnvelope,
    AccountEventType,
    AccountStatus,
    CashProjection,
    DomainInvariantViolation,
    ExchangeRateEvidence,
    Fill,
    JournalEntry,
    LedgerPosting,
    Money,
    PositionProjection,
    Reservation,
    ReservationStatus,
    SimulationAccount,
    VersionReference,
)
from finance_god.domain.ledger import (
    AccountOpenedPayload,
    AccountResetClosedPayload,
    CashReleasedPayload,
    CashReservedPayload,
    FundAction,
    FundFillPayload,
    PositionReservedPayload,
    ReservationKind,
    ReversalPayload,
    TradeFillPayload,
    TradeSide,
    canonical_hash,
    canonical_money,
    canonical_quantity,
    canonical_rate,
    canonical_utc,
)
from finance_god.domain.models import FrozenModel
from finance_god.domain.simulation_rules import (
    derived_money,
    proportional_consumption,
    proportional_remaining,
    require_rule_version,
)

ZERO = Decimal("0")
CNY = "CNY"


class IdempotentCommand(FrozenModel):
    owner_user_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=160)
    correlation_id: str = Field(min_length=1, max_length=160)
    causation_id: str = Field(min_length=1, max_length=160)
    source: VersionReference


class CreateAccountCommand(IdempotentCommand):
    initial_cash_rmb: Decimal = Field(gt=0)

    @field_validator("initial_cash_rmb")
    @classmethod
    def normalize_initial_cash(cls, value: Decimal) -> Decimal:
        return canonical_money(value, "initial_cash_rmb")


class ResetAccountCommand(IdempotentCommand):
    account_id: str = Field(min_length=1, max_length=160)
    initial_cash_rmb: Decimal = Field(gt=0)

    @field_validator("initial_cash_rmb")
    @classmethod
    def normalize_initial_cash(cls, value: Decimal) -> Decimal:
        return canonical_money(value, "initial_cash_rmb")


class FreezeCashCommand(IdempotentCommand):
    account_id: str = Field(min_length=1, max_length=160)
    order_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    amount: Money
    reservation_kind: ReservationKind = ReservationKind.CASH_BUY
    exchange_rate_evidence: ExchangeRateEvidence | None = None

    @model_validator(mode="after")
    def validate_freeze(self) -> FreezeCashCommand:
        if self.amount.amount <= ZERO:
            raise DomainInvariantViolation("freeze amount must be positive")
        if self.reservation_kind is ReservationKind.FUND_REDEMPTION:
            raise DomainInvariantViolation("fund redemption reserves position")
        _rmb_value(self.amount, self.exchange_rate_evidence)
        return self


class ReleaseCashCommand(IdempotentCommand):
    account_id: str = Field(min_length=1, max_length=160)
    reservation_id: str = Field(min_length=1, max_length=160)


class ReservePositionCommand(IdempotentCommand):
    account_id: str = Field(min_length=1, max_length=160)
    order_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    quantity: Decimal = Field(gt=0)

    @field_validator("quantity")
    @classmethod
    def normalize_quantity(cls, value: Decimal) -> Decimal:
        return canonical_quantity(value, "reserve_position.quantity")


class TradeFillCommand(IdempotentCommand):
    account_id: str = Field(min_length=1, max_length=160)
    reservation_id: str | None = Field(default=None, max_length=160)
    order_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    fee: Decimal = Field(ge=0)
    borrow_fee: Decimal = Field(default=ZERO, ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    slippage_bps: Decimal
    market_evidence: VersionReference
    model_version: str = Field(min_length=1, max_length=80)
    exchange_rate_evidence: ExchangeRateEvidence | None = None

    @field_validator("quantity")
    @classmethod
    def normalize_quantity(cls, value: Decimal) -> Decimal:
        return canonical_quantity(value, "fill.quantity")

    @field_validator("price", "fee", "borrow_fee")
    @classmethod
    def normalize_money(cls, value: Decimal, info: object) -> Decimal:
        return canonical_money(value, "fill money")

    @field_validator("slippage_bps")
    @classmethod
    def normalize_slippage(cls, value: Decimal) -> Decimal:
        return canonical_rate(value, "slippage_bps")


class RecordBuyFillCommand(TradeFillCommand):
    reservation_id: str = Field(min_length=1, max_length=160)


class RecordSellFillCommand(TradeFillCommand):
    reservation_id: None = None


class RecordShortFillCommand(TradeFillCommand):
    reservation_id: str = Field(min_length=1, max_length=160)
    margin_change_rmb: Decimal = Field(gt=0)


class RecordCoverFillCommand(TradeFillCommand):
    reservation_id: str = Field(min_length=1, max_length=160)


class ConfirmFundCommand(IdempotentCommand):
    account_id: str = Field(min_length=1, max_length=160)
    reservation_id: str = Field(min_length=1, max_length=160)
    order_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    units: Decimal = Field(gt=0)
    nav: Decimal = Field(gt=0)
    fee: Decimal = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    market_evidence: VersionReference
    model_version: str = Field(min_length=1, max_length=80)
    exchange_rate_evidence: ExchangeRateEvidence | None = None
    settled: bool = False

    @field_validator("units")
    @classmethod
    def normalize_units(cls, value: Decimal) -> Decimal:
        return canonical_quantity(value, "fund.units")

    @field_validator("nav", "fee")
    @classmethod
    def normalize_money(cls, value: Decimal) -> Decimal:
        return canonical_money(value, "fund money")


class ReverseEventCommand(IdempotentCommand):
    account_id: str = Field(min_length=1, max_length=160)
    original_event_id: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=500)


class SimulationLedgerService:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        rules: RuleCatalog,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._rules = rules

    async def create_account(self, command: CreateAccountCommand) -> str:
        scope = "create_account"
        request_hash = _request_hash(command)
        async with self._uow_factory() as uow:
            await uow.locks.owner(command.owner_user_id)
            prior = await self._idempotent_result(uow, scope, command, request_hash)
            if prior is not None:
                return prior
            if await uow.accounts.get_current(command.owner_user_id):
                raise DomainInvariantViolation("owner already has a current account")
            now = self._now()
            account = SimulationAccount(
                account_id=self._ids.new_id("account"),
                owner_user_id=command.owner_user_id,
                initial_cash_rmb=command.initial_cash_rmb,
                created_at=now,
            )
            await uow.accounts.add(account)
            await uow.flush()
            event = await self._event(
                uow,
                account,
                AccountEventType.ACCOUNT_OPENED,
                AccountOpenedPayload(
                    initial_cash=Money(currency=CNY, amount=command.initial_cash_rmb)
                ),
                command,
                now,
            )
            await self._append_event_bundle(
                uow, event, self._event_journal(event)
            )
            await uow.account_projections.add(
                CashProjection(
                    account_id=account.account_id,
                    currency=CNY,
                    total=command.initial_cash_rmb,
                    rmb_total=command.initial_cash_rmb,
                    revision=event.sequence,
                )
            )
            await self._finish_idempotency(
                uow, scope, command, request_hash, account.account_id, now
            )
            return account.account_id

    async def reset_account(self, command: ResetAccountCommand) -> str:
        scope = "reset_account"
        request_hash = _request_hash(command)
        async with self._uow_factory() as uow:
            await uow.locks.account(command.account_id)
            prior = await self._idempotent_result(uow, scope, command, request_hash)
            if prior is not None:
                return prior
            old = await self._owned_account(uow, command.account_id, command.owner_user_id)
            await self._assert_resettable(uow, old)
            now = self._now()
            new_id = self._ids.new_id("account")
            if new_id == old.account_id:
                raise DomainInvariantViolation("account reset requires a new account id")
            closed = old.close_for_reset(closed_at=now)
            await uow.accounts.save(closed, expected_revision=old.revision)
            await uow.flush()
            close_event = await self._event(
                uow,
                old,
                AccountEventType.ACCOUNT_RESET_CLOSED,
                AccountResetClosedPayload(new_account_id=new_id),
                command,
                now,
            )
            await self._append_event_bundle(uow, close_event, None)
            new_account = SimulationAccount(
                account_id=new_id,
                owner_user_id=command.owner_user_id,
                initial_cash_rmb=command.initial_cash_rmb,
                created_at=now,
                reset_from_account_id=old.account_id,
            )
            await uow.accounts.add(new_account)
            await uow.flush()
            open_event = await self._event(
                uow,
                new_account,
                AccountEventType.ACCOUNT_OPENED,
                AccountOpenedPayload(
                    initial_cash=Money(currency=CNY, amount=command.initial_cash_rmb)
                ),
                command,
                now,
            )
            await self._append_event_bundle(
                uow, open_event, self._event_journal(open_event)
            )
            await uow.account_projections.add(
                CashProjection(
                    account_id=new_id,
                    currency=CNY,
                    total=command.initial_cash_rmb,
                    rmb_total=command.initial_cash_rmb,
                    revision=open_event.sequence,
                )
            )
            await self._finish_idempotency(
                uow, scope, command, request_hash, new_id, now
            )
            return new_id

    async def freeze_cash(self, command: FreezeCashCommand) -> str:
        scope = "freeze_cash"
        request_hash = _request_hash(command)
        async with self._uow_factory() as uow:
            await uow.locks.account(command.account_id)
            prior = await self._idempotent_result(uow, scope, command, request_hash)
            if prior is not None:
                return prior
            account = await self._owned_account(uow, command.account_id, command.owner_user_id)
            rmb_amount = _rmb_value(
                command.amount,
                command.exchange_rate_evidence,
                rule_version=self._rules.simulation_rule_version,
            )
            cash = await self._cash(uow, account.account_id, CNY)
            if cash.rmb_available < rmb_amount:
                raise DomainInvariantViolation("insufficient available cash")
            now = self._now()
            reservation = Reservation(
                reservation_id=self._ids.new_id("reservation"),
                account_id=account.account_id,
                order_id=command.order_id,
                instrument_id=command.instrument_id,
                kind=command.reservation_kind,
                native_amount=command.amount,
                rmb_amount=rmb_amount,
            )
            event = await self._event(
                uow,
                account,
                AccountEventType.CASH_RESERVED,
                CashReservedPayload(
                    reservation_id=reservation.reservation_id,
                    order_id=command.order_id,
                    instrument_id=command.instrument_id,
                    reservation_kind=command.reservation_kind,
                    native_amount=command.amount,
                    rmb_amount=Money(currency=CNY, amount=rmb_amount),
                    exchange_rate=command.exchange_rate_evidence,
                ),
                command,
                now,
            )
            await self._append_event_bundle(
                uow, event, self._event_journal(event)
            )
            await uow.reservations.add(reservation)
            await uow.activities.open(
                activity_id=self._ids.new_id("activity"),
                account_id=account.account_id,
                activity_type=command.reservation_kind.value,
                reference_id=reservation.reservation_id,
                occurred_at=now,
            )
            updated_cash = CashProjection.model_validate(
                {
                    **cash.model_dump(mode="python"),
                    "frozen": cash.frozen + rmb_amount,
                    "rmb_frozen": cash.rmb_frozen + rmb_amount,
                    "revision": cash.revision + 1,
                }
            )
            await uow.account_projections.save(
                updated_cash, expected_revision=cash.revision
            )
            await self._finish_idempotency(
                uow, scope, command, request_hash, reservation.reservation_id, now
            )
            return reservation.reservation_id

    async def release_cash(self, command: ReleaseCashCommand) -> str:
        scope = "release_cash"
        request_hash = _request_hash(command)
        async with self._uow_factory() as uow:
            await uow.locks.account(command.account_id)
            prior = await self._idempotent_result(uow, scope, command, request_hash)
            if prior is not None:
                return prior
            account = await self._owned_account(uow, command.account_id, command.owner_user_id)
            reservation = await self._reservation(uow, command.reservation_id, account.account_id)
            if reservation.kind is ReservationKind.FUND_REDEMPTION:
                raise DomainInvariantViolation("position reservation requires position release")
            cash = await self._cash(uow, account.account_id, CNY)
            now = self._now()
            released = reservation.release()
            event = await self._event(
                uow,
                account,
                AccountEventType.CASH_RELEASED,
                CashReleasedPayload(
                    reservation_id=reservation.reservation_id,
                    order_id=reservation.order_id,
                    native_amount=Money(
                        currency=reservation.native_amount.currency,
                        amount=reservation.remaining_native,
                    ),
                    rmb_amount=Money(currency=CNY, amount=reservation.remaining_rmb),
                ),
                command,
                now,
            )
            await self._append_event_bundle(
                uow,
                event,
                self._event_journal(event),
            )
            await uow.reservations.save(
                released, expected_revision=reservation.revision
            )
            await uow.activities.complete(reservation.reservation_id, occurred_at=now)
            updated_cash = CashProjection.model_validate(
                {
                    **cash.model_dump(mode="python"),
                    "frozen": cash.frozen - reservation.remaining_rmb,
                    "rmb_frozen": cash.rmb_frozen - reservation.remaining_rmb,
                    "revision": cash.revision + 1,
                }
            )
            await uow.account_projections.save(
                updated_cash, expected_revision=cash.revision
            )
            await self._finish_idempotency(
                uow, scope, command, request_hash, reservation.reservation_id, now
            )
            return reservation.reservation_id

    async def reserve_position(self, command: ReservePositionCommand) -> str:
        scope = "reserve_position"
        request_hash = _request_hash(command)
        async with self._uow_factory() as uow:
            await uow.locks.account(command.account_id)
            prior = await self._idempotent_result(uow, scope, command, request_hash)
            if prior is not None:
                return prior
            account = await self._owned_account(uow, command.account_id, command.owner_user_id)
            position = await self._position(uow, account.account_id, command.instrument_id)
            if position.settled_quantity - position.frozen_quantity < command.quantity:
                raise DomainInvariantViolation("insufficient settled position")
            now = self._now()
            reservation = Reservation(
                reservation_id=self._ids.new_id("reservation"),
                account_id=account.account_id,
                order_id=command.order_id,
                instrument_id=command.instrument_id,
                kind=ReservationKind.FUND_REDEMPTION,
                native_amount=Money(currency=position.currency, amount=ZERO),
                rmb_amount=ZERO,
                quantity=command.quantity,
            )
            event = await self._event(
                uow,
                account,
                AccountEventType.POSITION_RESERVED,
                PositionReservedPayload(
                    reservation_id=reservation.reservation_id,
                    order_id=command.order_id,
                    instrument_id=command.instrument_id,
                    quantity=command.quantity,
                ),
                command,
                now,
            )
            await self._append_event_bundle(uow, event, None)
            await uow.reservations.add(reservation)
            await uow.activities.open(
                activity_id=self._ids.new_id("activity"),
                account_id=account.account_id,
                activity_type="fund_redemption",
                reference_id=reservation.reservation_id,
                occurred_at=now,
            )
            updated = PositionProjection.model_validate(
                {
                    **position.model_dump(mode="python"),
                    "frozen_quantity": position.frozen_quantity + command.quantity,
                    "revision": position.revision + 1,
                }
            )
            await uow.position_projections.save(
                updated, expected_revision=position.revision
            )
            await self._finish_idempotency(
                uow, scope, command, request_hash, reservation.reservation_id, now
            )
            return reservation.reservation_id

    async def record_buy_fill(self, command: RecordBuyFillCommand) -> str:
        return await self._record_trade_fill(command, TradeSide.BUY)

    async def record_sell_fill(self, command: RecordSellFillCommand) -> str:
        return await self._record_trade_fill(command, TradeSide.SELL)

    async def record_short_fill(self, command: RecordShortFillCommand) -> str:
        return await self._record_trade_fill(command, TradeSide.SHORT)

    async def record_cover_fill(self, command: RecordCoverFillCommand) -> str:
        return await self._record_trade_fill(command, TradeSide.COVER)

    async def _record_trade_fill(
        self, command: TradeFillCommand, side: TradeSide
    ) -> str:
        scope = f"record_{side.value}_fill"
        request_hash = _request_hash(command)
        async with self._uow_factory() as uow:
            await uow.locks.account(command.account_id)
            prior = await self._idempotent_result(uow, scope, command, request_hash)
            if prior is not None:
                return prior
            account = await self._owned_account(uow, command.account_id, command.owner_user_id)
            rule_version = self._rules.simulation_rule_version
            native_gross = derived_money(
                command.quantity * command.price,
                rule_version=rule_version,
                label="fill gross",
            )
            native_total = derived_money(
                native_gross + command.fee + command.borrow_fee,
                rule_version=rule_version,
                label="fill total",
            )
            rmb_gross = _rmb_value(
                Money(currency=command.currency, amount=native_gross),
                command.exchange_rate_evidence,
                rule_version=rule_version,
            )
            rmb_fee = _rmb_value(
                Money(currency=command.currency, amount=command.fee),
                command.exchange_rate_evidence,
                rule_version=rule_version,
            )
            rmb_borrow = _rmb_value(
                Money(currency=command.currency, amount=command.borrow_fee),
                command.exchange_rate_evidence,
                rule_version=rule_version,
            )
            rmb_total = derived_money(
                rmb_gross + rmb_fee + rmb_borrow,
                rule_version=rule_version,
                label="fill RMB total",
            )
            reservation = (
                await self._reservation(uow, command.reservation_id, account.account_id)
                if command.reservation_id
                else None
            )
            position = await uow.position_projections.get(
                account.account_id, command.instrument_id
            )
            margin_change = ZERO
            if side is TradeSide.SHORT:
                if not isinstance(command, RecordShortFillCommand):
                    raise DomainInvariantViolation("short fill requires margin")
                margin_change = command.margin_change_rmb
            elif side is TradeSide.COVER:
                if position is None or position.short_quantity < command.quantity:
                    raise DomainInvariantViolation("cover exceeds short position")
                margin_change = -proportional_consumption(
                    position.margin_rmb,
                    consumed=command.quantity,
                    total=position.short_quantity,
                    rule_version=rule_version,
                    label="cover margin release",
                )
            now = self._now()
            payload = TradeFillPayload(
                side=side,
                reservation_id=command.reservation_id,
                order_id=command.order_id,
                instrument_id=command.instrument_id,
                quantity=command.quantity,
                native_gross=Money(currency=command.currency, amount=native_gross),
                native_fee=Money(currency=command.currency, amount=command.fee),
                native_borrow_fee=Money(
                    currency=command.currency, amount=command.borrow_fee
                ),
                rmb_gross=Money(currency=CNY, amount=rmb_gross),
                rmb_fee=Money(currency=CNY, amount=rmb_fee),
                rmb_borrow_fee=Money(currency=CNY, amount=rmb_borrow),
                margin_change_rmb=Money(
                    currency=CNY, amount=margin_change
                ),
                exchange_rate=command.exchange_rate_evidence,
                slippage_bps=command.slippage_bps,
                market_evidence=command.market_evidence,
                model_version=command.model_version,
            )
            event = await self._event(
                uow,
                account,
                _event_type(side),
                payload,
                command,
                now,
            )
            updated_position, updated_cash, updated_reservation = await self._trade_state(
                uow,
                account.account_id,
                position,
                reservation,
                payload,
                native_total,
                rmb_total,
                event.sequence,
            )
            fill = self._fill(event, payload)
            journal = self._event_journal(event)
            await self._append_event_bundle(uow, event, journal, fill)
            await self._save_position(uow, position, updated_position)
            await self._save_cash_set(uow, updated_cash)
            if reservation and updated_reservation:
                await uow.reservations.save(
                    updated_reservation, expected_revision=reservation.revision
                )
                if updated_reservation.status is ReservationStatus.CONSUMED:
                    await uow.activities.complete(
                        reservation.reservation_id, occurred_at=now
                    )
            await self._finish_idempotency(
                uow, scope, command, request_hash, fill.fill_id, now
            )
            return fill.fill_id

    async def confirm_fund_subscription(self, command: ConfirmFundCommand) -> str:
        return await self._confirm_fund(command, FundAction.SUBSCRIBE)

    async def confirm_fund_redemption(self, command: ConfirmFundCommand) -> str:
        return await self._confirm_fund(command, FundAction.REDEEM)

    async def reverse_latest_event(self, command: ReverseEventCommand) -> str:
        scope = "reverse_latest_event"
        request_hash = _request_hash(command)
        async with self._uow_factory() as uow:
            await uow.locks.account(command.account_id)
            prior = await self._idempotent_result(uow, scope, command, request_hash)
            if prior is not None:
                return prior
            account = await self._owned_account(
                uow, command.account_id, command.owner_user_id
            )
            events = await uow.events.list(account.account_id)
            original = validate_reversal_request(
                events, command.original_event_id
            )
            original_journal = await uow.journals.get_by_event(original.event_id)
            if original_journal is None:
                raise DomainInvariantViolation("original journal not found")
            original_reservation_id = getattr(original.payload, "reservation_id", None)
            original_reservation = (
                await uow.reservations.get(original_reservation_id)
                if isinstance(original_reservation_id, str)
                else None
            )
            now = self._now()
            reversal = await self._event(
                uow,
                account,
                AccountEventType.REVERSAL_RECORDED,
                ReversalPayload(
                    original_event_id=original.event_id,
                    original_event_hash=original.event_hash,
                    reason=command.reason,
                ),
                command,
                now,
            )
            journal = self._event_journal(
                reversal, reversed_journal=original_journal
            )
            await self._append_event_bundle(uow, reversal, journal)
            cash, positions, reservations = project_event_stream(
                (*events, reversal)
            )
            await replace_projections(
                uow, account.account_id, cash, positions, reservations
            )
            await self._synchronize_reversal_activity(
                uow,
                original,
                reservations,
                original_reservation,
                now,
            )
            await self._finish_idempotency(
                uow, scope, command, request_hash, reversal.event_id, now
            )
            return reversal.event_id

    async def _confirm_fund(
        self, command: ConfirmFundCommand, action: FundAction
    ) -> str:
        scope = f"confirm_fund_{action.value}"
        request_hash = _request_hash(command)
        async with self._uow_factory() as uow:
            await uow.locks.account(command.account_id)
            prior = await self._idempotent_result(uow, scope, command, request_hash)
            if prior is not None:
                return prior
            account = await self._owned_account(uow, command.account_id, command.owner_user_id)
            reservation = await self._reservation(uow, command.reservation_id, account.account_id)
            rule_version = self._rules.simulation_rule_version
            gross = derived_money(
                command.units * command.nav,
                rule_version=rule_version,
                label="fund gross",
            )
            rmb_gross = _rmb_value(
                Money(currency=command.currency, amount=gross),
                command.exchange_rate_evidence,
                rule_version=rule_version,
            )
            rmb_fee = _rmb_value(
                Money(currency=command.currency, amount=command.fee),
                command.exchange_rate_evidence,
                rule_version=rule_version,
            )
            position = await uow.position_projections.get(
                account.account_id, command.instrument_id
            )
            now = self._now()
            payload = FundFillPayload(
                action=action,
                reservation_id=reservation.reservation_id,
                order_id=command.order_id,
                instrument_id=command.instrument_id,
                units=command.units,
                nav=Money(currency=command.currency, amount=command.nav),
                native_gross=Money(currency=command.currency, amount=gross),
                native_fee=Money(currency=command.currency, amount=command.fee),
                rmb_gross=Money(currency=CNY, amount=rmb_gross),
                rmb_fee=Money(currency=CNY, amount=rmb_fee),
                exchange_rate=command.exchange_rate_evidence,
                market_evidence=command.market_evidence,
                model_version=command.model_version,
                settled=command.settled,
            )
            event = await self._event(
                uow,
                account,
                (
                    AccountEventType.FUND_SUBSCRIPTION_CONFIRMED
                    if action is FundAction.SUBSCRIBE
                    else AccountEventType.FUND_REDEMPTION_CONFIRMED
                ),
                payload,
                command,
                now,
            )
            updated_position, updated_cash, updated_reservation = await self._fund_state(
                uow, account.account_id, position, reservation, payload, event.sequence
            )
            fill = self._fund_fill(event, payload)
            await self._append_event_bundle(
                uow, event, self._event_journal(event), fill
            )
            await self._save_position(uow, position, updated_position)
            await self._save_cash_set(uow, updated_cash)
            await uow.reservations.save(
                updated_reservation, expected_revision=reservation.revision
            )
            if updated_reservation.status is ReservationStatus.CONSUMED:
                await uow.activities.complete(
                    reservation.reservation_id, occurred_at=now
                )
            await self._finish_idempotency(
                uow, scope, command, request_hash, fill.fill_id, now
            )
            return fill.fill_id

    async def _trade_state(
        self,
        uow: UnitOfWork,
        account_id: str,
        current: PositionProjection | None,
        reservation: Reservation | None,
        payload: TradeFillPayload,
        native_total: Decimal,
        rmb_total: Decimal,
        sequence: int,
    ) -> tuple[
        PositionProjection, tuple[tuple[CashProjection | None, CashProjection], ...], Reservation | None
    ]:
        position = current or PositionProjection(
            account_id=account_id,
            instrument_id=payload.instrument_id,
            currency=payload.native_gross.currency,
        )
        if position.currency != payload.native_gross.currency:
            raise DomainInvariantViolation("position currency does not match fill")
        cash_changes: list[tuple[CashProjection | None, CashProjection]] = []
        updated_reservation: Reservation | None = None
        if payload.side in {TradeSide.BUY, TradeSide.COVER}:
            if reservation is None:
                raise DomainInvariantViolation("cash-funded fill requires reservation")
            updated_reservation = reservation.consume_cash(
                order_id=payload.order_id,
                instrument_id=payload.instrument_id,
                expected_kind={
                    TradeSide.BUY: ReservationKind.CASH_BUY,
                    TradeSide.COVER: ReservationKind.CASH_COVER,
                }[payload.side],
                native_amount=native_total,
                rmb_amount=rmb_total,
            )
            cash = await self._cash(uow, account_id, CNY)
            cash_changes.append(
                (
                    cash,
                    CashProjection.model_validate(
                        {
                            **cash.model_dump(mode="python"),
                            "total": cash.total - rmb_total,
                            "frozen": cash.frozen - rmb_total,
                            "rmb_total": cash.rmb_total - rmb_total,
                            "rmb_frozen": cash.rmb_frozen - rmb_total,
                            "revision": cash.revision + 1,
                        }
                    ),
                )
            )
        if payload.side in {TradeSide.SELL, TradeSide.SHORT}:
            net_native = canonical_money(
                payload.native_gross.amount
                - payload.native_fee.amount
                - payload.native_borrow_fee.amount,
                "net proceeds",
            )
            net_rmb = canonical_money(
                payload.rmb_gross.amount
                - payload.rmb_fee.amount
                - payload.rmb_borrow_fee.amount,
                "net RMB proceeds",
            )
            proceeds = await uow.account_projections.get(
                account_id, payload.native_gross.currency
            )
            base = proceeds or CashProjection(
                account_id=account_id,
                currency=payload.native_gross.currency,
            )
            cash_changes.append(
                (
                    proceeds,
                    CashProjection.model_validate(
                        {
                            **base.model_dump(mode="python"),
                            "total": base.total + net_native,
                            "rmb_total": base.rmb_total + net_rmb,
                            "revision": base.revision + 1,
                        }
                    ),
                )
            )
        if payload.side is TradeSide.BUY:
            position = PositionProjection.model_validate(
                {
                    **position.model_dump(mode="python"),
                    "long_quantity": position.long_quantity + payload.quantity,
                    "settled_quantity": position.settled_quantity + payload.quantity,
                    "long_cost_native": position.long_cost_native
                    + payload.native_gross.amount,
                    "long_cost_rmb": position.long_cost_rmb + payload.rmb_gross.amount,
                    "revision": position.revision + 1,
                }
            )
        elif payload.side is TradeSide.SELL:
            if position.settled_quantity - position.frozen_quantity < payload.quantity:
                raise DomainInvariantViolation("sell exceeds settled long position")
            position = PositionProjection.model_validate(
                {
                    **position.model_dump(mode="python"),
                    "long_quantity": position.long_quantity - payload.quantity,
                    "settled_quantity": position.settled_quantity - payload.quantity,
                    "long_cost_native": proportional_remaining(
                        position.long_cost_native,
                        consumed=payload.quantity,
                        total=position.long_quantity,
                        rule_version=self._rules.simulation_rule_version,
                        label="remaining native cost",
                    ),
                    "long_cost_rmb": proportional_remaining(
                        position.long_cost_rmb,
                        consumed=payload.quantity,
                        total=position.long_quantity,
                        rule_version=self._rules.simulation_rule_version,
                        label="remaining RMB cost",
                    ),
                    "revision": position.revision + 1,
                }
            )
        elif payload.side is TradeSide.SHORT:
            if reservation is None:
                raise DomainInvariantViolation("short fill requires short-margin reservation")
            margin = payload.margin_change_rmb.amount
            updated_reservation = reservation.consume_cash(
                order_id=payload.order_id,
                instrument_id=payload.instrument_id,
                expected_kind=ReservationKind.SHORT_MARGIN,
                native_amount=margin,
                rmb_amount=margin,
            )
            margin_cash = await self._cash(uow, account_id, CNY)
            cash_changes.append(
                (
                    margin_cash,
                    CashProjection.model_validate(
                        {
                            **margin_cash.model_dump(mode="python"),
                            "frozen": margin_cash.frozen - margin,
                            "margin": margin_cash.margin + margin,
                            "rmb_frozen": margin_cash.rmb_frozen - margin,
                            "rmb_margin": margin_cash.rmb_margin + margin,
                            "revision": margin_cash.revision + 1,
                        }
                    ),
                )
            )
            position = PositionProjection.model_validate(
                {
                    **position.model_dump(mode="python"),
                    "short_quantity": position.short_quantity + payload.quantity,
                    "short_proceeds_native": position.short_proceeds_native
                    + payload.native_gross.amount,
                    "short_proceeds_rmb": position.short_proceeds_rmb
                    + payload.rmb_gross.amount,
                    "margin_rmb": position.margin_rmb + margin,
                    "borrow_fee_rmb": position.borrow_fee_rmb
                    + payload.rmb_borrow_fee.amount,
                    "revision": position.revision + 1,
                }
            )
        else:
            if position.short_quantity < payload.quantity:
                raise DomainInvariantViolation("cover exceeds short position")
            released_margin = -payload.margin_change_rmb.amount
            if released_margin > position.margin_rmb:
                raise DomainInvariantViolation("margin release exceeds position margin")
            margin_cash = await self._cash(uow, account_id, CNY)
            cash_changes.append(
                (
                    margin_cash,
                    CashProjection.model_validate(
                        {
                            **margin_cash.model_dump(mode="python"),
                            "margin": margin_cash.margin - released_margin,
                            "rmb_margin": margin_cash.rmb_margin - released_margin,
                            "revision": margin_cash.revision + 1,
                        }
                    ),
                )
            )
            remaining_short_proceeds_native = proportional_remaining(
                position.short_proceeds_native,
                consumed=payload.quantity,
                total=position.short_quantity,
                rule_version=self._rules.simulation_rule_version,
                label="remaining short proceeds",
            )
            remaining_short_proceeds_rmb = proportional_remaining(
                position.short_proceeds_rmb,
                consumed=payload.quantity,
                total=position.short_quantity,
                rule_version=self._rules.simulation_rule_version,
                label="remaining short RMB proceeds",
            )
            remaining_borrow_fee = proportional_remaining(
                position.borrow_fee_rmb + payload.rmb_borrow_fee.amount,
                consumed=payload.quantity,
                total=position.short_quantity,
                rule_version=self._rules.simulation_rule_version,
                label="remaining short borrow fee",
            )
            position = PositionProjection.model_validate(
                {
                    **position.model_dump(mode="python"),
                    "short_quantity": position.short_quantity - payload.quantity,
                    "short_proceeds_native": remaining_short_proceeds_native,
                    "short_proceeds_rmb": remaining_short_proceeds_rmb,
                    "margin_rmb": position.margin_rmb - released_margin,
                    "borrow_fee_rmb": remaining_borrow_fee,
                    "revision": position.revision + 1,
                }
            )
        return position, _merge_cash_changes(tuple(cash_changes)), updated_reservation

    async def _fund_state(
        self,
        uow: UnitOfWork,
        account_id: str,
        current: PositionProjection | None,
        reservation: Reservation,
        payload: FundFillPayload,
        sequence: int,
    ) -> tuple[
        PositionProjection, tuple[tuple[CashProjection | None, CashProjection], ...], Reservation
    ]:
        position = current or PositionProjection(
            account_id=account_id,
            instrument_id=payload.instrument_id,
            currency=payload.native_gross.currency,
        )
        if payload.action is FundAction.SUBSCRIBE:
            total_native = payload.native_gross.amount + payload.native_fee.amount
            total_rmb = payload.rmb_gross.amount + payload.rmb_fee.amount
            consumed = reservation.consume_cash(
                order_id=payload.order_id,
                instrument_id=payload.instrument_id,
                expected_kind=ReservationKind.FUND_SUBSCRIPTION,
                native_amount=total_native,
                rmb_amount=total_rmb,
            )
            cny_cash = await self._cash(uow, account_id, CNY)
            updated_cash = CashProjection.model_validate(
                {
                    **cny_cash.model_dump(mode="python"),
                    "total": cny_cash.total - total_rmb,
                    "frozen": cny_cash.frozen - total_rmb,
                    "rmb_total": cny_cash.rmb_total - total_rmb,
                    "rmb_frozen": cny_cash.rmb_frozen - total_rmb,
                    "revision": cny_cash.revision + 1,
                }
            )
            updated_position = PositionProjection.model_validate(
                {
                    **position.model_dump(mode="python"),
                    "long_quantity": position.long_quantity + payload.units,
                    "settled_quantity": position.settled_quantity
                    + (payload.units if payload.settled else ZERO),
                    "long_cost_native": position.long_cost_native
                    + payload.native_gross.amount,
                    "long_cost_rmb": position.long_cost_rmb + payload.rmb_gross.amount,
                    "revision": position.revision + 1,
                }
            )
            return updated_position, ((cny_cash, updated_cash),), consumed
        consumed = reservation.consume_position(
            payload.units,
            order_id=payload.order_id,
            instrument_id=payload.instrument_id,
            expected_kind=ReservationKind.FUND_REDEMPTION,
        )
        if position.frozen_quantity < payload.units:
            raise DomainInvariantViolation("redemption exceeds frozen position")
        updated_position = PositionProjection.model_validate(
            {
                **position.model_dump(mode="python"),
                "long_quantity": position.long_quantity - payload.units,
                "settled_quantity": position.settled_quantity - payload.units,
                "frozen_quantity": position.frozen_quantity - payload.units,
                "long_cost_native": proportional_remaining(
                    position.long_cost_native,
                    consumed=payload.units,
                    total=position.long_quantity,
                    rule_version=self._rules.simulation_rule_version,
                    label="remaining fund cost",
                ),
                "long_cost_rmb": proportional_remaining(
                    position.long_cost_rmb,
                    consumed=payload.units,
                    total=position.long_quantity,
                    rule_version=self._rules.simulation_rule_version,
                    label="remaining fund RMB cost",
                ),
                "revision": position.revision + 1,
            }
        )
        native_net = payload.native_gross.amount - payload.native_fee.amount
        rmb_net = payload.rmb_gross.amount - payload.rmb_fee.amount
        cash = await uow.account_projections.get(
            account_id, payload.native_gross.currency
        )
        base = cash or CashProjection(
            account_id=account_id, currency=payload.native_gross.currency
        )
        updated_cash = CashProjection.model_validate(
            {
                **base.model_dump(mode="python"),
                "total": base.total + native_net,
                "rmb_total": base.rmb_total + rmb_net,
                "revision": base.revision + 1,
            }
        )
        return updated_position, ((cash, updated_cash),), consumed

    async def _append_event_bundle(
        self,
        uow: UnitOfWork,
        event: AccountEventEnvelope,
        journal: JournalEntry | None,
        fill: Fill | None = None,
    ) -> None:
        await uow.events.append(event)
        await uow.flush()
        if journal is not None:
            await uow.journals.append(journal)
        if fill is not None:
            await uow.fills.append(fill)
        await uow.audits.append(
            audit_id=self._ids.new_id("audit"),
            owner_user_id=event.owner_user_id,
            account_id=event.account_id,
            event_id=event.event_id,
            event_hash=event.event_hash,
            journal_hash=journal.journal_hash if journal is not None else None,
            action=event.event_type.value,
            correlation_id=event.correlation_id,
            occurred_at=event.occurred_at,
        )
        await uow.outbox.append(
            message_id=self._ids.new_id("message"),
            topic=f"simulation.{event.event_type.value}",
            aggregate_id=event.account_id,
            event_id=event.event_id,
            event_hash=event.event_hash,
            occurred_at=event.occurred_at,
        )
        await uow.flush()

    async def _synchronize_reversal_activity(
        self,
        uow: UnitOfWork,
        original: AccountEventEnvelope,
        reservations: dict[str, Reservation],
        original_reservation: Reservation | None,
        now: datetime,
    ) -> None:
        payload = original.payload
        reservation_id = getattr(payload, "reservation_id", None)
        if not isinstance(reservation_id, str):
            return
        if isinstance(payload, CashReservedPayload):
            await uow.activities.complete(reservation_id, occurred_at=now)
            return
        projected = reservations.get(reservation_id)
        if (
            original_reservation is not None
            and original_reservation.status is ReservationStatus.CONSUMED
            and projected is not None
            and projected.status is ReservationStatus.ACTIVE
        ):
            await uow.activities.reopen(reservation_id)
        elif isinstance(payload, CashReleasedPayload):
            await uow.activities.reopen(reservation_id)

    async def _event(
        self,
        uow: UnitOfWork,
        account: SimulationAccount,
        event_type: AccountEventType,
        payload: object,
        command: IdempotentCommand,
        occurred_at: datetime,
    ) -> AccountEventEnvelope:
        require_rule_version(self._rules.simulation_rule_version)
        previous = await uow.events.last(account.account_id)
        return AccountEventEnvelope.create(
            event_id=self._ids.new_id("event"),
            account_id=account.account_id,
            owner_user_id=account.owner_user_id,
            sequence=previous.sequence + 1 if previous else 1,
            event_type=event_type,
            occurred_at=occurred_at,
            correlation_id=command.correlation_id,
            causation_id=command.causation_id,
            source=command.source,
            rule_version=self._rules.simulation_rule_version,
            previous_hash=previous.event_hash if previous else None,
            payload=payload,
        )

    async def _idempotent_result(
        self,
        uow: UnitOfWork,
        scope: str,
        command: IdempotentCommand,
        request_hash: str,
    ) -> str | None:
        prior = await uow.idempotency.get(
            scope, command.owner_user_id, command.idempotency_key
        )
        if prior is None:
            return None
        if prior.request_hash != request_hash:
            raise DomainInvariantViolation(
                "idempotency key was already used with a different payload"
            )
        return prior.result_reference

    async def _finish_idempotency(
        self,
        uow: UnitOfWork,
        scope: str,
        command: IdempotentCommand,
        request_hash: str,
        result_reference: str,
        now: datetime,
    ) -> None:
        await uow.idempotency.add(
            scope=scope,
            owner_user_id=command.owner_user_id,
            key=command.idempotency_key,
            request_hash=request_hash,
            result_reference=result_reference,
            created_at=now,
        )
        await uow.flush()
        await uow.commit()

    async def _owned_account(
        self, uow: UnitOfWork, account_id: str, owner_user_id: str
    ) -> SimulationAccount:
        account = await uow.accounts.get(account_id)
        if (
            account is None
            or account.owner_user_id != owner_user_id
            or account.status is not AccountStatus.ACTIVE
            or not account.current
        ):
            raise DomainInvariantViolation("active account not found")
        return account

    async def _assert_resettable(
        self, uow: UnitOfWork, account: SimulationAccount
    ) -> None:
        if await uow.activities.has_open(account.account_id):
            raise DomainInvariantViolation("account has non-terminal activity")
        cash = await uow.account_projections.list(account.account_id)
        positions = await uow.position_projections.list(account.account_id)
        reservations = await uow.reservations.list(account.account_id)
        if any(item.frozen != ZERO or item.margin != ZERO for item in cash):
            raise DomainInvariantViolation("account with frozen cash or margin cannot reset")
        if any(item.long_quantity != ZERO or item.short_quantity != ZERO for item in positions):
            raise DomainInvariantViolation("account with positions cannot reset")
        if any(item.status is ReservationStatus.ACTIVE for item in reservations):
            raise DomainInvariantViolation("account with active reservation cannot reset")

    async def _cash(
        self, uow: UnitOfWork, account_id: str, currency: str
    ) -> CashProjection:
        cash = await uow.account_projections.get(account_id, currency)
        if cash is None:
            raise DomainInvariantViolation(f"{currency} cash projection not found")
        return cash

    async def _position(
        self, uow: UnitOfWork, account_id: str, instrument_id: str
    ) -> PositionProjection:
        position = await uow.position_projections.get(account_id, instrument_id)
        if position is None:
            raise DomainInvariantViolation("position not found")
        return position

    async def _reservation(
        self, uow: UnitOfWork, reservation_id: str, account_id: str
    ) -> Reservation:
        reservation = await uow.reservations.get(reservation_id)
        if reservation is None or reservation.account_id != account_id:
            raise DomainInvariantViolation("reservation not found")
        return reservation

    async def _save_position(
        self,
        uow: UnitOfWork,
        current: PositionProjection | None,
        updated: PositionProjection,
    ) -> None:
        if current is None:
            await uow.position_projections.add(updated)
        else:
            await uow.position_projections.save(
                updated, expected_revision=current.revision
            )

    async def _save_cash_set(
        self,
        uow: UnitOfWork,
        changes: tuple[tuple[CashProjection | None, CashProjection], ...],
    ) -> None:
        for current, updated in changes:
            if current is None:
                await uow.account_projections.add(updated)
            else:
                await uow.account_projections.save(
                    updated, expected_revision=current.revision
                )

    def _event_journal(
        self,
        event: AccountEventEnvelope,
        *,
        reversed_journal: JournalEntry | None = None,
    ) -> JournalEntry:
        rows = expected_posting_rows(
            event, reversed_journal=reversed_journal
        )
        if rows is None:
            raise DomainInvariantViolation("event does not have journal semantics")
        return JournalEntry.create(
            journal_id=self._ids.new_id("journal"),
            account_id=event.account_id,
            event_id=event.event_id,
            occurred_at=event.occurred_at,
            rule_version=self._rules.simulation_rule_version,
            reversal_of_journal_id=(
                reversed_journal.journal_id
                if reversed_journal is not None
                else None
            ),
            postings=tuple(
                LedgerPosting.create(
                    posting_id=self._ids.new_id("posting"),
                    sequence=sequence,
                    account_code=code,
                    original=Money(currency=currency, amount=native),
                    rmb_amount=rmb,
                )
                for sequence, (code, currency, native, rmb) in enumerate(
                    rows, start=1
                )
            ),
        )

    def _fill(self, event: AccountEventEnvelope, payload: TradeFillPayload) -> Fill:
        return Fill(
            fill_id=self._ids.new_id("fill"),
            event_id=event.event_id,
            account_id=event.account_id,
            order_id=payload.order_id,
            reservation_id=payload.reservation_id,
            instrument_id=payload.instrument_id,
            transaction_type=payload.side.value,
            quantity=payload.quantity,
            native_gross=payload.native_gross,
            native_fee=payload.native_fee,
            native_borrow_fee=payload.native_borrow_fee,
            rmb_gross=payload.rmb_gross.amount,
            rmb_fee=payload.rmb_fee.amount,
            rmb_borrow_fee=payload.rmb_borrow_fee.amount,
            margin_change_rmb=payload.margin_change_rmb.amount,
            slippage_bps=payload.slippage_bps,
            exchange_rate=payload.exchange_rate,
            market_evidence=payload.market_evidence,
            model_version=payload.model_version,
            rule_version=event.rule_version,
            occurred_at=event.occurred_at,
        )

    def _fund_fill(self, event: AccountEventEnvelope, payload: FundFillPayload) -> Fill:
        return Fill(
            fill_id=self._ids.new_id("fill"),
            event_id=event.event_id,
            account_id=event.account_id,
            order_id=payload.order_id,
            reservation_id=payload.reservation_id,
            instrument_id=payload.instrument_id,
            transaction_type=f"fund_{payload.action.value}",
            quantity=payload.units,
            native_gross=payload.native_gross,
            native_fee=payload.native_fee,
            native_borrow_fee=Money(currency=payload.native_gross.currency, amount=ZERO),
            rmb_gross=payload.rmb_gross.amount,
            rmb_fee=payload.rmb_fee.amount,
            rmb_borrow_fee=ZERO,
            margin_change_rmb=ZERO,
            slippage_bps=ZERO,
            exchange_rate=payload.exchange_rate,
            market_evidence=payload.market_evidence,
            model_version=payload.model_version,
            rule_version=event.rule_version,
            occurred_at=event.occurred_at,
        )

    def _now(self) -> datetime:
        return canonical_utc(self._clock.now())


def _request_hash(command: FrozenModel) -> str:
    return canonical_hash(
        command.model_dump(mode="python", exclude={"idempotency_key"})
    )


def _rmb_value(
    money: Money,
    evidence: ExchangeRateEvidence | None,
    *,
    rule_version: str = "simulation-rules-v1",
) -> Decimal:
    if money.currency == CNY:
        if evidence is not None:
            raise DomainInvariantViolation("CNY fact must not provide FX evidence")
        return money.amount
    if evidence is None:
        raise DomainInvariantViolation("cross-currency fact requires FX evidence")
    if evidence.base_currency != money.currency or evidence.quote_currency != CNY:
        raise DomainInvariantViolation("FX evidence currency pair does not match")
    return derived_money(
        money.amount * evidence.rate,
        rule_version=rule_version,
        label="converted RMB",
    )


def _event_type(side: TradeSide) -> AccountEventType:
    return {
        TradeSide.BUY: AccountEventType.BUY_FILL_RECORDED,
        TradeSide.SELL: AccountEventType.SELL_FILL_RECORDED,
        TradeSide.SHORT: AccountEventType.SHORT_FILL_RECORDED,
        TradeSide.COVER: AccountEventType.COVER_FILL_RECORDED,
    }[side]


def _merge_cash_changes(
    changes: tuple[tuple[CashProjection | None, CashProjection], ...],
) -> tuple[tuple[CashProjection | None, CashProjection], ...]:
    merged: dict[str, tuple[CashProjection | None, CashProjection]] = {}
    for current, updated in changes:
        existing = merged.get(updated.currency)
        if existing is None:
            merged[updated.currency] = (current, updated)
            continue
        original, prior = existing
        merged[updated.currency] = (
            original,
            CashProjection.model_validate(
                {
                    **updated.model_dump(mode="python"),
                    "total": prior.total + (updated.total - (current.total if current else ZERO)),
                    "frozen": prior.frozen + (updated.frozen - (current.frozen if current else ZERO)),
                    "margin": prior.margin + (updated.margin - (current.margin if current else ZERO)),
                    "rmb_total": prior.rmb_total + (updated.rmb_total - (current.rmb_total if current else ZERO)),
                    "rmb_frozen": prior.rmb_frozen + (updated.rmb_frozen - (current.rmb_frozen if current else ZERO)),
                    "rmb_margin": prior.rmb_margin + (updated.rmb_margin - (current.rmb_margin if current else ZERO)),
                    "revision": prior.revision,
                }
            ),
        )
    return tuple(merged[key] for key in sorted(merged))
