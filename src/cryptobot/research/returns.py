"""Observed closed-trade return evaluation (Worker 1, Q-006).

Command: ``python -m cryptobot.research.returns --exp EXP-003 --out <dir>``.

Method: ``specs/exp-returns.md`` (frozen before results). Signal mechanics
stay with the frozen EXP manifests and ``runner.py``; this module replays
longer (600-bar) fixtures of the SAME scenarios/seeds through purged
chronological splits and scores every signal as a closed trade: limit-touch
entry within the 15 s expiry, then stop/target/time exits from the
strategy exit policy. Gross returns come from observed replay fills;
net subtracts the frozen ``NET_S1_V1`` 26 bps round-trip haircut.

Labels: ``conservative-simulation`` throughout. Synthetic diagnostics only;
promotion stays NONE; forward paper is NOT run here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass

from cryptobot.coordination import Side
from cryptobot.strategies.contract import (
    ARM_IDS_S3,
    ARM_IDS_S4,
    STRATEGY_VERSION,
)

from .experiments import (
    EXP_003,
    EXP_004,
    REGISTRY_VERSION,
    S3_SCENARIOS,
    S4_SCENARIOS,
    TRAIN_SEEDS_S3,
    TRAIN_SEEDS_S4,
    VALIDATION_SEEDS_S3,
    VALIDATION_SEEDS_S4,
)
from .runner import EVALUATORS
from .synthetic import GENERATOR_ID, generate_fixture

N_BARS = 600
WARMUP = 120
MAX_HORIZON = 135  # holding_limit_s (120) + entry_expiry_s (15)
TRAIN_RANGE = (120, 240)
PURGE_BARS = 135  # == MAX_HORIZON; train outcomes can never reach validation
VAL_RANGE = (375, 465)  # scored inclusive; (465, 600) is outcome room
HOLDOUT_RANGE = (120, 465)  # one scored region; outcomes to 600
HOLDOUT_SEEDS_S3 = (91, 92)
HOLDOUT_SEEDS_S4 = (93, 94)
ROUNDTRIP_COST_BPS = 2 * (5.0 + 5.0) + 5.0 + 1.0  # NET_S1_V1 = 26.0
TAKE_R = 1.5
S3_MID_LOOKBACK = 64

RETURN_EXPS = {
    "EXP-003": {"arms": list(ARM_IDS_S3), "scenarios": list(S3_SCENARIOS),
                "train": list(TRAIN_SEEDS_S3),
                "validation": list(VALIDATION_SEEDS_S3),
                "holdout": list(HOLDOUT_SEEDS_S3)},
    "EXP-004": {"arms": list(ARM_IDS_S4), "scenarios": list(S4_SCENARIOS),
                "train": list(TRAIN_SEEDS_S4),
                "validation": list(VALIDATION_SEEDS_S4),
                "holdout": list(HOLDOUT_SEEDS_S4)},
}

__all__ = [
    "ClosedTrade",
    "HOLDOUT_RANGE",
    "HOLDOUT_SEEDS_S3",
    "HOLDOUT_SEEDS_S4",
    "MAX_HORIZON",
    "N_BARS",
    "PURGE_BARS",
    "RETURN_EXPS",
    "ROUNDTRIP_COST_BPS",
    "TRAIN_RANGE",
    "VAL_RANGE",
    "WARMUP",
    "evaluate_signal",
    "exits_for_signal",
    "main",
    "run_returns",
    "split_ranges",
]


@dataclass(frozen=True)
class ClosedTrade:
    """One scored signal: entry fill or expiry, then a closing exit."""

    status: str  # "closed" | "expired"
    arm: str
    side: str  # "LONG" | "SHORT"
    signal_t: int
    entry_t: int | None
    entry_px: float | None
    exit_t: int | None
    exit_px: float | None
    exit_kind: str  # "stop" | "target" | "time" | "expired"
    gross_bps: float
    net_bps: float

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "arm": self.arm,
            "side": self.side,
            "signal_t": self.signal_t,
            "entry_t": self.entry_t,
            "entry_px": self.entry_px,
            "exit_t": self.exit_t,
            "exit_px": self.exit_px,
            "exit_kind": self.exit_kind,
            "gross_bps": self.gross_bps,
            "net_bps": self.net_bps,
        }


def split_ranges(n_bars: int = N_BARS) -> dict[str, tuple[int, int]]:
    """Purged chronological geometry; validates the 135-bar outcome room."""
    lo_t, hi_t = TRAIN_RANGE
    lo_v, hi_v = VAL_RANGE
    if not (0 < WARMUP <= lo_t < hi_t < hi_t + PURGE_BARS <= lo_v <= hi_v):
        raise ValueError("degenerate purged geometry")
    if hi_v + MAX_HORIZON > n_bars:
        raise ValueError(
            f"n_bars={n_bars} leaves no outcome room past val end {hi_v}")
    if HOLDOUT_RANGE[1] + MAX_HORIZON > n_bars:
        raise ValueError("n_bars too short for holdout outcomes")
    return {
        "train": TRAIN_RANGE,
        "purge": (hi_t, hi_t + PURGE_BARS),
        "validation": VAL_RANGE,
        "holdout": HOLDOUT_RANGE,
    }


def exits_for_signal(arm: str, intent, bars, t: int) -> tuple[float, float, int]:
    """Stop / target / time-exit index for one signal (spec section 4)."""
    bar = bars[t]
    assert bar is not None
    close_t = bar.close
    stop = intent.invalidation_price
    if arm in ARM_IDS_S3:
        window = bars[t - S3_MID_LOOKBACK + 1:t + 1]
        assert all(b is not None for b in window)
        high = max(b.high for b in window)  # type: ignore[union-attr]
        low = min(b.low for b in window)  # type: ignore[union-attr]
        target = (high + low) / 2
    else:
        risk = abs(close_t - stop)
        target = close_t + TAKE_R * risk if intent.side is Side.LONG \
            else close_t - TAKE_R * risk
    return stop, target, t + intent.holding_limit_s


def evaluate_signal(arm: str, intent, bars, t: int) -> ClosedTrade:
    """Score one signal as a closed trade (or expiry). Pure replay."""
    side = intent.side
    sgn = 1.0 if side is Side.LONG else -1.0
    stop, target, time_t = exits_for_signal(arm, intent, bars, t)
    # 1 s grid: expiry span in bars (ts diff, robust to minute rollover).
    expiry_span = int((intent.entry_expiry_utc -
                       intent.evidence_ts_utc).total_seconds())
    entry_t: int | None = None
    for j in range(t + 1, min(t + expiry_span, len(bars) - 1) + 1):
        bj = bars[j]
        if bj is None:
            continue
        if bj.low <= intent.entry_high and bj.high >= intent.entry_low:
            entry_t = j
            break
    if entry_t is None:
        return ClosedTrade("expired", arm, side.value, t, None, None, None,
                           None, "expired", 0.0, 0.0)
    entry_px = bars[entry_t].close  # type: ignore[union-attr]
    exit_t: int | None = None
    exit_px = 0.0
    exit_kind = "time"
    for k in range(entry_t, min(time_t, len(bars) - 1) + 1):
        bk = bars[k]
        if bk is None:
            continue
        if k >= time_t:
            exit_t, exit_px, exit_kind = k, bk.close, "time"
            break
        if side is Side.LONG:
            if bk.low <= stop:
                exit_t, exit_px, exit_kind = k, stop, "stop"
                break
            if bk.high >= target:
                exit_t, exit_px, exit_kind = k, target, "target"
                break
        else:
            if bk.high >= stop:
                exit_t, exit_px, exit_kind = k, stop, "stop"
                break
            if bk.low <= target:
                exit_t, exit_px, exit_kind = k, target, "target"
                break
    assert exit_t is not None  # time bar always in-fixture by geometry
    gross = sgn * (exit_px - entry_px) / entry_px * 1e4
    net = gross - ROUNDTRIP_COST_BPS
    return ClosedTrade("closed", arm, side.value, t, entry_t, entry_px,
                       exit_t, exit_px, exit_kind, gross, net)


def _fixture_hash(fixture) -> str:
    canonical = json.dumps(fixture.to_dict(), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_returns(exp_id: str, out_dir,
                splits: tuple[str, ...] = ("train", "validation", "holdout")
                ) -> dict:
    """Replay return fixtures; persist trades.jsonl + summary.json."""
    from pathlib import Path

    if exp_id not in RETURN_EXPS:
        raise ValueError(f"unknown return experiment {exp_id!r}")
    cfg = RETURN_EXPS[exp_id]
    ranges = split_ranges()
    out = Path(out_dir) / exp_id
    out.mkdir(parents=True, exist_ok=True)
    trades_path = out / "trades.jsonl"
    if trades_path.exists():
        trades_path.unlink()
    summary: dict[str, dict[str, dict[str, float | int]]] = {}
    n_trades = 0
    with trades_path.open("w", encoding="utf-8") as fh:
        for split in splits:
            if split not in ("train", "validation", "holdout"):
                raise ValueError(f"unknown split {split!r}")
            lo, hi = ranges[split]
            for scenario in cfg["scenarios"]:
                for seed in cfg[split]:
                    fixture = generate_fixture(seed=seed, scenario=scenario,
                                               n_bars=N_BARS)
                    fhash = _fixture_hash(fixture)
                    bars = list(fixture.bars)
                    for arm in cfg["arms"]:
                        evaluate = EVALUATORS[arm]
                        key = f"{arm}|{split}"
                        cell = summary.setdefault(key, {
                            "n_signals": 0, "n_entered": 0, "n_expired": 0,
                            "n_stop": 0, "n_target": 0, "n_time": 0,
                            "gross_total_bps": 0.0, "net_total_bps": 0.0,
                        })
                        for t in range(max(lo, WARMUP), hi + 1):
                            long_d, short_d = evaluate(
                                bars, t, arm, fixture.instrument)
                            for decision in (long_d, short_d):
                                intent = decision.intent
                                if intent is None:
                                    continue
                                cell["n_signals"] += 1
                                trade = evaluate_signal(arm, intent, bars, t)
                                if trade.status == "closed":
                                    cell["n_entered"] += 1
                                    cell[f"n_{trade.exit_kind}"] += 1
                                    cell["gross_total_bps"] += trade.gross_bps
                                    cell["net_total_bps"] += trade.net_bps
                                else:
                                    cell["n_expired"] += 1
                                rec = trade.to_dict()
                                rec.update({
                                    "exp_id": exp_id, "split": split,
                                    "scenario": scenario, "seed": seed,
                                    "fixture_hash": fhash,
                                    "instrument": fixture.instrument,
                                })
                                fh.write(json.dumps(rec) + "\n")
                                n_trades += 1
    for cell in summary.values():
        n = cell["n_entered"]
        cell["gross_mean_bps"] = cell["gross_total_bps"] / n if n else 0.0
        cell["net_mean_bps"] = cell["net_total_bps"] / n if n else 0.0
    doc = {
        "exp_id": exp_id,
        "method": "specs/exp-returns.md",
        "generator": GENERATOR_ID,
        "n_bars": N_BARS,
        "registry_version": REGISTRY_VERSION,
        "strategy_version": STRATEGY_VERSION,
        "ranges": {k: list(v) for k, v in ranges.items()},
        "promotion_rule": "NONE",
        "n_trades_scored": n_trades,
        "cells": summary,
    }
    (out / "summary.json").write_text(json.dumps(doc, indent=2),
                                      encoding="utf-8")
    return doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Observed return evaluation")
    parser.add_argument("--exp", required=True, choices=["EXP-003", "EXP-004"])
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--splits", default="train,validation,holdout",
                        help="comma-separated subset to score")
    args = parser.parse_args(argv)
    doc = run_returns(args.exp, args.out,
                      tuple(s for s in args.splits.split(",") if s))
    n = doc["n_trades_scored"]
    print(f"{args.exp}: scored {n} signal-trades "
          f"({args.splits}) -> {args.out}/{args.exp}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
