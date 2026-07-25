"""backfill clocks for simulation accounts created before clock support

Revision ID: 20260725_0022
Revises: 20260725_0021
"""

from alembic import op

revision = "20260725_0022"
down_revision = "20260725_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(
            """
            INSERT INTO simulation_clocks (
                account_id,
                simulation_start_at,
                real_anchor_at,
                status,
                paused_at,
                timezone,
                speed,
                revision,
                last_resume_key
            )
            SELECT
                account.account_id,
                datetime(
                    account.created_at,
                    CASE strftime('%w', account.created_at)
                        WHEN '6' THEN '-1 day'
                        WHEN '0' THEN '-2 days'
                        ELSE '+0 days'
                    END,
                    'start of day',
                    '+9 hours',
                    '+31 minutes'
                ),
                CURRENT_TIMESTAMP,
                'running',
                NULL,
                'Asia/Shanghai',
                1,
                1,
                NULL
            FROM simulation_accounts AS account
            LEFT JOIN simulation_clocks AS clock
                ON clock.account_id = account.account_id
            WHERE clock.account_id IS NULL
            """
        )
        return

    op.execute(
        """
        INSERT INTO simulation_clocks (
            account_id,
            simulation_start_at,
            real_anchor_at,
            status,
            paused_at,
            timezone,
            speed,
            revision,
            last_resume_key
        )
        SELECT
            account.account_id,
            (
                date_trunc(
                    'day',
                    account.created_at AT TIME ZONE 'Asia/Shanghai'
                    - CASE EXTRACT(ISODOW FROM account.created_at AT TIME ZONE 'Asia/Shanghai')
                        WHEN 6 THEN INTERVAL '1 day'
                        WHEN 7 THEN INTERVAL '2 days'
                        ELSE INTERVAL '0 days'
                    END
                ) + INTERVAL '9 hours 31 minutes'
            ) AT TIME ZONE 'Asia/Shanghai',
            CURRENT_TIMESTAMP,
            'running',
            NULL,
            'Asia/Shanghai',
            1,
            1,
            NULL
        FROM simulation_accounts AS account
        LEFT JOIN simulation_clocks AS clock
            ON clock.account_id = account.account_id
        WHERE clock.account_id IS NULL
        """
    )


def downgrade() -> None:
    # Historical account clocks become normal business state after creation.
    # Removing them would make existing accounts unreadable, so downgrade is non-destructive.
    pass
