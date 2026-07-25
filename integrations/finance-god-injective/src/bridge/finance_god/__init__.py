"""Read-only, explicitly triggered Finance-God integration."""

from .client import FinanceGodClient, FinanceGodError, SourceSnapshotProjection

__all__ = ["FinanceGodClient", "FinanceGodError", "SourceSnapshotProjection"]
