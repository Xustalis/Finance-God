"""Desk bootstrap: one authenticated load for workspace shell state."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from inspect import isawaitable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from finance_god.api.auth import AuthenticationError, OwnerResolver

DeskSection = Literal["information", "portfolio", "watchlist", "trading"]
QuickCommandStage = Literal["initial", "after_answer", "after_workflow"]
_DESK_SECTIONS = frozenset(("information", "portfolio", "watchlist", "trading"))
_LOGGER = logging.getLogger(__name__)

ProfileProvider = Callable[[str], Awaitable[dict | None]]
QuickCommandProvider = Callable[
    [
        str,
        QuickCommandStage,
        DeskSection,
        str,
        str,
        "SuitabilityProfileProjection",
        str | None,
        dict | None,
    ],
    Awaitable[tuple[str, str, str]],
]
QuickCommandContextProvider = Callable[
    [str, QuickCommandStage, str],
    Awaitable[str | dict],
]
InstrumentNameProvider = Callable[[str], str]
# Live capability probe: only report True when the dependency is actually reachable.
# Static True is forbidden — callers must probe runtime / worker / market before enabling.
CapabilityProvider = Callable[[], dict[str, bool] | Awaitable[dict[str, bool]]]

# Policy defaults that never flip True from configuration alone.
_POLICY_CAPABILITIES: dict[str, bool] = {
    "workflow_claim": False,
    "ui_actions": True,
    "settings_excluded": True,
    "order_submit": False,
    "order_cancel": False,
    "fund_transfer": False,
}

SAFE_UI_ACTIONS: tuple[dict[str, str], ...] = (
    {
        "id": "navigate_information",
        "object": "workspace",
        "mutation": "ui_only",
        "descriptor_version": "1",
    },
    {
        "id": "navigate_portfolio",
        "object": "workspace",
        "mutation": "ui_only",
        "descriptor_version": "1",
    },
    {
        "id": "navigate_watchlist",
        "object": "workspace",
        "mutation": "ui_only",
        "descriptor_version": "1",
    },
    {
        "id": "navigate_trading",
        "object": "workspace",
        "mutation": "ui_only",
        "descriptor_version": "1",
    },
    {
        "id": "select_symbol",
        "object": "instrument",
        "mutation": "ui_only",
        "descriptor_version": "1",
    },
    {
        "id": "set_workspace_filter",
        "object": "workspace",
        "mutation": "ui_only",
        "descriptor_version": "1",
    },
    {
        "id": "set_workspace_sort",
        "object": "workspace",
        "mutation": "ui_only",
        "descriptor_version": "1",
    },
    {
        "id": "open_record",
        "object": "workspace_record",
        "mutation": "ui_only",
        "descriptor_version": "1",
    },
    {
        "id": "locate_candidate",
        "object": "research_candidate",
        "mutation": "ui_only",
        "descriptor_version": "1",
    },
    {
        "id": "fill_trade_draft",
        "object": "order_draft",
        "mutation": "draft_only",
        "descriptor_version": "1",
    },
    {
        "id": "refresh_market",
        "object": "market",
        "mutation": "ui_only",
        "descriptor_version": "1",
    },
    {
        "id": "open_workflow_artifact",
        "object": "workflow_artifact",
        "mutation": "ui_only",
        "descriptor_version": "1",
    },
    {
        "id": "open_reminder",
        "object": "reminder",
        "mutation": "ui_only",
        "descriptor_version": "1",
    },
    {
        "id": "open_trade_plan",
        "object": "trade_plan",
        "mutation": "ui_only",
        "descriptor_version": "1",
    },
)

_FORBIDDEN_PROFILE_KEYS = frozenset(
    {
        "password",
        "credential",
        "credentials",
        "token",
        "secret",
        "api_key",
        "settings",
    }
)


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SuitabilityProfileProjection(APIModel):
    """Desensitized investor projection safe for Agent/desk bootstrap."""

    version: int | None = None
    archetype_code: str | None = None
    archetype_title: str | None = None
    risk_level: str | None = None
    loss_tolerance_percent: float | None = None
    confidence: float | None = None
    completeness: float | None = None
    education_only: bool | None = None
    selected_direction: str | None = None
    recommended_directions: tuple[str, ...] = ()
    projection_version: str = "suitability-v1"
    available: bool = False
    degraded: bool = False


class UiActionDescriptor(APIModel):
    id: str
    object: str
    mutation: str
    descriptor_version: str = "1"


class DeskBootstrapResponse(APIModel):
    owner_id: str
    section: DeskSection
    symbol: str
    context_version: str
    profile_projection: SuitabilityProfileProjection
    ui_action_catalog: tuple[UiActionDescriptor, ...]
    capabilities: dict[str, bool]
    generated_at: datetime


class QuickCommandRequest(APIModel):
    stage: QuickCommandStage
    section: DeskSection
    symbol: str = Field(min_length=1, max_length=32)
    context_version: str = Field(min_length=1, max_length=160)
    decision_id: str | None = Field(default=None, min_length=1, max_length=160)
    run_id: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def require_stage_reference(self):
        if self.stage == "initial" and (
            self.decision_id is not None or self.run_id is not None
        ):
            raise ValueError("initial suggestions do not accept a result reference")
        if self.stage == "after_answer" and (
            self.decision_id is None or self.run_id is not None
        ):
            raise ValueError("after_answer requires only decision_id")
        if self.stage == "after_workflow" and (
            self.run_id is None or self.decision_id is not None
        ):
            raise ValueError("after_workflow requires only run_id")
        return self


class QuickCommandResponse(APIModel):
    quick_commands: tuple[str, ...]
    quick_commands_error: str | None = None
    generated_at: datetime


def create_desk_routes(
    *,
    owner_resolver: OwnerResolver,
    profile_provider: ProfileProvider | None = None,
    now: Callable[[], datetime] | None = None,
    default_symbol: str = "000001.SZ",
    workflow_worker_enabled: bool = True,
    capability_provider: CapabilityProvider | None = None,
    quick_command_provider: QuickCommandProvider | None = None,
    quick_command_context_provider: QuickCommandContextProvider | None = None,
    instrument_name_provider: InstrumentNameProvider | None = None,
) -> list[Route]:
    clock = now or (lambda: datetime.now(UTC))

    async def bootstrap(request: Request) -> JSONResponse:
        try:
            owner_id = await _owner(owner_resolver, request)
            section = _section(request)
            symbol = _symbol(request, default_symbol)
            generated_at = clock()
            projection, capabilities = await asyncio.gather(
                _profile_projection(profile_provider, owner_id),
                _resolve_capabilities(
                    capability_provider,
                    workflow_worker_enabled=workflow_worker_enabled,
                ),
            )
            context_version = (
                f"desk:{owner_id}:{section}:{symbol}:"
                f"{int(generated_at.timestamp())}"
            )
            body = DeskBootstrapResponse(
                owner_id=owner_id,
                section=section,
                symbol=symbol,
                context_version=context_version,
                profile_projection=projection,
                ui_action_catalog=tuple(
                    UiActionDescriptor.model_validate(item) for item in SAFE_UI_ACTIONS
                ),
                capabilities=capabilities,
                generated_at=generated_at,
            )
            return JSONResponse(body.model_dump(mode="json"))
        except Exception as error:  # noqa: BLE001 - HTTP boundary
            return _error_response(error)

    async def quick_commands(request: Request) -> JSONResponse:
        try:
            owner_id = await _owner(owner_resolver, request)
        except AuthenticationError as error:
            return JSONResponse(
                {"error": {"code": "UNAUTHORIZED", "message": str(error)}},
                status_code=401,
            )
        try:
            payload = QuickCommandRequest.model_validate(await request.json())
        except (ValidationError, ValueError) as error:
            return JSONResponse(
                {"error": {"code": "INVALID_REQUEST", "message": str(error)}},
                status_code=400,
            )
        try:
            expected_context = (
                f"desk:{owner_id}:{payload.section}:{payload.symbol}:"
            )
            if not payload.context_version.startswith(expected_context):
                return JSONResponse(
                    {
                        "error": {
                            "code": "STALE_CONTEXT",
                            "message": "页面上下文已经变化，请刷新后重试。",
                        }
                    },
                    status_code=409,
                )
            if quick_command_provider is None:
                raise RuntimeError("quick-command generation service is unavailable")
            answer_text: str | None = None
            workflow_evidence: dict | None = None
            reference = payload.decision_id or payload.run_id
            if reference is not None:
                if quick_command_context_provider is None:
                    raise RuntimeError("quick-command context service is unavailable")
                context = await quick_command_context_provider(
                    owner_id,
                    payload.stage,
                    reference,
                )
                if payload.stage == "after_answer":
                    if not isinstance(context, str):
                        raise RuntimeError("direct-answer context is invalid")
                    answer_text = context
                else:
                    if not isinstance(context, dict):
                        raise RuntimeError("workflow evidence context is invalid")
                    workflow_evidence = context
            projection = await _profile_projection(profile_provider, owner_id)
            generated_at = clock()
            generated = await quick_command_provider(
                owner_id,
                payload.stage,
                payload.section,
                payload.symbol,
                (
                    instrument_name_provider(payload.symbol)
                    if instrument_name_provider is not None
                    else payload.symbol
                ),
                projection,
                answer_text,
                workflow_evidence,
            )
            return JSONResponse(
                QuickCommandResponse(
                    quick_commands=generated,
                    generated_at=generated_at,
                ).model_dump(mode="json")
            )
        except Exception as error:  # noqa: BLE001 - visible optional feature boundary
            _LOGGER.error(
                "desk quick-command refresh failed: %s",
                type(error).__name__,
            )
            return JSONResponse(
                QuickCommandResponse(
                    quick_commands=(),
                    quick_commands_error=(
                        "快捷指令生成暂时不可用，请直接输入任务。"
                    ),
                    generated_at=clock(),
                ).model_dump(mode="json"),
                status_code=200,
            )

    async def apply_ui_action(request: Request) -> JSONResponse:
        """Apply a versioned safe UI action and return a formal receipt.

        Receipts are only ``applied``, ``rejected``, or ``stale_context``.
        Settings, order submit/cancel, fund transfer, and DOM selectors are never
        accepted — they are absent from ``SAFE_UI_ACTIONS`` and rejected if forged.
        """
        try:
            owner_id = await _owner(owner_resolver, request)
            try:
                payload = await request.json()
            except Exception as error:  # noqa: BLE001 - client body errors
                raise ValueError("request body must be valid JSON") from error
            command = UiActionCommand.model_validate(payload)
            generated_at = clock()
            catalog_ids = {item["id"] for item in SAFE_UI_ACTIONS}
            if command.action_id not in catalog_ids:
                return JSONResponse(
                    UiActionReceipt(
                        receipt="rejected",
                        action_id=command.action_id,
                        reason="action_not_in_catalog",
                        owner_id=owner_id,
                        applied_at=generated_at,
                    ).model_dump(mode="json")
                )
            if command.action_id in _FORBIDDEN_ACTION_IDS:
                return JSONResponse(
                    UiActionReceipt(
                        receipt="rejected",
                        action_id=command.action_id,
                        reason="action_forbidden",
                        owner_id=owner_id,
                        applied_at=generated_at,
                    ).model_dump(mode="json")
                )
            expected_prefix = f"desk:{owner_id}:"
            if not command.context_version.startswith(expected_prefix):
                return JSONResponse(
                    UiActionReceipt(
                        receipt="stale_context",
                        action_id=command.action_id,
                        reason="context_version_mismatch",
                        owner_id=owner_id,
                        applied_at=generated_at,
                    ).model_dump(mode="json")
                )
            invalid_reason = validate_action_parameters(
                command.action_id, command.parameters
            )
            if invalid_reason is not None:
                return JSONResponse(
                    UiActionReceipt(
                        receipt="rejected",
                        action_id=command.action_id,
                        reason=invalid_reason,
                        owner_id=owner_id,
                        parameters=command.parameters,
                        applied_at=generated_at,
                    ).model_dump(mode="json")
                )
            return JSONResponse(
                UiActionReceipt(
                    receipt="applied",
                    action_id=command.action_id,
                    reason=None,
                    owner_id=owner_id,
                    parameters=command.parameters,
                    applied_at=generated_at,
                ).model_dump(mode="json")
            )
        except Exception as error:  # noqa: BLE001 - HTTP boundary
            return _error_response(error)

    return [
        Route("/desk/bootstrap", bootstrap, methods=["GET"]),
        Route("/desk/quick-commands", quick_commands, methods=["POST"]),
        Route("/desk/ui-actions", apply_ui_action, methods=["POST"]),
    ]


# Never accept these even if a client forges them outside the catalog.
_FORBIDDEN_ACTION_IDS = frozenset(
    {
        "open_settings",
        "submit_order",
        "cancel_order",
        "fund_transfer",
        "login",
        "dom_click",
        "css_selector",
    }
)


class UiActionCommand(APIModel):
    action_id: str
    context_version: str
    parameters: dict[str, str] = {}


class UiActionReceipt(APIModel):
    receipt: Literal["applied", "rejected", "stale_context"]
    action_id: str
    reason: str | None = None
    owner_id: str
    parameters: dict[str, str] = {}
    applied_at: datetime


_SECTIONS = frozenset({"information", "portfolio", "watchlist", "trading"})
_DRAFT_SIDES = frozenset({"buy", "sell"})
_PRICE_TYPES = frozenset({"market", "limit"})
_CANDIDATE_TARGETS = frozenset({"watchlist", "research"})
_RECORD_TYPES = frozenset(
    {"position", "watchlist", "candidate", "draft", "order", "fill"}
)


def validate_action_parameters(
    action_id: str, parameters: dict[str, str]
) -> str | None:
    """Validate the public semantic action contract without interpreting selectors."""
    if any(
        key in parameters
        for key in ("selector", "css_selector", "xpath", "coordinates", "dom")
    ):
        return "selector_parameters_forbidden"
    if action_id.startswith("navigate_"):
        return None if action_id.removeprefix("navigate_") in _SECTIONS else "invalid_section"
    if action_id == "select_symbol":
        symbol = parameters.get("symbol", "").strip()
        return None if symbol and len(symbol) <= 32 else "invalid_symbol"
    if action_id == "refresh_market":
        return None
    if action_id in {"set_workspace_filter", "set_workspace_sort"}:
        section = parameters.get("section", "")
        field = parameters.get("field", "").strip()
        value = parameters.get("value", "").strip()
        return None if section in _SECTIONS and field and value else "invalid_workspace_control"
    if action_id == "open_record":
        return (
            None
            if parameters.get("record_type") in _RECORD_TYPES
            and parameters.get("record_id", "").strip()
            else "invalid_record"
        )
    if action_id == "locate_candidate":
        return (
            None
            if parameters.get("symbol", "").strip()
            and parameters.get("target") in _CANDIDATE_TARGETS
            else "invalid_candidate_target"
        )
    if action_id == "fill_trade_draft":
        side = parameters.get("side")
        price_type = parameters.get("price_type")
        quantity = parameters.get("quantity", "")
        try:
            valid_quantity = float(quantity) > 0
            valid_limit = price_type != "limit" or float(parameters.get("limit_price", "")) > 0
        except ValueError:
            return "invalid_trade_draft"
        return (
            None
            if side in _DRAFT_SIDES
            and price_type in _PRICE_TYPES
            and valid_quantity
            and valid_limit
            else "invalid_trade_draft"
        )
    if action_id in {"open_workflow_artifact", "open_reminder", "open_trade_plan"}:
        parameter_name = {
            "open_workflow_artifact": "artifact_id",
            "open_reminder": "reminder_id",
            "open_trade_plan": "plan_id",
        }[action_id]
        return None if parameters.get(parameter_name, "").strip() else "invalid_record"
    return "action_not_in_catalog"


def project_suitability_profile(raw: dict | None) -> SuitabilityProfileProjection:
    """Project raw investor profile into the desensitized desk/Agent contract.

    Drops secrets and raw questionnaire/objective fields. Safe for injection into
    Agent research payloads and DeskBootstrap.
    """
    if not raw:
        return SuitabilityProfileProjection(available=False, degraded=False)
    cleaned = {
        key: value
        for key, value in raw.items()
        if key not in _FORBIDDEN_PROFILE_KEYS
        and key not in _AGENT_EXCLUDED_PROFILE_KEYS
        and not str(key).startswith("secret")
    }
    directions = cleaned.get("recommended_directions") or ()
    if not isinstance(directions, (list, tuple)):
        directions = ()
    return SuitabilityProfileProjection(
        version=_as_int(cleaned.get("version")),
        archetype_code=_as_str(cleaned.get("archetype_code")),
        archetype_title=_as_str(cleaned.get("archetype_title")),
        risk_level=_as_str(cleaned.get("risk_level")),
        loss_tolerance_percent=_as_float(cleaned.get("loss_tolerance_percent")),
        confidence=_as_float(cleaned.get("confidence")),
        completeness=_as_float(cleaned.get("completeness")),
        education_only=_as_bool(cleaned.get("education_only")),
        selected_direction=_as_str(cleaned.get("selected_direction")),
        recommended_directions=tuple(str(item) for item in directions if item),
        available=True,
        degraded=False,
    )


# Raw questionnaire / objective detail must never reach Agent or desk bootstrap.
_AGENT_EXCLUDED_PROFILE_KEYS = frozenset(
    {
        "objective_profile",
        "dimension_scores",
        "answers",
        "questionnaire",
        "income",
        "raw_answers",
    }
)


async def _profile_projection(
    provider: ProfileProvider | None,
    owner_id: str,
) -> SuitabilityProfileProjection:
    if provider is None:
        return SuitabilityProfileProjection(available=False, degraded=True)
    try:
        raw = await provider(owner_id)
    except Exception:  # noqa: BLE001 - projection must degrade, not fail desk
        return SuitabilityProfileProjection(available=False, degraded=True)
    if not raw:
        return SuitabilityProfileProjection(available=False, degraded=False)
    return project_suitability_profile(raw)


def _section(request: Request) -> DeskSection:
    raw = request.query_params.get("section", "information").strip().lower()
    if raw in _DESK_SECTIONS:
        return raw  # type: ignore[return-value]
    raise ValueError("section must be information|portfolio|watchlist|trading")


def _symbol(request: Request, default_symbol: str) -> str:
    raw = request.query_params.get("symbol", default_symbol).strip().upper()
    if not raw or len(raw) > 32:
        raise ValueError("symbol is required and must be at most 32 characters")
    return raw


async def _owner(owner_resolver: OwnerResolver, request: Request) -> str:
    owner_id = (await owner_resolver(request)).strip()
    if not owner_id or len(owner_id) > 160:
        raise AuthenticationError("authenticated owner is required")
    return owner_id


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return None


async def _resolve_capabilities(
    capability_provider: CapabilityProvider | None,
    *,
    workflow_worker_enabled: bool,
) -> dict[str, bool]:
    """Merge policy defaults with live probe results.

    Without a provider, workflow create/worker stay False — never advertise them
    from a config flag alone. Policy denials (order_submit / order_cancel /
    fund_transfer / workflow_claim) stay False even if a provider lies.
    """
    del workflow_worker_enabled  # config alone is not evidence of a live worker
    capabilities: dict[str, bool] = {
        **_POLICY_CAPABILITIES,
        "workflow_create": False,
        "workflow_worker": False,
        "agent_answer": False,
        "market_data": False,
    }
    if capability_provider is None:
        return capabilities

    try:
        probed = capability_provider()
        if isawaitable(probed):
            probed = await probed
    except Exception:  # noqa: BLE001 - capability probe must degrade, not fail bootstrap
        return capabilities

    if not isinstance(probed, dict):
        return capabilities

    sticky_false = frozenset(
        {"order_submit", "order_cancel", "fund_transfer", "workflow_claim"}
    )
    for key, value in probed.items():
        if not isinstance(key, str) or not isinstance(value, bool):
            continue
        if key in sticky_false:
            capabilities[key] = False
            continue
        capabilities[key] = value

    for key in sticky_false:
        capabilities[key] = False
    capabilities["settings_excluded"] = True
    capabilities.setdefault("ui_actions", True)
    return capabilities


def _error_response(error: Exception) -> JSONResponse:
    if isinstance(error, ValidationError):
        return _error("VALIDATION_ERROR", str(error), 422)
    if isinstance(error, AuthenticationError):
        return _error("UNAUTHORIZED", str(error), 401)
    if isinstance(error, ValueError):
        return _error("INVALID_REQUEST", str(error), 400)
    raise error


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status_code,
    )


__all__ = [
    "CapabilityProvider",
    "DeskBootstrapResponse",
    "QuickCommandProvider",
    "SuitabilityProfileProjection",
    "UiActionCommand",
    "UiActionDescriptor",
    "UiActionReceipt",
    "create_desk_routes",
    "project_suitability_profile",
]
