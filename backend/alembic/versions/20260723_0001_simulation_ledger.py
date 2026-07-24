"""Create the append-only simulation ledger and rebuildable projections.

Revision ID: 20260723_0001
Revises:
Create Date: 2026-07-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260723_0001"
down_revision = None
branch_labels = None
depends_on = None

FACT_TABLES = (
    "account_events",
    "journal_entries",
    "ledger_postings",
    "fills",
    "audit_records",
)
UTC = sa.DateTime(timezone=True)
MONEY = sa.Numeric(28, 8)
QUANTITY = sa.Numeric(28, 12)
RATE = sa.Numeric(28, 12)


def upgrade() -> None:
    _create_accounts()
    _create_events()
    _create_journals()
    _create_projections()
    _create_reservations()
    _create_fills()
    _create_operational_tables()
    _create_fact_guards()


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "sqlite":
        for table in FACT_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
    elif dialect == "postgresql":
        for table in FACT_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
    for table in (
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
    ):
        op.drop_table(table)
    if dialect == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS finance_god_prevent_fact_mutation()")


def _create_accounts() -> None:
    op.create_table(
        "simulation_accounts",
        sa.Column("account_id", sa.String(160), primary_key=True),
        sa.Column("owner_user_id", sa.String(160), nullable=False),
        sa.Column("initial_cash_rmb", MONEY, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("current", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("closed_at", UTC),
        sa.Column(
            "reset_from_account_id",
            sa.String(160),
            sa.ForeignKey("simulation_accounts.account_id"),
        ),
        sa.CheckConstraint(
            "initial_cash_rmb > 0", name="ck_account_initial_cash_positive"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_account_revision_positive"),
        sa.CheckConstraint(
            "status IN ('active','suspended','closed')",
            name="ck_account_status",
        ),
        sa.CheckConstraint(
            "(status = 'closed' AND current = false AND closed_at IS NOT NULL) OR "
            "(status <> 'closed' AND closed_at IS NULL)",
            name="ck_account_lifecycle",
        ),
    )
    op.create_index(
        "ix_simulation_accounts_owner_user_id",
        "simulation_accounts",
        ["owner_user_id"],
    )
    op.create_index(
        "uq_current_account_per_owner",
        "simulation_accounts",
        ["owner_user_id"],
        unique=True,
        sqlite_where=sa.text("current = 1"),
        postgresql_where=sa.text("current = true"),
    )


def _create_events() -> None:
    op.create_table(
        "account_events",
        sa.Column("event_id", sa.String(160), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(160),
            sa.ForeignKey("simulation_accounts.account_id"),
            nullable=False,
        ),
        sa.Column("owner_user_id", sa.String(160), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("occurred_at", UTC, nullable=False),
        sa.Column("correlation_id", sa.String(160), nullable=False),
        sa.Column("causation_id", sa.String(160), nullable=False),
        sa.Column("source_object_type", sa.String(80), nullable=False),
        sa.Column("source_object_id", sa.String(160), nullable=False),
        sa.Column("source_version", sa.String(80), nullable=False),
        sa.Column("rule_version", sa.String(80), nullable=False),
        sa.Column("previous_hash", sa.String(64)),
        sa.Column("event_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("payload_kind", sa.String(40), nullable=False),
        sa.Column("new_account_id", sa.String(160)),
        sa.Column("reservation_id", sa.String(160)),
        sa.Column("order_id", sa.String(160)),
        sa.Column("reservation_kind", sa.String(40)),
        sa.Column("trade_side", sa.String(16)),
        sa.Column("fund_action", sa.String(16)),
        sa.Column("instrument_id", sa.String(160)),
        sa.Column("native_currency", sa.String(3)),
        sa.Column("native_amount", MONEY),
        sa.Column("native_gross", MONEY),
        sa.Column("native_fee", MONEY),
        sa.Column("native_borrow_fee", MONEY),
        sa.Column("rmb_amount", MONEY),
        sa.Column("rmb_gross", MONEY),
        sa.Column("rmb_fee", MONEY),
        sa.Column("rmb_borrow_fee", MONEY),
        sa.Column("margin_change_rmb", MONEY),
        sa.Column("quantity", QUANTITY),
        sa.Column("nav", MONEY),
        sa.Column("slippage_bps", RATE),
        sa.Column("fx_base_currency", sa.String(3)),
        sa.Column("fx_quote_currency", sa.String(3)),
        sa.Column("fx_rate", RATE),
        sa.Column("fx_observed_at", UTC),
        sa.Column("fx_source_object_type", sa.String(80)),
        sa.Column("fx_source_object_id", sa.String(160)),
        sa.Column("fx_source_version", sa.String(80)),
        sa.Column("market_object_type", sa.String(80)),
        sa.Column("market_object_id", sa.String(160)),
        sa.Column("market_version", sa.String(80)),
        sa.Column("model_version", sa.String(80)),
        sa.Column("settled", sa.Boolean()),
        sa.Column("original_event_id", sa.String(160)),
        sa.Column("original_event_hash", sa.String(64)),
        sa.Column("correction_reason", sa.String(500)),
        sa.UniqueConstraint(
            "account_id", "sequence", name="uq_event_account_sequence"
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_event_sequence_positive"),
        sa.CheckConstraint(
            "event_type IN ('account_opened','account_reset_closed','cash_reserved',"
            "'cash_released','position_reserved','buy_fill_recorded',"
            "'sell_fill_recorded','short_fill_recorded','cover_fill_recorded',"
            "'fund_subscription_confirmed','fund_redemption_confirmed',"
            "'reversal_recorded')",
            name="ck_event_type",
        ),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_event_hash_length"),
        sa.CheckConstraint(
            "previous_hash IS NULL OR length(previous_hash) = 64",
            name="ck_previous_hash_length",
        ),
    )
    op.create_index("ix_account_events_account_id", "account_events", ["account_id"])


def _create_journals() -> None:
    op.create_table(
        "journal_entries",
        sa.Column("journal_id", sa.String(160), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(160),
            sa.ForeignKey("simulation_accounts.account_id"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            sa.String(160),
            sa.ForeignKey("account_events.event_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("occurred_at", UTC, nullable=False),
        sa.Column("rule_version", sa.String(80), nullable=False),
        sa.Column(
            "reversal_of_journal_id",
            sa.String(160),
            sa.ForeignKey("journal_entries.journal_id"),
        ),
        sa.Column("journal_hash", sa.String(64), nullable=False),
    )
    op.create_index(
        "ix_journal_entries_account_id", "journal_entries", ["account_id"]
    )
    op.create_table(
        "ledger_postings",
        sa.Column("posting_id", sa.String(160), primary_key=True),
        sa.Column(
            "journal_id",
            sa.String(160),
            sa.ForeignKey("journal_entries.journal_id"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("account_code", sa.String(80), nullable=False),
        sa.Column("original_currency", sa.String(3), nullable=False),
        sa.Column("original_amount", MONEY, nullable=False),
        sa.Column("rmb_amount", MONEY, nullable=False),
        sa.Column("posting_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "journal_id", "sequence", name="uq_posting_journal_sequence"
        ),
        sa.CheckConstraint(
            "sequence >= 1", name="ck_posting_sequence_positive"
        ),
    )
    op.create_index(
        "ix_ledger_postings_journal_id", "ledger_postings", ["journal_id"]
    )


def _create_projections() -> None:
    op.create_table(
        "account_projections",
        sa.Column(
            "account_id",
            sa.String(160),
            sa.ForeignKey("simulation_accounts.account_id"),
            primary_key=True,
        ),
        sa.Column("currency", sa.String(3), primary_key=True),
        sa.Column("total", MONEY, nullable=False),
        sa.Column("frozen", MONEY, nullable=False),
        sa.Column("margin", MONEY, nullable=False),
        sa.Column("rmb_total", MONEY, nullable=False),
        sa.Column("rmb_frozen", MONEY, nullable=False),
        sa.Column("rmb_margin", MONEY, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "total >= 0 AND frozen >= 0 AND margin >= 0",
            name="ck_cash_native_nonnegative",
        ),
        sa.CheckConstraint(
            "rmb_total >= 0 AND rmb_frozen >= 0 AND rmb_margin >= 0",
            name="ck_cash_rmb_nonnegative",
        ),
        sa.CheckConstraint(
            "frozen + margin <= total", name="ck_cash_native_allocated"
        ),
        sa.CheckConstraint(
            "rmb_frozen + rmb_margin <= rmb_total",
            name="ck_cash_rmb_allocated",
        ),
        sa.CheckConstraint("revision >= 0", name="ck_cash_revision"),
    )
    op.create_table(
        "position_projections",
        sa.Column(
            "account_id",
            sa.String(160),
            sa.ForeignKey("simulation_accounts.account_id"),
            primary_key=True,
        ),
        sa.Column("instrument_id", sa.String(160), primary_key=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("long_quantity", QUANTITY, nullable=False),
        sa.Column("short_quantity", QUANTITY, nullable=False),
        sa.Column("settled_quantity", QUANTITY, nullable=False),
        sa.Column("frozen_quantity", QUANTITY, nullable=False),
        sa.Column("long_cost_native", MONEY, nullable=False),
        sa.Column("long_cost_rmb", MONEY, nullable=False),
        sa.Column("short_proceeds_native", MONEY, nullable=False),
        sa.Column("short_proceeds_rmb", MONEY, nullable=False),
        sa.Column("margin_rmb", MONEY, nullable=False),
        sa.Column("borrow_fee_rmb", MONEY, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "long_quantity >= 0 AND short_quantity >= 0 "
            "AND settled_quantity >= 0 AND frozen_quantity >= 0",
            name="ck_position_quantities_nonnegative",
        ),
        sa.CheckConstraint(
            "frozen_quantity <= settled_quantity "
            "AND settled_quantity <= long_quantity",
            name="ck_position_quantity_relationships",
        ),
        sa.CheckConstraint(
            "long_cost_native >= 0 AND long_cost_rmb >= 0 "
            "AND short_proceeds_native >= 0 AND short_proceeds_rmb >= 0 "
            "AND margin_rmb >= 0 AND borrow_fee_rmb >= 0",
            name="ck_position_amounts_nonnegative",
        ),
        sa.CheckConstraint(
            "short_quantity <> 0 OR "
            "(short_proceeds_native = 0 AND short_proceeds_rmb = 0 "
            "AND margin_rmb = 0 AND borrow_fee_rmb = 0)",
            name="ck_position_closed_short_zero",
        ),
        sa.CheckConstraint("revision >= 0", name="ck_position_revision"),
    )


def _create_reservations() -> None:
    op.create_table(
        "reservations",
        sa.Column("reservation_id", sa.String(160), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(160),
            sa.ForeignKey("simulation_accounts.account_id"),
            nullable=False,
        ),
        sa.Column("order_id", sa.String(160), nullable=False),
        sa.Column("instrument_id", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("native_currency", sa.String(3), nullable=False),
        sa.Column("native_amount", MONEY, nullable=False),
        sa.Column("rmb_amount", MONEY, nullable=False),
        sa.Column("quantity", QUANTITY, nullable=False),
        sa.Column("consumed_native", MONEY, nullable=False),
        sa.Column("consumed_rmb", MONEY, nullable=False),
        sa.Column("consumed_quantity", QUANTITY, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "account_id", "order_id", name="uq_reservation_account_order"
        ),
        sa.CheckConstraint(
            "kind IN ('cash_buy','cash_cover','short_margin','fund_subscription',"
            "'fund_redemption')",
            name="ck_reservation_kind",
        ),
        sa.CheckConstraint(
            "status IN ('active','released','consumed')",
            name="ck_reservation_status",
        ),
        sa.CheckConstraint(
            "native_amount >= 0 AND rmb_amount >= 0 AND quantity >= 0 "
            "AND consumed_native >= 0 AND consumed_rmb >= 0 "
            "AND consumed_quantity >= 0",
            name="ck_reservation_nonnegative",
        ),
        sa.CheckConstraint(
            "consumed_native <= native_amount AND consumed_rmb <= rmb_amount "
            "AND consumed_quantity <= quantity",
            name="ck_reservation_consumption",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_reservation_revision"),
    )
    op.create_index(
        "ix_reservations_account_id", "reservations", ["account_id"]
    )


def _create_fills() -> None:
    op.create_table(
        "fills",
        sa.Column("fill_id", sa.String(160), primary_key=True),
        sa.Column(
            "event_id",
            sa.String(160),
            sa.ForeignKey("account_events.event_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "account_id",
            sa.String(160),
            sa.ForeignKey("simulation_accounts.account_id"),
            nullable=False,
        ),
        sa.Column("order_id", sa.String(160), nullable=False),
        sa.Column("reservation_id", sa.String(160)),
        sa.Column("instrument_id", sa.String(160), nullable=False),
        sa.Column("transaction_type", sa.String(40), nullable=False),
        sa.Column("quantity", QUANTITY, nullable=False),
        sa.Column("native_currency", sa.String(3), nullable=False),
        sa.Column("native_gross", MONEY, nullable=False),
        sa.Column("native_fee", MONEY, nullable=False),
        sa.Column("native_borrow_fee", MONEY, nullable=False),
        sa.Column("rmb_gross", MONEY, nullable=False),
        sa.Column("rmb_fee", MONEY, nullable=False),
        sa.Column("rmb_borrow_fee", MONEY, nullable=False),
        sa.Column("margin_change_rmb", MONEY, nullable=False),
        sa.Column("slippage_bps", RATE, nullable=False),
        sa.Column("fx_base_currency", sa.String(3)),
        sa.Column("fx_quote_currency", sa.String(3)),
        sa.Column("fx_rate", RATE),
        sa.Column("fx_observed_at", UTC),
        sa.Column("fx_source_object_type", sa.String(80)),
        sa.Column("fx_source_object_id", sa.String(160)),
        sa.Column("fx_source_version", sa.String(80)),
        sa.Column("market_object_type", sa.String(80), nullable=False),
        sa.Column("market_object_id", sa.String(160), nullable=False),
        sa.Column("market_version", sa.String(80), nullable=False),
        sa.Column("model_version", sa.String(80), nullable=False),
        sa.Column("rule_version", sa.String(80), nullable=False),
        sa.Column("occurred_at", UTC, nullable=False),
    )
    op.create_index("ix_fills_account_id", "fills", ["account_id"])


def _create_operational_tables() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column(
            "id", sa.Integer(), primary_key=True, autoincrement=True
        ),
        sa.Column("scope", sa.String(80), nullable=False),
        sa.Column("owner_user_id", sa.String(160), nullable=False),
        sa.Column("key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("result_reference", sa.String(160), nullable=False),
        sa.Column("created_at", UTC, nullable=False),
        sa.UniqueConstraint(
            "scope",
            "owner_user_id",
            "key",
            name="uq_idempotency_scope_owner_key",
        ),
    )
    op.create_table(
        "audit_records",
        sa.Column("audit_id", sa.String(160), primary_key=True),
        sa.Column("owner_user_id", sa.String(160), nullable=False),
        sa.Column(
            "account_id",
            sa.String(160),
            sa.ForeignKey("simulation_accounts.account_id"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            sa.String(160),
            sa.ForeignKey("account_events.event_id"),
        ),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("journal_hash", sa.String(64)),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("correlation_id", sa.String(160), nullable=False),
        sa.Column("occurred_at", UTC, nullable=False),
    )
    op.create_index("ix_audit_records_account_id", "audit_records", ["account_id"])
    op.create_index("ix_audit_records_event_id", "audit_records", ["event_id"])
    op.create_table(
        "outbox_messages",
        sa.Column("message_id", sa.String(160), primary_key=True),
        sa.Column("topic", sa.String(160), nullable=False),
        sa.Column("aggregate_id", sa.String(160), nullable=False),
        sa.Column(
            "event_id",
            sa.String(160),
            sa.ForeignKey("account_events.event_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", UTC, nullable=False),
        sa.Column("published_at", UTC),
    )
    op.create_table(
        "account_activities",
        sa.Column("activity_id", sa.String(160), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(160),
            sa.ForeignKey("simulation_accounts.account_id"),
            nullable=False,
        ),
        sa.Column("activity_type", sa.String(80), nullable=False),
        sa.Column("reference_id", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("opened_at", UTC, nullable=False),
        sa.Column("completed_at", UTC),
        sa.UniqueConstraint("reference_id", name="uq_activity_reference"),
        sa.CheckConstraint(
            "status IN ('open','completed','cancelled','failed')",
            name="ck_activity_status",
        ),
    )
    op.create_index(
        "ix_account_activities_account_id",
        "account_activities",
        ["account_id"],
    )


def _create_fact_guards() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "sqlite":
        for table in FACT_TABLES:
            op.execute(
                f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'append-only fact table'); END"
            )
            op.execute(
                f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'append-only fact table'); END"
            )
    elif dialect == "postgresql":
        op.execute(
            "CREATE OR REPLACE FUNCTION finance_god_prevent_fact_mutation() "
            "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
            "RAISE EXCEPTION 'append-only fact table'; END $$"
        )
        for table in FACT_TABLES:
            op.execute(
                f"CREATE TRIGGER {table}_no_mutation "
                f"BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW "
                "EXECUTE FUNCTION finance_god_prevent_fact_mutation()"
            )
