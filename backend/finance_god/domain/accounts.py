from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from .errors import DomainInvariantViolation
from .ledger import canonical_money, canonical_utc
from .models import FrozenModel


class AccountStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class SimulationAccount(FrozenModel):
    account_id: str = Field(min_length=1, max_length=160)
    owner_user_id: str = Field(min_length=1, max_length=160)
    initial_cash_rmb: Decimal = Field(gt=0)
    status: AccountStatus = AccountStatus.ACTIVE
    current: bool = True
    revision: int = Field(default=1, ge=1)
    created_at: AwareDatetime
    closed_at: AwareDatetime | None = None
    reset_from_account_id: str | None = None

    @field_validator("initial_cash_rmb")
    @classmethod
    def normalize_initial_cash(cls, value: Decimal) -> Decimal:
        return canonical_money(value, "initial_cash_rmb")

    @field_validator("created_at", "closed_at")
    @classmethod
    def normalize_times(cls, value: datetime | None) -> datetime | None:
        return canonical_utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        if self.current and self.status is AccountStatus.CLOSED:
            raise DomainInvariantViolation("a closed account cannot be current")
        if self.status is AccountStatus.CLOSED and self.closed_at is None:
            raise DomainInvariantViolation("a closed account requires closed_at")
        if self.status is not AccountStatus.CLOSED and self.closed_at is not None:
            raise DomainInvariantViolation("only a closed account may have closed_at")
        return self

    def close_for_reset(self, *, closed_at: datetime) -> SimulationAccount:
        if self.status is not AccountStatus.ACTIVE or not self.current:
            raise DomainInvariantViolation("only the current active account can be reset")
        return SimulationAccount.model_validate(
            {
                **self.model_dump(mode="python"),
                "status": AccountStatus.CLOSED,
                "current": False,
                "revision": self.revision + 1,
                "closed_at": closed_at,
            }
        )
