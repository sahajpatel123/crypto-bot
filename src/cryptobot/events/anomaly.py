"""Unscheduled-shock policy interface (Worker 4, EV-001).

Session measures market/feed stress (spread widening, book thinning,
abrupt returns, latency, exchange errors) and calls evaluate() before
admitting entries. The policy is a pure threshold/hysteresis/cooldown
function over caller-supplied readings: it never reads the market itself,
never places orders, and never liquidates. Panic liquidation on a
transient spike is NOT an action in this vocabulary; the strongest action
is halt-entries (exit-only for new risk, protection untouched).

Threshold defaults are explicit starting assumptions, labeled as such in
specs/events.md; they require development/validation tuning before any
live use.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

ACTIONS = ("allow", "reject-entries", "cancel-entries", "reduce-risk",
           "halt-entries")
_ACTION_RANK = {name: rank for rank, name in enumerate(ACTIONS)}


@dataclass(frozen=True)
class AnomalyConfig:
    spread_widen_bps: float = 25.0
    spread_baseline_window_s: int = 300
    book_thin_ratio: float = 0.3
    book_baseline_window_s: int = 300
    abs_return_bps: float = 50.0
    return_window_s: int = 60
    latency_ms: float = 2000.0
    exchange_errors: int = 3
    error_window_s: int = 60
    recovery_fraction: float = 0.5
    clear_streak: int = 3
    cooldown_s: int = 300

    def __post_init__(self) -> None:
        for name in ("spread_widen_bps", "book_thin_ratio",
                     "abs_return_bps", "latency_ms", "recovery_fraction"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        for name in ("spread_baseline_window_s", "book_baseline_window_s",
                     "return_window_s", "exchange_errors", "error_window_s",
                     "clear_streak", "cooldown_s"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        if not 0.0 < self.recovery_fraction < 1.0:
            raise ValueError("recovery_fraction must be in (0, 1)")
        if self.book_thin_ratio > 1.0:
            raise ValueError("book_thin_ratio must be <= 1")


@dataclass(frozen=True)
class AnomalyReading:
    spread_bps: float | None = None
    book_depth_ratio: float | None = None
    abs_return_bps: float | None = None
    latency_ms: float | None = None
    exchange_error_count: int = 0

    def __post_init__(self) -> None:
        if self.exchange_error_count < 0:
            raise ValueError("exchange_error_count must be >= 0")


@dataclass(frozen=True)
class AnomalyBaseline:
    spread_bps: float | None = None
    book_depth_notional: float | None = None


@dataclass
class AnomalyState:
    tripped: tuple[str, ...] = ()
    ok_streak: int = 0
    cooldown_until_utc: datetime | None = None


@dataclass(frozen=True)
class AnomalyDecision:
    action: str
    reason: str
    triggered: tuple[str, ...] = ()
    cooldown_until_utc: datetime | None = None

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise ValueError(f"unknown action: {self.action!r}")
        object.__setattr__(self, "triggered", tuple(self.triggered))
        if (self.cooldown_until_utc is not None
                and self.cooldown_until_utc.tzinfo is None):
            raise ValueError("cooldown_until_utc must be timezone-aware")


def _breaches(config: AnomalyConfig, reading: AnomalyReading,
              baseline: AnomalyBaseline) -> dict[str, str]:
    hits: dict[str, str] = {}
    if (reading.spread_bps is not None
            and reading.spread_bps >= config.spread_widen_bps):
        hits["spread"] = "reject-entries"
    if (reading.book_depth_ratio is not None
            and reading.book_depth_ratio <= config.book_thin_ratio):
        hits["book-thin"] = "reject-entries"
    if (reading.abs_return_bps is not None
            and reading.abs_return_bps >= config.abs_return_bps):
        hits["shock-return"] = "cancel-entries"
    if (reading.latency_ms is not None
            and reading.latency_ms >= config.latency_ms):
        hits["latency"] = "halt-entries"
    if reading.exchange_error_count >= config.exchange_errors > 0:
        hits["exchange-errors"] = "halt-entries"
    return hits


def _recovered(config: AnomalyConfig, name: str, reading: AnomalyReading,
               baseline: AnomalyBaseline) -> bool:
    margin = config.recovery_fraction
    if name == "spread":
        return (reading.spread_bps is not None
                and reading.spread_bps
                <= config.spread_widen_bps * margin)
    if name == "book-thin":
        floor = config.book_thin_ratio + (1.0 - config.book_thin_ratio) * (
            1.0 - margin)
        return (reading.book_depth_ratio is not None
                and reading.book_depth_ratio >= floor)
    if name == "shock-return":
        return (reading.abs_return_bps is not None
                and reading.abs_return_bps
                <= config.abs_return_bps * margin)
    if name == "latency":
        return (reading.latency_ms is not None
                and reading.latency_ms <= config.latency_ms * margin)
    if name == "exchange-errors":
        return reading.exchange_error_count == 0
    return True


def evaluate(config: AnomalyConfig, reading: AnomalyReading,
             baseline: AnomalyBaseline, state: AnomalyState,
             now_utc: datetime) -> AnomalyDecision:
    """Fold one reading into policy state and return the entry action.

    Hysteresis: a tripped signal clears only after ``clear_streak``
    consecutive recovered readings. Cooldown: after the trip set empties,
    the strongest recent action persists until ``cooldown_until_utc``.
    Missing (None) readings never trip and never clear a trip.
    """
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    hits = _breaches(config, reading, baseline)
    tripped = set(state.tripped)
    for name in hits:
        tripped.add(name)
    if hits:
        state.ok_streak = 0
    else:
        state.ok_streak += 1
        if state.ok_streak >= max(config.clear_streak, 1):
            for name in list(tripped):
                if _recovered(config, name, reading, baseline):
                    tripped.discard(name)
            if not tripped:
                state.ok_streak = 0
    if hits or tripped:
        state.cooldown_until_utc = now_utc + timedelta(
            seconds=config.cooldown_s)
    state.tripped = tuple(sorted(tripped))
    if not tripped:
        if state.cooldown_until_utc is not None \
                and now_utc < state.cooldown_until_utc:
            return AnomalyDecision(
                action="reject-entries", reason="anomaly:cooldown",
                triggered=(),
                cooldown_until_utc=state.cooldown_until_utc)
        return AnomalyDecision(action="allow", reason="anomaly:clear",
                               triggered=(),
                               cooldown_until_utc=state.cooldown_until_utc)
    worst = "allow"
    for name in tripped:
        action = hits.get(name)
        if action is None:
            action = {"spread": "reject-entries",
                      "book-thin": "reject-entries",
                      "shock-return": "cancel-entries",
                      "latency": "halt-entries",
                      "exchange-errors": "halt-entries"}[name]
        if _ACTION_RANK[action] > _ACTION_RANK[worst]:
            worst = action
    return AnomalyDecision(
        action=worst,
        reason=f"anomaly:{worst}:" + ",".join(state.tripped),
        triggered=state.tripped,
        cooldown_until_utc=state.cooldown_until_utc)
