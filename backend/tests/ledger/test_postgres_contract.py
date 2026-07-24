from __future__ import annotations

import asyncio
import os
import unittest
from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from finance_god.application import (
    ResetAccountCommand,
    SimulationLedgerService,
    rebuild_projections,
)
from finance_god.domain import (
    DomainInvariantViolation,
    ExchangeRateEvidence,
    JournalEntry,
    LedgerPosting,
    ReservationKind,
    canonical_hash,
)
from finance_god.infrastructure.persistence import (
    SqlAlchemyUnitOfWork,
    create_session_factory,
)
from finance_god.infrastructure.persistence.models import (
    AccountEventRow,
    AccountProjectionRow,
    AuditRow,
    IdempotencyRow,
    JournalRow,
    LedgerPostingRow,
    OutboxRow,
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

POSTGRES_URL = os.getenv("FINANCE_GOD_TEST_POSTGRES_URL")
BACKEND = Path(__file__).resolve().parents[2]
LEDGER_TABLES = (
    "account_activities",
    "outbox_messages",
    "audit_records",
    "idempotency_records",
    "fills",
    "reservations",
    "position_projections",
    "account_projections",
    "ledger_postings",
    "journal_entries",
    "account_events",
    "simulation_accounts",
    "alembic_version",
)


def _require_test_database(database_url: str) -> None:
    database = make_url(database_url).database or ""
    if "test" not in database.lower() or database.lower() in {
        "postgres",
        "template0",
        "template1",
    }:
        raise RuntimeError(
            "FINANCE_GOD_TEST_POSTGRES_URL must target a dedicated test database"
        )


async def _clear_ledger_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "DROP TABLE IF EXISTS "
                    + ", ".join(LEDGER_TABLES)
                    + " CASCADE"
                )
            )
            await connection.execute(
                text(
                    "DROP FUNCTION IF EXISTS "
                    "finance_god_prevent_fact_mutation()"
                )
            )
    finally:
        await engine.dispose()


@unittest.skipUnless(
    POSTGRES_URL,
    "FINANCE_GOD_TEST_POSTGRES_URL is not configured",
)
class PostgresLedgerContractTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        assert POSTGRES_URL is not None
        _require_test_database(POSTGRES_URL)
        await _clear_ledger_schema(POSTGRES_URL)
        config = Config(str(BACKEND / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", POSTGRES_URL)
        await asyncio.to_thread(command.upgrade, config, "head")
        self.engine, self.sessions = create_session_factory(POSTGRES_URL)
        self.service = SimulationLedgerService(
            uow_factory=lambda: SqlAlchemyUnitOfWork(self.sessions),
            clock=FixedClock(),
            ids=SequentialIds(),
            rules=Rules(),
        )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
    async def test_postgres_full_market_lifecycle_and_reset(self) -> None:
        account_id = await self.service.create_account(create_command())
        usd_reservation = await self.service.freeze_cash(
            freeze_command(
                account_id,
                Decimal("100"),
                key="usd-freeze",
                order="usd-buy",
                instrument="AAPL.US",
                currency="USD",
            )
        )
        await self.service.record_buy_fill(
            buy_command(
                account_id,
                usd_reservation,
                key="usd-buy",
                order="usd-buy",
                instrument="AAPL.US",
                currency="USD",
            )
        )
        await self.service.record_sell_fill(
            sell_command(
                account_id,
                key="usd-sell",
                order="usd-sell",
                instrument="AAPL.US",
                currency="USD",
            )
        )

        margin = await self.service.freeze_cash(
            freeze_command(
                account_id,
                Decimal("50"),
                key="margin",
                order="short",
                reservation_kind=ReservationKind.SHORT_MARGIN,
            )
        )
        await self.service.record_short_fill(
            short_command(account_id, margin, key="short", order="short")
        )
        cover = await self.service.freeze_cash(
            freeze_command(
                account_id,
                Decimal("101"),
                key="cover-freeze",
                order="cover",
                reservation_kind=ReservationKind.CASH_COVER,
            )
        )
        await self.service.record_cover_fill(
            cover_command(account_id, cover, key="cover", order="cover")
        )
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            short_position = await uow.position_projections.get(
                account_id, "600519.SSE"
            )
            cny_cash = await uow.account_projections.get(account_id, "CNY")
        assert short_position is not None and cny_cash is not None
        self.assertEqual(short_position.short_quantity, Decimal("0E-12"))
        self.assertEqual(short_position.margin_rmb, Decimal("0E-8"))
        self.assertEqual(short_position.borrow_fee_rmb, Decimal("0E-8"))
        self.assertEqual(cny_cash.margin, Decimal("0E-8"))

        fund_cash = await self.service.freeze_cash(
            freeze_command(
                account_id,
                Decimal("101"),
                key="fund-cash",
                order="fund-sub",
                reservation_kind=ReservationKind.FUND_SUBSCRIPTION,
            )
        )
        await self.service.confirm_fund_subscription(
            fund_command(
                account_id,
                fund_cash,
                key="fund-sub",
                order="fund-sub",
                units=Decimal("10"),
                nav=Decimal("10"),
                fee=Decimal("1"),
            )
        )
        fund_units = await self.service.reserve_position(
            reserve_fund_position(
                account_id,
                key="fund-reserve",
                order="fund-red",
                quantity=Decimal("10"),
            )
        )
        await self.service.confirm_fund_redemption(
            fund_command(
                account_id,
                fund_units,
                key="fund-red",
                order="fund-red",
                units=Decimal("10"),
                nav=Decimal("11"),
                fee=Decimal("1"),
            )
        )
        new_id = await self.service.reset_account(
            ResetAccountCommand(
                owner_user_id="owner-1",
                idempotency_key="reset",
                correlation_id="reset",
                causation_id="reset",
                source=SOURCE,
                account_id=account_id,
                initial_cash_rmb=Decimal("50000"),
            )
        )
        self.assertNotEqual(new_id, account_id)
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            old = await uow.accounts.get(account_id)
            events = await uow.events.list(account_id)
        assert old is not None
        self.assertFalse(old.current)
        self.assertTrue(
            {
                "buy_fill_recorded",
                "sell_fill_recorded",
                "short_fill_recorded",
                "cover_fill_recorded",
                "fund_subscription_confirmed",
                "fund_redemption_confirmed",
            }.issubset({item.event_type.value for item in events})
        )

    async def test_postgres_binding_rounding_and_cost_residuals(self) -> None:
        fx = ExchangeRateEvidence(
            base_currency="USD",
            quote_currency="CNY",
            rate=Decimal("7.123456789012"),
            observed_at=NOW_UTC,
            source=SOURCE,
        )
        account_id = await self.service.create_account(create_command())
        usd_reservation = await self.service.freeze_cash(
            freeze_command(
                account_id,
                Decimal("1"),
                key="pg-round-freeze",
                order="pg-round-buy",
                instrument="ROUND.US",
                currency="USD",
                exchange_rate=fx,
            )
        )
        async with self.sessions() as session:
            before = await session.scalar(
                select(func.count(AccountEventRow.event_id)).where(
                    AccountEventRow.account_id == account_id
                )
            )
        with self.assertRaises(DomainInvariantViolation):
            await self.service.record_buy_fill(
                buy_command(
                    account_id,
                    usd_reservation,
                    key="pg-wrong-order",
                    order="wrong-order",
                    instrument="ROUND.US",
                    currency="USD",
                    exchange_rate=fx,
                )
            )
        async with self.sessions() as session:
            after = await session.scalar(
                select(func.count(AccountEventRow.event_id)).where(
                    AccountEventRow.account_id == account_id
                )
            )
        self.assertEqual(after, before)
        await self.service.record_buy_fill(
            buy_command(
                account_id,
                usd_reservation,
                key="pg-round-buy",
                order="pg-round-buy",
                instrument="ROUND.US",
                quantity=Decimal("0.333333333333"),
                price=Decimal("0.12345678"),
                currency="USD",
                exchange_rate=fx,
            )
        )
        cycle_reservation = await self.service.freeze_cash(
            freeze_command(
                account_id,
                Decimal("0.99999999"),
                key="pg-cycle-freeze",
                order="pg-cycle-buy",
                instrument="CYCLE.SSE",
            )
        )
        await self.service.record_buy_fill(
            buy_command(
                account_id,
                cycle_reservation,
                key="pg-cycle-buy",
                order="pg-cycle-buy",
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
                    key=f"pg-cycle-sell-{index}",
                    order=f"pg-cycle-sell-{index}",
                    instrument="CYCLE.SSE",
                    quantity=quantity,
                    price=Decimal("0.4"),
                    fee=Decimal("0"),
                )
            )
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            position = await uow.position_projections.get(
                account_id, "CYCLE.SSE"
            )
            fills = await uow.fills.list(account_id)
        assert position is not None
        self.assertEqual(position.long_cost_rmb, Decimal("0E-8"))
        self.assertEqual(fills[0].rmb_gross, Decimal("0.29314635"))

    async def test_postgres_rebuild_rejects_rehashed_posting_tamper(self) -> None:
        account_id = await self.service.create_account(create_command())
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            events = await uow.events.list(account_id)
            journal = await uow.journals.get_by_event(events[0].event_id)
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
                text(
                    "DROP TRIGGER ledger_postings_no_mutation "
                    "ON ledger_postings"
                )
            )
            await connection.execute(
                text(
                    "DROP TRIGGER journal_entries_no_mutation "
                    "ON journal_entries"
                )
            )
            await connection.execute(
                text(
                    "DROP TRIGGER audit_records_no_mutation "
                    "ON audit_records"
                )
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
                .where(AuditRow.event_id == events[0].event_id)
                .values(journal_hash=forged_journal.journal_hash)
            )
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            with self.assertRaisesRegex(
                DomainInvariantViolation, "semantics"
            ):
                await rebuild_projections(uow, account_id)

    async def test_postgres_rejects_rehashed_shifted_posting_sequences(
        self,
    ) -> None:
        account_id = await self.service.create_account(create_command())
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            events = await uow.events.list(account_id)
            journal = await uow.journals.get_by_event(events[0].event_id)
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
                text(
                    "DROP TRIGGER ledger_postings_no_mutation "
                    "ON ledger_postings"
                )
            )
            await connection.execute(
                text(
                    "DROP TRIGGER journal_entries_no_mutation "
                    "ON journal_entries"
                )
            )
            await connection.execute(
                text(
                    "DROP TRIGGER audit_records_no_mutation "
                    "ON audit_records"
                )
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
                .where(AuditRow.event_id == events[0].event_id)
                .values(journal_hash=forged_journal_hash)
            )
        async with SqlAlchemyUnitOfWork(self.sessions) as uow:
            with self.assertRaisesRegex(
                DomainInvariantViolation, "posting sequences"
            ):
                await rebuild_projections(uow, account_id)

    async def test_postgres_atomic_rollback(self) -> None:
        service = SimulationLedgerService(
            uow_factory=lambda: SqlAlchemyUnitOfWork(self.sessions),
            clock=FixedClock(),
            ids=SequentialIds(fixed_message=True),
            rules=Rules(),
        )
        account_id = await service.create_account(create_command())
        with self.assertRaises(DBAPIError):
            await service.freeze_cash(
                freeze_command(
                    account_id, Decimal("100"), key="rollback", order="rollback"
                )
            )
        async with self.sessions() as session:
            projection = await session.get(
                AccountProjectionRow, (account_id, "CNY")
            )
            assert projection is not None
            self.assertEqual(projection.frozen, Decimal("0E-8"))
            self.assertEqual(
                await session.scalar(select(func.count(ReservationRow.reservation_id))),
                0,
            )
            self.assertEqual(
                await session.scalar(
                    select(func.count(IdempotencyRow.id)).where(
                        IdempotencyRow.scope == "freeze_cash"
                    )
                ),
                0,
            )

    async def test_postgres_same_and_different_key_concurrency(self) -> None:
        first, second = await asyncio.gather(
            self.service.create_account(create_command()),
            self.service.create_account(create_command()),
        )
        self.assertEqual(first, second)
        same = freeze_command(
            first, Decimal("100"), key="same", order="same-order"
        )
        result_one, result_two = await asyncio.gather(
            self.service.freeze_cash(same),
            self.service.freeze_cash(same),
        )
        self.assertEqual(result_one, result_two)
        await asyncio.gather(
            self.service.freeze_cash(
                freeze_command(
                    first, Decimal("200"), key="different-1", order="order-2"
                )
            ),
            self.service.freeze_cash(
                freeze_command(
                    first, Decimal("300"), key="different-2", order="order-3"
                )
            ),
        )
        async with self.sessions() as session:
            projection = await session.get(AccountProjectionRow, (first, "CNY"))
            assert projection is not None
            self.assertEqual(projection.frozen, Decimal("600.00000000"))
            self.assertEqual(
                await session.scalar(
                    select(func.count(AccountEventRow.event_id)).where(
                        AccountEventRow.account_id == first
                    )
                ),
                4,
            )

    async def test_postgres_rebuild_and_writer_are_serialized(self) -> None:
        account_id = await self.service.create_account(create_command())
        reservation = await self.service.freeze_cash(
            freeze_command(
                account_id, Decimal("100"), key="buy-freeze", order="buy"
            )
        )
        await self.service.record_buy_fill(
            buy_command(account_id, reservation, key="buy", order="buy")
        )
        writer = freeze_command(
            account_id, Decimal("50"), key="writer", order="writer"
        )

        async def rebuild() -> str:
            async with SqlAlchemyUnitOfWork(self.sessions) as uow:
                return await rebuild_projections(uow, account_id)

        checksums = await asyncio.gather(
            rebuild(),
            rebuild(),
            self.service.freeze_cash(writer),
        )
        self.assertEqual(checksums[0], checksums[1])
        async with self.sessions() as session:
            projection = await session.get(
                AccountProjectionRow, (account_id, "CNY")
            )
            assert projection is not None
            self.assertEqual(projection.frozen, Decimal("50.00000000"))
            self.assertEqual(
                await session.scalar(
                    select(func.count(AuditRow.audit_id)).where(
                        AuditRow.action == "projection_rebuild"
                    )
                ),
                2,
            )

    async def test_postgres_fact_tables_reject_update_delete(self) -> None:
        account_id = await self.service.create_account(create_command())
        async with self.sessions() as session:
            event_id = await session.scalar(
                select(AccountEventRow.event_id).where(
                    AccountEventRow.account_id == account_id
                )
            )
        assert event_id is not None
        async with self.sessions.begin() as session:
            with self.assertRaises(DBAPIError):
                await session.execute(
                    update(AccountEventRow)
                    .where(AccountEventRow.event_id == event_id)
                    .values(correlation_id="tamper")
                )
        async with self.sessions.begin() as session:
            with self.assertRaises(DBAPIError):
                await session.execute(
                    delete(AccountEventRow).where(
                        AccountEventRow.event_id == event_id
                    )
                )
        async with self.sessions() as session:
            self.assertEqual(
                await session.scalar(
                    select(func.count(OutboxRow.message_id)).where(
                        OutboxRow.event_id == event_id
                    )
                ),
                1,
            )


if __name__ == "__main__":
    unittest.main()
