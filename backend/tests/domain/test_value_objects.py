from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import ValidationError

from finance_god.domain import (
    AccountStatus,
    DomainInvariantViolation,
    JournalEntry,
    LedgerPosting,
    Money,
    SimulationAccount,
    VersionReference,
)

NOW = datetime(2026, 7, 23, tzinfo=timezone.utc)


class ValueObjectTest(unittest.TestCase):
    def test_simulation_account_requires_positive_initial_cash_and_is_frozen(
        self,
    ) -> None:
        with self.assertRaises(ValidationError):
            account(initial_cash=Decimal("0"))

        created = account()
        with self.assertRaises(ValidationError):
            setattr(created, "initial_cash_rmb", Decimal("200000"))

    def test_account_identity_carries_owner_current_and_revision(self) -> None:
        original = account()
        closed = original.close_for_reset(closed_at=NOW)
        self.assertEqual(original.owner_user_id, "user-1")
        self.assertTrue(original.current)
        self.assertFalse(closed.current)
        self.assertEqual(closed.revision, 2)

    def test_journal_rejects_unbalanced_original_or_rmb_amounts(self) -> None:
        with self.assertRaises(DomainInvariantViolation):
            JournalEntry.create(
                journal_id="journal-1",
                account_id="account-1",
                event_id="event-1",
                occurred_at=NOW,
                rule_version="simulation-rules-v1",
                postings=(
                    LedgerPosting.create(
                        posting_id="p1",
                        sequence=1,
                        account_code="cash",
                        original=Money(currency="CNY", amount=Decimal("100")),
                        rmb_amount=Decimal("100"),
                    ),
                    LedgerPosting.create(
                        posting_id="p2",
                        sequence=2,
                        account_code="equity",
                        original=Money(currency="CNY", amount=Decimal("-99")),
                        rmb_amount=Decimal("-99"),
                    ),
                ),
            )

        balanced = JournalEntry.create(
            journal_id="journal-2",
            account_id="account-1",
            event_id="event-2",
            occurred_at=NOW,
            rule_version="simulation-rules-v1",
            postings=(
                LedgerPosting.create(
                    posting_id="p3",
                    sequence=1,
                    account_code="cash",
                    original=Money(currency="CNY", amount=Decimal("100")),
                    rmb_amount=Decimal("100"),
                ),
                LedgerPosting.create(
                    posting_id="p4",
                    sequence=2,
                    account_code="equity",
                    original=Money(currency="CNY", amount=Decimal("-100")),
                    rmb_amount=Decimal("-100"),
                ),
            ),
        )
        self.assertEqual(sum(p.rmb_amount for p in balanced.postings), Decimal("0"))

    def test_string_fields_are_trimmed_and_blank_values_are_rejected(self) -> None:
        reference = VersionReference(
            object_type=" market_snapshot ",
            object_id=" 600519.SSE ",
            version=" 1 ",
        )
        self.assertEqual(reference.object_type, "market_snapshot")
        self.assertEqual(reference.object_id, "600519.SSE")
        self.assertEqual(reference.version, "1")

        with self.assertRaises(DomainInvariantViolation):
            VersionReference(
                object_type=" ",
                object_id="600519.SSE",
                version="1",
            )


def account(initial_cash: Decimal = Decimal("100000")) -> SimulationAccount:
    return SimulationAccount(
        account_id="account-1",
        owner_user_id="user-1",
        initial_cash_rmb=initial_cash,
        status=AccountStatus.ACTIVE,
        current=True,
        revision=1,
        created_at=NOW,
        reset_from_account_id=None,
    )


if __name__ == "__main__":
    unittest.main()
