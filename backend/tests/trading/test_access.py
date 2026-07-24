from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from finance_god.domain.models import VersionReference
from finance_god.trading.access import (
    AccessResolutionCode,
    AccessResolver,
    AuthenticatedPrincipal,
    AuthorizationLimits,
    AuthorizationSnapshot,
    AuthorizationStatus,
    AutonomyLevel,
    CooldownSnapshot,
    FixtureAccessProvider,
    RuntimeEnvironment,
)

NOW = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)


class FixedClock:
    def now(self) -> datetime:
        return NOW


def version(kind: str, object_id: str, value: str = "1") -> VersionReference:
    return VersionReference(object_type=kind, object_id=object_id, version=value)


def limits() -> AuthorizationLimits:
    return AuthorizationLimits(
        max_single_order_amount=Decimal("100000"),
        max_daily_turnover_amount=Decimal("200000"),
        max_single_asset_ratio=Decimal("0.18"),
        max_broad_etf_ratio=Decimal("0.30"),
        max_otc_fund_ratio=Decimal("0.25"),
        max_industry_ratio=Decimal("0.30"),
        max_gross_ratio=Decimal("1.00"),
        max_short_gross_ratio=Decimal("0.25"),
        max_single_short_ratio=Decimal("0.08"),
        max_price_deviation_ratio=Decimal("0.08"),
        max_slippage_bps=Decimal("80"),
        max_all_in_cost_ratio=Decimal("0.015"),
    )


def principal(*, fixture: bool = False) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        principal_id="principal-1",
        user_id="user-1",
        session_id="server-session-1",
        authenticated_at=NOW - timedelta(seconds=1),
        captured_at=NOW - timedelta(seconds=1),
        valid_until=NOW + timedelta(minutes=5),
        source_version=version(
            "fixture_identity" if fixture else "identity_session", "server-session-1"
        ),
        source_revision="1",
        is_fixture=fixture,
    )


def authorization(*, fixture: bool = False) -> AuthorizationSnapshot:
    return AuthorizationSnapshot(
        authorization_id="mandate-1",
        user_id="user-1",
        status=AuthorizationStatus.ACTIVE,
        autonomy_level=AutonomyLevel.L2,
        allowed_markets=("CN", "HK", "US"),
        allowed_assets=("stock", "etf", "lof", "otc_fund"),
        allowed_sides=("buy", "sell", "short", "subscribe", "redeem", "convert"),
        allowed_order_types=("market", "limit", "fund"),
        short_markets=("HK", "US"),
        limits=limits(),
        valid_from=NOW - timedelta(days=1),
        captured_at=NOW - timedelta(seconds=1),
        valid_until=NOW + timedelta(days=1),
        source_version=version(
            "fixture_authorization" if fixture else "investment_mandate",
            "mandate-1",
        ),
        source_revision="1",
        is_fixture=fixture,
    )


def cooldown(*, fixture: bool = False) -> CooldownSnapshot:
    return CooldownSnapshot(
        cooldown_id="cooldown-1",
        user_id="user-1",
        active=False,
        captured_at=NOW - timedelta(seconds=1),
        valid_until=NOW + timedelta(minutes=5),
        source_version=version(
            "fixture_cooldown" if fixture else "cooldown", "cooldown-1"
        ),
        source_revision="1",
        is_fixture=fixture,
    )


class RaisingIdentity:
    def current_principal(self) -> AuthenticatedPrincipal:
        raise ConnectionError("identity upstream unavailable")


class StaticProvider:
    def current_principal(self) -> AuthenticatedPrincipal:
        return principal()

    def authorization_for(
        self, authenticated: AuthenticatedPrincipal
    ) -> AuthorizationSnapshot:
        del authenticated
        return authorization()

    def cooldown_for(self, authenticated: AuthenticatedPrincipal) -> CooldownSnapshot:
        del authenticated
        return cooldown()


class AccessTest(unittest.TestCase):
    def test_missing_adapter_and_upstream_failure_are_fail_closed(self) -> None:
        missing = AccessResolver(
            environment=RuntimeEnvironment.PRODUCTION,
            identity_provider=None,
            authorization_provider=None,
            clock=FixedClock(),
        ).resolve()
        self.assertFalse(missing.allowed)
        self.assertEqual(missing.code, AccessResolutionCode.ADAPTER_MISSING)
        self.assertIsNone(missing.principal)
        self.assertIsNone(missing.authorization)
        self.assertIsNone(missing.cooldown)

        unavailable = AccessResolver(
            environment=RuntimeEnvironment.PRODUCTION,
            identity_provider=RaisingIdentity(),
            authorization_provider=StaticProvider(),
            clock=FixedClock(),
        ).resolve()
        self.assertFalse(unavailable.allowed)
        self.assertEqual(unavailable.code, AccessResolutionCode.UPSTREAM_UNAVAILABLE)

    def test_provider_resolution_never_accepts_a_client_selected_user(self) -> None:
        resolution = AccessResolver(
            environment=RuntimeEnvironment.PRODUCTION,
            identity_provider=StaticProvider(),
            authorization_provider=StaticProvider(),
            clock=FixedClock(),
        ).resolve()
        self.assertTrue(resolution.allowed)
        self.assertEqual(resolution.principal, principal())
        self.assertEqual(resolution.authorization, authorization())

    def test_fixture_requires_explicit_enablement_and_non_production_environment(
        self,
    ) -> None:
        with self.assertRaises(PermissionError):
            FixtureAccessProvider(
                environment=RuntimeEnvironment.PRODUCTION,
                enabled=True,
                principal=principal(fixture=True),
                authorization=authorization(fixture=True),
                cooldown=cooldown(fixture=True),
            )
        with self.assertRaises(PermissionError):
            FixtureAccessProvider(
                environment=RuntimeEnvironment.STAGING,
                enabled=True,
                principal=principal(fixture=True),
                authorization=authorization(fixture=True),
                cooldown=cooldown(fixture=True),
            )
        with self.assertRaises(PermissionError):
            FixtureAccessProvider(
                environment=RuntimeEnvironment.TEST,
                enabled=False,
                principal=principal(fixture=True),
                authorization=authorization(fixture=True),
                cooldown=cooldown(fixture=True),
            )

        provider = FixtureAccessProvider(
            environment=RuntimeEnvironment.TEST,
            enabled=True,
            principal=principal(fixture=True),
            authorization=authorization(fixture=True),
            cooldown=cooldown(fixture=True),
        )
        result = AccessResolver(
            environment=RuntimeEnvironment.TEST,
            identity_provider=provider,
            authorization_provider=provider,
            clock=FixedClock(),
        ).resolve()
        self.assertTrue(result.allowed)
        self.assertTrue(result.fixture_response)
        self.assertIsNotNone(result.authorization)
        assert result.authorization is not None
        self.assertEqual(
            result.authorization.source_version.object_type,
            "fixture_authorization",
        )
        forbidden = AccessResolver(
            environment=RuntimeEnvironment.PRODUCTION,
            identity_provider=provider,
            authorization_provider=provider,
            clock=FixedClock(),
        ).resolve()
        self.assertFalse(forbidden.allowed)
        self.assertEqual(
            forbidden.code,
            AccessResolutionCode.FIXTURE_FORBIDDEN,
        )
        self.assertIsNone(forbidden.principal)
        self.assertIsNone(forbidden.authorization)
        self.assertIsNone(forbidden.cooldown)

    def test_unknown_scope_values_and_non_finite_limits_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            authorization().model_validate(
                {
                    **authorization().model_dump(),
                    "allowed_assets": ("stock", "crypto"),
                }
            )
        with self.assertRaises(ValueError):
            AuthorizationLimits.model_validate(
                {
                    **limits().model_dump(),
                    "max_single_order_amount": Decimal("NaN"),
                }
            )

    def test_access_source_versions_bind_type_id_and_revision_at_construction(
        self,
    ) -> None:
        invalid_inputs = (
            (
                AuthenticatedPrincipal,
                {
                    **principal().model_dump(),
                    "source_version": version(
                        "client_claim",
                        "server-session-1",
                    ),
                },
            ),
            (
                AuthorizationSnapshot,
                {
                    **authorization().model_dump(),
                    "source_version": version(
                        "investment_mandate",
                        "another-mandate",
                    ),
                },
            ),
            (
                CooldownSnapshot,
                {
                    **cooldown().model_dump(),
                    "source_version": version(
                        "cooldown",
                        "cooldown-1",
                        "2",
                    ),
                },
            ),
        )
        for model, values in invalid_inputs:
            with self.subTest(model=model.__name__):
                with self.assertRaises(ValueError):
                    model.model_validate(values)

    def test_production_formal_resolution_revalidates_forged_provider_models(
        self,
    ) -> None:
        class ForgedProvider:
            def __init__(
                self,
                *,
                authenticated: AuthenticatedPrincipal,
                mandate: AuthorizationSnapshot,
                cooldown_snapshot: CooldownSnapshot,
            ) -> None:
                self.authenticated = authenticated
                self.mandate = mandate
                self.cooldown_snapshot = cooldown_snapshot

            def current_principal(self) -> AuthenticatedPrincipal:
                return self.authenticated

            def authorization_for(
                self,
                authenticated: AuthenticatedPrincipal,
            ) -> AuthorizationSnapshot:
                del authenticated
                return self.mandate

            def cooldown_for(
                self,
                authenticated: AuthenticatedPrincipal,
            ) -> CooldownSnapshot:
                del authenticated
                return self.cooldown_snapshot

        providers = (
            ForgedProvider(
                authenticated=principal().model_copy(
                    update={
                        "source_version": version(
                            "client_claim",
                            "server-session-1",
                        )
                    }
                ),
                mandate=authorization(),
                cooldown_snapshot=cooldown(),
            ),
            ForgedProvider(
                authenticated=principal(),
                mandate=authorization().model_copy(
                    update={
                        "source_version": version(
                            "investment_mandate",
                            "another-mandate",
                        )
                    }
                ),
                cooldown_snapshot=cooldown(),
            ),
            ForgedProvider(
                authenticated=principal(),
                mandate=authorization(),
                cooldown_snapshot=cooldown().model_copy(
                    update={
                        "source_version": version(
                            "cooldown",
                            "cooldown-1",
                            "2",
                        )
                    }
                ),
            ),
        )
        for provider in providers:
            with self.subTest(provider=provider):
                resolution = AccessResolver(
                    environment=RuntimeEnvironment.PRODUCTION,
                    identity_provider=provider,
                    authorization_provider=provider,
                    clock=FixedClock(),
                ).resolve()
                self.assertFalse(resolution.allowed)
                self.assertEqual(
                    resolution.code,
                    AccessResolutionCode.UPSTREAM_UNAVAILABLE,
                )
                self.assertIsNone(resolution.principal)
                self.assertIsNone(resolution.authorization)
                self.assertIsNone(resolution.cooldown)

    def test_owner_mismatch_and_stale_provider_snapshot_fail_closed(self) -> None:
        class MismatchProvider(StaticProvider):
            def authorization_for(
                self, authenticated: AuthenticatedPrincipal
            ) -> AuthorizationSnapshot:
                del authenticated
                return authorization().model_copy(update={"user_id": "user-2"})

        mismatch = AccessResolver(
            environment=RuntimeEnvironment.PRODUCTION,
            identity_provider=MismatchProvider(),
            authorization_provider=MismatchProvider(),
            clock=FixedClock(),
        ).resolve()
        self.assertFalse(mismatch.allowed)
        self.assertEqual(mismatch.code, AccessResolutionCode.OWNER_MISMATCH)

        class StaleProvider(StaticProvider):
            def current_principal(self) -> AuthenticatedPrincipal:
                return principal().model_copy(
                    update={
                        "authenticated_at": NOW - timedelta(seconds=32),
                        "captured_at": NOW - timedelta(seconds=31),
                    }
                )

        stale = AccessResolver(
            environment=RuntimeEnvironment.PRODUCTION,
            identity_provider=StaleProvider(),
            authorization_provider=StaleProvider(),
            clock=FixedClock(),
        ).resolve()
        self.assertFalse(stale.allowed)
        self.assertEqual(stale.code, AccessResolutionCode.STALE_RESPONSE)


if __name__ == "__main__":
    unittest.main()
