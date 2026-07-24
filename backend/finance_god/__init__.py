"""Finance-God package with lazily loaded orchestration exports."""

__version__ = "0.2.0"

__all__ = [
    "WORKFLOW_DEFINITIONS",
    "MultiAgentRuntime",
    "Orchestrator",
    "WorkflowArtifact",
    "WorkflowContext",
    "WorkflowExecutor",
    "WorkflowIntent",
    "WorkflowRun",
    "WorkflowStatus",
]


def __getattr__(name: str) -> object:
    """Load the Agent runtime only when an orchestration export is requested."""
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from . import orchestration

    value = getattr(orchestration, name)
    globals()[name] = value
    return value
