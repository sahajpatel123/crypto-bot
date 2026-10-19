"""Structured metrics counters + JSON export (T3.4).

Counters the live trial needs on one screen: drops, stale marks,
unknown outcomes, protection gaps, slippage vs predicted, daily P&L.
JSON log lines are emitted by the Session checkpoint/alert stream;
this module is the in-process counter store behind the export.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

COUNTERS = ("feed_drops", "stale_marks", "unknown_outcomes",
            "protection_gaps", "drop_breaker_trips", "safe_modes")


class Metrics:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {k: 0 for k in COUNTERS}
        self.slippage_bps: list[float] = []
        self.daily_pnl_usdt: float = 0.0

    def inc(self, name: str, n: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + int(n)

    def note_slippage(self, predicted_bps: float, realized_bps: float) -> None:
        self.slippage_bps.append(float(realized_bps) - float(predicted_bps))

    def export(self) -> dict[str, Any]:
        slip = self.slippage_bps
        return {"counters": dict(self.counters),
                "slippage_vs_predicted_bps": {
                    "n": len(slip),
                    "mean": (sum(slip) / len(slip)) if slip else None,
                    "max": max(slip) if slip else None},
                "daily_pnl_usdt": self.daily_pnl_usdt}

    def write_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.export(), indent=1,
                                   sort_keys=True) + "\n")
        return path
