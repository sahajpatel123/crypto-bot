"""STUDY-01: 60s momentum-scalp measurement (read-only, manager-owned).

Preregistered in reports/pivot/STUDY-01.md. Reads a capture's
events.jsonl, builds causal 1s aggTrade bars, emits LONG/SHORT signals
on trailing-60s momentum, and scores 60s forward returns gross and net
of the frozen 26bps round-trip charge. Optimistic execution (fills at
bar closes, zero latency) — favors the hypothesis by construction.

Outputs results JSON to --out plus a human table on stdout.
Exit 0 results written; 2 input/contract error.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

EXIT_BLOCKED = 2
RT_COST_BPS = 26.0
WARMUP_BARS = 130
TRAIL_S = 60
HOLD_S = 60


def load_bars(capture: Path, symbol: str) -> dict[int, float]:
    """sec -> close from causal aggTrade exchange times (no forward-fill)."""
    events = capture / "events.jsonl"
    if not events.exists():
        raise ValueError(f"{capture}: events.jsonl missing")
    bars: dict[int, float] = {}
    n_trades = 0
    with open(events, "rb") as fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("channel") != "aggTrade":
                continue
            if ev.get("symbol") != symbol:
                continue
            ts = ev.get("exchange_ts_ms")
            if isinstance(ts, bool) or not isinstance(ts, (int, float)) \
                    or ts <= 0:
                continue
            try:
                price = float((ev.get("payload") or {}).get("price"))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(price) or price <= 0:
                continue
            n_trades += 1
            bars[int(ts) // 1000] = price  # receipt order; last wins
    if not bars:
        raise ValueError(f"{capture}: no aggTrade bars for {symbol}")
    return bars


def score_side(closes: dict[int, float], ordered: list[int],
               threshold_bps: float, side: str) -> dict:
    """Score one side. LONG: trail>=+thr; SHORT: trail<=-thr."""
    gross: list[float] = []
    t = 0
    busy_until = -1
    # Warmup over trade-present seconds only.
    start_idx = WARMUP_BARS
    for i in range(start_idx, len(ordered)):
        sec = ordered[i]
        if sec <= busy_until:
            continue
        prev = closes.get(sec - TRAIL_S)
        cur = closes.get(sec)
        if prev is None or cur is None or prev <= 0:
            continue
        trail = (cur / prev - 1.0) * 1e4
        fire = (trail >= threshold_bps if side == "LONG"
                else trail <= -threshold_bps)
        if not fire:
            continue
        fwd = closes.get(sec + HOLD_S)
        if fwd is None:
            continue  # missing forward bar: skip, never impute
        move = (fwd / cur - 1.0) * 1e4
        move = move if side == "LONG" else -move
        gross.append(move)
        busy_until = sec + HOLD_S
        t += 1
    n = len(gross)
    if n == 0:
        return {"n": 0, "gross_mean_bps": None, "gross_std_bps": None,
                "net_mean_bps": None, "net_hit_rate": None,
                "net_winners": 0}
    mean = sum(gross) / n
    var = sum((g - mean) ** 2 for g in gross) / n
    net = [g - RT_COST_BPS for g in gross]
    winners = sum(1 for x in net if x > 0)
    return {"n": n, "gross_mean_bps": round(mean, 2),
            "gross_std_bps": round(math.sqrt(var), 2),
            "net_mean_bps": round(sum(net) / n, 2),
            "net_hit_rate": round(winners / n, 4),
            "net_winners": winners}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="STUDY-01 momentum-scalp measurement (read-only)")
    parser.add_argument("--capture", required=True)
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--thresholds", default="15,30")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        capture = Path(args.capture)
        thresholds = [float(x) for x in args.thresholds.split(",")]
        if any(th <= 0 for th in thresholds):
            raise ValueError("thresholds must be > 0")
        symbols = [s.strip().upper() for s in args.symbols.split(",")
                   if s.strip()]
        if not symbols:
            raise ValueError("no symbols given")
        cells: dict[str, dict] = {}
        for symbol in symbols:
            closes = load_bars(capture, symbol)
            ordered = sorted(closes)
            for thr in thresholds:
                for side in ("LONG", "SHORT"):
                    key = f"{symbol}|{thr:g}bps|{side}"
                    cells[key] = score_side(closes, ordered, thr, side)
    except ValueError as exc:
        print(f"BLOCKED: {exc}")
        return EXIT_BLOCKED
    result = {"capture": str(capture), "rt_cost_bps": RT_COST_BPS,
              "warmup_bars": WARMUP_BARS, "trail_s": TRAIL_S,
              "hold_s": HOLD_S, "cells": cells}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"STUDY-01 cells -> {args.out} "
          f"(rt_cost={RT_COST_BPS}bps, optimistic execution)")
    for key in sorted(cells):
        c = cells[key]
        print(f"  {key}: n={c['n']} gross_mean={c['gross_mean_bps']} "
              f"gross_std={c['gross_std_bps']} net_mean={c['net_mean_bps']} "
              f"net_hit={c['net_hit_rate']} winners={c['net_winners']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
