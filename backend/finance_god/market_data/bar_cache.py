"""Persistent normalized bar cache owned by the market-data boundary."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import Lock
from time import time
from typing import Any


class PersistentBarCache:
    """Store complete normalized bar responses by symbol and frequency."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS market_bar_cache (
                    symbol TEXT NOT NULL,
                    frequency TEXT NOT NULL,
                    fetched_at REAL NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (symbol, frequency)
                )
                """
            )

    def get(
        self,
        symbol: str,
        frequency: str,
    ) -> tuple[float, dict[str, Any]] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT fetched_at, payload
                FROM market_bar_cache
                WHERE symbol = ? AND frequency = ?
                """,
                (symbol, frequency),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[1])
        if not isinstance(payload, dict):
            raise ValueError("cached market bars payload must be an object")
        return float(row[0]), payload

    def put(self, symbol: str, frequency: str, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO market_bar_cache(symbol, frequency, fetched_at, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(symbol, frequency) DO UPDATE SET
                    fetched_at = excluded.fetched_at,
                    payload = excluded.payload
                """,
                (symbol, frequency, time(), encoded),
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=10)
