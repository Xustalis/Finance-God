from __future__ import annotations

import hashlib
import json


def canonical_request_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stable_idempotency_key(prefix: str, value: object) -> str:
    normalized_prefix = prefix.strip().strip(":")
    if not normalized_prefix:
        raise ValueError("idempotency key prefix is required")
    key = f"{normalized_prefix}:{canonical_request_hash(value)}"
    if len(key) > 160:
        raise ValueError("stable idempotency key exceeds 160 characters")
    return key
