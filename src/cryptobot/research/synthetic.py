"""Labelled synthetic replay fixtures (Worker 1, Q-001).

Deterministic generator ``SYNTH_V1``: identical inputs always yield identical
bars. Prices are constructed (not sampled) so trigger behaviour is exact;
the seed drives only volume/flow microstructure jitter. Every bar and every
fixture carries ``source: "synthetic"``. Not market data; not validated.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptobot.strategies.s1 import Bar

GENERATOR_ID = "SYNTH_V1"
SOURCE_LABEL = "synthetic"

SCENARIO_LONG = "long-breakout"
SCENARIO_SHORT = "short-breakout"
SCENARIO_FLAT = "flat"
SCENARIO_CHOPPY = "choppy"
SCENARIO_GAP = "gap"
SCENARIO_WIDE_SPREAD = "wide-spread"
SCENARIO_S2_LONG = "s2-long-pullback"
SCENARIO_S2_SHORT = "s2-short-pullback"
SCENARIO_S3_LONG = "s3-long-range"
SCENARIO_S3_SHORT = "s3-short-range"
SCENARIO_S4_LONG = "s4-long-reclaim"
SCENARIO_S4_SHORT = "s4-short-reclaim"
SCENARIOS = (
    SCENARIO_LONG,
    SCENARIO_SHORT,
    SCENARIO_FLAT,
    SCENARIO_CHOPPY,
    SCENARIO_GAP,
    SCENARIO_WIDE_SPREAD,
    SCENARIO_S2_LONG,
    SCENARIO_S2_SHORT,
    SCENARIO_S3_LONG,
    SCENARIO_S3_SHORT,
    SCENARIO_S4_LONG,
    SCENARIO_S4_SHORT,
)

__all__ = [
    "GENERATOR_ID",
    "SOURCE_LABEL",
    "SCENARIOS",
    "SCENARIO_CHOPPY",
    "SCENARIO_FLAT",
    "SCENARIO_GAP",
    "SCENARIO_LONG",
    "SCENARIO_S2_LONG",
    "SCENARIO_S2_SHORT",
    "SCENARIO_S3_LONG",
    "SCENARIO_S3_SHORT",
    "SCENARIO_S4_LONG",
    "SCENARIO_S4_SHORT",
    "SCENARIO_SHORT",
    "SCENARIO_WIDE_SPREAD",
    "Fixture",
    "generate_fixture",
]


@dataclass(frozen=True)
class Fixture:
    label: str
    generator: str
    scenario: str
    seed: int
    instrument: str
    t0_utc: datetime
    step_s: int
    bars: tuple[Bar | None, ...]
    notes: str

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "generator": self.generator,
            "scenario": self.scenario,
            "seed": self.seed,
            "instrument": self.instrument,
            "t0_utc": self.t0_utc.isoformat(),
            "step_s": self.step_s,
            "bars": [None if b is None else b.to_dict() for b in self.bars],
            "notes": self.notes,
        }

    @staticmethod
    def from_dict(d: dict) -> Fixture:
        return Fixture(
            label=d["label"],
            generator=d["generator"],
            scenario=d["scenario"],
            seed=d["seed"],
            instrument=d["instrument"],
            t0_utc=datetime.fromisoformat(d["t0_utc"]),
            step_s=d["step_s"],
            bars=tuple(
                None if b is None else Bar.from_dict(b) for b in d["bars"]
            ),
            notes=d["notes"],
        )


def _flat_bar(ts: datetime, price: float, volume: float, buy_frac: float,
              spread_bps: float) -> Bar:
    return Bar(ts_utc=ts, open=price, high=price, low=price, close=price,
               volume=volume, trades=max(1, int(volume)),
               buy_frac=buy_frac, spread_bps=spread_bps)


def _trend_bar(ts: datetime, prev_close: float, close: float, volume: float,
               buy_frac: float, spread_bps: float) -> Bar:
    wick = 0.2 / 1e4  # 0.2 bps wicks keep high/low strict but tiny
    hi = max(prev_close, close) * (1.0 + wick)
    lo = min(prev_close, close) * (1.0 - wick)
    return Bar(ts_utc=ts, open=prev_close, high=hi, low=lo, close=close,
               volume=volume, trades=max(1, int(volume)),
               buy_frac=buy_frac, spread_bps=spread_bps)


def generate_fixture(
    *,
    seed: int,
    scenario: str,
    n_bars: int = 240,
    instrument: str = "BTCUSDT",
    t0_utc: datetime | None = None,
    base_price: float = 67000.0,
    volume_spike: bool = True,
    flow_bias: bool = True,
    s3_range_bps: float = 60.0,
) -> Fixture:
    """Build a deterministic labelled fixture (see module docstring).

    Breakout scenarios hold exactly flat for 150 bars, ramp 1.2 bps/bar for
    10 bars (total 12 bps), then hold the new level. S2 pullback scenarios
    hold flat for 150 bars, trend 0.6 bps/bar for 50 bars (total 30 bps),
    pull back 2.5 bps/bar for 8 bars (total 20 bps), resume 1.5 bps/bar for
    5 bars, then hold. S3 range scenarios form a ``s3_range_bps`` range,
    return to the edge, touch it for 5 bars, then drift off. S4 reclaim
    scenarios trend 30 bps, hold, pierce 3 bps, then reverse 4 bps/bar for
    4 bars. ``volume_spike`` / ``flow_bias`` toggle the S1/S2 confirming
    arms' inputs on impulse/resumption bars (S3/S4 have no V/F arms).
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}")
    if n_bars < 200:
        raise ValueError("n_bars must be >= 200 (history + trigger room)")
    t0 = t0_utc or datetime(2026, 1, 2, tzinfo=UTC)
    rng = random.Random(seed)
    direction = -1.0 if scenario in (SCENARIO_SHORT, SCENARIO_S2_SHORT,
                                     SCENARIO_S3_SHORT, SCENARIO_S4_LONG) else 1.0
    impulse = scenario in (SCENARIO_LONG, SCENARIO_SHORT, SCENARIO_WIDE_SPREAD)
    s2 = scenario in (SCENARIO_S2_LONG, SCENARIO_S2_SHORT)
    s3 = scenario in (SCENARIO_S3_LONG, SCENARIO_S3_SHORT)
    s4 = scenario in (SCENARIO_S4_LONG, SCENARIO_S4_SHORT)
    s2_peak = base_price * (1.0 + direction * 30.0 / 1e4)
    s2_trough = s2_peak * (1.0 - direction * 20.0 / 1e4)
    s2_hold = s2_trough * (1.0 + direction * 7.5 / 1e4)
    s3_edge = base_price * (1.0 + direction * s3_range_bps / 1e4)
    s4_level = base_price * (1.0 + direction * 30.0 / 1e4)
    s4_hold = s4_level * (1.0 - direction * 16.0 / 1e4)

    closes: list[float] = []
    for i in range(n_bars):
        if scenario == SCENARIO_CHOPPY:
            # Bounded 2 bps sine, 200-bar period: 30-bar returns stay < 5 bps.
            import math

            closes.append(base_price * (1.0 + 0.0002 * math.sin(6.28318 * i / 200)))
        elif impulse and 150 <= i < 160:
            step = (i - 150 + 1) * 1.2 / 1e4
            closes.append(base_price * (1.0 + direction * step))
        elif impulse and i >= 160:
            closes.append(base_price * (1.0 + direction * 12.0 / 1e4))
        elif s2 and 150 <= i < 200:
            frac = (i - 150 + 1) / 50
            closes.append(base_price * (1.0 + direction * 30.0 / 1e4 * frac))
        elif s2 and 200 <= i < 208:
            step = (i - 200 + 1) * 2.5 / 1e4
            closes.append(s2_peak * (1.0 - direction * step))
        elif s2 and 208 <= i < 213:
            step = (i - 208 + 1) * 1.5 / 1e4
            closes.append(s2_trough * (1.0 + direction * step))
        elif s2 and i >= 213:
            closes.append(s2_hold)
        elif s3 and 150 <= i < 160:
            frac = (i - 150 + 1) / 10
            closes.append(base_price * (1.0 + direction * s3_range_bps / 1e4 * frac))
        elif s3 and 160 <= i < 170:
            frac = (i - 160 + 1) / 10
            closes.append(s3_edge + (base_price - s3_edge) * frac)
        elif s3 and 170 <= i < 210:
            closes.append(base_price)
        elif s3 and 210 <= i < 215:
            closes.append(base_price * (1.0 + direction * 1.0 / 1e4))
        elif s3 and 215 <= i < 220:
            closes.append(base_price * (1.0 + direction * (5.0 + 2.0 * (i - 215)) / 1e4))
        elif s3 and i >= 220:
            closes.append(base_price * (1.0 + direction * 13.0 / 1e4))
        elif s4 and 150 <= i < 190:
            frac = (i - 150 + 1) / 40
            closes.append(base_price * (1.0 + direction * 30.0 / 1e4 * frac))
        elif s4 and 190 <= i < 195:
            closes.append(s4_level)
        elif s4 and 195 <= i < 198:
            pierce = {195: 1.0, 196: 3.0, 197: 1.0}[i]
            closes.append(s4_level * (1.0 + direction * pierce / 1e4))
        elif s4 and 198 <= i < 202:
            step = (i - 198 + 1) * 4.0 / 1e4
            closes.append(s4_level * (1.0 - direction * step))
        elif s4 and i >= 202:
            closes.append(s4_hold)
        else:
            closes.append(base_price)

    bars: list[Bar | None] = []
    for i in range(n_bars):
        ts = t0 + timedelta(seconds=i)
        on_conf = (impulse and 150 <= i < 160) or (s2 and 208 <= i < 213)
        if scenario == SCENARIO_GAP and (160 <= i <= 162 or 200 <= i <= 206):
            bars.append(None)
            continue
        if on_conf and volume_spike:
            volume = 400.0 + rng.uniform(0.0, 5.0)
        else:
            volume = 100.0 + rng.uniform(0.0, 5.0)
        if on_conf and flow_bias:
            buy_frac = min(1.0, max(0.0,
                            (0.75 if direction > 0 else 0.25) + rng.uniform(-0.01, 0.01)))
        else:
            buy_frac = min(1.0, max(0.0, 0.5 + rng.uniform(-0.02, 0.02)))
        spread = 10.0 if scenario == SCENARIO_WIDE_SPREAD and on_conf \
            else max(0.0, 1.0 + rng.uniform(-0.1, 0.1))
        if i == 0 or closes[i] == closes[i - 1]:
            bars.append(_flat_bar(ts, closes[i], volume, buy_frac, spread))
        else:
            bars.append(_trend_bar(ts, closes[i - 1], closes[i], volume,
                                   buy_frac, spread))
    if impulse:
        shape = "flat-150 + 10-bar 12bps impulse + hold"
    elif s2:
        shape = "flat-150 + 50-bar 30bps trend + 8-bar 20bps pullback + 5-bar resume + hold"
    elif s3:
        shape = f"flat-150 + range {s3_range_bps}bps + edge touch 5-bar + drift"
    elif s4:
        shape = "flat-150 + 40-bar 30bps leg + 3bps pierce + 4-bar reversal + hold"
    else:
        shape = "control"
    notes = (
        f"{GENERATOR_ID} {scenario}: {shape}; "
        f"volume_spike={volume_spike} flow_bias={flow_bias}; "
        "seed drives volume/flow jitter only"
    )
    return Fixture(
        label=SOURCE_LABEL,
        generator=GENERATOR_ID,
        scenario=scenario,
        seed=seed,
        instrument=instrument,
        t0_utc=t0,
        step_s=1,
        bars=tuple(bars),
        notes=notes,
    )
