"""Unified registry for all local agent definitions."""

from __future__ import annotations

from collections.abc import Iterable

from .contracts import AgentDefinition
from .definitions import AGENT_DEFINITIONS


class AgentRegistry:
    def __init__(self, definitions: Iterable[AgentDefinition] = AGENT_DEFINITIONS) -> None:
        values = tuple(definitions)
        self._definitions = {item.agent_id: item for item in values}
        if len(self._definitions) != len(values):
            raise ValueError("agent definitions must have unique identifiers")

    def get(self, agent_id: str) -> AgentDefinition:
        try:
            return self._definitions[agent_id]
        except KeyError as error:
            raise ValueError(f"unknown agent: {agent_id}") from error

    def list(self) -> tuple[AgentDefinition, ...]:
        return tuple(self._definitions.values())

    def __len__(self) -> int:
        return len(self._definitions)

