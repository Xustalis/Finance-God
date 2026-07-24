from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Protocol, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from finance_god.domain.models import VersionReference

from .rules_v1 import ACCESS_PROVIDER_MAX_AGE

ALLOWED_MARKETS = frozenset({"CN", "HK", "US"})
ALLOWED_ASSETS = frozenset({"stock", "etf", "lof", "otc_fund"})
ALLOWED_SIDES = frozenset(
    {
        "buy",
        "sell",
        "short",
        "subscribe",
        "redeem",
        "convert",
        "recurring_invest",
    }
)
ALLOWED_ORDER_TYPES = frozenset({"market", "limit", "fund"})
SHORT_MARKETS = frozenset({"HK", "US"})


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def trim_external_strings(cls, value: object) -> object:
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError("decimal fields must be finite")
            exponent = value.as_tuple().exponent
            if not isinstance(exponent, int):
                raise ValueError("decimal fields must be finite")
            if len(value.as_tuple().digits) > 28 or -exponent > 12:
                raise ValueError("decimal fields exceed 28 digits or 12 decimal places")
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("string fields cannot be blank")
        return value


class RuntimeEnvironment(str, Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class AuthorizationStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    REVOKED = "revoked"
    EXPIRED = "expired"


class AutonomyLevel(str, Enum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"


class Clock(Protocol):
    def now(self) -> datetime: ...


class AuthenticatedPrincipal(FrozenModel):
    principal_id: str = Field(min_length=1, max_length=160)
    user_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    authenticated_at: AwareDatetime
    captured_at: AwareDatetime
    valid_until: AwareDatetime
    source_version: VersionReference
    is_fixture: bool

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        _require_utc(self.authenticated_at, "authenticated_at")
        _require_utc(self.captured_at, "captured_at")
        _require_utc(self.valid_until, "valid_until")
        if self.authenticated_at > self.captured_at:
            raise ValueError("authentication cannot occur after capture")
        if self.valid_until <= self.captured_at:
            raise ValueError("principal validity must end after capture")
        return self


class AuthorizationLimits(FrozenModel):
    max_single_order_amount: Decimal = Field(gt=0, max_digits=28, decimal_places=8)
    max_daily_turnover_amount: Decimal = Field(gt=0, max_digits=28, decimal_places=8)
    max_single_asset_ratio: Decimal = Field(gt=0, le=1)
    max_broad_etf_ratio: Decimal = Field(gt=0, le=1)
    max_otc_fund_ratio: Decimal = Field(gt=0, le=1)
    max_industry_ratio: Decimal = Field(gt=0, le=1)
    max_gross_ratio: Decimal = Field(gt=0)
    max_short_gross_ratio: Decimal = Field(gt=0)
    max_single_short_ratio: Decimal = Field(gt=0)
    max_price_deviation_ratio: Decimal = Field(gt=0)
    max_slippage_bps: Decimal = Field(gt=0)
    max_all_in_cost_ratio: Decimal = Field(gt=0)


class AuthorizationSnapshot(FrozenModel):
    authorization_id: str = Field(min_length=1, max_length=160)
    user_id: str = Field(min_length=1, max_length=160)
    status: AuthorizationStatus
    autonomy_level: AutonomyLevel
    allowed_markets: tuple[str, ...] = Field(min_length=1)
    allowed_assets: tuple[str, ...] = Field(min_length=1)
    allowed_sides: tuple[str, ...] = Field(min_length=1)
    allowed_order_types: tuple[str, ...] = Field(min_length=1)
    short_markets: tuple[str, ...]
    limits: AuthorizationLimits
    valid_from: AwareDatetime
    captured_at: AwareDatetime
    valid_until: AwareDatetime
    source_version: VersionReference
    is_fixture: bool

    @field_validator(
        "allowed_markets",
        "allowed_assets",
        "allowed_sides",
        "allowed_order_types",
        "short_markets",
        mode="before",
    )
    @classmethod
    def normalize_scope(cls, values: object) -> tuple[str, ...]:
        if not isinstance(values, (tuple, list)):
            raise ValueError("authorization scope must be a sequence")
        normalized = tuple(str(value).strip() for value in values)
        if any(not value or len(value) > 80 for value in normalized):
            raise ValueError("authorization scope values must be non-blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("authorization scope cannot contain duplicates")
        return tuple(sorted(normalized))

    @model_validator(mode="after")
    def validate_scope_values(self) -> Self:
        scopes = (
            ("allowed_markets", self.allowed_markets, ALLOWED_MARKETS),
            ("allowed_assets", self.allowed_assets, ALLOWED_ASSETS),
            ("allowed_sides", self.allowed_sides, ALLOWED_SIDES),
            ("allowed_order_types", self.allowed_order_types, ALLOWED_ORDER_TYPES),
            ("short_markets", self.short_markets, SHORT_MARKETS),
        )
        for name, values, allowed in scopes:
            unknown = set(values) - allowed
            if unknown:
                raise ValueError(
                    f"{name} contains unsupported values: {sorted(unknown)}"
                )
        if not set(self.short_markets).issubset(self.allowed_markets):
            raise ValueError("short_markets must be a subset of allowed_markets")
        return self

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        _require_utc(self.valid_from, "valid_from")
        _require_utc(self.captured_at, "captured_at")
        _require_utc(self.valid_until, "valid_until")
        if self.valid_from > self.captured_at:
            raise ValueError("authorization cannot be captured before valid_from")
        if self.valid_until <= self.captured_at:
            raise ValueError("authorization validity must end after capture")
        return self


class CooldownSnapshot(FrozenModel):
    cooldown_id: str = Field(min_length=1, max_length=160)
    user_id: str = Field(min_length=1, max_length=160)
    active: bool
    captured_at: AwareDatetime
    valid_until: AwareDatetime
    source_version: VersionReference
    is_fixture: bool

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        _require_utc(self.captured_at, "captured_at")
        _require_utc(self.valid_until, "valid_until")
        if self.valid_until <= self.captured_at:
            raise ValueError("cooldown validity must end after capture")
        return self


class IdentityProvider(Protocol):
    """Resolves the server-authenticated session; no client-selected user input."""

    def current_principal(self) -> AuthenticatedPrincipal: ...


class AuthorizationProvider(Protocol):
    def authorization_for(
        self, principal: AuthenticatedPrincipal
    ) -> AuthorizationSnapshot: ...

    def cooldown_for(self, principal: AuthenticatedPrincipal) -> CooldownSnapshot: ...


class AccessResolutionCode(str, Enum):
    ALLOWED = "allowed"
    ADAPTER_MISSING = "adapter_missing"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    OWNER_MISMATCH = "owner_mismatch"
    STALE_RESPONSE = "stale_response"
    EXPIRED = "expired"
    FIXTURE_FORBIDDEN = "fixture_forbidden"
    FIXTURE_MISMATCH = "fixture_mismatch"


class AccessResolution(FrozenModel):
    allowed: bool
    code: AccessResolutionCode
    message: str = Field(min_length=1, max_length=500)
    checked_at: AwareDatetime
    environment: RuntimeEnvironment
    resolution_reference: VersionReference
    valid_until: AwareDatetime
    principal: AuthenticatedPrincipal | None
    authorization: AuthorizationSnapshot | None
    cooldown: CooldownSnapshot | None
    fixture_response: bool

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        complete = all(
            value is not None
            for value in (self.principal, self.authorization, self.cooldown)
        )
        if self.allowed and (
            self.code is not AccessResolutionCode.ALLOWED or not complete
        ):
            raise ValueError("allowed access requires complete upstream snapshots")
        if not self.allowed and self.code is AccessResolutionCode.ALLOWED:
            raise ValueError("denied access requires a failure code")
        if not self.allowed and complete:
            raise ValueError("denied access must not expose upstream snapshots")
        if self.valid_until <= self.checked_at:
            raise ValueError("access resolution must retain positive validity")
        return self


class AccessResolver:
    def __init__(
        self,
        *,
        environment: RuntimeEnvironment,
        identity_provider: IdentityProvider | None,
        authorization_provider: AuthorizationProvider | None,
        clock: Clock,
    ) -> None:
        if not isinstance(environment, RuntimeEnvironment):
            raise TypeError("environment must be a RuntimeEnvironment")
        self._environment = environment
        self._identity_provider = identity_provider
        self._authorization_provider = authorization_provider
        self._clock = clock

    def resolve(self) -> AccessResolution:
        now = self._clock.now()
        _require_utc(now, "clock")
        if self._identity_provider is None or self._authorization_provider is None:
            return self._denied(
                AccessResolutionCode.ADAPTER_MISSING,
                "identity or authorization adapter is not configured",
                now,
            )
        try:
            principal = self._identity_provider.current_principal()
            authorization = self._authorization_provider.authorization_for(principal)
            cooldown = self._authorization_provider.cooldown_for(principal)
        except Exception as exc:
            return self._denied(
                AccessResolutionCode.UPSTREAM_UNAVAILABLE,
                f"access upstream unavailable ({type(exc).__name__})",
                now,
            )
        if (
            principal.user_id != authorization.user_id
            or principal.user_id != cooldown.user_id
        ):
            return self._denied(
                AccessResolutionCode.OWNER_MISMATCH,
                "identity, authorization, and cooldown owners do not match",
                now,
                principal,
                authorization,
                cooldown,
            )
        captured = (
            principal.captured_at,
            authorization.captured_at,
            cooldown.captured_at,
        )
        if any(
            now < value or now - value > ACCESS_PROVIDER_MAX_AGE for value in captured
        ):
            return self._denied(
                AccessResolutionCode.STALE_RESPONSE,
                "access provider response is older than 30 seconds",
                now,
                principal,
                authorization,
                cooldown,
            )
        if any(
            now >= value
            for value in (
                principal.valid_until,
                authorization.valid_until,
                cooldown.valid_until,
            )
        ):
            return self._denied(
                AccessResolutionCode.EXPIRED,
                "access provider response has expired",
                now,
                principal,
                authorization,
                cooldown,
            )
        fixture = any(
            value.is_fixture for value in (principal, authorization, cooldown)
        )
        if fixture and not all(
            value.is_fixture for value in (principal, authorization, cooldown)
        ):
            return self._denied(
                AccessResolutionCode.FIXTURE_MISMATCH,
                "fixture and non-fixture access snapshots cannot be mixed",
                now,
                principal,
                authorization,
                cooldown,
            )
        if fixture and self._environment not in {
            RuntimeEnvironment.DEVELOPMENT,
            RuntimeEnvironment.TEST,
        }:
            return self._denied(
                AccessResolutionCode.FIXTURE_FORBIDDEN,
                "fixture access is forbidden in staging and production",
                now,
                principal,
                authorization,
                cooldown,
            )
        return AccessResolution(
            allowed=True,
            code=AccessResolutionCode.ALLOWED,
            message="access snapshots resolved",
            checked_at=now,
            environment=self._environment,
            resolution_reference=self._resolution_reference(
                AccessResolutionCode.ALLOWED,
                now,
                principal,
                authorization,
                cooldown,
            ),
            valid_until=min(
                principal.valid_until,
                authorization.valid_until,
                cooldown.valid_until,
            ),
            principal=principal,
            authorization=authorization,
            cooldown=cooldown,
            fixture_response=fixture,
        )

    def _denied(
        self,
        code: AccessResolutionCode,
        message: str,
        now: datetime,
        principal: AuthenticatedPrincipal | None = None,
        authorization: AuthorizationSnapshot | None = None,
        cooldown: CooldownSnapshot | None = None,
    ) -> AccessResolution:
        return AccessResolution(
            allowed=False,
            code=code,
            message=message,
            checked_at=now,
            environment=self._environment,
            resolution_reference=self._resolution_reference(
                code,
                now,
                principal,
                authorization,
                cooldown,
            ),
            valid_until=now + ACCESS_PROVIDER_MAX_AGE,
            principal=None,
            authorization=None,
            cooldown=None,
            fixture_response=any(
                value is not None and value.is_fixture
                for value in (principal, authorization, cooldown)
            ),
        )

    def _resolution_reference(
        self,
        code: AccessResolutionCode,
        now: datetime,
        principal: AuthenticatedPrincipal | None,
        authorization: AuthorizationSnapshot | None,
        cooldown: CooldownSnapshot | None,
    ) -> VersionReference:
        source_versions = [
            value.source_version
            for value in (principal, authorization, cooldown)
            if value is not None
        ]
        del now
        payload = "|".join(
            [
                self._environment.value,
                code.value,
                *(
                    f"{item.object_type}:{item.object_id}:{item.version}"
                    for item in source_versions
                ),
            ]
        )
        return VersionReference(
            object_type="access_resolution",
            object_id=f"{self._environment.value}:{code.value}",
            version=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        )


class FixtureAccessProvider:
    """Explicit development/test fixture; never enabled by request data."""

    def __init__(
        self,
        *,
        environment: RuntimeEnvironment,
        enabled: bool,
        principal: AuthenticatedPrincipal,
        authorization: AuthorizationSnapshot,
        cooldown: CooldownSnapshot,
    ) -> None:
        if not isinstance(environment, RuntimeEnvironment):
            raise TypeError("environment must be a RuntimeEnvironment")
        if environment not in {
            RuntimeEnvironment.DEVELOPMENT,
            RuntimeEnvironment.TEST,
        }:
            raise PermissionError(
                "fixture access is forbidden outside development/test"
            )
        if enabled is not True:
            raise PermissionError("fixture access requires explicit enablement")
        if not all(value.is_fixture for value in (principal, authorization, cooldown)):
            raise ValueError("fixture snapshots must be marked as fixtures")
        if not all(
            value.source_version.object_type.startswith("fixture_")
            for value in (principal, authorization, cooldown)
        ):
            raise ValueError("fixture sources must carry an auditable fixture marker")
        self._principal = principal
        self._authorization = authorization
        self._cooldown = cooldown

    def current_principal(self) -> AuthenticatedPrincipal:
        return self._principal

    def authorization_for(
        self, principal: AuthenticatedPrincipal
    ) -> AuthorizationSnapshot:
        self._require_fixture_principal(principal)
        return self._authorization

    def cooldown_for(self, principal: AuthenticatedPrincipal) -> CooldownSnapshot:
        self._require_fixture_principal(principal)
        return self._cooldown

    def _require_fixture_principal(self, principal: AuthenticatedPrincipal) -> None:
        if principal != self._principal:
            raise PermissionError("fixture provider only serves its fixed principal")


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")


def _require_utc(value: datetime, field_name: str) -> None:
    _require_aware(value)
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC")
