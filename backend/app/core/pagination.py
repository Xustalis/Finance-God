"""Unified pagination utilities.

Provides a generic ``PaginatedResponse`` Pydantic model and helper functions
used by every list endpoint to ensure a consistent pagination contract
across the entire API.
"""

from __future__ import annotations

import math
from typing import Any, Generic, Sequence, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard paginated list response returned by all list endpoints.

    Attributes:
        items: The page of results.
        total: Total number of matching records.
        page: Current 1-based page number.
        page_size: Requested page size.
        total_pages: Computed total number of pages.
    """

    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int


def paginate(items: Sequence[Any], total: int, page: int, page_size: int) -> dict[str, Any]:
    """Build a pagination dict from query results.

    The returned dict matches the ``PaginatedResponse`` schema and can be
    passed directly to ``PaginatedResponse(**paginate(...))`` or returned
    as-is from a FastAPI endpoint.

    Args:
        items: The slice of results for the current page.
        total: Total number of matching records (usually from ``COUNT(*)``).
        page: Current 1-based page number.
        page_size: Requested page size.

    Returns:
        A dict with keys ``items``, ``total``, ``page``, ``page_size``,
        ``total_pages``.
    """
    return {
        "items": list(items),
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size) if page_size > 0 else 0,
    }


def get_offset(page: int, page_size: int) -> int:
    """Compute the SQL ``OFFSET`` value from 1-based page and page size.

    Args:
        page: 1-based page number (must be >= 1).
        page_size: Number of items per page (must be >= 1).

    Returns:
        Zero-based offset.
    """
    return (max(page, 1) - 1) * page_size
