from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN

from .errors import DomainInvariantViolation

SIMULATION_RULE_VERSION = "simulation-rules-v1"
MONEY_QUANTUM = Decimal("0.00000001")
ZERO = Decimal("0")


def derived_money(value: Decimal, *, rule_version: str, label: str) -> Decimal:
    require_rule_version(rule_version)
    if not value.is_finite():
        raise DomainInvariantViolation(f"{label} must be finite")
    rounded = value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
    return ZERO.quantize(MONEY_QUANTUM) if rounded.is_zero() else rounded


def proportional_remaining(
    balance: Decimal,
    *,
    consumed: Decimal,
    total: Decimal,
    rule_version: str,
    label: str,
) -> Decimal:
    require_rule_version(rule_version)
    if total <= ZERO or consumed <= ZERO or consumed > total:
        raise DomainInvariantViolation(f"{label} has invalid proportional inputs")
    if consumed == total:
        return ZERO.quantize(MONEY_QUANTUM)
    return derived_money(
        balance * (total - consumed) / total,
        rule_version=rule_version,
        label=label,
    )


def proportional_consumption(
    balance: Decimal,
    *,
    consumed: Decimal,
    total: Decimal,
    rule_version: str,
    label: str,
) -> Decimal:
    remaining = proportional_remaining(
        balance,
        consumed=consumed,
        total=total,
        rule_version=rule_version,
        label=label,
    )
    return derived_money(
        balance - remaining,
        rule_version=rule_version,
        label=label,
    )


def require_rule_version(rule_version: str) -> None:
    if rule_version != SIMULATION_RULE_VERSION:
        raise DomainInvariantViolation(
            f"unsupported simulation rule version: {rule_version}"
        )
