---
name: agent-framework-router
description: Discover, validate, plan, and run VeriFolio's unified local TradingAgents, FinRobot, and QuantSkills agents.
---

# Agent Framework Router

Use the unified registry as the only Agent source of truth.

1. Run `agent_framework/.venv/bin/python -m research_runtime.catalog --verify`.
2. Read `agent_framework/catalog/agent-table.md` and use the exact `agent_id`.
3. Route automatically with an `AgentRequest`, or set `requested_agent_ids` to call named Agents.
4. Never bypass `minimum_profile`, `required_resources`, or per-task `authorized_actions`.
5. Treat prompt `proposed_actions` as review requests, not completed side effects.
6. Do not register accounts, publish, start CTP, copy positions, synchronize trades, or place or
   cancel orders unless a concrete external adapter exists and the user explicitly authorizes that
   exact action for the current run.

Regenerate review artifacts with
`agent_framework/.venv/bin/python agent_framework/scripts/build_agent_catalog.py` after definitions
change. Skill descriptors remain reference instructions and do not grant external permissions.

