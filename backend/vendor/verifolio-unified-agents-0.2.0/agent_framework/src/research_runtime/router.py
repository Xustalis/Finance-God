"""Deterministic capability routing over the unified agent registry."""

from __future__ import annotations

from .contracts import (
    AgentAssignment,
    AgentDefinition,
    AgentPlan,
    AgentRequest,
    RoutingNotice,
)
from .registry import AgentRegistry


class AgentRoutingError(ValueError):
    """Raised when an explicitly requested agent cannot be authorized."""


class AgentRouter:
    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    def plan(self, request: AgentRequest) -> AgentPlan:
        if request.requested_agent_ids:
            return self._explicit_plan(request)
        return self._automatic_plan(request)

    def _explicit_plan(self, request: AgentRequest) -> AgentPlan:
        assignments = []
        for agent_id in request.requested_agent_ids:
            definition = self._registry.get(agent_id)
            self._require_authorized(definition, request)
            assignments.append(
                AgentAssignment(agent_id=agent_id, reason="explicitly requested by caller")
            )
        return AgentPlan(run_id=request.run_id, assignments=assignments)

    def _automatic_plan(self, request: AgentRequest) -> AgentPlan:
        assignments: list[AgentAssignment] = []
        notices: list[RoutingNotice] = []
        definitions = sorted(self._registry.list(), key=lambda item: (item.priority, item.agent_id))
        for definition in definitions:
            if not self._matches(definition, request):
                continue
            if not request.profile.allows(definition.minimum_profile):
                notices.append(
                    RoutingNotice(
                        agent_id=definition.agent_id,
                        reason=(
                            f"requires {definition.minimum_profile.value} execution profile"
                        ),
                    )
                )
                continue
            missing_authorizations = sorted(
                definition.authorization_by_task.get(request.task_type, set())
                - request.authorized_actions
            )
            if missing_authorizations:
                notices.append(
                    RoutingNotice(
                        agent_id=definition.agent_id,
                        reason="matched but explicit per-run authorization is missing",
                        missing_authorizations=missing_authorizations,
                    )
                )
                continue
            missing = sorted(definition.required_resources - request.available_resources)
            if missing:
                notices.append(
                    RoutingNotice(
                        agent_id=definition.agent_id,
                        reason="matched but required resources are unavailable",
                        missing_resources=missing,
                    )
                )
                continue
            if len(assignments) >= request.max_agents:
                notices.append(
                    RoutingNotice(
                        agent_id=definition.agent_id,
                        reason="matched after the run's max_agents limit was reached",
                    )
                )
                continue
            assignments.append(
                AgentAssignment(agent_id=definition.agent_id, reason="capability route matched")
            )
        if not assignments:
            details = "; ".join(
                f"{notice.agent_id}: {notice.reason}"
                + (
                    f" ({', '.join(notice.missing_resources)})"
                    if notice.missing_resources
                    else ""
                )
                + (
                    f" ({', '.join(notice.missing_authorizations)})"
                    if notice.missing_authorizations
                    else ""
                )
                for notice in notices
            )
            raise AgentRoutingError(f"no authorized agent matched the request: {details}")
        return AgentPlan(run_id=request.run_id, assignments=assignments, notices=notices)

    @staticmethod
    def _matches(definition: AgentDefinition, request: AgentRequest) -> bool:
        if not definition.auto_select or request.task_type not in definition.task_types:
            return False
        if definition.asset_kinds and request.asset_kind not in definition.asset_kinds:
            return False
        if definition.always_active:
            return True
        return bool(definition.routing_tags.intersection(request.tags))

    @staticmethod
    def _require_authorized(definition: AgentDefinition, request: AgentRequest) -> None:
        if not request.profile.allows(definition.minimum_profile):
            raise AgentRoutingError(
                f"{definition.agent_id} requires {definition.minimum_profile.value} "
                "execution profile"
            )
        missing_authorizations = sorted(
            definition.authorization_by_task.get(request.task_type, set())
            - request.authorized_actions
        )
        if missing_authorizations:
            raise AgentRoutingError(
                f"{definition.agent_id} requires explicit authorization for: "
                f"{', '.join(missing_authorizations)}"
            )
        missing = sorted(definition.required_resources - request.available_resources)
        if missing:
            raise AgentRoutingError(
                f"{definition.agent_id} requires unavailable resources: {', '.join(missing)}"
            )
