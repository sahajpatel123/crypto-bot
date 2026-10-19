"""Frozen synthetic 30-day benchmark (Worker 1, Q-007).

Stand-in substrate until E-008 lands the real 30-accounting-day dataset.
Fully constructed (no RNG): identical code always yields identical events.
COMPRESSED TIME: 30 contiguous 600 s days (labeled, not accounting days);
dev starts 23:00 IST so an accounting midnight rolls mid-dev. Price shapes
mirror the SYNTH_V1 scenario geometry the baselines were built against.

Two frozen datasets: ``synth_quotes`` (trades + observed BBO) and
``synth_noquotes`` (trades only → the ``research-spread-profile`` applies;
S5 ineligible there with reasons). Both implement the B5 reader surface
(``events(symbol, day)``, ``coverage()``, ``manifest_sha()``) that
``research/backtest.py`` consumes, so the harness swaps to E-008 without
code changes.

Move sizes clear the B7 reward-vs-cost gate (round-trip 26 bps, cost-contract-v1): impulses
30 bps, pullback resume 25 bps, ranges 80 bps wide (mid ≈ 40 bps away),
reclaims with 6 bps pierce + 24 bps reversal. Smaller moves would be
correctly rejected as reward-below-cost and could never exercise the
fill lifecycle; sizing scenarios to clear admission is benchmark design,
not tuning (no strategy parameter changes).

XRP-scale pricing (base 2.0) is deliberate: with the 120 USDT pilot
policy, BTC-scale prices size sub-step dust quantities (risk quantizes
to 1e-8 in replay without venue filters; the engine correctly enforces
the 0.001 LOT step), crashing runs. Bps economics are price-invariant,
so the cheaper scale isolates harness/strategy proof from the open
pilot-vs-BTC-tick question (reported to manager/W3 separately).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

BENCHMARK_ID = "synth-benchmark-30d-v1"
SYMBOL = "XRPUSDT"
BASE_PRICE = 2.0
DAY_SECONDS = 600
N_DAYS = 30
# 2026-09-11 23:00 IST == 17:30 UTC: midnight rolls inside dev days.
T0_MS = 1_787_791_800_000
INPUT_CLASS = "synthetic-benchmark"
BBO_SPREAD_BPS = 1.0  # observed-spread scale for the quotes dataset
BBO_QTY = 10000.0  # modeled top size (labeled, exceeds pilot fills)

IMPULSE = "impulse"
PULLBACK = "pullback"
RANGE = "range"
RECLAIM = "reclaim"
FLAT = "flat"
CHOPPY = "choppy"

# Frozen day → (scenario, direction) table (+1 long / -1 short / 0 control).
DAY_TABLE = {
    1: (IMPULSE, 1), 2: (PULLBACK, 1), 3: (RANGE, 1), 4: (RECLAIM, -1),
    5: (FLAT, 0), 6: (CHOPPY, 0), 7: (IMPULSE, -1), 8: (PULLBACK, -1),
    9: (RANGE, -1), 10: (RECLAIM, 1), 11: (FLAT, 0), 12: (CHOPPY, 0),
    13: (IMPULSE, 1), 14: (RANGE, 1), 15: (FLAT, 0),
    16: (IMPULSE, 1), 17: (PULLBACK, 1), 18: (RANGE, -1), 19: (RECLAIM, -1),
    20: (FLAT, 0), 21: (CHOPPY, 0), 22: (IMPULSE, -1),
    23: (PULLBACK, 1), 24: (RANGE, 1), 25: (RECLAIM, -1), 26: (IMPULSE, 1),
    27: (FLAT, 0), 28: (CHOPPY, 0), 29: (RANGE, -1), 30: (RECLAIM, 1),
}

__all__ = [
    "BENCHMARK_ID",
    "DAY_TABLE",
    "INPUT_CLASS",
    "N_DAYS",
    "SYMBOL",
    "SynthBenchmark",
    "day_closes",
]


def _bps(bps: float) -> float:
    """Absolute move for ``bps`` at the benchmark base price."""
    return BASE_PRICE * bps / 1e4


def day_closes(day: int) -> list[float]:
    """Deterministic per-second closes for benchmark ``day`` (1-based).

    All moves are defined in bps (price-scale free); XRP-scale pricing
    keeps pilot-sized quantities far above venue steps (see module note
    on the pilot-vs-BTC-tick finding).
    """
    scenario, direction = DAY_TABLE[day]
    d = float(direction)
    out: list[float] = []
    for s in range(DAY_SECONDS):
        if scenario == CHOPPY:
            import math
            out.append(BASE_PRICE * (1.0 + 0.0002 * math.sin(6.28318 * s / 200)))
            continue
        if scenario == IMPULSE:
            if s < 150:
                px = BASE_PRICE
            elif s < 160:
                px = BASE_PRICE + d * _bps(30.0) * (s - 150 + 1) / 10
            else:
                px = BASE_PRICE + d * _bps(30.0)
        elif scenario == PULLBACK:
            peak = BASE_PRICE + d * _bps(30.0)
            trough = peak - d * _bps(40.0)
            hold = trough + d * _bps(25.0)
            if s < 150:
                px = BASE_PRICE
            elif s < 200:
                px = BASE_PRICE + d * _bps(30.0) * (s - 150 + 1) / 50
            elif s < 208:
                px = peak - d * _bps(40.0) * (s - 200 + 1) / 8
            elif s < 213:
                px = trough + d * _bps(25.0) * (s - 208 + 1) / 5
            else:
                px = hold
        elif scenario == RANGE:
            edge = BASE_PRICE + d * _bps(80.0)
            if s < 150:
                px = BASE_PRICE
            elif s < 160:
                px = BASE_PRICE + (edge - BASE_PRICE) * (s - 150 + 1) / 10
            elif s < 170:
                px = edge + (BASE_PRICE - edge) * (s - 160 + 1) / 10
            elif s < 210:
                px = BASE_PRICE
            elif s < 215:
                px = BASE_PRICE + d * _bps(1.0)
            elif s < 220:
                px = BASE_PRICE + d * (_bps(5.0) + _bps(2.0) * (s - 215))
            else:
                px = BASE_PRICE + d * _bps(13.0)
        elif scenario == RECLAIM:
            level = BASE_PRICE + d * _bps(30.0)
            hold_px = level - d * _bps(24.0)
            if s < 150:
                px = BASE_PRICE
            elif s < 190:
                px = BASE_PRICE + d * _bps(30.0) * (s - 150 + 1) / 40
            elif s < 195:
                px = level
            elif s < 198:
                px = level + d * _bps({195: 2.0, 196: 6.0, 197: 2.0}[s])
            elif s < 202:
                px = level - d * _bps(6.0) * (s - 198 + 1)
            else:
                px = hold_px
        else:  # FLAT
            px = BASE_PRICE
        out.append(px)
    return out


@dataclass(frozen=True)
class SynthBenchmark:
    """B5-reader-shaped handle over the frozen synthetic days."""

    dataset_id: str = "synth_quotes"  # or "synth_noquotes" (trades only)
    symbol: str = SYMBOL

    def __post_init__(self) -> None:
        if self.dataset_id not in ("synth_quotes", "synth_noquotes"):
            raise ValueError(f"unknown synth dataset {self.dataset_id!r}")

    def days(self) -> tuple[int, ...]:
        return tuple(range(1, N_DAYS + 1))

    def events(self, symbol: str, day: int):
        """Yield normalized day events in causal order (streaming)."""
        if symbol != self.symbol:
            raise ValueError(f"unknown symbol {symbol!r}")
        if day not in DAY_TABLE:
            raise ValueError(f"day {day} out of range 1..{N_DAYS}")
        with_quotes = self.dataset_id == "synth_quotes"
        closes = day_closes(day)
        base_ms = T0_MS + (day - 1) * DAY_SECONDS * 1000
        agg = (day - 1) * 1_000_000
        for s, px in enumerate(closes):
            w = base_ms + s * 1000
            prev = closes[s - 1] if s else px
            buying = px >= prev
            if with_quotes:
                half = px * BBO_SPREAD_BPS / 1e4 / 2
                yield {"v": 1, "format": "cryptobot-events/1",
                       "input_class": INPUT_CLASS, "source": BENCHMARK_ID,
                       "route": "synth", "run_id": "", "seq": 0,
                       "channel": "bookTicker", "symbol": symbol,
                       "exchange_ts_ms": w + 100, "local_recv_ms": w + 105,
                       "local_mono_ns": 0, "gap_kind": None, "venue_seq": 0,
                       "payload": {"bid": px - half, "ask": px + half,
                                   "bid_qty": BBO_QTY, "ask_qty": BBO_QTY}}
            agg += 1
            yield {"v": 1, "format": "cryptobot-events/1",
                   "input_class": INPUT_CLASS, "source": BENCHMARK_ID,
                   "route": "synth", "run_id": "", "seq": 0,
                   "channel": "aggTrade", "symbol": symbol,
                   "exchange_ts_ms": w + 200, "local_recv_ms": w + 205,
                   "local_mono_ns": 0, "gap_kind": None, "venue_seq": agg,
                   "payload": {"agg_id": agg, "price": px, "qty": 0.5,
                               "first_id": agg, "last_id": agg,
                               "trade_ts_ms": w + 200,
                               "buyer_is_maker": not buying}}

    def coverage(self) -> dict:
        """Per-day channel inventory (quotes observed or not)."""
        with_quotes = self.dataset_id == "synth_quotes"
        return {
            "dataset_id": self.dataset_id,
            "benchmark_id": BENCHMARK_ID,
            "symbol": self.symbol,
            "days": [
                {"day": d, "scenario": DAY_TABLE[d][0],
                 "direction": DAY_TABLE[d][1],
                 "channels": ["aggTrade", "bookTicker"] if with_quotes
                             else ["aggTrade"],
                 "quotes_observed": with_quotes}
                for d in self.days()
            ],
        }

    def manifest_sha(self) -> str:
        canonical = json.dumps(
            {"benchmark_id": BENCHMARK_ID, "dataset_id": self.dataset_id,
             "symbol": self.symbol,
             "days": [(d, DAY_TABLE[d][0], DAY_TABLE[d][1])
                      for d in self.days()]},
            sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
