# Third-party notices

## TradingAgents

The local registry contains an independent, evidence-only reimplementation of 12 role
responsibilities and their broad ordering from
`references/projects/tradingagents` (Apache-2.0, fixed reference commit
`a33fd4c0f134485a43553a2c23a63cb14adbd88f`). It does not import the upstream market-data,
memory, recommendation, or execution runtime.

## FinRobot

The registry independently adapts 10 library roles and 8 equity-report responsibilities from the
local FinRobot reference (Apache-2.0 and its NOTICE). Local prompts are constrained to caller
evidence and the unified structured result contract; upstream AutoGen/OpenAI Agents tools and
trading paths are not imported.

The optional FMP metrics adapter invokes a local compatibility subprocess and dynamically loads
FinRobot's financial-data processor. Credentials are passed only through the process environment;
captured stdout/stderr are not persisted. Artifacts are written only under
`agent_framework/live-runs/finrobot/`.

## QuantSkills

Four deterministic Monitor adapters and the QuantSkills workflow-role definitions were written
against the public Agent/SKILL contracts in `references/projects/quantskills-agents`. GPL-3.0
scripts, report templates, strategy implementations, and execution code are not imported or
copied into this runtime.

The Liangshuyuan task package declares MIT terms in its Agent contract. Its roles are re-expressed
through the same structured prompt adapter. Publication and CTP/order actions are not implemented;
their declared names remain explicit per-run authorization gates.

## PandaData

The PandaData integration calls the public `panda_data` SDK through a fixed read-only dataset
allowlist. Raw provider records are excluded from serialized Agent artifacts. Authentication,
missing dependencies, invalid fields, empty results, and provider failures remain explicit errors.

