"""Version tracking utilities for all versioned domain objects.

Per PRD BR-03: All core objects must have version fields for full traceability.
Every domain object (portfolio, strategy, mandate, etc.) carries an integer
version that increments on each mutation, enabling audit trails and
optimistic-concurrency checks.
"""


def compute_next_version(current_version: int) -> int:
    """Return the next sequential version number.

    Args:
        current_version: The current version (must be >= 0).

    Returns:
        current_version + 1.

    Raises:
        ValueError: If current_version is negative.
    """
    if current_version < 0:
        raise ValueError(f"Version must be non-negative, got {current_version}")
    return current_version + 1


def validate_version_chain(versions: list[int]) -> bool:
    """Check that versions form a consecutive sequence starting from 1.

    This is used to verify the integrity of a version history — e.g. when
    loading all versions of a strategy from the database.

    Args:
        versions: Ordered list of version numbers.

    Returns:
        True if versions == [1, 2, ..., n], False otherwise.
    """
    if not versions:
        return False
    return versions == list(range(1, len(versions) + 1))
