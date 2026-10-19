"""Pessimistic fill realism for paper/replay (T1.9, parameterized F0.4c).

Zero-slippage paper fills fabricate edge. This model walks the visible
book (worst covered level when depth is insufficient, plus an
empty-book penalty) and adds a latency penalty calibrated to measured
feed age. It never improves a price: buys pay >= book VWAP, sells
receive <= book VWAP.

F0.4c replaces the "always one tick adverse"
(FillModel(prob_slippage=1.0)) rule with PaperFillParams: an explicit,
versioned, provenance-stamped parameter set. Defaults are
ASSUMED-pessimistic (documented below, not measured). The calibration
path (F2.2 `cryptobot calibrate`) fits spread/slippage/latency from
demo-drill, paper and live fills and writes a versioned cost model;
the paper engine loads it via PaperFillParams.from_dict. Automatic
updates may only make costs MORE conservative; relaxing requires a
fresh verdict run.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PaperFillParameters:
    """Explicit adverse-fill model for paper/replay (F0.4c, F2.2).

    The old rule ("always slip exactly one tick") was unfalsifiable and
    ignored measured conditions. This model derives an expected adverse
    move in ticks from three measured inputs:

    * ``spread_bps`` — quoted spread at decision time (crossing cost);
    * ``depth_multiple`` — order qty / visible top-of-book qty (impact);
    * ``latency_ms`` — order-path latency, converted to drift with
      ``latency_drift_bps_per_s`` measured from the replay tape.

    ``floor_ticks`` keeps the model pessimistic when all measurements
    look benign (a fill is never better than one tick adverse), and
    ``cap_ticks`` bounds the paper simulator's one-tick Nautilus
    primitive. ``calibrate`` (F2.2) fits these parameters from recorded
    fills and may only make them MORE conservative automatically; a
    relaxation requires a fresh verdict run.
    """

    tick_size_bps: float = 1.0
    spread_bps: float = 2.0
    depth_multiple: float = 1.0
    latency_ms: float = 250.0
    latency_drift_bps_per_s: float = 2.0
    impact_bps_per_depth: float = 1.0
    floor_ticks: float = 1.0
    cap_ticks: float = 5.0

    def __post_init__(self) -> None:
        for name in ("tick_size_bps", "spread_bps", "latency_ms",
                     "latency_drift_bps_per_s", "impact_bps_per_depth",
                     "floor_ticks", "cap_ticks"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
            if value < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.depth_multiple < 1.0:
            raise ValueError("depth_multiple must be >= 1 (order/visible)")
        if self.tick_size_bps <= 0:
            raise ValueError("tick_size_bps must be > 0")
        if self.cap_ticks < self.floor_ticks:
            raise ValueError("cap_ticks must be >= floor_ticks")

    @property
    def adverse_bps(self) -> float:
        """Expected adverse price move in bps (never below floor)."""
        half_spread = self.spread_bps / 2.0
        impact = (self.depth_multiple - 1.0) * self.impact_bps_per_depth
        drift = self.latency_ms / 1000.0 * self.latency_drift_bps_per_s
        raw_ticks = (half_spread + impact + drift) / self.tick_size_bps
        return max(self.floor_ticks, min(self.cap_ticks, raw_ticks)) \
            * self.tick_size_bps

    @property
    def expected_ticks(self) -> float:
        return self.adverse_bps / self.tick_size_bps

    @property
    def slippage_probability(self) -> float:
        """Probability parameter for the one-tick Nautilus fill model.

        The simulator applies at most one tick, so this saturates at
        1.0; the bps value above is what replay/paper accounting and any
        stress report must use. Keeping >=1.0 is the conservative rule.
        """
        return min(1.0, self.expected_ticks)


@dataclass(frozen=True)
class PaperFillParams:
    """Versioned paper-fill parameters (F0.4c).

    Fields:
      version: schema version (1). Unknown versions refuse to load.
      spread_bps: round-trip spread cost proxy (half-spread x2).
      slippage_bps: adverse slippage per round trip (queue + impact).
      latency_ms_p95: p95 decision-to-ack latency driving the fill
        delay model and the latency_bps penalty term.
      latency_bps: adverse price drift applied per fill for latency.
      empty_book_bps: penalty per unit of uncovered quantity when
        visible depth cannot cover the order (thin-book conservatism).
      provenance: ASSUMED (defaults, pessimistic) or MEASURED
        (F2.2 calibration output with source/asof).
      source: calibration origin ("assumed-pessimistic", "demo-drill",
        "paper", "live") for audit.
      asof_utc: ISO timestamp of the calibration (None for defaults).
      fill_model_note: documents the nautilus FillModel mapping so the
        1-tick rule is never silently reintroduced.
    """

    version: int = 1
    spread_bps: float = 2.0
    slippage_bps: float = 6.0
    latency_ms_p95: int = 50
    latency_bps: float = 2.0
    empty_book_bps: float = 25.0
    provenance: str = "ASSUMED"
    source: str = "assumed-pessimistic"
    asof_utc: str | None = None
    fill_model_note: str = (
        "nautilus FillModel(prob_slippage=1.0) replaced: matching timing "
        "kept, fill economics set by these params (book-walk + latency "
        "penalty + audit top-up); see NautilusPaperEngine.slippage_audit")

    @classmethod
    def default_pessimistic(cls) -> PaperFillParams:
        """Conservative ASSUMED defaults (pre-calibration).

        Values mirror cost_model_v2 taker assumptions (2 spread + 6
        slip) plus a 2bps latency drift and 25bps thin-book penalty.
        Pessimistic by construction; F2.2 replaces with MEASURED.
        """
        return cls()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params


def pessimistic_fill_price(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def maker_fill(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def stressed_pnl(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"gross": float(gross_pnl), "costs_1x": float(costs_1x),
            "pnl_1x": float(gross_pnl) - float(costs_1x),
            "pnl_2x": float(gross_pnl) - 2.0 * float(costs_1x)}
