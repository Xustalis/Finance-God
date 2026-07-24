from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Annotated, Any, ClassVar, Mapping, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from .errors import DomainInvariantViolation, InvalidStateTransition

PositiveDecimal = Annotated[Decimal, Field(gt=0)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]


def _clean_string_tuple(values: object) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise DomainInvariantViolation("expected a sequence of strings")
    cleaned: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise DomainInvariantViolation("expected a sequence of strings")
        stripped = value.strip()
        if not stripped:
            raise DomainInvariantViolation("string items cannot be blank")
        cleaned.append(stripped)
    return tuple(cleaned)


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainInvariantViolation(f"{field_name} must be timezone-aware")


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def strip_string_fields(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            raise DomainInvariantViolation("string fields cannot be blank")
        return stripped


class VersionReference(FrozenModel):
    object_type: str = Field(min_length=1, max_length=80)
    object_id: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=80)

    @property
    def identity(self) -> tuple[str, str]:
        return self.object_type, self.object_id


class AuditReference(FrozenModel):
    audit_id: str = Field(min_length=1, max_length=160)
    actor_id: str = Field(min_length=1, max_length=160)
    recorded_at: AwareDatetime


class VersionedState(FrozenModel):
    revision: int = Field(ge=1)
    status: Enum
    audit_reference: AuditReference

    TRANSITIONS: ClassVar[Mapping[Any, frozenset[Any]]]

    def _ensure_transition(self, target: Enum) -> None:
        if target not in self.TRANSITIONS[self.status]:
            raise InvalidStateTransition(type(self).__name__, self.status, target)

    def _replace(self, **changes: object) -> Self:
        values = self.model_dump(exclude_computed_fields=True)
        values.update(changes)
        return type(self).model_validate(values)

    def _ensure_new_audit(self, audit_reference: AuditReference) -> None:
        if audit_reference.audit_id == self.audit_reference.audit_id:
            raise DomainInvariantViolation(
                "a new version requires a new audit reference"
            )
        if audit_reference.recorded_at <= self.audit_reference.recorded_at:
            raise DomainInvariantViolation(
                "a new version audit must be later than the current audit"
            )

    def _transition(
        self,
        target: Enum,
        *,
        audit_reference: AuditReference,
        **changes: object,
    ) -> Self:
        self._ensure_transition(target)
        self._ensure_new_audit(audit_reference)
        return self._replace(
            status=target,
            revision=self.revision + 1,
            audit_reference=audit_reference,
            **changes,
        )


class InputVersionedState(VersionedState):
    input_versions: tuple[VersionReference, ...] = Field(min_length=1)
    invalidated_by_versions: tuple[VersionReference, ...] = ()

    @field_validator("input_versions", "invalidated_by_versions")
    @classmethod
    def canonicalize_versions(
        cls, references: tuple[VersionReference, ...]
    ) -> tuple[VersionReference, ...]:
        ordered = tuple(
            sorted(
                references,
                key=lambda item: (item.object_type, item.object_id, item.version),
            )
        )
        identities = [item.identity for item in ordered]
        if len(identities) != len(set(identities)):
            raise DomainInvariantViolation(
                "an input snapshot cannot reference two versions of the same object"
            )
        return ordered

    def _expire_if_inputs_changed(
        self,
        current_input_versions: tuple[VersionReference, ...],
        expired_status: Enum,
        audit_reference: AuditReference,
    ) -> Self:
        current = self.canonicalize_versions(current_input_versions)
        if current == self.input_versions:
            return self
        if self.status == expired_status:
            return self
        return self._transition(
            expired_status,
            audit_reference=audit_reference,
            invalidated_by_versions=current,
        )


class WorkflowRunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    ATTENTION_REQUIRED = "attention_required"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    BLOCKED = "blocked"
    EXPIRED = "expired"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"


class WorkflowBlockReason(str, Enum):
    USER_PAUSED = "user_paused"
    HARD_RISK = "hard_risk"


class WorkflowCancellationReason(str, Enum):
    USER_PAUSED = "user_paused"


NON_TRADING_WORKFLOWS = frozenset({"review_only", "data_quality_review"})
WORKFLOW_OUTPUT_RECORDING_STATUSES = frozenset(
    {
        WorkflowRunStatus.RUNNING,
        WorkflowRunStatus.CANCEL_REQUESTED,
        WorkflowRunStatus.CANCELLING,
    }
)


class WorkflowDependencySnapshot(FrozenModel):
    run_reference: VersionReference
    workflow_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    workflow_version: str = Field(min_length=1, max_length=80)
    status: WorkflowRunStatus
    trade_eligible: bool
    final_artifact: VersionReference
    evidence_references: tuple[VersionReference, ...] = Field(min_length=1)
    node_contribution_references: tuple[VersionReference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_trade_dependency(self) -> Self:
        if self.status is not WorkflowRunStatus.COMPLETED or not self.trade_eligible:
            raise DomainInvariantViolation(
                "trade plan dependencies must be completed and trade eligible"
            )
        if self.workflow_key in NON_TRADING_WORKFLOWS:
            raise DomainInvariantViolation(
                f"{self.workflow_key} cannot be a trade plan dependency"
            )
        return self


class TradePlanStatus(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    CONFIRMED = "confirmed"
    EXECUTING = "executing"
    PARTIALLY_COMPLETED = "partially_completed"
    COMPLETED = "completed"
    EXPIRED = "expired"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


TRADE_PLAN_TRANSITIONS: Mapping[TradePlanStatus, frozenset[TradePlanStatus]] = (
    MappingProxyType(
        {
            TradePlanStatus.DRAFT: frozenset(
                {
                    TradePlanStatus.PENDING_REVIEW,
                    TradePlanStatus.EXPIRED,
                    TradePlanStatus.REJECTED,
                    TradePlanStatus.CANCELLED,
                }
            ),
            TradePlanStatus.PENDING_REVIEW: frozenset(
                {
                    TradePlanStatus.DRAFT,
                    TradePlanStatus.CONFIRMED,
                    TradePlanStatus.EXPIRED,
                    TradePlanStatus.REJECTED,
                    TradePlanStatus.CANCELLED,
                }
            ),
            TradePlanStatus.CONFIRMED: frozenset(
                {
                    TradePlanStatus.EXECUTING,
                    TradePlanStatus.EXPIRED,
                    TradePlanStatus.REJECTED,
                    TradePlanStatus.CANCELLED,
                }
            ),
            TradePlanStatus.EXECUTING: frozenset(
                {
                    TradePlanStatus.PARTIALLY_COMPLETED,
                    TradePlanStatus.COMPLETED,
                    TradePlanStatus.EXPIRED,
                    TradePlanStatus.CANCELLED,
                }
            ),
            TradePlanStatus.PARTIALLY_COMPLETED: frozenset(
                {
                    TradePlanStatus.COMPLETED,
                    TradePlanStatus.EXPIRED,
                    TradePlanStatus.CANCELLED,
                }
            ),
            TradePlanStatus.COMPLETED: frozenset(),
            TradePlanStatus.EXPIRED: frozenset(),
            TradePlanStatus.REJECTED: frozenset(),
            TradePlanStatus.CANCELLED: frozenset(),
        }
    )
)


class TradePlanAction(FrozenModel):
    """One structured proposed order inside a versioned trade plan."""

    action_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    side: str = Field(pattern=r"^(buy|sell)$")
    order_type: str = Field(default="market", pattern=r"^(market|limit)$")
    quantity: PositiveDecimal | None = None
    limit_price: PositiveDecimal | None = None
    reference_price: PositiveDecimal | None = None
    time_in_force: str = Field(
        default="day",
        pattern=r"^(day|good_til_cancelled|immediate_or_cancel)$",
    )
    included: bool = True
    rationale: str = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_order_parameters(self) -> Self:
        if self.order_type == "limit" and self.limit_price is None:
            raise DomainInvariantViolation("a limit plan action requires limit_price")
        if self.order_type != "limit" and self.limit_price is not None:
            raise DomainInvariantViolation(
                "limit_price belongs only to a limit plan action"
            )
        return self


class TradePlan(InputVersionedState):
    plan_id: str = Field(min_length=1, max_length=160)
    account_id: str = Field(min_length=1, max_length=160)
    status: TradePlanStatus
    purpose: str = Field(min_length=1, max_length=1000)
    actions: tuple[TradePlanAction, ...] = Field(min_length=1)
    estimated_fee_rmb: NonNegativeDecimal
    portfolio_impact: str = Field(min_length=1, max_length=2000)
    disagreements: tuple[str, ...]
    workflow_dependencies: tuple[WorkflowDependencySnapshot, ...] = ()
    expires_at: AwareDatetime

    TRANSITIONS = TRADE_PLAN_TRANSITIONS

    @field_validator("disagreements", mode="before")
    @classmethod
    def clean_text_items(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_string_tuple(values)

    @model_validator(mode="after")
    def validate_initial_expiry(self) -> Self:
        action_ids = [action.action_id for action in self.actions]
        if len(action_ids) != len(set(action_ids)):
            raise DomainInvariantViolation("trade plan action ids must be unique")
        if self.revision == 1 and self.expires_at <= self.audit_reference.recorded_at:
            raise DomainInvariantViolation(
                "trade plan expiry must be later than its creation audit"
            )
        return self

    def revise(
        self,
        *,
        actions: tuple[TradePlanAction, ...],
        input_versions: tuple[VersionReference, ...],
        estimated_fee_rmb: Decimal,
        portfolio_impact: str,
        audit_reference: AuditReference,
    ) -> TradePlan:
        if self.status not in {
            TradePlanStatus.DRAFT,
            TradePlanStatus.PENDING_REVIEW,
        }:
            raise DomainInvariantViolation(
                "only a draft or pending trade plan can be revised"
            )
        if audit_reference.recorded_at >= self.expires_at:
            raise DomainInvariantViolation("an expired trade plan cannot be revised")
        self._ensure_new_audit(audit_reference)
        return self._replace(
            revision=self.revision + 1,
            status=TradePlanStatus.PENDING_REVIEW,
            actions=actions,
            input_versions=input_versions,
            estimated_fee_rmb=estimated_fee_rmb,
            portfolio_impact=portfolio_impact,
            audit_reference=audit_reference,
        )

    def transition(
        self, target: TradePlanStatus, *, audit_reference: AuditReference
    ) -> TradePlan:
        if target is TradePlanStatus.EXPIRED:
            raise DomainInvariantViolation(
                "use an explicit trade plan expiration operation"
            )
        pre_execution_statuses = {
            TradePlanStatus.DRAFT,
            TradePlanStatus.PENDING_REVIEW,
            TradePlanStatus.CONFIRMED,
        }
        if (
            self.status in pre_execution_statuses
            and audit_reference.recorded_at >= self.expires_at
        ):
            raise DomainInvariantViolation(
                "an expired trade plan cannot advance toward execution"
            )
        return self._transition(target, audit_reference=audit_reference)

    def expire_if_inputs_changed(
        self,
        current_input_versions: tuple[VersionReference, ...],
        *,
        audit_reference: AuditReference,
    ) -> TradePlan:
        return self._expire_if_inputs_changed(
            current_input_versions,
            TradePlanStatus.EXPIRED,
            audit_reference,
        )

    def expire_at(self, now: datetime, *, audit_reference: AuditReference) -> TradePlan:
        _require_aware_datetime(now, "now")
        if self.status is TradePlanStatus.EXPIRED:
            return self
        if now < self.expires_at:
            raise DomainInvariantViolation("trade plan has not reached its expiry")
        if audit_reference.recorded_at < now:
            raise DomainInvariantViolation(
                "expiry audit cannot precede the evaluated time"
            )
        return self._transition(
            TradePlanStatus.EXPIRED,
            audit_reference=audit_reference,
        )


class OrderDraftStatus(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


ORDER_DRAFT_TRANSITIONS: Mapping[OrderDraftStatus, frozenset[OrderDraftStatus]] = (
    MappingProxyType(
        {
            OrderDraftStatus.DRAFT: frozenset(
                {
                    OrderDraftStatus.PENDING_REVIEW,
                    OrderDraftStatus.EXPIRED,
                    OrderDraftStatus.CANCELLED,
                }
            ),
            OrderDraftStatus.PENDING_REVIEW: frozenset(
                {
                    OrderDraftStatus.DRAFT,
                    OrderDraftStatus.CONFIRMED,
                    OrderDraftStatus.EXPIRED,
                    OrderDraftStatus.CANCELLED,
                }
            ),
            OrderDraftStatus.CONFIRMED: frozenset({OrderDraftStatus.EXPIRED}),
            OrderDraftStatus.EXPIRED: frozenset(),
            OrderDraftStatus.CANCELLED: frozenset(),
        }
    )
)


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"
    SHORT = "short"
    COVER = "cover"
    SUBSCRIBE = "subscribe"
    REDEEM = "redeem"
    CONVERT = "convert"
    RECURRING_INVEST = "recurring_invest"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    FUND = "fund"


class TimeInForce(str, Enum):
    DAY = "day"
    GOOD_TIL_CANCELLED = "good_til_cancelled"
    IMMEDIATE_OR_CANCEL = "immediate_or_cancel"


EXCHANGE_ORDER_SIDES = frozenset(
    {OrderSide.BUY, OrderSide.SELL, OrderSide.SHORT, OrderSide.COVER}
)
FUND_ORDER_SIDES = frozenset(
    {
        OrderSide.SUBSCRIBE,
        OrderSide.REDEEM,
        OrderSide.CONVERT,
        OrderSide.RECURRING_INVEST,
    }
)
FUND_AMOUNT_SIDES = frozenset({OrderSide.SUBSCRIBE, OrderSide.RECURRING_INVEST})
FUND_UNIT_SIDES = frozenset({OrderSide.REDEEM, OrderSide.CONVERT})


class OrderDraft(InputVersionedState):
    draft_id: str = Field(min_length=1, max_length=160)
    status: OrderDraftStatus
    account_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    side: OrderSide
    order_type: OrderType
    quantity: PositiveDecimal | None
    amount: PositiveDecimal | None = None
    limit_price: PositiveDecimal | None
    time_in_force: TimeInForce | None
    fund_rule_version: VersionReference | None = None
    valid_until: AwareDatetime

    TRANSITIONS = ORDER_DRAFT_TRANSITIONS

    @model_validator(mode="after")
    def validate_parameters(self) -> Self:
        if (self.quantity is None) == (self.amount is None):
            raise DomainInvariantViolation(
                "an order draft requires exactly one of quantity or amount"
            )
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise DomainInvariantViolation("a limit order requires limit_price")
        if self.order_type is not OrderType.LIMIT and self.limit_price is not None:
            raise DomainInvariantViolation("limit_price belongs only to a limit order")
        if self.order_type in {OrderType.MARKET, OrderType.LIMIT}:
            self._validate_exchange_parameters()
        else:
            self._validate_fund_parameters()
        if (
            self.status is not OrderDraftStatus.EXPIRED
            and self.valid_until <= self.audit_reference.recorded_at
        ):
            raise DomainInvariantViolation("order draft validity must be in the future")
        return self

    def _validate_exchange_parameters(self) -> None:
        if self.side not in EXCHANGE_ORDER_SIDES:
            raise DomainInvariantViolation("exchange orders require an exchange side")
        if self.quantity is None or self.amount is not None:
            raise DomainInvariantViolation("exchange orders require quantity")
        if self.time_in_force is None:
            raise DomainInvariantViolation("exchange orders require time_in_force")
        if self.fund_rule_version is not None:
            raise DomainInvariantViolation(
                "fund_rule_version belongs only to fund orders"
            )

    def _validate_fund_parameters(self) -> None:
        if self.side not in FUND_ORDER_SIDES:
            raise DomainInvariantViolation("fund orders require a fund side")
        if self.time_in_force is not None:
            raise DomainInvariantViolation(
                "time_in_force belongs only to exchange orders"
            )
        if self.fund_rule_version is None:
            raise DomainInvariantViolation("fund orders require fund_rule_version")
        if self.side in FUND_AMOUNT_SIDES and self.amount is None:
            raise DomainInvariantViolation("this fund operation requires amount")
        if self.side in FUND_UNIT_SIDES and self.quantity is None:
            raise DomainInvariantViolation("this fund operation requires quantity")

    def transition(
        self, target: OrderDraftStatus, *, audit_reference: AuditReference
    ) -> OrderDraft:
        return self._transition(target, audit_reference=audit_reference)

    def expire_if_inputs_changed(
        self,
        current_input_versions: tuple[VersionReference, ...],
        *,
        audit_reference: AuditReference,
    ) -> OrderDraft:
        return self._expire_if_inputs_changed(
            current_input_versions,
            OrderDraftStatus.EXPIRED,
            audit_reference,
        )

    def expire_at(
        self, now: datetime, *, audit_reference: AuditReference
    ) -> OrderDraft:
        _require_aware_datetime(now, "now")
        if self.status is OrderDraftStatus.EXPIRED:
            return self
        if now < self.valid_until:
            raise DomainInvariantViolation("order draft has not reached its expiry")
        if audit_reference.recorded_at < now:
            raise DomainInvariantViolation(
                "expiry audit cannot precede the evaluated time"
            )
        return self._transition(
            OrderDraftStatus.EXPIRED,
            audit_reference=audit_reference,
        )


class ExchangeOrderStatus(str, Enum):
    SUBMITTING = "submitting"
    UNKNOWN = "unknown"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


EXCHANGE_ORDER_TRANSITIONS: Mapping[
    ExchangeOrderStatus, frozenset[ExchangeOrderStatus]
] = MappingProxyType(
    {
        ExchangeOrderStatus.SUBMITTING: frozenset(
            {
                ExchangeOrderStatus.UNKNOWN,
                ExchangeOrderStatus.ACCEPTED,
                ExchangeOrderStatus.REJECTED,
            }
        ),
        ExchangeOrderStatus.UNKNOWN: frozenset(
            {
                ExchangeOrderStatus.ACCEPTED,
                ExchangeOrderStatus.PARTIALLY_FILLED,
                ExchangeOrderStatus.FILLED,
                ExchangeOrderStatus.CANCELLED,
                ExchangeOrderStatus.REJECTED,
                ExchangeOrderStatus.EXPIRED,
            }
        ),
        ExchangeOrderStatus.ACCEPTED: frozenset(
            {
                ExchangeOrderStatus.PARTIALLY_FILLED,
                ExchangeOrderStatus.FILLED,
                ExchangeOrderStatus.CANCELLING,
                ExchangeOrderStatus.EXPIRED,
            }
        ),
        ExchangeOrderStatus.PARTIALLY_FILLED: frozenset(
            {
                ExchangeOrderStatus.FILLED,
                ExchangeOrderStatus.CANCELLING,
                ExchangeOrderStatus.EXPIRED,
            }
        ),
        ExchangeOrderStatus.FILLED: frozenset(),
        ExchangeOrderStatus.CANCELLING: frozenset(
            {
                ExchangeOrderStatus.UNKNOWN,
                ExchangeOrderStatus.PARTIALLY_FILLED,
                ExchangeOrderStatus.FILLED,
                ExchangeOrderStatus.CANCELLED,
            }
        ),
        ExchangeOrderStatus.CANCELLED: frozenset(),
        ExchangeOrderStatus.REJECTED: frozenset(),
        ExchangeOrderStatus.EXPIRED: frozenset(),
    }
)


def derive_exchange_fill_status(
    order_quantity: Decimal, cumulative_filled: Decimal
) -> ExchangeOrderStatus:
    if order_quantity <= 0:
        raise DomainInvariantViolation("order quantity must be positive")
    if cumulative_filled < 0:
        raise DomainInvariantViolation("cumulative fill cannot be negative")
    if cumulative_filled > order_quantity:
        raise DomainInvariantViolation("cumulative fill cannot exceed order quantity")
    if cumulative_filled == order_quantity:
        return ExchangeOrderStatus.FILLED
    if cumulative_filled > 0:
        return ExchangeOrderStatus.PARTIALLY_FILLED
    return ExchangeOrderStatus.ACCEPTED


class ExchangeOrder(VersionedState):
    order_id: str = Field(min_length=1, max_length=160)
    status: ExchangeOrderStatus
    idempotency_key: str = Field(min_length=1, max_length=160)
    draft_reference: VersionReference
    quantity: PositiveDecimal
    cumulative_filled: NonNegativeDecimal

    TRANSITIONS = EXCHANGE_ORDER_TRANSITIONS

    @model_validator(mode="after")
    def validate_fill_state(self) -> Self:
        if self.cumulative_filled > self.quantity:
            raise DomainInvariantViolation(
                "cumulative fill cannot exceed order quantity"
            )
        zero_fill_statuses = {
            ExchangeOrderStatus.SUBMITTING,
            ExchangeOrderStatus.UNKNOWN,
            ExchangeOrderStatus.ACCEPTED,
            ExchangeOrderStatus.REJECTED,
        }
        if self.status in zero_fill_statuses and self.cumulative_filled != 0:
            raise DomainInvariantViolation(
                f"{self.status.value} order cannot carry a confirmed fill"
            )
        if (
            self.status is ExchangeOrderStatus.FILLED
            and self.cumulative_filled != self.quantity
        ):
            raise DomainInvariantViolation("filled order must have its full quantity")
        if (
            self.status is ExchangeOrderStatus.PARTIALLY_FILLED
            and not 0 < self.cumulative_filled < self.quantity
        ):
            raise DomainInvariantViolation(
                "partially filled order must have a partial cumulative fill"
            )
        incomplete_statuses = {
            ExchangeOrderStatus.CANCELLING,
            ExchangeOrderStatus.CANCELLED,
            ExchangeOrderStatus.EXPIRED,
        }
        if (
            self.status in incomplete_statuses
            and self.cumulative_filled >= self.quantity
        ):
            raise DomainInvariantViolation(
                f"{self.status.value} order cannot carry a full fill"
            )
        return self

    def transition(
        self, target: ExchangeOrderStatus, *, audit_reference: AuditReference
    ) -> ExchangeOrder:
        return self._transition(target, audit_reference=audit_reference)

    def record_fill(
        self, fill_quantity: Decimal, *, audit_reference: AuditReference
    ) -> ExchangeOrder:
        if fill_quantity <= 0:
            raise DomainInvariantViolation("fill quantity must be positive")
        cumulative = self.cumulative_filled + fill_quantity
        target = derive_exchange_fill_status(self.quantity, cumulative)
        self._ensure_transition(target)
        self._ensure_new_audit(audit_reference)
        return self._replace(
            status=target,
            revision=self.revision + 1,
            cumulative_filled=cumulative,
            audit_reference=audit_reference,
        )


class FundOrderStatus(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    PENDING_NAV = "pending_nav"
    CONFIRMING = "confirming"
    CONFIRMED = "confirmed"
    PARTIALLY_CONFIRMED = "partially_confirmed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


FUND_ORDER_TRANSITIONS: Mapping[FundOrderStatus, frozenset[FundOrderStatus]] = (
    MappingProxyType(
        {
            FundOrderStatus.DRAFT: frozenset(
                {
                    FundOrderStatus.PENDING_REVIEW,
                    FundOrderStatus.CANCELLED,
                    FundOrderStatus.REJECTED,
                }
            ),
            FundOrderStatus.PENDING_REVIEW: frozenset(
                {
                    FundOrderStatus.DRAFT,
                    FundOrderStatus.SUBMITTED,
                    FundOrderStatus.CANCELLED,
                    FundOrderStatus.REJECTED,
                }
            ),
            FundOrderStatus.SUBMITTED: frozenset(
                {
                    FundOrderStatus.ACCEPTED,
                    FundOrderStatus.CANCELLED,
                    FundOrderStatus.REJECTED,
                }
            ),
            FundOrderStatus.ACCEPTED: frozenset(
                {
                    FundOrderStatus.PENDING_NAV,
                    FundOrderStatus.CANCELLED,
                    FundOrderStatus.REJECTED,
                }
            ),
            FundOrderStatus.PENDING_NAV: frozenset(
                {
                    FundOrderStatus.CONFIRMING,
                    FundOrderStatus.CANCELLED,
                    FundOrderStatus.REJECTED,
                }
            ),
            FundOrderStatus.CONFIRMING: frozenset(
                {
                    FundOrderStatus.CONFIRMED,
                    FundOrderStatus.PARTIALLY_CONFIRMED,
                    FundOrderStatus.REJECTED,
                }
            ),
            FundOrderStatus.CONFIRMED: frozenset(),
            FundOrderStatus.PARTIALLY_CONFIRMED: frozenset(),
            FundOrderStatus.CANCELLED: frozenset(),
            FundOrderStatus.REJECTED: frozenset(),
        }
    )
)


class FundOrder(VersionedState):
    order_id: str = Field(min_length=1, max_length=160)
    status: FundOrderStatus
    idempotency_key: str = Field(min_length=1, max_length=160)
    draft_reference: VersionReference
    requested_amount: PositiveDecimal | None
    requested_units: PositiveDecimal | None

    TRANSITIONS = FUND_ORDER_TRANSITIONS

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if (self.requested_amount is None) == (self.requested_units is None):
            raise DomainInvariantViolation(
                "a fund order requires exactly one of requested amount or units"
            )
        return self

    def transition(
        self, target: FundOrderStatus, *, audit_reference: AuditReference
    ) -> FundOrder:
        return self._transition(target, audit_reference=audit_reference)


class RiskCheckStatus(str, Enum):
    CHECKING = "checking"
    PASSED = "passed"
    CONFIRMATION_REQUIRED = "confirmation_required"
    BLOCKED = "blocked"
    EXPIRED = "expired"


class RiskSeverity(str, Enum):
    SOFT = "soft"
    HARD = "hard"


class RiskReason(FrozenModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    severity: RiskSeverity
    message: str = Field(min_length=1, max_length=1000)


RISK_CHECK_TRANSITIONS: Mapping[RiskCheckStatus, frozenset[RiskCheckStatus]] = (
    MappingProxyType(
        {
            RiskCheckStatus.CHECKING: frozenset(
                {
                    RiskCheckStatus.PASSED,
                    RiskCheckStatus.CONFIRMATION_REQUIRED,
                    RiskCheckStatus.BLOCKED,
                    RiskCheckStatus.EXPIRED,
                }
            ),
            RiskCheckStatus.PASSED: frozenset({RiskCheckStatus.EXPIRED}),
            RiskCheckStatus.CONFIRMATION_REQUIRED: frozenset({RiskCheckStatus.EXPIRED}),
            RiskCheckStatus.BLOCKED: frozenset({RiskCheckStatus.EXPIRED}),
            RiskCheckStatus.EXPIRED: frozenset(),
        }
    )
)


class RiskCheckResult(InputVersionedState):
    risk_check_id: str = Field(min_length=1, max_length=160)
    status: RiskCheckStatus
    order_version: VersionReference
    rule_version: VersionReference
    reasons: tuple[RiskReason, ...]
    checked_at: AwareDatetime
    expires_at: AwareDatetime
    soft_confirmation: AuditReference | None = None

    TRANSITIONS = RISK_CHECK_TRANSITIONS

    @computed_field
    @property
    def reason_hash(self) -> str:
        payload = "|".join(
            f"{reason.code}:{reason.severity.value}:{reason.message}"
            for reason in self.reasons
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        severities = {reason.severity for reason in self.reasons}
        hard_reason_statuses = {
            RiskCheckStatus.BLOCKED,
            RiskCheckStatus.EXPIRED,
        }
        if RiskSeverity.HARD in severities and self.status not in hard_reason_statuses:
            raise DomainInvariantViolation(
                "hard risk reasons require blocked or expired status"
            )
        if (
            self.status is RiskCheckStatus.BLOCKED
            and RiskSeverity.HARD not in severities
        ):
            raise DomainInvariantViolation(
                "a blocked risk result requires a hard reason"
            )
        if self.status is RiskCheckStatus.CONFIRMATION_REQUIRED and (
            not self.reasons or severities != {RiskSeverity.SOFT}
        ):
            raise DomainInvariantViolation(
                "confirmation_required requires only soft risk reasons"
            )
        if self.status is RiskCheckStatus.PASSED and self.reasons:
            raise DomainInvariantViolation(
                "a passed risk result cannot contain reasons"
            )
        if self.status is RiskCheckStatus.CHECKING and self.reasons:
            raise DomainInvariantViolation("checking cannot contain result reasons")
        if self.soft_confirmation is not None and self.status not in {
            RiskCheckStatus.CONFIRMATION_REQUIRED,
            RiskCheckStatus.EXPIRED,
        }:
            raise DomainInvariantViolation(
                "soft confirmation belongs only to a pending or expired soft risk"
            )
        if self.expires_at <= self.checked_at:
            raise DomainInvariantViolation(
                "risk check expiry must be later than checked_at"
            )
        return self

    def can_submit_at(self, now: datetime) -> bool:
        _require_aware_datetime(now, "now")
        if (
            now < self.checked_at
            or now < self.audit_reference.recorded_at
            or now >= self.expires_at
        ):
            return False
        return self.status is RiskCheckStatus.PASSED or (
            self.status is RiskCheckStatus.CONFIRMATION_REQUIRED
            and self.soft_confirmation is not None
        )

    def transition(
        self,
        target: RiskCheckStatus,
        *,
        audit_reference: AuditReference,
        reasons: tuple[RiskReason, ...] | None = None,
    ) -> RiskCheckResult:
        return self._transition(
            target,
            audit_reference=audit_reference,
            reasons=self.reasons if reasons is None else reasons,
            soft_confirmation=(
                self.soft_confirmation if target is RiskCheckStatus.EXPIRED else None
            ),
        )

    def confirm_soft_risk(self, audit_reference: AuditReference) -> RiskCheckResult:
        if self.status is not RiskCheckStatus.CONFIRMATION_REQUIRED:
            raise InvalidStateTransition(
                type(self).__name__, self.status, "soft_risk_confirmed"
            )
        if self.soft_confirmation is not None:
            raise DomainInvariantViolation("soft risk is already confirmed")
        self._ensure_new_audit(audit_reference)
        return self._replace(
            revision=self.revision + 1,
            soft_confirmation=audit_reference,
            audit_reference=audit_reference,
        )

    def expire_if_inputs_changed(
        self,
        current_input_versions: tuple[VersionReference, ...],
        *,
        audit_reference: AuditReference,
    ) -> RiskCheckResult:
        return self._expire_if_inputs_changed(
            current_input_versions,
            RiskCheckStatus.EXPIRED,
            audit_reference,
        )


WORKFLOW_RUN_TRANSITIONS: Mapping[WorkflowRunStatus, frozenset[WorkflowRunStatus]] = (
    MappingProxyType(
        {
            WorkflowRunStatus.QUEUED: frozenset(
                {
                    WorkflowRunStatus.RUNNING,
                    WorkflowRunStatus.FAILED,
                    WorkflowRunStatus.TIMED_OUT,
                    WorkflowRunStatus.BLOCKED,
                }
            ),
            WorkflowRunStatus.RUNNING: frozenset(
                {
                    WorkflowRunStatus.COMPLETED,
                    WorkflowRunStatus.ATTENTION_REQUIRED,
                    WorkflowRunStatus.FAILED,
                    WorkflowRunStatus.TIMED_OUT,
                    WorkflowRunStatus.BLOCKED,
                    WorkflowRunStatus.CANCEL_REQUESTED,
                }
            ),
            WorkflowRunStatus.COMPLETED: frozenset({WorkflowRunStatus.EXPIRED}),
            WorkflowRunStatus.ATTENTION_REQUIRED: frozenset(
                {WorkflowRunStatus.EXPIRED}
            ),
            WorkflowRunStatus.FAILED: frozenset(),
            WorkflowRunStatus.TIMED_OUT: frozenset(),
            WorkflowRunStatus.BLOCKED: frozenset(),
            WorkflowRunStatus.EXPIRED: frozenset(),
            WorkflowRunStatus.CANCEL_REQUESTED: frozenset(
                {
                    WorkflowRunStatus.CANCELLING,
                    WorkflowRunStatus.CANCELLED,
                }
            ),
            WorkflowRunStatus.CANCELLING: frozenset({WorkflowRunStatus.CANCELLED}),
            WorkflowRunStatus.CANCELLED: frozenset(),
        }
    )
)


class WorkflowRun(InputVersionedState):
    run_id: str = Field(min_length=1, max_length=160)
    workflow_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    workflow_version: str = Field(min_length=1, max_length=80)
    status: WorkflowRunStatus
    trade_eligible: bool
    final_artifact: VersionReference | None
    evidence_references: tuple[VersionReference, ...]
    node_contribution_references: tuple[VersionReference, ...]
    completed_node_artifacts: tuple[VersionReference, ...]
    errors: tuple[str, ...]
    permissions: tuple[str, ...]
    block_reason: WorkflowBlockReason | None
    cancellation_reason: WorkflowCancellationReason | None

    TRANSITIONS = WORKFLOW_RUN_TRANSITIONS

    @field_validator("errors", "permissions", mode="before")
    @classmethod
    def clean_text_items(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_string_tuple(values)

    @model_validator(mode="after")
    def validate_governance(self) -> Self:
        if self.trade_eligible and self.status is not WorkflowRunStatus.COMPLETED:
            raise DomainInvariantViolation(
                "only a completed workflow can be trade eligible"
            )
        if self.trade_eligible and self.workflow_key in NON_TRADING_WORKFLOWS:
            raise DomainInvariantViolation(
                f"{self.workflow_key} can never be trade eligible"
            )
        if self.status is WorkflowRunStatus.COMPLETED and self.final_artifact is None:
            raise DomainInvariantViolation(
                "a completed workflow requires a versioned final artifact"
            )
        if self.trade_eligible and (
            not self.evidence_references or not self.node_contribution_references
        ):
            raise DomainInvariantViolation(
                "trade eligible workflow requires evidence and node contributions"
            )
        if self.status is WorkflowRunStatus.QUEUED and (
            self.final_artifact is not None
            or self.evidence_references
            or self.node_contribution_references
            or self.completed_node_artifacts
        ):
            raise DomainInvariantViolation(
                "queued workflow cannot contain execution outputs"
            )
        if self.status is WorkflowRunStatus.BLOCKED and self.block_reason is None:
            raise DomainInvariantViolation("a blocked workflow requires block_reason")
        if (
            self.status is not WorkflowRunStatus.BLOCKED
            and self.block_reason is not None
        ):
            raise DomainInvariantViolation(
                "block_reason belongs only to a blocked workflow"
            )
        cancellation_states = {
            WorkflowRunStatus.CANCEL_REQUESTED,
            WorkflowRunStatus.CANCELLING,
            WorkflowRunStatus.CANCELLED,
        }
        if self.status in cancellation_states and self.cancellation_reason is None:
            raise DomainInvariantViolation(
                "a cancellation state requires cancellation_reason"
            )
        if (
            self.status not in cancellation_states
            and self.cancellation_reason is not None
        ):
            raise DomainInvariantViolation(
                "cancellation_reason belongs only to cancellation states"
            )
        return self

    @property
    def can_create_trade_plan(self) -> bool:
        return (
            self.status is WorkflowRunStatus.COMPLETED
            and self.trade_eligible
            and self.workflow_key not in NON_TRADING_WORKFLOWS
        )

    def transition(
        self,
        target: WorkflowRunStatus,
        *,
        audit_reference: AuditReference,
        trade_eligible: bool | None = None,
        block_reason: WorkflowBlockReason | None = None,
        cancellation_reason: WorkflowCancellationReason | None = None,
        final_artifact: VersionReference | None = None,
        errors: tuple[str, ...] | None = None,
    ) -> WorkflowRun:
        self._ensure_transition(target)
        if target is WorkflowRunStatus.COMPLETED and trade_eligible is None:
            raise DomainInvariantViolation(
                "completed workflow requires an explicit trade_eligible decision"
            )
        if (
            self.status is WorkflowRunStatus.RUNNING
            and target is WorkflowRunStatus.BLOCKED
            and block_reason is WorkflowBlockReason.USER_PAUSED
        ):
            raise DomainInvariantViolation(
                "a running workflow must use the cancellation protocol"
            )
        eligible = trade_eligible if trade_eligible is not None else False
        cancellation_states = {
            WorkflowRunStatus.CANCEL_REQUESTED,
            WorkflowRunStatus.CANCELLING,
            WorkflowRunStatus.CANCELLED,
        }
        selected_cancellation_reason = (
            cancellation_reason or self.cancellation_reason
            if target in cancellation_states
            else None
        )
        return self._transition(
            target,
            audit_reference=audit_reference,
            trade_eligible=eligible,
            block_reason=block_reason,
            cancellation_reason=selected_cancellation_reason,
            final_artifact=final_artifact or self.final_artifact,
            errors=self.errors if errors is None else errors,
        )

    def record_completed_node_artifact(
        self,
        reference: VersionReference,
        *,
        audit_reference: AuditReference,
    ) -> WorkflowRun:
        return self._record_output_reference(
            "completed_node_artifacts",
            reference,
            audit_reference,
        )

    def record_evidence(
        self,
        reference: VersionReference,
        *,
        audit_reference: AuditReference,
    ) -> WorkflowRun:
        return self._record_output_reference(
            "evidence_references",
            reference,
            audit_reference,
        )

    def record_node_contribution(
        self,
        reference: VersionReference,
        *,
        audit_reference: AuditReference,
    ) -> WorkflowRun:
        return self._record_output_reference(
            "node_contribution_references",
            reference,
            audit_reference,
        )

    def _record_output_reference(
        self,
        field_name: str,
        reference: VersionReference,
        audit_reference: AuditReference,
    ) -> WorkflowRun:
        if self.status not in WORKFLOW_OUTPUT_RECORDING_STATUSES:
            raise InvalidStateTransition(
                type(self).__name__,
                self.status,
                f"record_{field_name}",
            )
        existing = getattr(self, field_name)
        if reference in existing:
            raise DomainInvariantViolation(
                f"{field_name} already contains {reference.object_id}"
            )
        self._ensure_new_audit(audit_reference)
        return self._replace(
            revision=self.revision + 1,
            audit_reference=audit_reference,
            **{field_name: (*existing, reference)},
        )

    def expire_if_inputs_changed(
        self,
        current_input_versions: tuple[VersionReference, ...],
        *,
        audit_reference: AuditReference,
    ) -> WorkflowRun:
        current = self.canonicalize_versions(current_input_versions)
        if current == self.input_versions or self.status is WorkflowRunStatus.EXPIRED:
            return self
        return self._transition(
            WorkflowRunStatus.EXPIRED,
            audit_reference=audit_reference,
            invalidated_by_versions=current,
            trade_eligible=False,
        )


class NotificationCategory(str, Enum):
    WORKFLOW = "workflow"
    DATA_QUALITY = "data_quality"
    RISK = "risk"
    TRADE_PLAN = "trade_plan"
    ORDER = "order"
    FILL = "fill"
    REVIEW = "review"
    AUTHORIZATION = "authorization"


class NotificationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    HARD_RISK = "hard_risk"
    REQUIRED = "required"


class NotificationStatus(str, Enum):
    UNREAD = "unread"
    READ = "read"


class TaskType(str, Enum):
    DATA_QUALITY = "data_quality"
    WORKFLOW_ATTENTION = "workflow_attention"
    TRADE_PLAN_PENDING = "trade_plan_pending"
    ORDER_PENDING = "order_pending"
    UNKNOWN_ORDER = "unknown_order"
    REVIEW_COMPLETED = "review_completed"
    AUTHORIZATION_EXPIRING = "authorization_expiring"


class WatchlistGroup(FrozenModel):
    group_id: str = Field(min_length=1, max_length=160)
    owner_user_id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    revision: int = Field(ge=1)
    created_at: AwareDatetime = Field(...)
    updated_at: AwareDatetime = Field(...)

    @model_validator(mode="after")
    def validate_name(self) -> Self:
        if not self.name.strip():
            raise DomainInvariantViolation("watchlist group name cannot be blank")
        return self


class WatchlistInstrument(FrozenModel):
    instrument_id: str = Field(min_length=1, max_length=160)
    group_id: str = Field(min_length=1, max_length=160)
    revision: int = Field(ge=1)
    added_at: AwareDatetime = Field(...)
    added_by: str = Field(...)


class CandidateIgnore(FrozenModel):
    owner_user_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=64)
    note: str | None = Field(default=None, max_length=500)
    revision: int = Field(ge=1)
    created_at: AwareDatetime = Field(...)
    updated_at: AwareDatetime = Field(...)


class Notification(FrozenModel):
    notification_id: str = Field(min_length=1, max_length=160)
    owner_user_id: str = Field(min_length=1, max_length=160)
    category: NotificationCategory
    severity: NotificationSeverity
    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=1000)
    source_object_type: str = Field(min_length=1, max_length=80)
    source_object_id: str = Field(min_length=1, max_length=160)
    source_version: str = Field(min_length=1, max_length=80)
    required: bool = False
    status: NotificationStatus
    created_at: AwareDatetime
    read_at: AwareDatetime | None = None
    audit_reference: AuditReference

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if self.source_object_type not in {"TradePlan", "OrderDraft", "WorkflowRun"}:
            raise DomainInvariantViolation(
                "source_object_type must reference approved authoritative object"
            )
        return self


class NotificationPreference(FrozenModel):
    owner_user_id: str
    category_preferences: dict[NotificationCategory, bool]
    updated_at: AwareDatetime


class Task(FrozenModel):
    task_id: str = Field(min_length=1, max_length=160)
    type: TaskType
    priority: int = Field(ge=1, le=5)
    reason: str = Field(min_length=1, max_length=500)
    associated_object_type: str = Field(min_length=1, max_length=80)
    associated_object_id: str = Field(min_length=1, max_length=160)
    associated_object_version: str = Field(min_length=1, max_length=80)
    created_at: AwareDatetime
    target_link: str | None = None
