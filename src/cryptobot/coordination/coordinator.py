"""Minimal coordinator: dedup same-direction, stand aside on opposing (manager-owned)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .intent import Intent


@dataclass(frozen=True)
class CoordinatorDecision:
    accepted: Intent | None
    rejected: tuple[Intent, ...]
    reason: str


class Coordinator:
    def select(self, intents: list[Intent], now_utc: datetime | None = None) -> CoordinatorDecision:
        now = now_utc or datetime.now(UTC)
        valid = [i for i in intents if i.entry_expiry_utc >= now and i.data_quality != "halt"]
        if not valid:
            return CoordinatorDecision(None, tuple(intents), "no-valid-intents")
        by_key: dict[tuple[str, str], Intent] = {}
        for intent in valid:
            key = (intent.instrument, intent.side.value)
            if key not in by_key:
                by_key[key] = intent
        instruments: dict[str, set[str]] = {}
        for (symbol, side) in by_key:
            instruments.setdefault(symbol, set()).add(side)
        for symbol, sides in instruments.items():
            if len(sides) > 1:
                return CoordinatorDecision(None, tuple(intents), f"opposing-signals-stand-aside:{symbol}")
        first = valid[0]
        chosen = by_key[(first.instrument, first.side.value)]
        rejected = tuple(i for i in intents if i is not chosen)
        return CoordinatorDecision(chosen, rejected, "single-owner-selected")
