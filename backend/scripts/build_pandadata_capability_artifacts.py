"""Regenerate redacted PandaData capability artifacts from the live catalog."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from finance_god.market_data import (
    CATALOG,
    DEFAULT_INSTRUMENT_MASTER,
    PRODUCTION_AVAILABLE_ENDPOINTS,
)
from finance_god.market_data.capabilities import CAPABILITY_RESOURCE_DIR

_ARTIFACT_DIR = CAPABILITY_RESOURCE_DIR


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    manifest_path = _ARTIFACT_DIR / "endpoint-manifest-v1.json"
    verification_path = _ARTIFACT_DIR / "verification-summary-v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    records = {item.endpoint: item for item in CATALOG.all()}
    master_metadata = {
        "instrument_master_identity": DEFAULT_INSTRUMENT_MASTER.identity,
        "instrument_master_version": DEFAULT_INSTRUMENT_MASTER.version,
    }
    manifest.update(master_metadata)
    verification.update(master_metadata)

    for item in manifest["endpoints"]:
        record = records[item["endpoint"]]
        item.update(
            {
                "status": record.status,
                "reason": record.reason,
                "verified_scope_sets": [
                    sorted(scope) for scope in record.verified_scope_sets
                ],
                "allowed_request_shape_hashes": list(
                    record.allowed_request_shape_hashes
                ),
                "availability": record.availability,
                "category": record.category,
            }
        )

    production_endpoints = sorted(PRODUCTION_AVAILABLE_ENDPOINTS)
    manifest["production_available_endpoint_count"] = len(production_endpoints)
    manifest["production_available_endpoints"] = production_endpoints
    verified = []
    for record in records.values():
        if record.status != "verified_once_research":
            continue
        verified.append(
            {
                "endpoint": record.endpoint,
                "verified_scope_sets": [
                    sorted(scope) for scope in record.verified_scope_sets
                ],
                "result": "verified_once_research",
                "rows": {
                    "classification": "non_empty_at_probe",
                    "exact_count_retained": False,
                },
                "schema": {
                    "classification": "accepted_at_probe",
                    "field_names_retained": False,
                },
                "probe_time": {
                    "value": date.today().isoformat(),
                    "precision": "day",
                    "exact_time_retained": False,
                },
                "sdk_version": manifest["sdk_version"],
                "request_shape_sha256s": list(record.allowed_request_shape_hashes),
                "trade_eligible": False,
                "availability": record.availability,
                "category": record.category,
                "stability_confirmed": False,
            }
        )
    verification["verified"] = sorted(verified, key=lambda item: item["endpoint"])
    verification["probe_endpoint_count"] = len(verified)
    verification["production_available_endpoint_count"] = len(production_endpoints)
    verification["production_available_endpoints"] = production_endpoints
    _write(manifest_path, manifest)
    _write(verification_path, verification)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
