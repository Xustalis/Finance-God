from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceSnapshotCreate(APIModel):
    plan_id: str = Field(min_length=1, max_length=160)


class PlanCreate(APIModel):
    side: str = Field(pattern=r"^(buy|sell)$")
    price: Decimal = Field(gt=0)
    quantity: Decimal = Field(gt=0)
    source_snapshot_id: str | None = Field(default=None, max_length=160)

    @field_serializer("price", "quantity")
    def serialize_decimal(self, value: Decimal) -> str:
        return format(value, "f")


class PlanConfirm(APIModel):
    expected_revision: int = Field(ge=1)


class ErrorBody(APIModel):
    code: str
    message: str


class ErrorResponse(APIModel):
    error: ErrorBody
