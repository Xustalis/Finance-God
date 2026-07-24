"""Fail-closed PandaData 0.0.12 capability catalog."""

from __future__ import annotations

import inspect
import json
from collections.abc import Iterable
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .instruments import (
    DEFAULT_INSTRUMENT_MASTER_IDENTITY,
    DEFAULT_INSTRUMENT_MASTER_VERSION,
)

CAPABILITY_CATALOG_VERSION = "pandadata-capabilities-v1"
EXPECTED_SDK_VERSION = "0.0.12"

ALL_ENDPOINTS = tuple(  # noqa: C409 - generated audited endpoint manifest
    ["get_adj_factor", "get_adj_factor_hk", "get_audit_opinion", "get_block_trade", "get_broker_build_process", "get_broker_flow_daily", "get_broker_grade", "get_broker_loss_rank", "get_broker_ls_ratio", "get_broker_netmarg", "get_broker_netmarg_change", "get_broker_oi_value", "get_broker_profit", "get_broker_profit_rank", "get_broker_totlmarg", "get_broker_variety_profit", "get_client", "get_concept_constituents", "get_concept_list", "get_factor", "get_factor_hk", "get_factory", "get_fina_ex", "get_fina_forecast", "get_fina_performance", "get_fina_reports", "get_fina_statement", "get_fund_daily", "get_fund_daily_post", "get_fund_daily_pre", "get_fund_detail", "get_fund_etf_constituents", "get_fund_etf_cr", "get_fund_etf_cr_limits", "get_fund_etf_cr_net", "get_future_basis", "get_future_calendar_arbitrage", "get_future_contract_indicators", "get_future_contract_pool", "get_future_contract_rank", "get_future_daily", "get_future_daily_post", "get_future_detail", "get_future_dominant", "get_future_dominant_corr", "get_future_free_ratio", "get_future_free_spread", "get_future_inventory", "get_future_ls_ratio", "get_future_market_post", "get_future_min", "get_future_net_flow", "get_future_netcap_change", "get_future_netposi_rank", "get_future_nonbroker_net", "get_future_spot_profit", "get_future_symbol_posi", "get_future_term_structure", "get_future_trader_quote", "get_future_variety_mcap", "get_future_variety_posi", "get_future_virtual_ratio", "get_future_warehouse_receipt", "get_hk_daily", "get_hk_daily_post", "get_hk_daily_pre", "get_hk_detail", "get_holder_count", "get_hsgt_hold", "get_index_component", "get_index_constituent", "get_index_daily", "get_index_detail", "get_index_indicator", "get_index_min", "get_index_weights", "get_industry_constituents", "get_industry_detail", "get_investor_activity", "get_last_trade_date", "get_lhb_detail", "get_lhb_list", "get_macro_ad", "get_macro_ag", "get_macro_ar", "get_macro_au", "get_macro_bm", "get_macro_cal", "get_macro_cal_config", "get_macro_cal_info", "get_macro_ce", "get_macro_ch", "get_macro_ci", "get_macro_cm", "get_macro_detail", "get_macro_dt", "get_macro_ec", "get_macro_ed", "get_macro_ee", "get_macro_eh", "get_macro_en", "get_macro_ep", "get_macro_ew", "get_macro_fa", "get_macro_fb", "get_macro_fe", "get_macro_fi", "get_macro_fs", "get_macro_gb", "get_macro_ha", "get_macro_in", "get_macro_ir", "get_macro_is", "get_macro_li", "get_macro_mb", "get_macro_md", "get_macro_me", "get_macro_na", "get_macro_nf", "get_macro_of", "get_macro_or", "get_macro_ph", "get_macro_pi", "get_macro_pm", "get_macro_pp", "get_macro_pr", "get_macro_rb", "get_macro_rc", "get_macro_re", "get_macro_se", "get_macro_sm", "get_macro_st", "get_macro_te", "get_macro_th", "get_macro_tm", "get_macro_tr", "get_macro_ut", "get_macro_wr", "get_margin", "get_market_data", "get_market_min_data", "get_option_daily", "get_option_detail", "get_option_exercise", "get_option_implied_volatility", "get_option_risk_indicators", "get_option_spot_market", "get_option_static", "get_option_underlying_detail", "get_option_underlying_volatility", "get_prev_trade_date", "get_repurchase", "get_restricted_list", "get_share_float", "get_stock_allotment", "get_stock_cash_dividend", "get_stock_competitor_information", "get_stock_daily", "get_stock_daily_post", "get_stock_daily_pre", "get_stock_detail", "get_stock_dividend", "get_stock_dividend_activity", "get_stock_dividend_amount", "get_stock_dividend_event", "get_stock_financial_activity", "get_stock_financial_event", "get_stock_industry", "get_stock_industry_median", "get_stock_insider_trade", "get_stock_insider_transaction", "get_stock_intermediary_information", "get_stock_investor_centralization", "get_stock_investor_concentration", "get_stock_investor_leaderboard", "get_stock_investor_ranking", "get_stock_ir_activity", "get_stock_ir_event", "get_stock_market_activity", "get_stock_market_event", "get_stock_meeting_activity", "get_stock_meeting_event", "get_stock_min", "get_stock_mktfin_indicator", "get_stock_mktfin_metric", "get_stock_ncycl_consensus", "get_stock_ncycl_estimate", "get_stock_operating_indicator", "get_stock_operating_metric", "get_stock_pledge", "get_stock_pledge_stat", "get_stock_private_placement", "get_stock_pv_indicator", "get_stock_pv_metric", "get_stock_recommendation_consensus", "get_stock_recommendation_estimate", "get_stock_rela_party_trans", "get_stock_rt_daily", "get_stock_rt_min", "get_stock_sector_median", "get_stock_shareholder_change", "get_stock_shareholder_holding", "get_stock_shareholder_report", "get_stock_split", "get_stock_status_change", "get_stock_status_over_allotment", "get_stock_top20_centralization", "get_stock_top20_concentration", "get_top_holders", "get_trade_cal", "get_trade_list", "get_us_daily", "get_us_detail"]
)

HARD_DISABLED = frozenset(
    {
        "get_factor_hk",
        "get_fund_daily",
        "get_fund_daily_post",
        "get_fund_daily_pre",
        "get_fund_detail",
        "get_fund_etf_constituents",
        "get_fund_etf_cr",
        "get_fund_etf_cr_limits",
        "get_fund_etf_cr_net",
        "get_index_component",
        "get_index_constituent",
        "get_market_data",
        "get_market_min_data",
        "get_option_daily",
        "get_option_exercise",
        "get_option_risk_indicators",
        "get_option_spot_market",
        "get_option_static",
        "get_stock_competitor_information",
        "get_stock_intermediary_information",
        "get_stock_rela_party_trans",
        "get_stock_status_over_allotment",
    }
)

NOT_DATA = frozenset({"get_client", "get_factory"})

VERIFIED_SCOPES: dict[str, tuple[frozenset[str], ...]] = {
    "get_last_trade_date": tuple(frozenset({scope}) for scope in ("SH", "HK", "US")),
    "get_trade_cal": tuple(frozenset({scope}) for scope in ("SH", "HK", "US")),
    "get_stock_rt_daily": (frozenset({"A_SHARE_STOCK"}),),
    "get_stock_daily": (frozenset({"A_SHARE_STOCK_ONLY"}),),
    "get_stock_min": (frozenset({"A_SHARE_STOCK", "frequency=1m"}),),
    "get_stock_rt_min": (frozenset({"A_SHARE_STOCK", "frequency=1m"}),),
    "get_stock_detail": (frozenset({"A_SHARE_STOCK_ONLY"}),),
    "get_hk_daily": (frozenset({"HK_EQUITY"}),),
    "get_hk_detail": (frozenset({"HK_EQUITY"}),),
    "get_us_daily": (frozenset({"US_EQUITY", "CLOSED_SESSION_ONLY"}),),
    "get_us_detail": (frozenset({"US_EQUITY"}),),
    "get_index_daily": (frozenset({"CN_INDEX"}),),
    "get_index_detail": (frozenset({"CN_INDEX"}),),
    "get_index_weights": (frozenset({"CN_INDEX"}),),
    "get_future_daily": (frozenset({"RESEARCH_ONLY"}),),
    "get_future_detail": (frozenset({"RESEARCH_ONLY"}),),
    "get_future_dominant": (frozenset({"RESEARCH_ONLY"}),),
    "get_option_detail": (frozenset({"RESEARCH_ONLY"}),),
    "get_option_underlying_detail": (frozenset({"RESEARCH_ONLY"}),),
    "get_option_underlying_volatility": (frozenset({"RESEARCH_ONLY"}),),
    "get_option_implied_volatility": (frozenset({"RESEARCH_ONLY"}),),
    "get_fina_reports": (frozenset({"CN_EQUITY"}),),
    "get_factor": (frozenset({"CN_EQUITY"}),),
    "get_industry_detail": (frozenset({"CN_EQUITY"}),),
    "get_industry_constituents": (frozenset({"CN_EQUITY"}),),
    "get_macro_detail": (frozenset({"RESEARCH_ONLY", "BOUNDED_FIELDS"}),),
    "get_macro_tr": (frozenset({"RESEARCH_ONLY"}),),
}


class CapabilityStatus(StrEnum):
    VERIFIED_ONCE_RESEARCH = "verified_once_research"
    DISABLED = "disabled"
    NOT_DATA = "not_data"


class RequestShape(BaseModel):
    """Canonical request shape built by typed adapters, never by API callers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    endpoint: str = Field(pattern=r"^get_[a-z0-9_]+$")
    scopes: frozenset[str]
    category: str = Field(min_length=1, max_length=64)
    frequency: str = Field(min_length=1, max_length=32)
    parameter_names: tuple[str, ...]
    constraints: tuple[str, ...]
    instrument_master_identity: str = Field(min_length=1, max_length=96)
    instrument_master_version: str = Field(min_length=64, max_length=64)

    @property
    def sha256(self) -> str:
        payload = self.model_dump(mode="json")
        payload["scopes"] = sorted(self.scopes)
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class CapabilityRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    endpoint: str = Field(pattern=r"^get_[a-z0-9_]+$")
    status: str = Field(
        pattern=r"^(verified_once_research|disabled|not_data)$"
    )
    reason: str
    verified_scope_sets: tuple[frozenset[str], ...] = ()
    allowed_request_shape_hashes: tuple[str, ...] = ()
    trade_eligible: bool = False
    stability_eligible: bool = False
    evidence_ref: str | None = None


class CapabilityCatalogError(RuntimeError):
    """Base error for catalog drift or disabled access."""


class SDKDriftError(CapabilityCatalogError):
    """Installed SDK differs from the audited SDK surface."""


class CapabilityDisabledError(CapabilityCatalogError):
    """Endpoint or requested scope has not passed capability verification."""


def endpoint_manifest_hash(endpoints: Iterable[str] = ALL_ENDPOINTS) -> str:
    return sha256("\n".join(sorted(endpoints)).encode()).hexdigest()


_SHAPE_SPECS: dict[str, tuple[str, str, tuple[str, ...], tuple[str, ...]]] = {
    "get_last_trade_date": (
        "calendar",
        "1d",
        ("exchange",),
        ("exchange_exact_scope",),
    ),
    "get_trade_cal": (
        "calendar",
        "1d",
        ("end_date", "exchange", "start_date"),
        ("bounded_date_range", "exchange_exact_scope"),
    ),
    "get_stock_rt_daily": (
        "snapshot",
        "snapshot",
        ("symbol",),
        ("cn_equity_master", "single_symbol"),
    ),
    "get_stock_daily": (
        "bar",
        "1d",
        ("end_date", "start_date", "symbol"),
        (
            "bounded_date_range",
            "cn_equity_master",
            "response_order=descending",
            "single_symbol",
        ),
    ),
    "get_stock_min": (
        "bar",
        "1m",
        ("end_date", "frequency", "start_date", "symbol"),
        (
            "bounded_date_range",
            "cn_equity_master",
            "frequency=1m",
            "response_order=descending",
            "single_symbol",
        ),
    ),
    "get_stock_rt_min": (
        "bar",
        "1m",
        ("frequency", "symbol"),
        ("cn_equity_master", "frequency=1m", "single_symbol"),
    ),
    "get_stock_detail": (
        "master",
        "static",
        ("symbol",),
        ("cn_equity_master", "bounded_symbols"),
    ),
    "get_hk_daily": (
        "bar",
        "1d",
        ("end_date", "start_date", "symbol"),
        (
            "bounded_date_range",
            "hk_equity_master",
            "response_order=descending",
            "single_symbol",
        ),
    ),
    "get_hk_detail": (
        "master",
        "static",
        ("symbol",),
        ("bounded_symbols", "hk_equity_master"),
    ),
    "get_us_daily": (
        "bar",
        "1d",
        ("end_date", "start_date", "symbol"),
        (
            "bounded_date_range",
            "closed_session_only",
            "response_order=descending",
            "single_symbol",
            "us_equity_master",
        ),
    ),
    "get_us_detail": (
        "master",
        "static",
        ("symbol",),
        ("bounded_symbols", "us_equity_master"),
    ),
    "get_index_daily": (
        "bar",
        "1d",
        ("end_date", "start_date", "symbol"),
        (
            "bounded_date_range",
            "cn_index_master",
            "response_order=descending",
            "single_symbol",
        ),
    ),
    "get_index_detail": (
        "master",
        "static",
        ("symbol",),
        ("bounded_symbols", "cn_index_master"),
    ),
    "get_index_weights": (
        "index_weight",
        "1d",
        ("end_date", "index_symbol", "start_date"),
        ("bounded_date_range", "cn_index_master", "single_index"),
    ),
    "get_future_daily": (
        "derivative_research",
        "1d",
        ("end_date", "start_date", "symbol"),
        ("bounded_date_range", "research_only"),
    ),
    "get_future_detail": (
        "derivative_research",
        "static",
        ("exchange", "fields", "is_trading", "symbol"),
        ("bounded_fields", "research_only"),
    ),
    "get_future_dominant": (
        "derivative_research",
        "1d",
        ("end_date", "start_date", "underlying_symbol"),
        ("bounded_date_range", "research_only"),
    ),
    "get_option_detail": (
        "derivative_research",
        "static",
        ("exchange", "fields", "option_type", "status", "symbol"),
        ("bounded_fields", "research_only"),
    ),
    "get_option_underlying_detail": (
        "derivative_research",
        "static",
        ("exchange", "fields", "symbol"),
        ("bounded_fields", "research_only"),
    ),
    "get_option_underlying_volatility": (
        "derivative_research",
        "1d",
        ("end_date", "exchange", "fields", "period", "start_date", "symbol"),
        ("bounded_date_range", "bounded_fields", "research_only"),
    ),
    "get_option_implied_volatility": (
        "derivative_research",
        "1d",
        ("end_date", "fields", "start_date", "symbol"),
        ("bounded_date_range", "bounded_fields", "research_only"),
    ),
    "get_fina_reports": (
        "financial",
        "event",
        ("date", "end_quarter", "fields", "is_latest", "start_quarter", "symbol"),
        ("bounded_fields", "cn_equity_master"),
    ),
    "get_factor": (
        "factor",
        "1d",
        ("end_date", "factors", "index_component", "start_date", "symbol", "type"),
        ("bounded_date_range", "bounded_factors", "cn_equity_master"),
    ),
    "get_industry_detail": (
        "industry",
        "static",
        ("fields", "level"),
        ("bounded_fields", "cn_industry"),
    ),
    "get_industry_constituents": (
        "industry",
        "static",
        ("fields", "industry_code", "level", "stock_symbol"),
        ("bounded_fields", "cn_equity_master"),
    ),
    "get_macro_detail": (
        "macro",
        "static",
        ("category", "fields", "symbol"),
        ("bounded_fields", "research_only"),
    ),
    "get_macro_tr": (
        "macro",
        "1d",
        ("end_date", "fields", "start_date", "symbol"),
        ("bounded_date_range", "bounded_fields", "research_only"),
    ),
}


def request_shape(
    endpoint: str,
    scopes: Iterable[str],
    *,
    parameter_names: Iterable[str] | None = None,
    instrument_master_identity: str = DEFAULT_INSTRUMENT_MASTER_IDENTITY,
    instrument_master_version: str = DEFAULT_INSTRUMENT_MASTER_VERSION,
) -> RequestShape:
    try:
        category, frequency, parameters, constraints = _SHAPE_SPECS[endpoint]
    except KeyError as error:
        raise CapabilityDisabledError(
            f"{endpoint} has no audited typed request shape"
        ) from error
    return RequestShape(
        endpoint=endpoint,
        scopes=frozenset(scopes),
        category=category,
        frequency=frequency,
        parameter_names=(
            tuple(sorted(parameter_names))
            if parameter_names is not None
            else parameters
        ),
        constraints=constraints,
        instrument_master_identity=instrument_master_identity,
        instrument_master_version=instrument_master_version,
    )


def _signature_hash(method: Any) -> str:
    signature = str(inspect.signature(method))
    return sha256(signature.encode()).hexdigest()


def _full_signature_hash(hashes: dict[str, str]) -> str:
    material = "\n".join(
        f"{endpoint}:{hashes[endpoint]}" for endpoint in sorted(hashes)
    )
    return sha256(material.encode()).hexdigest()


def _load_signature_manifest() -> tuple[dict[str, str], str]:
    path = (
        Path(__file__).resolve().parents[3]
        / "artifacts"
        / "pandadata-capabilities"
        / "endpoint-manifest-v1.json"
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SDKDriftError("audited SDK signature manifest is unavailable") from error
    hashes = {
        str(item["endpoint"]): str(item["signature_sha256"])
        for item in payload.get("endpoints", [])
    }
    if set(hashes) != set(ALL_ENDPOINTS):
        raise SDKDriftError("audited SDK signature manifest is incomplete")
    computed = _full_signature_hash(hashes)
    recorded = payload.get("full_signature_manifest_sha256")
    if recorded is None:
        raise SDKDriftError("audited SDK full signature manifest hash is missing")
    if recorded != computed:
        raise SDKDriftError("audited SDK signature manifest hash is invalid")
    return hashes, computed


class PandaDataCapabilityCatalog:
    """Single source of truth for all 213 audited SDK public methods."""

    def __init__(
        self,
        *,
        signature_hashes: dict[str, str] | None = None,
        full_signature_hash: str | None = None,
    ) -> None:
        if signature_hashes is None:
            signature_hashes, loaded_full_hash = _load_signature_manifest()
            full_signature_hash = full_signature_hash or loaded_full_hash
        computed_full_hash = _full_signature_hash(signature_hashes)
        if full_signature_hash != computed_full_hash:
            raise SDKDriftError("full SDK signature catalog hash mismatch")
        self._signature_hashes = dict(signature_hashes)
        self._full_signature_hash = computed_full_hash
        self._records = {
            endpoint: self._record(endpoint) for endpoint in ALL_ENDPOINTS
        }

    @classmethod
    def for_injected_test_sdk(cls, sdk: Any) -> PandaDataCapabilityCatalog:
        hashes = {
            endpoint: _signature_hash(getattr(sdk, endpoint))
            for endpoint in ALL_ENDPOINTS
        }
        return cls(
            signature_hashes=hashes,
            full_signature_hash=_full_signature_hash(hashes),
        )

    def all(self) -> tuple[CapabilityRecord, ...]:
        return tuple(self._records[name] for name in sorted(self._records))

    def get(self, endpoint: str) -> CapabilityRecord:
        record = self._records.get(endpoint)
        if record is None:
            raise CapabilityDisabledError(
                f"endpoint is outside audited SDK {EXPECTED_SDK_VERSION}: {endpoint}"
            )
        return record

    def validate_sdk(self, sdk: Any, *, sdk_version: str) -> None:
        actual = frozenset(name for name in dir(sdk) if name.startswith("get_"))
        expected = frozenset(ALL_ENDPOINTS)
        if sdk_version != EXPECTED_SDK_VERSION:
            raise SDKDriftError(
                f"SDK version drift: expected {EXPECTED_SDK_VERSION}, got {sdk_version}"
            )
        if actual != expected:
            added = sorted(actual - expected)
            removed = sorted(expected - actual)
            raise SDKDriftError(
                "SDK endpoint drift; fail closed; "
                f"added={added[:5]}, removed={removed[:5]}"
            )
        actual_hashes = {
            endpoint: _signature_hash(getattr(sdk, endpoint))
            for endpoint in ALL_ENDPOINTS
        }
        changed = sorted(
            endpoint
            for endpoint in ALL_ENDPOINTS
            if actual_hashes[endpoint] != self._signature_hashes[endpoint]
        )
        if changed or _full_signature_hash(actual_hashes) != self._full_signature_hash:
            raise SDKDriftError(
                f"SDK signature drift; fail closed; changed={changed[:5]}"
            )

    def authorize(
        self,
        endpoint: str,
        scopes: Iterable[str],
        shape: RequestShape,
    ) -> CapabilityRecord:
        record = self.get(endpoint)
        requested = frozenset(scopes)
        if record.status != CapabilityStatus.VERIFIED_ONCE_RESEARCH:
            raise CapabilityDisabledError(
                f"{endpoint} disabled: {record.reason}"
            )
        if requested not in record.verified_scope_sets:
            raise CapabilityDisabledError(
                f"{endpoint} scope was not verified: {sorted(requested)}"
            )
        if shape.endpoint != endpoint or shape.scopes != requested:
            raise CapabilityDisabledError(
                f"{endpoint} typed request shape does not match endpoint/scope"
            )
        if shape.sha256 not in record.allowed_request_shape_hashes:
            raise CapabilityDisabledError(
                f"{endpoint} request shape was not verified"
            )
        return record

    @staticmethod
    def _record(endpoint: str) -> CapabilityRecord:
        if endpoint in HARD_DISABLED:
            return CapabilityRecord(
                endpoint=endpoint,
                status=CapabilityStatus.DISABLED,
                reason="sdk_warning_deprecated_or_unreleased",
            )
        if endpoint in NOT_DATA:
            return CapabilityRecord(
                endpoint=endpoint,
                status=CapabilityStatus.NOT_DATA,
                reason="sdk_helper_not_data_endpoint",
            )
        scopes = VERIFIED_SCOPES.get(endpoint)
        if scopes is not None:
            shapes = tuple(
                request_shape(endpoint, scope).sha256 for scope in scopes
            )
            return CapabilityRecord(
                endpoint=endpoint,
                status=CapabilityStatus.VERIFIED_ONCE_RESEARCH,
                reason="single_probe_research_display_only_not_trade_eligible",
                verified_scope_sets=scopes,
                allowed_request_shape_hashes=shapes,
                trade_eligible=False,
                stability_eligible=False,
                evidence_ref=(
                    "artifacts/pandadata-capabilities/"
                    "verification-summary-v1.json"
                ),
            )
        return CapabilityRecord(
            endpoint=endpoint,
            status=CapabilityStatus.DISABLED,
            reason="not_probed",
        )


CATALOG = PandaDataCapabilityCatalog()
