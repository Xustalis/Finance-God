class DomainError(Exception):
    """Base error for explicit domain failures."""


class InvalidStateTransition(DomainError):
    def __init__(self, model_name: str, current: object, target: object) -> None:
        super().__init__(
            f"{model_name} cannot transition from {current!s} to {target!s}"
        )
        self.model_name = model_name
        self.current = current
        self.target = target


class DomainInvariantViolation(DomainError):
    """Raised when a command would create an invalid domain fact."""


class ConcurrentCommandConflict(DomainError):
    """Raised when an aggregate or projection revision changed concurrently."""


class ActiveWorkflowConflict(ConcurrentCommandConflict):
    """Raised when an owner already has a non-terminal workflow run."""

    def __init__(self, active_run_id: str) -> None:
        super().__init__("workflow owner already has an active run")
        self.active_run_id = active_run_id
