from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from collections.abc import Callable
from typing import Any, cast

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    DDL,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Any
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("UTCDateTime requires a timezone-aware value")
        return value.astimezone(timezone.utc)

    def process_result_value(
        self, value: datetime | None, dialect: Any
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


MONEY = Numeric(28, 8, asdecimal=True)
RATE = Numeric(28, 12, asdecimal=True)
QUANTITY = Numeric(28, 12, asdecimal=True)


class Base(DeclarativeBase):
    pass


class AccountRow(Base):
    __tablename__ = "simulation_accounts"
    __table_args__ = (
        CheckConstraint("initial_cash_rmb > 0", name="ck_account_initial_cash_positive"),
        CheckConstraint("revision >= 1", name="ck_account_revision_positive"),
        CheckConstraint(
            "status IN ('active','suspended','closed')", name="ck_account_status"
        ),
        CheckConstraint(
            "(status = 'closed' AND current = false AND closed_at IS NOT NULL) OR "
            "(status <> 'closed' AND closed_at IS NULL)",
            name="ck_account_lifecycle",
        ),
        Index(
            "uq_current_account_per_owner",
            "owner_user_id",
            unique=True,
            sqlite_where=text("current = 1"),
            postgresql_where=text("current = true"),
        ),
    )

    account_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    initial_cash_rmb: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    current: Mapped[bool] = mapped_column(Boolean, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    reset_from_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("simulation_accounts.account_id")
    )


class AccountEventRow(Base):
    __tablename__ = "account_events"
    __table_args__ = (
        UniqueConstraint("account_id", "sequence", name="uq_event_account_sequence"),
        CheckConstraint("sequence >= 1", name="ck_event_sequence_positive"),
        CheckConstraint(
            "event_type IN ('account_opened','account_reset_closed','cash_reserved',"
            "'cash_released','position_reserved','buy_fill_recorded',"
            "'sell_fill_recorded','short_fill_recorded','cover_fill_recorded',"
            "'fund_subscription_confirmed','fund_redemption_confirmed',"
            "'reversal_recorded')",
            name="ck_event_type",
        ),
        CheckConstraint("length(event_hash) = 64", name="ck_event_hash_length"),
        CheckConstraint(
            "previous_hash IS NULL OR length(previous_hash) = 64",
            name="ck_previous_hash_length",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("simulation_accounts.account_id"), nullable=False, index=True
    )
    owner_user_id: Mapped[str] = mapped_column(String(160), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(160), nullable=False)
    causation_id: Mapped[str] = mapped_column(String(160), nullable=False)
    source_object_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_object_id: Mapped[str] = mapped_column(String(160), nullable=False)
    source_version: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    payload_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    new_account_id: Mapped[str | None] = mapped_column(String(160))
    reservation_id: Mapped[str | None] = mapped_column(String(160))
    order_id: Mapped[str | None] = mapped_column(String(160))
    reservation_kind: Mapped[str | None] = mapped_column(String(40))
    trade_side: Mapped[str | None] = mapped_column(String(16))
    fund_action: Mapped[str | None] = mapped_column(String(16))
    instrument_id: Mapped[str | None] = mapped_column(String(160))
    native_currency: Mapped[str | None] = mapped_column(String(3))
    native_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    native_gross: Mapped[Decimal | None] = mapped_column(MONEY)
    native_fee: Mapped[Decimal | None] = mapped_column(MONEY)
    native_borrow_fee: Mapped[Decimal | None] = mapped_column(MONEY)
    rmb_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    rmb_gross: Mapped[Decimal | None] = mapped_column(MONEY)
    rmb_fee: Mapped[Decimal | None] = mapped_column(MONEY)
    rmb_borrow_fee: Mapped[Decimal | None] = mapped_column(MONEY)
    margin_change_rmb: Mapped[Decimal | None] = mapped_column(MONEY)
    quantity: Mapped[Decimal | None] = mapped_column(QUANTITY)
    nav: Mapped[Decimal | None] = mapped_column(MONEY)
    slippage_bps: Mapped[Decimal | None] = mapped_column(RATE)
    fx_base_currency: Mapped[str | None] = mapped_column(String(3))
    fx_quote_currency: Mapped[str | None] = mapped_column(String(3))
    fx_rate: Mapped[Decimal | None] = mapped_column(RATE)
    fx_observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    fx_source_object_type: Mapped[str | None] = mapped_column(String(80))
    fx_source_object_id: Mapped[str | None] = mapped_column(String(160))
    fx_source_version: Mapped[str | None] = mapped_column(String(80))
    market_object_type: Mapped[str | None] = mapped_column(String(80))
    market_object_id: Mapped[str | None] = mapped_column(String(160))
    market_version: Mapped[str | None] = mapped_column(String(80))
    model_version: Mapped[str | None] = mapped_column(String(80))
    settled: Mapped[bool | None] = mapped_column(Boolean)
    original_event_id: Mapped[str | None] = mapped_column(String(160))
    original_event_hash: Mapped[str | None] = mapped_column(String(64))
    correction_reason: Mapped[str | None] = mapped_column(String(500))


class JournalRow(Base):
    __tablename__ = "journal_entries"

    journal_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("simulation_accounts.account_id"), nullable=False, index=True
    )
    event_id: Mapped[str] = mapped_column(
        ForeignKey("account_events.event_id"), nullable=False, unique=True
    )
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(80), nullable=False)
    reversal_of_journal_id: Mapped[str | None] = mapped_column(
        ForeignKey("journal_entries.journal_id")
    )
    journal_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class LedgerPostingRow(Base):
    __tablename__ = "ledger_postings"
    __table_args__ = (
        UniqueConstraint(
            "journal_id", "sequence", name="uq_posting_journal_sequence"
        ),
        CheckConstraint("sequence >= 1", name="ck_posting_sequence_positive"),
    )

    posting_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    journal_id: Mapped[str] = mapped_column(
        ForeignKey("journal_entries.journal_id"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    account_code: Mapped[str] = mapped_column(String(80), nullable=False)
    original_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    original_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    rmb_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    posting_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class AccountProjectionRow(Base):
    __tablename__ = "account_projections"
    __table_args__ = (
        CheckConstraint(
            "total >= 0 AND frozen >= 0 AND margin >= 0",
            name="ck_cash_native_nonnegative",
        ),
        CheckConstraint(
            "rmb_total >= 0 AND rmb_frozen >= 0 AND rmb_margin >= 0",
            name="ck_cash_rmb_nonnegative",
        ),
        CheckConstraint("frozen + margin <= total", name="ck_cash_native_allocated"),
        CheckConstraint(
            "rmb_frozen + rmb_margin <= rmb_total", name="ck_cash_rmb_allocated"
        ),
        CheckConstraint("revision >= 0", name="ck_cash_revision"),
    )

    account_id: Mapped[str] = mapped_column(
        ForeignKey("simulation_accounts.account_id"), primary_key=True
    )
    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    frozen: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    margin: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    rmb_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    rmb_frozen: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    rmb_margin: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


class PositionProjectionRow(Base):
    __tablename__ = "position_projections"
    __table_args__ = (
        CheckConstraint(
            "long_quantity >= 0 AND short_quantity >= 0 AND settled_quantity >= 0 "
            "AND frozen_quantity >= 0",
            name="ck_position_quantities_nonnegative",
        ),
        CheckConstraint(
            "frozen_quantity <= settled_quantity AND settled_quantity <= long_quantity",
            name="ck_position_quantity_relationships",
        ),
        CheckConstraint(
            "long_cost_native >= 0 AND long_cost_rmb >= 0 "
            "AND short_proceeds_native >= 0 AND short_proceeds_rmb >= 0 "
            "AND margin_rmb >= 0 AND borrow_fee_rmb >= 0",
            name="ck_position_amounts_nonnegative",
        ),
        CheckConstraint(
            "short_quantity <> 0 OR "
            "(short_proceeds_native = 0 AND short_proceeds_rmb = 0 "
            "AND margin_rmb = 0 AND borrow_fee_rmb = 0)",
            name="ck_position_closed_short_zero",
        ),
        CheckConstraint("revision >= 0", name="ck_position_revision"),
    )

    account_id: Mapped[str] = mapped_column(
        ForeignKey("simulation_accounts.account_id"), primary_key=True
    )
    instrument_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    long_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    short_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    settled_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    frozen_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    long_cost_native: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    long_cost_rmb: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    short_proceeds_native: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    short_proceeds_rmb: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    margin_rmb: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    borrow_fee_rmb: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


class ReservationRow(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint("account_id", "order_id", name="uq_reservation_account_order"),
        CheckConstraint(
            "kind IN ('cash_buy','cash_cover','short_margin','fund_subscription',"
            "'fund_redemption')",
            name="ck_reservation_kind",
        ),
        CheckConstraint(
            "status IN ('active','released','consumed')",
            name="ck_reservation_status",
        ),
        CheckConstraint(
            "native_amount >= 0 AND rmb_amount >= 0 AND quantity >= 0 "
            "AND consumed_native >= 0 AND consumed_rmb >= 0 "
            "AND consumed_quantity >= 0",
            name="ck_reservation_nonnegative",
        ),
        CheckConstraint(
            "consumed_native <= native_amount AND consumed_rmb <= rmb_amount "
            "AND consumed_quantity <= quantity",
            name="ck_reservation_consumption",
        ),
        CheckConstraint("revision >= 1", name="ck_reservation_revision"),
    )

    reservation_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("simulation_accounts.account_id"), nullable=False, index=True
    )
    order_id: Mapped[str] = mapped_column(String(160), nullable=False)
    instrument_id: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    native_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    native_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    rmb_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    consumed_native: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    consumed_rmb: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    consumed_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


class FillRow(Base):
    __tablename__ = "fills"

    fill_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("account_events.event_id"), nullable=False, unique=True
    )
    account_id: Mapped[str] = mapped_column(
        ForeignKey("simulation_accounts.account_id"), nullable=False, index=True
    )
    order_id: Mapped[str] = mapped_column(String(160), nullable=False)
    reservation_id: Mapped[str | None] = mapped_column(String(160))
    instrument_id: Mapped[str] = mapped_column(String(160), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(40), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    native_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    native_gross: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    native_fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    native_borrow_fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    rmb_gross: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    rmb_fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    rmb_borrow_fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    margin_change_rmb: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    slippage_bps: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    fx_base_currency: Mapped[str | None] = mapped_column(String(3))
    fx_quote_currency: Mapped[str | None] = mapped_column(String(3))
    fx_rate: Mapped[Decimal | None] = mapped_column(RATE)
    fx_observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    fx_source_object_type: Mapped[str | None] = mapped_column(String(80))
    fx_source_object_id: Mapped[str | None] = mapped_column(String(160))
    fx_source_version: Mapped[str | None] = mapped_column(String(80))
    market_object_type: Mapped[str] = mapped_column(String(80), nullable=False)
    market_object_id: Mapped[str] = mapped_column(String(160), nullable=False)
    market_version: Mapped[str] = mapped_column(String(80), nullable=False)
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(80), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class IdempotencyRow(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "scope", "owner_user_id", "key", name="uq_idempotency_scope_owner_key"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(80), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(160), nullable=False)
    key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class AuditRow(Base):
    __tablename__ = "audit_records"

    audit_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(160), nullable=False)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("simulation_accounts.account_id"), nullable=False, index=True
    )
    event_id: Mapped[str | None] = mapped_column(
        ForeignKey("account_events.event_id"), index=True
    )
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    journal_hash: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(160), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class OutboxRow(Base):
    __tablename__ = "outbox_messages"

    message_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    topic: Mapped[str] = mapped_column(String(160), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("account_events.event_id"), nullable=False, unique=True
    )
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AccountActivityRow(Base):
    __tablename__ = "account_activities"
    __table_args__ = (
        UniqueConstraint("reference_id", name="uq_activity_reference"),
        CheckConstraint(
            "status IN ('open','completed','cancelled','failed')",
            name="ck_activity_status",
        ),
    )

    activity_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("simulation_accounts.account_id"), nullable=False, index=True
    )
    activity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


FACT_TABLES: tuple[Table, ...] = (
    cast(Table, AccountEventRow.__table__),
    cast(Table, JournalRow.__table__),
    cast(Table, LedgerPostingRow.__table__),
    cast(Table, FillRow.__table__),
    cast(Table, AuditRow.__table__),
)
typed_ddl = cast(Callable[[str], DDL], DDL)

for table in FACT_TABLES:
    event.listen(
        table,
        "after_create",
        typed_ddl(
            f"CREATE TRIGGER {table.name}_no_update "
            f"BEFORE UPDATE ON {table.name} "
            "BEGIN SELECT RAISE(ABORT, 'append-only fact table'); END"
        ).execute_if(dialect="sqlite"),
    )
    event.listen(
        table,
        "after_create",
        typed_ddl(
            f"CREATE TRIGGER {table.name}_no_delete "
            f"BEFORE DELETE ON {table.name} "
            "BEGIN SELECT RAISE(ABORT, 'append-only fact table'); END"
        ).execute_if(dialect="sqlite"),
    )

event.listen(
    Base.metadata,
    "before_create",
    typed_ddl(
        "CREATE OR REPLACE FUNCTION finance_god_prevent_fact_mutation() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION 'append-only fact table'; END $$"
    ).execute_if(dialect="postgresql"),
)
for table in FACT_TABLES:
    event.listen(
        table,
        "after_create",
        typed_ddl(
            f"CREATE TRIGGER {table.name}_no_mutation "
            f"BEFORE UPDATE OR DELETE ON {table.name} "
            "FOR EACH ROW EXECUTE FUNCTION finance_god_prevent_fact_mutation()"
        ).execute_if(dialect="postgresql"),
    )
