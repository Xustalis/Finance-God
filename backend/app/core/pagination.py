"""统一分页工具"""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PageRequest(BaseModel):
    page: int = 1
    page_size: int = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class PageResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int

    @classmethod
    def create(cls, items: list[T], total: int, page: int, page_size: int) -> "PageResponse[T]":
        return cls(items=items, total=total, page=page, page_size=page_size)
