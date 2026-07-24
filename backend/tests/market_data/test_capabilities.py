from __future__ import annotations

import json

import pytest
from finance_god.market_data import (
    ALL_ENDPOINTS,
    CATALOG,
    EXPECTED_SDK_VERSION,
    HARD_DISABLED,
    NOT_DATA,
    PRODUCTION_AVAILABLE_ENDPOINTS,
    VERIFIED_SCOPES,
    CapabilityDisabledError,
    PandaDataCapabilityCatalog,
    SDKDriftError,
    capability_catalog_summary,
    request_shape,
)
from finance_god.market_data.capabilities import (
    CAPABILITY_RESOURCE_DIR,
    endpoint_manifest_hash,
)
from finance_god.market_data.instruments import DEFAULT_INSTRUMENT_MASTER
from pydantic import ValidationError

from .conftest import FakeSDK


def test_catalog_covers_all_213_sdk_get_methods_once() -> None:
    records = CATALOG.all()

    assert len(ALL_ENDPOINTS) == 213
    assert len(records) == 213
    assert len({record.endpoint for record in records}) == 213
    assert {record.endpoint for record in records} == set(ALL_ENDPOINTS)


def test_catalog_has_exact_audited_status_counts_and_reasons() -> None:
    records = CATALOG.all()
    statuses = {
        status: sum(item.status == status for item in records)
        for status in (
            "verified_once_research",
            "disabled",
            "not_data",
        )
    }

    assert len(HARD_DISABLED) == 22
    assert len(VERIFIED_SCOPES) == 30
    assert len(NOT_DATA) == 2
    assert statuses == {
        "verified_once_research": 30,
        "disabled": 181,
        "not_data": 2,
    }
    assert all(
        record.trade_eligible is False and record.stability_confirmed is False
        for record in records
    )
    assert all(
        CATALOG.get(endpoint).reason == "sdk_warning_deprecated_or_unreleased"
        for endpoint in HARD_DISABLED
    )
    assert all(
        CATALOG.get(endpoint).reason == "not_probed"
        for endpoint in set(ALL_ENDPOINTS)
        - HARD_DISABLED
        - NOT_DATA
        - set(VERIFIED_SCOPES)
    )


def test_catalog_separates_exact_production_availability_from_trade_and_stability() -> (
    None
):
    records = CATALOG.all()
    summary = capability_catalog_summary(records)

    assert len(PRODUCTION_AVAILABLE_ENDPOINTS) == 29
    assert {
        record.endpoint
        for record in records
        if record.availability == "production_available"
    } == set(PRODUCTION_AVAILABLE_ENDPOINTS)
    assert summary["availability"] == {
        "production_available": 29,
        "verified_research_only": 1,
        "disabled": 22,
        "not_verified": 159,
        "not_data": 2,
    }
    assert summary["trade_eligible"] == 0
    assert summary["stability_confirmed"] == 0

    stock_detail = CATALOG.get("get_stock_detail")
    assert stock_detail.status == "verified_once_research"
    assert stock_detail.availability == "verified_research_only"
    assert stock_detail.trade_eligible is False
    assert stock_detail.stability_confirmed is False


def test_catalog_summary_rejects_incomplete_records_instead_of_under_counting() -> None:
    with pytest.raises(ValidationError):
        capability_catalog_summary(({"endpoint": "get_stock_daily"},))


def test_research_derivatives_and_funds_never_gain_execution_permissions() -> None:
    research_or_derivative = {
        endpoint
        for endpoint, scopes in VERIFIED_SCOPES.items()
        if any("RESEARCH_ONLY" in scope for scope in scopes)
    }

    assert research_or_derivative
    assert all(
        CATALOG.get(endpoint).trade_eligible is False
        and CATALOG.get(endpoint).stability_confirmed is False
        for endpoint in research_or_derivative
    )
    assert all(
        CATALOG.get(endpoint).availability == "disabled"
        and CATALOG.get(endpoint).status == "disabled"
        for endpoint in HARD_DISABLED
        if endpoint.startswith("get_fund_")
    )


def test_sdk_surface_and_version_drift_fail_closed() -> None:
    sdk = FakeSDK()
    catalog = PandaDataCapabilityCatalog.for_injected_test_sdk(sdk)
    catalog.validate_sdk(sdk, sdk_version=EXPECTED_SDK_VERSION)

    with pytest.raises(SDKDriftError, match="version drift"):
        catalog.validate_sdk(sdk, sdk_version="0.0.13")

    class RemovedEndpointSDK(FakeSDK):
        def __dir__(self) -> list[str]:
            return [name for name in super().__dir__() if name != "get_us_daily"]

    with pytest.raises(SDKDriftError, match="endpoint drift"):
        catalog.validate_sdk(RemovedEndpointSDK(), sdk_version=EXPECTED_SDK_VERSION)

    class ChangedSignatureSDK(FakeSDK):
        def get_us_daily(self, symbol: str) -> object:
            return []

    with pytest.raises(SDKDriftError, match="signature drift"):
        catalog.validate_sdk(ChangedSignatureSDK(), sdk_version=EXPECTED_SDK_VERSION)


def test_verified_endpoint_allows_only_exact_probe_scope() -> None:
    scopes = {"A_SHARE_STOCK", "frequency=1m"}
    shape = request_shape(
        "get_stock_rt_min",
        scopes,
        parameter_names={"symbol", "frequency"},
    )
    assert (
        CATALOG.authorize("get_stock_rt_min", scopes, shape).status
        == "verified_once_research"
    )
    assert shape.instrument_master_identity == DEFAULT_INSTRUMENT_MASTER.identity
    assert shape.instrument_master_version == DEFAULT_INSTRUMENT_MASTER.version

    with pytest.raises(CapabilityDisabledError, match="scope was not verified"):
        CATALOG.authorize("get_stock_rt_min", {"A_SHARE_STOCK"}, shape)
    with pytest.raises(CapabilityDisabledError, match="scope was not verified"):
        CATALOG.authorize(
            "get_stock_rt_min",
            {"A_SHARE_STOCK", "frequency=1m", "ETF"},
            shape,
        )
    with pytest.raises(CapabilityDisabledError, match="disabled"):
        CATALOG.authorize(
            "get_fund_daily",
            {"FUND"},
            request_shape("get_stock_rt_daily", {"A_SHARE_STOCK"}),
        )
    with pytest.raises(CapabilityDisabledError, match="outside audited"):
        CATALOG.authorize(
            "get_new_unreviewed_endpoint",
            {"ANY"},
            request_shape("get_stock_rt_daily", {"A_SHARE_STOCK"}),
        )
    wrong_parameters = request_shape(
        "get_stock_rt_min",
        scopes,
        parameter_names={"symbol", "frequency", "caller_override"},
    )
    with pytest.raises(CapabilityDisabledError, match="shape was not verified"):
        CATALOG.authorize(
            "get_stock_rt_min",
            scopes,
            wrong_parameters,
        )


def test_redacted_capability_artifacts_match_runtime_catalog() -> None:
    manifest = json.loads(
        (CAPABILITY_RESOURCE_DIR / "endpoint-manifest-v1.json").read_text()
    )
    verification = json.loads(
        (CAPABILITY_RESOURCE_DIR / "verification-summary-v1.json").read_text()
    )
    rendered = json.dumps(
        {"manifest": manifest, "verification": verification},
        ensure_ascii=False,
    ).lower()

    assert manifest["public_get_method_count"] == 213
    assert manifest["endpoint_name_manifest_sha256"] == endpoint_manifest_hash()
    assert {item["endpoint"] for item in manifest["endpoints"]} == set(ALL_ENDPOINTS)
    assert len(manifest["full_signature_manifest_sha256"]) == 64
    assert manifest["instrument_master_identity"] == DEFAULT_INSTRUMENT_MASTER.identity
    assert manifest["instrument_master_version"] == DEFAULT_INSTRUMENT_MASTER.version
    assert all(
        item["trade_eligible"] is False
        and item["stability_confirmed"] is False
        and item["availability"] == CATALOG.get(item["endpoint"]).availability
        and item["category"] == CATALOG.get(item["endpoint"]).category
        and item["status"] == CATALOG.get(item["endpoint"]).status
        and item["reason"] == CATALOG.get(item["endpoint"]).reason
        and item["verified_scope_sets"]
        == [
            sorted(scope) for scope in CATALOG.get(item["endpoint"]).verified_scope_sets
        ]
        and item["allowed_request_shape_hashes"]
        == list(CATALOG.get(item["endpoint"]).allowed_request_shape_hashes)
        for item in manifest["endpoints"]
    )
    assert manifest["production_available_endpoint_count"] == 29
    assert set(manifest["production_available_endpoints"]) == set(
        PRODUCTION_AVAILABLE_ENDPOINTS
    )
    assert verification["probe_endpoint_count"] == 30
    assert verification["production_available_endpoint_count"] == 29
    assert set(verification["production_available_endpoints"]) == set(
        PRODUCTION_AVAILABLE_ENDPOINTS
    )
    assert verification["capability_status"] == "verified_once_research"
    assert verification["trade_eligible"] is False
    assert verification["stability_confirmed"] is False
    assert all(
        item["result"] == "verified_once_research"
        and item["trade_eligible"] is False
        and item["stability_confirmed"] is False
        and item["availability"] == CATALOG.get(item["endpoint"]).availability
        and item["category"] == CATALOG.get(item["endpoint"]).category
        for item in verification["verified"]
    )
    assert len(verification["disabled_warning_endpoints"]) == 22
    assert verification["contains_credentials"] is False
    assert verification["contains_full_urls"] is False
    assert "password" not in rendered
    assert "http://" not in rendered
    assert "https://" not in rendered
