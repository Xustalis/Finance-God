"""Inspect and verify the unified agent registry and referenced skills."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .definitions import AGENT_DEFINITIONS, serialize_agent_definition


class CatalogError(RuntimeError):
    """Raised when registry artifacts or referenced sources are invalid."""


_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
_SOURCE_CATALOG_DIR = Path(__file__).resolve().parents[2] / "catalog"
_INSTALLED_CATALOG_DIR = Path(sys.prefix) / "agent_framework" / "catalog"


def _catalog_dir() -> Path:
    for candidate in (_SOURCE_CATALOG_DIR, _INSTALLED_CATALOG_DIR):
        if candidate.is_dir():
            return candidate
    raise CatalogError(
        "agent catalog is missing; install the package with its catalog data files"
    )


def agents() -> list[dict[str, Any]]:
    """Serialize the live registry; generated JSON is never a second source of truth."""

    return [serialize_agent_definition(definition) for definition in AGENT_DEFINITIONS]


def skills() -> list[dict[str, Any]]:
    path = _catalog_dir() / "skills.json"
    if not path.is_file():
        raise CatalogError(f"skill catalog is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def verify_catalog() -> dict[str, int]:
    missing = []
    source_catalog = _SOURCE_CATALOG_DIR.is_dir()
    if source_catalog:
        for definition in AGENT_DEFINITIONS:
            for source_path in (definition.source_path, definition.upstream_path):
                if not (_WORKSPACE_ROOT / source_path).exists():
                    missing.append(f"{definition.agent_id}:{source_path}")
        for item in skills():
            if item["source_path"] and not (
                _WORKSPACE_ROOT / item["source_path"]
            ).is_file():
                missing.append(f"{item['id']}:{item['source_path']}")
    if missing:
        raise CatalogError(f"catalog references missing sources: {', '.join(missing)}")

    generated_path = _catalog_dir() / "agents.json"
    if not generated_path.is_file():
        raise CatalogError(f"generated agent catalog is missing: {generated_path}")
    generated = json.loads(generated_path.read_text(encoding="utf-8"))
    if generated != agents():
        raise CatalogError(
            "generated agent catalog is stale; run scripts/build_agent_catalog.py"
        )
    return {"agents": len(AGENT_DEFINITIONS), "skills": len(skills()), "paths_valid": 1}


def resolve_skill(identifier: str) -> Path:
    for item in skills():
        if item["id"] == identifier:
            path = _WORKSPACE_ROOT / item["source_path"]
            if path.is_file():
                return path
            raise CatalogError(f"skill source is unavailable: {identifier}")
    raise CatalogError(f"unknown skill: {identifier}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--list", choices=("agents", "skills"))
    parser.add_argument("--resolve-skill")
    arguments = parser.parse_args()

    if arguments.verify:
        print(json.dumps(verify_catalog(), ensure_ascii=False))
        return 0
    if arguments.resolve_skill:
        print(resolve_skill(arguments.resolve_skill))
        return 0
    if arguments.list:
        values = agents() if arguments.list == "agents" else skills()
        print(json.dumps(values, ensure_ascii=False, indent=2))
        return 0
    parser.error("choose --verify, --list, or --resolve-skill")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
