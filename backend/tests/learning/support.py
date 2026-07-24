from __future__ import annotations

from types import SimpleNamespace


def bars(closes: list[float]) -> tuple[SimpleNamespace, ...]:
    return tuple(
        SimpleNamespace(
            time=f"2026-01-{index + 1:02d}",
            open=value,
            high=value + 1.0,
            low=value - 1.0,
            close=value,
            volume=1_000.0,
            freshness="fresh",
            provider_time=f"2026-01-{index + 1:02d}",
        )
        for index, value in enumerate(closes)
    )


class Reader:
    def __init__(self, values: tuple[SimpleNamespace, ...]) -> None:
        self.values = values
        self.calls = 0

    def read_bars(self, symbol: str, *, limit: int):
        del symbol
        self.calls += 1
        return SimpleNamespace(
            bars=self.values[-limit:],
            quality=SimpleNamespace(frozen=False),
            frequency="日频",
            error_message=None,
        )
