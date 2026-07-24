"""Command-line entry point for the unified VeriFolio agent runtime."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from .config import FmpSettings, PandaDataSettings, Settings
from .contracts import AgentAdapterKind, AgentRequest, AssetKind, ExecutionProfile
from .data_provider import PandaDataProvider
from .llm import OpenAICompatibleChat
from .models import EvidenceRecord
from .registry import AgentRegistry
from .router import AgentRouter
from .runner import AgentRunner


def _parse_evidence(raw_value: str) -> EvidenceRecord:
    parts = raw_value.split("|", 2)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("evidence must use ID|SOURCE|EXCERPT")
    return EvidenceRecord(identifier=parts[0], source=parts[1], excerpt=parts[2])


def _parse_payload(raw_value: str) -> dict[str, object]:
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError as error:
        raise argparse.ArgumentTypeError(f"payload must be valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError("payload must be a JSON object")
    return payload


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--task-type", required=True)
    parser.add_argument(
        "--profile",
        choices=[item.value for item in ExecutionProfile],
        default="research",
    )
    parser.add_argument("--asset-kind", choices=[item.value for item in AssetKind], default="other")
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--resource", action="append", default=[])
    parser.add_argument("--authorize-action", action="append", default=[])
    parser.add_argument("--agent-id", action="append", default=[])
    parser.add_argument("--evidence", action="append", type=_parse_evidence, default=[])
    parser.add_argument("--payload-json", type=_parse_payload, default={})
    parser.add_argument("--max-agents", type=int, default=8)
    return parser.parse_args(argv)


def _runner_for(request: AgentRequest) -> AgentRunner:
    registry = AgentRegistry()
    plan = AgentRouter(registry).plan(request)
    adapters = {registry.get(item.agent_id).adapter for item in plan.assignments}
    chat_client = (
        OpenAICompatibleChat(Settings.from_environment())
        if AgentAdapterKind.PROMPT in adapters
        else None
    )
    provider = (
        PandaDataProvider(PandaDataSettings.from_environment())
        if AgentAdapterKind.DETERMINISTIC_MONITOR in adapters
        else None
    )
    fmp_settings = (
        FmpSettings.from_environment()
        if AgentAdapterKind.FINROBOT_METRICS in adapters
        else None
    )
    return AgentRunner(
        registry=registry,
        chat_client=chat_client,
        data_provider=provider,
        fmp_settings=fmp_settings,
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)
    request = AgentRequest(
        run_id=arguments.run_id,
        subject=arguments.subject,
        task_type=arguments.task_type,
        profile=arguments.profile,
        asset_kind=arguments.asset_kind,
        tags=set(arguments.tag),
        available_resources=set(arguments.resource),
        authorized_actions=set(arguments.authorize_action),
        requested_agent_ids=arguments.agent_id,
        evidence=arguments.evidence,
        payload=arguments.payload_json,
        max_agents=arguments.max_agents,
    )
    result = _runner_for(request).run(request)
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
