from __future__ import annotations

import unittest
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DatabaseError

from finance_god.application import (
    CreateAccountCommand,
    ReleaseCashCommand,
    ReverseEventCommand,
    ResetAccountCommand,
    SimulationLedgerService,
    rebuild_projections,
)
from finance_god.application.reversal_rules import validate_reversal_history
from finance_god.domain import (
    AccountEventEnvelope,
    DomainInvariantViolation,
    ExchangeRateEvidence,
    JournalEntry,
    LedgerPosting,
    Money,
    ReservationKind,
    ReversalPayload,
    canonical_hash,
    projection_checksum,
)
from finance_god.infrastructure.persistence import (
    Base,
    SqlAlchemyUnitOfWork,
    create_session_factory,
)
from finance_god.infrastructure.persistence.models import (
    AccountEventRow,
    AccountProjectionRow,
    AuditRow,
    FillRow,
    JournalRow,
    LedgerPostingRow,
    OutboxRow,
    PositionProjectionRow,
    ReservationRow,
)

from tests.ledger.support import (
    FixedClock,
    NOW_UTC,
    Rules,
    SOURCE,
    SequentialIds,
    buy_command,
    cover_command,
    create_command,
    freeze_command,
    fund_command,
    reserve_fund_position,
    sell_command,
    short_command,
)


class LedgerServiceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine, self.sessions = create_session_factory(
            "sqlite+aiosqlite:///:memory:"
        )
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.ids = SequentialIds()
        self.service = SimulationLedgerService(
            uow_factory=lambda: SqlAlchemyUnitOfWork(self.sessions),
            clock=FixedClock(),
            ids=self.ids,
            rules=Rules(),
        )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_no_default_cash_and_canonical_boundaries(self) -> None:
        with self.assertRaises(ValidationError):
            CreateAccountCommand(  # type: ignore[call-arg]
                owner_user_id="owner-1",
                idempotency_key="create",
                correlation_id="correlation",
                causation_id="causation",
                source=SOURCE,
            )
        with self.assertRaises(DomainInvariantViolation):
            Money(currency="CNY", amount=Decimal("1.000000001"))
        with self.assertRaises(DomainInvariantViolation):
            create_command(initial_cash=Decimal("1.000000001"))
        negative_zero = Money(currency="CNY", amount=Decimal("-0"))
        self.assertEqual(negative_zero.amount, Decimal("0E-8"))

        account_id = await self.service.create_account(create_command())
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            account = await uow.accounts.get(account_id)
            events = await uow.events.list(account_id)
        assert account is not None
        self.assertEqual(account.created_at, NOW_UTC)
        self.assertEqual(events[0].occurred_at, NOW_UTC)
        self.assertEqual(events[0].payload.initial_cash.amount, Decimal("100000.00000000"))  # type: ignore[union-attr]

    async def test_create_idempotency_and_payload_conflict(self) -> None:
        command = create_command()
        first = await self.service.create_account(command)
        second = await self.service.create_account(command)
        self.assertEqual(first, second)
        with self.assertRaisesRegex(DomainInvariantViolation, "different payload"):
            await self.service.create_account(
                create_command(initial_cash=Decimal("200000"))
            )
        async with self.sessions() as session:
            self.assertEqual(
                await session.scalar(select(func.count(AccountEventRow.event_id))), 1
            )

    async def test_freeze_release_partial_and_full_fill(self) -> None:
        account_id = await self.service.create_account(create_command())
        reservation_id = await self.service.freeze_cash(
            freeze_command(
                account_id, Decimal("1000"), key="freeze", order="order-1"
            )
        )
        await self.service.record_buy_fill(
            buy_command(
                account_id,
                reservation_id,
                key="fill-1",
                order="order-1",
                quantity=Decimal("4"),
                fee=Decimal("1"),
            )
        )
        await self.service.record_buy_fill(
            buy_command(
                account_id,
                reservation_id,
                key="fill-2",
                order="order-1",
                quantity=Decimal("5.98"),
                fee=Decimal("1"),
            )
        )
        cash = await self._cash(account_id, "CNY")
        reservation = await self._reservation(reservation_id)
        position = await self._position(account_id, "600519.SSE")
        self.assertEqual(cash.total, Decimal("99000.00000000"))
        self.assertEqual(cash.frozen, Decimal("0E-8"))
        self.assertEqual(reservation.status, "consumed")
        self.assertEqual(position.long_quantity, Decimal("9.980000000000"))
        self.assertEqual(position.long_cost_rmb, Decimal("998.00000000"))

        released_id = await self.service.freeze_cash(
            freeze_command(
                account_id, Decimal("300"), key="freeze-2", order="order-2"
            )
        )
        await self.service.release_cash(
            ReleaseCashCommand(
                owner_user_id="owner-1",
                idempotency_key="release",
                correlation_id="correlation-release",
                causation_id="request-release",
                source=SOURCE,
                account_id=account_id,
                reservation_id=released_id,
            )
        )
        self.assertEqual((await self._cash(account_id, "CNY")).frozen, Decimal("0E-8"))

    async def test_repeated_partial_sell_absorbs_cost_residual_on_full_close(
        self,
    ) -> None:
        account_id = await self.service.create_account(create_command())
        reservation = await self.service.freeze_cash(
            freeze_command(
                account_id,
                Decimal("0.99999999"),
                key="cycle-freeze",
                order="cycle-buy",
                instrument="CYCLE.SSE",
            )
        )
        await self.service.record_buy_fill(
            buy_command(
                account_id,
                reservation,
                key="cycle-buy",
                order="cycle-buy",
                instrument="CYCLE.SSE",
                quantity=Decimal("3"),
                price=Decimal("0.33333333"),
            )
        )
        for index, quantity in enumerate(
            (Decimal("1"), Decimal("2")), start=1
        ):
            await self.service.record_sell_fill(
                sell_command(
                    account_id,
                    key=f"cycle-sell-{index}",
                    order=f"cycle-sell-{index}",
                    instrument="CYCLE.SSE",
                    quantity=quantity,
                    price=Decimal("0.4"),
                    fee=Decimal("0"),
                )
            )
        position = await self._position(account_id, "CYCLE.SSE")
        self.assertEqual(position.long_quantity, Decimal("0E-12"))
        self.assertEqual(position.long_cost_native, Decimal("0E-8"))
        self.assertEqual(position.long_cost_rmb, Decimal("0E-8"))
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            await rebuild_projections(uow, account_id)

    async def test_fx_buy_and_sell_preserve_native_and_rmb_facts(self) -> None:
        account_id = await self.service.create_account(create_command())
        reservation_id = await self.service.freeze_cash(
            freeze_command(
                account_id,
                Decimal("100"),
                key="freeze-usd",
                order="buy-usd",
                instrument="AAPL.US",
                currency="USD",
            )
        )
        await self.service.record_buy_fill(
            buy_command(
                account_id,
                reservation_id,
                key="buy-usd",
                order="buy-usd",
                instrument="AAPL.US",
                currency="USD",
            )
        )
        await self.service.record_sell_fill(
            sell_command(
                account_id,
                key="sell-usd",
                order="sell-usd",
                instrument="AAPL.US",
                price=Decimal("110"),
                fee=Decimal("1"),
                currency="USD",
            )
        )
        usd = await self._cash(account_id, "USD")
        self.assertEqual(usd.total, Decimal("109.00000000"))
        self.assertEqual(usd.rmb_total, Decimal("782.62000000"))
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            fills = await uow.fills.list(account_id)
        self.assertEqual(fills[0].exchange_rate.observed_at, NOW_UTC)  # type: ignore[union-attr]
        self.assertEqual(fills[0].native_gross.currency, "USD")
        self.assertEqual(fills[0].rmb_gross, Decimal("718.00000000"))

    async def test_general_fx_and_derived_rounding_are_versioned(self) -> None:
        fx = ExchangeRateEvidence(
            base_currency="USD",
            quote_currency="CNY",
            rate=Decimal("7.123456789012"),
            observed_at=NOW_UTC,
            source=SOURCE,
        )
        account_id = await self.service.create_account(create_command())
        reservation_id = await self.service.freeze_cash(
            freeze_command(
                account_id,
                Decimal("1.00000000"),
                key="round-freeze",
                order="round-buy",
                instrument="ROUND.US",
                currency="USD",
                exchange_rate=fx,
            )
        )
        await self.service.record_buy_fill(
            buy_command(
                account_id,
                reservation_id,
                key="round-buy",
                order="round-buy",
                instrument="ROUND.US",
                quantity=Decimal("0.333333333333"),
                price=Decimal("0.12345678"),
                currency="USD",
                exchange_rate=fx,
            )
        )
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            fill = (await uow.fills.list(account_id))[0]
        self.assertEqual(fill.native_gross.amount, Decimal("0.04115226"))
        self.assertEqual(fill.rmb_gross, Decimal("0.29314635"))
        self.assertEqual(fill.exchange_rate, fx)

    async def test_reservation_binding_rejects_cross_order_kind_and_instrument(self) -> None:
        account_id = await self.service.create_account(create_command())
        reservation_id = await self.service.freeze_cash(
            freeze_command(
                account_id,
                Decimal("100"),
                key="binding-freeze",
                order="bound-order",
                instrument="BOUND.SSE",
            )
        )
        before = len(await self._events(account_id))
        invalid_commands = (
            buy_command(
                account_id,
                reservation_id,
                key="wrong-order",
                order="other-order",
                instrument="BOUND.SSE",
            ),
            buy_command(
                account_id,
                reservation_id,
                key="wrong-instrument",
                order="bound-order",
                instrument="OTHER.SSE",
            ),
        )
        for command in invalid_commands:
            with self.assertRaises(DomainInvariantViolation):
                await self.service.record_buy_fill(command)
            self.assertEqual(len(await self._events(account_id)), before)

        wrong_kind = await self.service.freeze_cash(
            freeze_command(
                account_id,
                Decimal("100"),
                key="wrong-kind-freeze",
                order="wrong-kind",
                instrument="BOUND.SSE",
                reservation_kind=ReservationKind.FUND_SUBSCRIPTION,
            )
        )
        before = len(await self._events(account_id))
        with self.assertRaises(DomainInvariantViolation):
            await self.service.record_buy_fill(
                buy_command(
                    account_id,
                    wrong_kind,
                    key="wrong-kind-buy",
                    order="wrong-kind",
                    instrument="BOUND.SSE",
                )
            )
        self.assertEqual(len(await self._events(account_id)), before)
        async with self.sessions() as session:
            self.assertEqual(
                await session.scalar(select(func.count(FillRow.fill_id))), 0
            )

    async def test_short_cover_margin_and_borrow_fee(self) -> None:
        account_id = await self.service.create_account(create_command())
        margin_reservation = await self.service.freeze_cash(
            freeze_command(
                account_id,
                Decimal("50"),
                key="margin",
                order="short-1",
                reservation_kind=ReservationKind.SHORT_MARGIN,
            )
        )
        await self.service.record_short_fill(
            short_command(
                account_id, margin_reservation, key="short", order="short-1"
            )
        )
        position = await self._position(account_id, "600519.SSE")
        self.assertEqual(position.short_quantity, Decimal("1.000000000000"))
        self.assertEqual(position.margin_rmb, Decimal("50.00000000"))
        self.assertEqual(position.borrow_fee_rmb, Decimal("1.00000000"))

        cover_reservation = await self.service.freeze_cash(
            freeze_command(
                account_id,
                Decimal("101"),
                key="cover-freeze",
                order="cover-1",
                reservation_kind=ReservationKind.CASH_COVER,
            )
        )
        await self.service.record_cover_fill(
            cover_command(
                account_id, cover_reservation, key="cover", order="cover-1"
            )
        )
        position = await self._position(account_id, "600519.SSE")
        cash = await self._cash(account_id, "CNY")
        self.assertEqual(position.short_quantity, Decimal("0E-12"))
        self.assertEqual(position.margin_rmb, Decimal("0E-8"))
        self.assertEqual(position.short_proceeds_native, Decimal("0E-8"))
        self.assertEqual(position.short_proceeds_rmb, Decimal("0E-8"))
        self.assertEqual(position.borrow_fee_rmb, Decimal("0E-8"))
        self.assertEqual(cash.margin, Decimal("0E-8"))
        self.assertEqual(cash.total, Decimal("99998.00000000"))

    async def test_fund_reserve_confirm_and_redeem(self) -> None:
        account_id = await self.service.create_account(create_command())
        subscription = await self.service.freeze_cash(
            freeze_command(
                account_id,
                Decimal("101"),
                key="fund-freeze",
                order="fund-sub",
                reservation_kind=ReservationKind.FUND_SUBSCRIPTION,
            )
        )
        before = len(await self._events(account_id))
        with self.assertRaises(DomainInvariantViolation):
            await self.service.confirm_fund_subscription(
                fund_command(
                    account_id,
                    subscription,
                    key="fund-sub-wrong-order",
                    order="other-fund-order",
                    units=Decimal("10"),
                    nav=Decimal("10"),
                    fee=Decimal("1"),
                )
            )
        self.assertEqual(len(await self._events(account_id)), before)
        await self.service.confirm_fund_subscription(
            fund_command(
                account_id,
                subscription,
                key="fund-sub",
                order="fund-sub",
                units=Decimal("10"),
                nav=Decimal("10"),
                fee=Decimal("1"),
            )
        )
        redemption = await self.service.reserve_position(
            reserve_fund_position(
                account_id,
                key="fund-reserve",
                order="fund-red",
                quantity=Decimal("5"),
            )
        )
        before = len(await self._events(account_id))
        with self.assertRaises(DomainInvariantViolation):
            await self.service.confirm_fund_redemption(
                fund_command(
                    account_id,
                    redemption,
                    key="fund-red-wrong-order",
                    order="other-redemption-order",
                    units=Decimal("5"),
                    nav=Decimal("11"),
                    fee=Decimal("1"),
                )
            )
        self.assertEqual(len(await self._events(account_id)), before)
        await self.service.confirm_fund_redemption(
            fund_command(
                account_id,
                redemption,
                key="fund-red",
                order="fund-red",
                units=Decimal("5"),
                nav=Decimal("11"),
                fee=Decimal("1"),
            )
        )
        final_redemption = await self.service.reserve_position(
            reserve_fund_position(
                account_id,
                key="fund-reserve-final",
                order="fund-red-final",
                quantity=Decimal("5"),
            )
        )
        await self.service.confirm_fund_redemption(
            fund_command(
                account_id,
                final_redemption,
                key="fund-red-final",
                order="fund-red-final",
                units=Decimal("5"),
                nav=Decimal("11"),
                fee=Decimal("1"),
            )
        )
        position = await self._position(account_id, "FUND.OF")
        self.assertEqual(position.long_quantity, Decimal("0E-12"))
        self.assertEqual(position.settled_quantity, Decimal("0E-12"))
        self.assertEqual(position.frozen_quantity, Decimal("0E-12"))
        self.assertEqual(position.long_cost_native, Decimal("0E-8"))
        self.assertEqual(position.long_cost_rmb, Decimal("0E-8"))

    async def test_reset_checks_activity_positions_and_preserves_lineage(self) -> None:
        first = await self.service.create_account(create_command())
        reservation = await self.service.freeze_cash(
            freeze_command(first, Decimal("100"), key="freeze", order="order")
        )
        with self.assertRaisesRegex(DomainInvariantViolation, "non-terminal"):
            await self.service.reset_account(self._reset(first, "blocked"))
        await self.service.release_cash(
            ReleaseCashCommand(
                owner_user_id="owner-1",
                idempotency_key="release",
                correlation_id="release",
                causation_id="release",
                source=SOURCE,
                account_id=first,
                reservation_id=reservation,
            )
        )
        second = await self.service.reset_account(self._reset(first, "reset"))
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            old = await uow.accounts.get(first)
            new = await uow.accounts.get(second)
            old_events = await uow.events.list(first)
        assert old is not None and new is not None
        self.assertFalse(old.current)
        self.assertEqual(new.reset_from_account_id, first)
        self.assertEqual(len(old_events), 4)
        async with self.sessions() as session:
            close_event = old_events[-1]
            self.assertEqual(
                await session.scalar(
                    select(func.count(OutboxRow.message_id)).where(
                        OutboxRow.event_id == close_event.event_id
                    )
                ),
                1,
            )
            self.assertEqual(
                await session.scalar(
                    select(func.count(AuditRow.audit_id)).where(
                        AuditRow.event_id == close_event.event_id
                    )
                ),
                1,
            )

    async def test_failure_rolls_back_all_tables(self) -> None:
        fixed_service = SimulationLedgerService(
            uow_factory=lambda: SqlAlchemyUnitOfWork(self.sessions),
            clock=FixedClock(),
            ids=SequentialIds(fixed_message=True),
            rules=Rules(),
        )
        account_id = await fixed_service.create_account(create_command())
        with self.assertRaises(DatabaseError):
            await fixed_service.freeze_cash(
                freeze_command(
                    account_id, Decimal("100"), key="rollback", order="rollback"
                )
            )
        async with self.sessions() as session:
            cash = await session.get(AccountProjectionRow, (account_id, "CNY"))
            assert cash is not None
            self.assertEqual(cash.frozen, Decimal("0E-8"))
            for model in (ReservationRow,):
                self.assertEqual(
                    await session.scalar(select(func.count()).select_from(model)), 0
                )

    async def test_reversal_is_append_only_and_restores_projection(self) -> None:
        account_id = await self.service.create_account(create_command())
        await self.service.freeze_cash(
            freeze_command(
                account_id, Decimal("100"), key="freeze", order="reversible"
            )
        )
        original = (await self._events(account_id))[-1]
        reversal_id = await self.service.reverse_latest_event(
            ReverseEventCommand(
                owner_user_id="owner-1",
                idempotency_key="reverse",
                correlation_id="reverse",
                causation_id="reverse",
                source=SOURCE,
                account_id=account_id,
                original_event_id=original.event_id,
                reason="operator correction",
            )
        )
        self.assertNotEqual(reversal_id, original.event_id)
        self.assertEqual((await self._cash(account_id, "CNY")).frozen, Decimal("0E-8"))
        async with self.sessions() as session:
            self.assertEqual(
                await session.scalar(select(func.count(ReservationRow.reservation_id))),
                0,
            )
            self.assertEqual(
                await session.scalar(select(func.count(AccountEventRow.event_id))), 3
            )
            reversal_journal = await session.scalar(
                select(JournalRow).where(JournalRow.event_id == reversal_id)
            )
            assert reversal_journal is not None
            self.assertIsNotNone(reversal_journal.reversal_of_journal_id)
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            await rebuild_projections(uow, account_id)

    async def test_reversal_rejects_rehashed_rebind_and_duplicate_target(
        self,
    ) -> None:
        account_id = await self.service.create_account(create_command())
        await self.service.freeze_cash(
            freeze_command(
                account_id,
                Decimal("100"),
                key="rebind-freeze",
                order="rebind-order",
            )
        )
        target = (await self._events(account_id))[-1]
        await self.service.reverse_latest_event(
            ReverseEventCommand(
                owner_user_id="owner-1",
                idempotency_key="rebind-reverse",
                correlation_id="rebind-reverse",
                causation_id="rebind-reverse",
                source=SOURCE,
                account_id=account_id,
                original_event_id=target.event_id,
                reason="operator correction",
            )
        )
        events = await self._events(account_id)
        reversal = events[-1]
        duplicate = AccountEventEnvelope.create(
            **{
                **reversal.model_dump(
                    mode="python",
                    exclude={"event_id", "sequence", "previous_hash", "payload", "event_hash"},
                ),
                "event_id": "event-duplicate-reversal",
                "sequence": reversal.sequence + 1,
                "previous_hash": reversal.event_hash,
                "payload": ReversalPayload(
                    original_event_id=target.event_id,
                    original_event_hash=target.event_hash,
                    reason="duplicate correction",
                ),
            }
        )
        with self.assertRaises(DomainInvariantViolation):
            validate_reversal_history((*events, duplicate))

        earlier = events[0]
        rebound = AccountEventEnvelope.create(
            **{
                **reversal.model_dump(
                    mode="python", exclude={"payload", "event_hash"}
                ),
                "payload": ReversalPayload(
                    original_event_id=earlier.event_id,
                    original_event_hash=earlier.event_hash,
                    reason="rebound correction",
                ),
            }
        )
        async with self.engine.begin() as connection:
            await connection.execute(
                text("DROP TRIGGER account_events_no_update")
            )
            await connection.execute(
                text("DROP TRIGGER audit_records_no_update")
            )
            await connection.execute(
                update(AccountEventRow)
                .where(AccountEventRow.event_id == reversal.event_id)
                .values(
                    original_event_id=earlier.event_id,
                    original_event_hash=earlier.event_hash,
                    correction_reason="rebound correction",
                    event_hash=rebound.event_hash,
                )
            )
            await connection.execute(
                update(AuditRow)
                .where(AuditRow.event_id == reversal.event_id)
                .values(event_hash=rebound.event_hash)
            )
            await connection.execute(
                update(OutboxRow)
                .where(OutboxRow.event_id == reversal.event_id)
                .values(event_hash=rebound.event_hash)
            )
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            with self.assertRaisesRegex(
                DomainInvariantViolation, "reversal target"
            ):
                await rebuild_projections(uow, account_id)

    async def test_rebuild_checksum_and_tamper_anchor_detection(self) -> None:
        account_id = await self.service.create_account(create_command())
        reservation = await self.service.freeze_cash(
            freeze_command(account_id, Decimal("100"), key="freeze", order="buy")
        )
        await self.service.record_buy_fill(
            buy_command(account_id, reservation, key="buy", order="buy")
        )
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            before = projection_checksum(
                await uow.account_projections.list(account_id),
                await uow.position_projections.list(account_id),
                await uow.reservations.list(account_id),
            )
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            self.assertEqual(await rebuild_projections(uow, account_id), before)

        last_event = (await self._events(account_id))[-1]
        async with self.engine.begin() as connection:
            await connection.execute(text("DROP TRIGGER account_events_no_update"))
            forged = AccountEventEnvelope.create(
                **{
                    **last_event.model_dump(mode="python", exclude={"event_hash"}),
                    "correlation_id": "forged-correlation",
                }
            )
            await connection.execute(
                update(AccountEventRow)
                .where(AccountEventRow.event_id == last_event.event_id)
                .values(
                    correlation_id=forged.correlation_id,
                    event_hash=forged.event_hash,
                )
            )
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            with self.assertRaisesRegex(DomainInvariantViolation, "anchor"):
                await rebuild_projections(uow, account_id)

    async def test_rebuild_rejects_semantically_rehashed_posting_tamper(self) -> None:
        account_id = await self.service.create_account(create_command())
        first_event = (await self._events(account_id))[0]
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            journal = await uow.journals.get_by_event(first_event.event_id)
        assert journal is not None
        original = journal.postings[0]
        forged_posting = LedgerPosting.create(
            posting_id=original.posting_id,
            sequence=original.sequence,
            account_code="cash:forged",
            original=original.original,
            rmb_amount=original.rmb_amount,
        )
        forged_journal = JournalEntry.create(
            **{
                **journal.model_dump(
                    mode="python", exclude={"journal_hash", "postings"}
                ),
                "postings": (forged_posting, *journal.postings[1:]),
            }
        )
        async with self.engine.begin() as connection:
            await connection.execute(
                text("DROP TRIGGER ledger_postings_no_update")
            )
            await connection.execute(
                text("DROP TRIGGER journal_entries_no_update")
            )
            await connection.execute(
                text("DROP TRIGGER audit_records_no_update")
            )
            await connection.execute(
                update(LedgerPostingRow)
                .where(
                    LedgerPostingRow.posting_id == original.posting_id
                )
                .values(
                    account_code=forged_posting.account_code,
                    posting_hash=forged_posting.posting_hash,
                )
            )
            await connection.execute(
                update(JournalRow)
                .where(JournalRow.journal_id == journal.journal_id)
                .values(journal_hash=forged_journal.journal_hash)
            )
            await connection.execute(
                update(AuditRow)
                .where(AuditRow.event_id == first_event.event_id)
                .values(journal_hash=forged_journal.journal_hash)
            )
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            with self.assertRaisesRegex(
                DomainInvariantViolation, "semantics"
            ):
                await rebuild_projections(uow, account_id)

    async def test_rebuild_rejects_rehashed_shifted_posting_sequences(self) -> None:
        account_id = await self.service.create_account(create_command())
        first_event = (await self._events(account_id))[0]
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            journal = await uow.journals.get_by_event(first_event.event_id)
        assert journal is not None
        forged_postings = tuple(
            LedgerPosting.create(
                posting_id=posting.posting_id,
                sequence=posting.sequence + 10,
                account_code=posting.account_code,
                original=posting.original,
                rmb_amount=posting.rmb_amount,
            )
            for posting in journal.postings
        )
        journal_values = journal.model_dump(
            mode="python", exclude={"journal_hash", "postings"}
        )
        journal_values["postings"] = forged_postings
        forged_journal_hash = canonical_hash(journal_values)
        async with self.engine.begin() as connection:
            await connection.execute(
                text("DROP TRIGGER ledger_postings_no_update")
            )
            await connection.execute(
                text("DROP TRIGGER journal_entries_no_update")
            )
            await connection.execute(
                text("DROP TRIGGER audit_records_no_update")
            )
            for posting in forged_postings:
                await connection.execute(
                    update(LedgerPostingRow)
                    .where(
                        LedgerPostingRow.posting_id == posting.posting_id
                    )
                    .values(
                        sequence=posting.sequence,
                        posting_hash=posting.posting_hash,
                    )
                )
            await connection.execute(
                update(JournalRow)
                .where(JournalRow.journal_id == journal.journal_id)
                .values(journal_hash=forged_journal_hash)
            )
            await connection.execute(
                update(AuditRow)
                .where(AuditRow.event_id == first_event.event_id)
                .values(journal_hash=forged_journal_hash)
            )
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            with self.assertRaisesRegex(
                DomainInvariantViolation, "posting sequences"
            ):
                await rebuild_projections(uow, account_id)

    async def test_sqlite_fk_and_append_only_triggers(self) -> None:
        account_id = await self.service.create_account(create_command())
        events = await self._events(account_id)
        async with self.sessions.begin() as session:
            with self.assertRaises(DatabaseError):
                await session.execute(
                    update(AccountEventRow)
                    .where(AccountEventRow.event_id == events[0].event_id)
                    .values(correlation_id="tamper")
                )
        async with self.sessions.begin() as session:
            with self.assertRaises(DatabaseError):
                await session.execute(
                    delete(AccountEventRow).where(
                        AccountEventRow.event_id == events[0].event_id
                    )
                )
        async with self.sessions.begin() as session:
            with self.assertRaises(DatabaseError):
                session.add(
                    FillRow(
                        fill_id="orphan",
                        event_id="missing",
                        account_id=account_id,
                        order_id="order",
                        instrument_id="instrument",
                        transaction_type="buy",
                        quantity=Decimal("1"),
                        native_currency="CNY",
                        native_gross=Decimal("1"),
                        native_fee=Decimal("0"),
                        native_borrow_fee=Decimal("0"),
                        rmb_gross=Decimal("1"),
                        rmb_fee=Decimal("0"),
                        rmb_borrow_fee=Decimal("0"),
                        margin_change_rmb=Decimal("0"),
                        slippage_bps=Decimal("0"),
                        market_object_type="market",
                        market_object_id="id",
                        market_version="1",
                        model_version="1",
                        rule_version="simulation-rules-v1",
                        occurred_at=NOW_UTC,
                    )
                )
                await session.flush()

    async def _cash(self, account_id: str, currency: str) -> AccountProjectionRow:
        async with self.sessions() as session:
            row = await session.get(AccountProjectionRow, (account_id, currency))
            assert row is not None
            session.expunge(row)
            return row

    async def _reservation(self, reservation_id: str) -> ReservationRow:
        async with self.sessions() as session:
            row = await session.get(ReservationRow, reservation_id)
            assert row is not None
            session.expunge(row)
            return row

    async def _position(
        self, account_id: str, instrument_id: str
    ) -> PositionProjectionRow:
        async with self.sessions() as session:
            row = await session.get(
                PositionProjectionRow, (account_id, instrument_id)
            )
            assert row is not None
            session.expunge(row)
            return row

    async def _events(self, account_id: str) -> tuple[AccountEventEnvelope, ...]:
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            return await uow.events.list(account_id)

    def _reset(self, account_id: str, key: str) -> ResetAccountCommand:
        return ResetAccountCommand(
            owner_user_id="owner-1",
            idempotency_key=key,
            correlation_id=f"correlation-{key}",
            causation_id=f"request-{key}",
            source=SOURCE,
            account_id=account_id,
            initial_cash_rmb=Decimal("50000"),
        )


if __name__ == "__main__":
    unittest.main()
