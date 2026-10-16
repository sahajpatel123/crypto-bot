"""Runtime strategy boundary (Worker 1, Q-005).

Implements ``specs/app_runtime_interfaces.md`` S1: ``MarketView``,
``StrategyOutcome``, the ``RuntimeStrategy`` protocol, and one adapter per
strategy (S1..S5, production BASE arms). Import direction is app -> here;
the manager's selector consumes ``StrategyOutcome`` lists.

Conventions owned here:

- ``MarketView.quality_reason`` carries ``;``-joined data reasons; a
  missing ``depth``/``flow`` MUST be explained by a ``depth:``/``flow:``
  token (E-007 vocabulary), which S5 relays verbatim into rejections.
- ``evaluate`` is pure (no I/O) and uses only the caller-provided window
  plus the causal ``now_utc``; expiry/holding derive from evidence time.
- Every evaluation returns an ``Intent`` or an explicit ``reject_reason``
  shaped ``<stage>:<cause>``. When both sides reject, the two side reasons
  join with ``|`` (``"<long>|<short>"``). A reject-check value that already
  contains ``:`` (relayed E-007/sync reasons) keeps its shape verbatim.
- ``DataQuality.HALT`` rejects at the boundary; ``DEGRADED`` still
  evaluates (strategies are gap-tolerant and the window is caller-bounded).
- F1 alignment rule: ``bars`` carries positionally-aligned slots (``None`` =
  missing). Adapters pass the aligned list to the evaluators WITHOUT
  stripping — stripping compresses time and corrupts lookback windows.
  Evaluation anchors at the last present bar; trailing ``None``s never crash.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from cryptobot.coordination import (
    DataQuality,
    ExitPolicy,
    Intent,
    decode_exit_rule,
)

from .contract import (ARM_BASE, S2_BASE, S3_BASE, S4_BASE, S5_BASE, SC_BASE,
                       X1_BASE)
from .s1 import Bar, EvalLog, evaluate_bar as _s1_bar
from .s2 import evaluate_bar as _s2_bar
from .s3 import evaluate_bar as _s3_bar
from .s4 import evaluate_bar as _s4_bar
from .s5 import evaluate_view as _s5_view
from .sc import evaluate_bar as _sc_bar
from .x1 import evaluate_bar as _x1_bar

__all__ = [
    "ADAPTERS",
    "DepthView",
    "FlowView",
    "MarketView",
    "RuntimeStrategy",
    "StrategyOutcome",
    "get_adapter",
]


@dataclass(frozen=True)
class DepthView:
    """Synced-book features from the E-007 bridge (never extrapolated)."""

    best_bid: float
    best_ask: float
    bid_qty: float
    ask_qty: float
    spread_bps: float
    bid_notional: float
    ask_notional: float
    levels: int
    imbalance: float  # top-K (bid-ask)/(bid+ask) in [-1, 1]
    ts_utc: datetime


@dataclass(frozen=True)
class FlowView:
    """Signed trade aggregates over one causal window (E-007 bridge)."""

    buy_notional: float
    sell_notional: float
    buy_count: int
    sell_count: int
    vwap: float
    trade_count: int
    window_start_utc: datetime
    window_end_utc: datetime


@dataclass(frozen=True)
class MarketView:
    """Bounded causal market snapshot for one strategy evaluation."""

    instrument: str
    bars: tuple[Bar | None, ...]  # aligned slots, oldest->newest; None = missing
    now_utc: datetime  # availability/causal time, tz-aware
    depth: DepthView | None  # synchronized book features or None + reason
    flow: FlowView | None  # signed trade aggregates or None + reason
    quality: DataQuality
    quality_reason: str = ""
    # Dual-symbol reference leg (X1.md §4; other families ignore).
    # Leader aligned slots + symbol + frozen beta, or all-None.
    ref_bars: tuple[Bar | None, ...] | None = None
    ref_instrument: str | None = None
    ref_beta: float | None = None

    def __post_init__(self) -> None:
        if not self.instrument:
            raise ValueError("MarketView.instrument must be non-empty")
        if self.now_utc.tzinfo is None:
            raise ValueError("MarketView.now_utc must be tz-aware")


@dataclass(frozen=True)
class StrategyOutcome:
    """One strategy's verdict: exactly one of intent / reject_reason set."""

    intent: Intent | None  # exactly one of intent / reject_reason set
    reject_reason: str = ""  # machine-readable: <stage>:<cause>
    exit_policy: ExitPolicy | None = None

    def __post_init__(self) -> None:
        if (self.intent is None) == (not self.reject_reason):
            raise ValueError("exactly one of intent / reject_reason must be set")


class RuntimeStrategy(Protocol):
    """S1 seam: pure per-cycle strategy evaluation."""

    strategy_id: str  # S1..S5 arm id from contract.ARM_IDS (+S5 arms)

    def evaluate(self, view: MarketView) -> StrategyOutcome: ...


def _last_present(bars: tuple[Bar | None, ...]) -> int | None:
    """Newest present-bar index, or None when no bar is present."""
    for i in range(len(bars) - 1, -1, -1):
        if bars[i] is not None:
            return i
    return None


def _gate_view(view: MarketView) -> str:
    """Boundary pre-gates; returns a reject reason or ``""`` to proceed."""
    if view.quality is DataQuality.HALT:
        return f"quality:{view.quality_reason or 'halt'}"
    t = _last_present(view.bars)
    if t is None:
        return "quality:empty-window"
    newest = view.bars[t]
    assert newest is not None
    if newest.ts_utc > view.now_utc:
        return "stale:bar-newer-than-now"
    return ""


def _side_reason(log: EvalLog) -> str:
    """First non-pass reject entry as ``<stage>:<cause>`` (verbatim if pre-shaped)."""
    for entry in log.rejects:
        stage, _, value = entry.partition("=")
        if value == "pass":
            continue
        return value if ":" in value else f"{stage}:{value}"
    return "unknown:no-intent"


def _finish(long_log_intent: tuple[EvalLog, Intent | None],
            short_log_intent: tuple[EvalLog, Intent | None]) -> StrategyOutcome:
    """First intent (long priority) wins; double reject joins both reasons."""
    for log, intent in (long_log_intent, short_log_intent):
        if intent is not None:
            try:
                policy = decode_exit_rule(intent.exit_rule)
            except ValueError:
                return StrategyOutcome(None, "exit:undecodable-rule")
            return StrategyOutcome(intent, "", policy)
    long_reason = _side_reason(long_log_intent[0])
    short_reason = _side_reason(short_log_intent[0])
    return StrategyOutcome(None, f"{long_reason}|{short_reason}")


class _BarsStrategy:
    """Adapter for bar-only strategies (S1..S4, BASE arm)."""

    def __init__(self, strategy_id: str, arm: str, evaluate_bar) -> None:
        self.strategy_id = strategy_id
        self._arm = arm
        self._evaluate_bar = evaluate_bar

    def evaluate(self, view: MarketView) -> StrategyOutcome:
        gate = _gate_view(view)
        if gate:
            return StrategyOutcome(None, gate)
        # Aligned list passed WITHOUT stripping (F1); anchor at last present.
        bars = list(view.bars)
        t = _last_present(view.bars)
        assert t is not None  # gated above
        long_d, short_d = self._evaluate_bar(bars, t, self._arm,
                                             view.instrument)
        return _finish((long_d.evaluation, long_d.intent),
                       (short_d.evaluation, short_d.intent))


class _S5Strategy:
    """Adapter for the microstructure baseline (S5 arm)."""

    strategy_id = S5_BASE

    def evaluate(self, view: MarketView) -> StrategyOutcome:
        gate = _gate_view(view)
        if gate:
            return StrategyOutcome(None, gate)
        long_d, short_d = _s5_view(view, S5_BASE, view.instrument)
        return _finish((long_d.evaluation, long_d.intent),
                       (short_d.evaluation, short_d.intent))


class _X1Strategy:
    """Adapter for the leader-laggard base arm (X1.md §4+§5).

    Reads the laggard bars plus the reference leg (leader bars +
    frozen beta) off the view. A missing reference leg or beta
    no-fires inside the evaluator (recorded reasons, never errors).
    """

    strategy_id = X1_BASE

    def evaluate(self, view: MarketView) -> StrategyOutcome:
        gate = _gate_view(view)
        if gate:
            return StrategyOutcome(None, gate)
        bars = list(view.bars)
        t = _last_present(view.bars)
        assert t is not None  # gated above
        ref = list(view.ref_bars) if view.ref_bars is not None else None
        long_d, short_d = _x1_bar(bars, t, X1_BASE, view.instrument,
                                  ref_bars=ref, beta=view.ref_beta)
        return _finish((long_d.evaluation, long_d.intent),
                       (short_d.evaluation, short_d.intent))


ADAPTERS: tuple[RuntimeStrategy, ...] = (
    _BarsStrategy(ARM_BASE, ARM_BASE, _s1_bar),
    _BarsStrategy(S2_BASE, S2_BASE, _s2_bar),
    _BarsStrategy(S3_BASE, S3_BASE, _s3_bar),
    _BarsStrategy(S4_BASE, S4_BASE, _s4_bar),
    _S5Strategy(),
    _BarsStrategy(SC_BASE, SC_BASE, _sc_bar),
    _X1Strategy(),
)


def get_adapter(strategy_id: str) -> RuntimeStrategy:
    """Return the runtime adapter for ``strategy_id`` (KeyError if unknown)."""
    for adapter in ADAPTERS:
        if adapter.strategy_id == strategy_id:
            return adapter
    raise KeyError(f"unknown runtime strategy {strategy_id!r}")
