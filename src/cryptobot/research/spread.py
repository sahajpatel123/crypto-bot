"""Research spread-cost assumption profile + sensitivity (Worker 1, Q-007).

Archive data without quotes cannot build spread-bearing bars (see
``market_data/bars.py``: spreadless windows convert to ``None``) and the
simulator cannot cross an observed BBO. The ``research-spread-profile``
is the LABELED assumption used for such data: frozen per-symbol spreads
applied as explicitly-marked modeled quotes. Sensitivity analysis reruns
affected comparisons under spread multipliers {0.5x, 1x, 2x} and tabulates
metric deltas (see ``research/backtest.py``).

Hard rules (tested):

- Modeled quotes are marked ``quote_source = "research-spread-profile"``
  and are never presented as observed. Observed BBO is never modified.
- Only windows WITH trades but WITHOUT observed BBO receive a modeled
  quote (centered on window VWAP). Windows without trades stay missing —
  no activity is fabricated.
- S5 never consumes modeled quotes (S5 card: no synchronized observed
  views ⇒ ineligible with reasons). The profile exists for S1–S4 bar
  construction and simulator crosses only.
"""
from __future__ import annotations

from dataclasses import dataclass

PROFILE_ID = "research-spread-profile"
SENSITIVITY_MULTIPLIERS = (0.5, 1.0, 2.0)
MODELED_QTY = 10.0  # frozen modeled top-of-book size (labeled, not observed)

__all__ = [
    "MODELED_QTY",
    "PROFILE_ID",
    "SENSITIVITY_MULTIPLIERS",
    "SpreadProfile",
    "apply_profile",
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


def apply_profile(day_events: list[dict], symbol: str,
                  spread_bps: float) -> tuple[list[dict], dict]:
    """Insert labeled modeled BBO into quoteless trade windows.

    Returns (new_events, manifest). Input events are never mutated;
    modeled quotes sort into causal position (window_start + 100ms).
    """
    if spread_bps <= 0:
        raise ValueError("spread_bps must be > 0")
    halves: dict[int, list[tuple[float, float]]] = {}  # window -> [(px, qty)]
    quoted: set[int] = set()
    for e in day_events:
        if e.get("symbol") != symbol:
            continue
        window = (int(e["exchange_ts_ms"]) // 1000) * 1000
        if e.get("channel") == "bookTicker":
            quoted.add(window)
        elif e.get("channel") == "aggTrade":
            p = e["payload"]
            halves.setdefault(window, []).append(
                (float(p["price"]), float(p["qty"])))
    modeled = []
    for window in sorted(halves):
        if window in quoted or not halves[window]:
            continue
        notion = sum(px * q for px, q in halves[window])
        qty = sum(q for _, q in halves[window])
        mid = notion / qty if qty > 0 else halves[window][0][0]
        half = mid * spread_bps / 1e4 / 2
        modeled.append({
            "v": 1, "format": "cryptobot-events/1",
            "input_class": day_events[0].get("input_class", "observed-public"),
            "source": "research-spread-profile", "route": "modeled-quote",
            "run_id": day_events[0].get("run_id", ""),
            "seq": 0,  # renumbered by capture prep
            "channel": "bookTicker", "symbol": symbol,
            "exchange_ts_ms": window + 100, "local_recv_ms": window + 100,
            "local_mono_ns": 0, "gap_kind": None, "venue_seq": 0,
            "payload": {"bid": mid - half, "ask": mid + half,
                        "bid_qty": MODELED_QTY, "ask_qty": MODELED_QTY,
                        "quote_source": PROFILE_ID,
                        "spread_bps_assumed": spread_bps},
        })
    merged = list(day_events) + modeled
    merged.sort(key=lambda e: (int(e["exchange_ts_ms"]),
                               0 if e.get("channel") == "bookTicker" else 1))
    manifest = {
        "profile_id": PROFILE_ID,
        "symbol": symbol,
        "spread_bps_assumed": spread_bps,
        "trade_windows": len(halves),
        "observed_quote_windows": len(quoted & set(halves)),
        "modeled_windows": len(modeled),
        "modeled_quote": "all modeled quotes carry quote_source + spread_bps_assumed",
    }
    return merged, manifest
