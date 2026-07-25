from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from bridge.settings import Settings, get_settings

SettingsDependency = Annotated[Settings, Depends(get_settings)]


def require_admin(
    request: Request,
    settings: SettingsDependency,
) -> None:
    scheme, _, supplied = request.headers.get("Authorization", "").partition(" ")
    expected = settings.admin_token.get_secret_value()
    if scheme.lower() != "bearer" or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "valid Bridge bearer token required"},
        )


def require_idempotency_key(request: Request) -> str:
    value = request.headers.get("Idempotency-Key", "").strip()
    if not value or len(value) > 160:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_IDEMPOTENCY_KEY",
                "message": "Idempotency-Key is required and must be at most 160 characters",
            },
        )
    return value
