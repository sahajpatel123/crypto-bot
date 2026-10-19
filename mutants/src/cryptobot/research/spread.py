"""Research spread-cost assumption profile + sensitivity (Worker 1, Q-007/Q-008).

Archive data without quotes cannot build spread-bearing bars (see
``market_data/bars.py``: spreadless windows convert to ``None``) and the
simulator cannot cross an observed BBO. The ``research-spread-profile``
is the LABELED assumption used for such data: frozen per-symbol spreads
applied as explicitly-marked modeled quotes. Sensitivity analysis reruns
affected comparisons under spread multipliers {0.5x, 1x, 2x} and tabulates
metric deltas (see ``research/backtest.py``).

Causality (Q-008 correction): a modeled quote may use ONLY information
available by its own timestamp. Each quoteless trade window gets exactly
one modeled quote centered on that window's FIRST trade price and stamped
at that trade's timestamp — never full-window VWAP at window+100ms (which
let later trades move earlier quotes). Rule versioned as
``SPREAD_RULE``; changing later trades cannot move earlier quotes,
decisions, orders, or fills (tested: future-data invariance).

Hard rules (tested):

- Modeled quotes are marked ``quote_source = "research-spread-profile"``
  and are never presented as observed. Observed BBO is never modified.
- Only windows WITH trades but WITHOUT observed BBO receive a modeled
  quote. Windows without trades stay missing — no activity is fabricated.
- S5 never consumes modeled quotes (S5 card: no synchronized observed
  views ⇒ ineligible with reasons). The profile exists for S1–S4 bar
  construction and simulator crosses only.
"""
from __future__ import annotations

from dataclasses import dataclass

PROFILE_ID = "research-spread-profile"
SPREAD_RULE = "causal-first-trade-v1"
SENSITIVITY_MULTIPLIERS = (0.5, 1.0, 2.0)
MODELED_QTY = 10.0  # frozen modeled top-of-book size (labeled, not observed)

__all__ = [
    "MODELED_QTY",
    "PROFILE_ID",
    "SENSITIVITY_MULTIPLIERS",
    "SPREAD_RULE",
    "SpreadProfile",
    "apply_profile",
    "iter_with_spread",
    "profile_spread_bps",
    "sensitivity_spreads",
]


@dataclass(frozen=True)
class SpreadProfile:
    """Frozen spread assumption (bps) for quote-less archive data."""

    profile_id: str = PROFILE_ID
    default_bps: float = 1.0
    per_symbol_bps: tuple[tuple[str, float], ...] = ()
    multipliers: tuple[float, ...] = SENSITIVITY_MULTIPLIERS

    def __post_init__(self) -> None:
        if self.profile_id != PROFILE_ID:
            raise ValueError("profile_id must be 'research-spread-profile'")
        if self.default_bps <= 0:
            raise ValueError("default_bps must be > 0")
        for _, bps in self.per_symbol_bps:
            if bps <= 0:
                raise ValueError("per-symbol spread must be > 0")


def profile_spread_bps(profile: SpreadProfile, symbol: str) -> float:
    """Frozen spread for ``symbol`` (per-symbol override or default)."""
    for sym, bps in profile.per_symbol_bps:
        if sym == symbol:
            return bps
    return profile.default_bps


def sensitivity_spreads(profile: SpreadProfile,
                        symbol: str) -> dict[float, float]:
    """Multiplier → spread bps for the sensitivity reruns."""
    base = profile_spread_bps(profile, symbol)
    return {m: base * m for m in profile.multipliers}


def _modeled_quote(symbol: str, ts: int, mid: float, spread_bps: float,
                   input_class: str, run_id: str) -> dict:
    half = mid * spread_bps / 1e4 / 2
    return {
        "v": 1, "format": "cryptobot-events/1",
        "input_class": input_class, "source": PROFILE_ID,
        "route": "modeled-quote", "run_id": run_id,
        "seq": 0,  # renumbered by capture prep
        "channel": "bookTicker", "symbol": symbol,
        "exchange_ts_ms": ts, "local_recv_ms": ts,
        "local_mono_ns": 0, "gap_kind": None, "venue_seq": 0,
        "payload": {"bid": mid - half, "ask": mid + half,
                    "bid_qty": MODELED_QTY, "ask_qty": MODELED_QTY,
                    "quote_source": PROFILE_ID,
                    "spread_rule": SPREAD_RULE,
                    "spread_bps_assumed": spread_bps},
    }


def _channel_rank(channel: str) -> int:
    return 0 if channel == "bookTicker" else 1


def iter_with_spread(event_stream, symbol: str, spread_bps: float,
                     stats: dict | None = None):
    """Yield a time-ordered stream with causal modeled quotes interleaved.

    Single pass; holds one open 1 s window (bounded). Each quoteless
    trade window emits exactly one modeled quote (first-trade center at
    first-trade ts) when the window closes. ``stats`` (when given)
    accumulates trade/quoted/modeled window counts. Input must be
    time-ordered for the symbol; other symbols pass through untouched.
    """
    if spread_bps <= 0:
        raise ValueError("spread_bps must be > 0")
    window: int | None = None
    buffered: list[dict] = []
    first_trade: tuple[int, float] | None = None
    has_bbo = False
    input_class = "observed-public"
    run_id = ""

    def _flush():
        nonlocal buffered, first_trade, has_bbo
        if window is None:
            return
        if first_trade is not None and not has_bbo:
            ts, mid = first_trade
            buffered.append(_modeled_quote(symbol, ts, mid, spread_bps,
                                           input_class, run_id))
            if stats is not None:
                stats["modeled_windows"] = stats.get("modeled_windows", 0) + 1
        if stats is not None and first_trade is not None:
            stats["trade_windows"] = stats.get("trade_windows", 0) + 1
            if has_bbo:
                stats["observed_quote_windows"] = stats.get(
                    "observed_quote_windows", 0) + 1
        buffered.sort(key=lambda e: (int(e["exchange_ts_ms"]),
                                     _channel_rank(str(e.get("channel")))))
        yield from buffered
        buffered = []
        first_trade = None
        has_bbo = False

    for e in event_stream:
        if e.get("symbol") != symbol:
            yield e
            continue
        input_class = str(e.get("input_class", input_class))
        run_id = str(e.get("run_id", run_id))
        ts = int(e["exchange_ts_ms"])
        w = (ts // 1000) * 1000
        if window is None:
            window = w
        if w != window:
            yield from _flush()
            window = w
        buffered.append(e)
        if e.get("channel") == "bookTicker":
            has_bbo = True
        elif e.get("channel") == "aggTrade":
            if first_trade is None or ts < first_trade[0]:
                first_trade = (ts, float(e["payload"]["price"]))
    yield from _flush()


def apply_profile(day_events: list[dict], symbol: str,
                  spread_bps: float) -> tuple[list[dict], dict]:
    """Insert labeled modeled BBO into quoteless trade windows.

    Small-input convenience over :func:`iter_with_spread` (same causal
    rule). Large-scale assembly streams through ``iter_with_spread``
    directly and never materializes day lists.
    """
    stats: dict = {}
    ordered = sorted(day_events,
                     key=lambda e: (int(e["exchange_ts_ms"]),
                                    _channel_rank(str(e.get("channel")))))
    merged = list(iter_with_spread(iter(ordered), symbol, spread_bps,
                                   stats))
    merged.sort(key=lambda e: (int(e["exchange_ts_ms"]),
                               _channel_rank(str(e.get("channel")))))
    manifest = {
        "profile_id": PROFILE_ID,
        "spread_rule": SPREAD_RULE,
        "symbol": symbol,
        "spread_bps_assumed": spread_bps,
        "trade_windows": stats.get("trade_windows", 0),
        "observed_quote_windows": stats.get("observed_quote_windows", 0),
        "modeled_windows": stats.get("modeled_windows", 0),
        "modeled_quote": "all modeled quotes carry quote_source + spread_rule + spread_bps_assumed",
    }
    return merged, manifest
