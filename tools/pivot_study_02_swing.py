"""STUDY-02: P3 4h swing-continuation measurement (read-only, manager-owned).

Preregistered in reports/pivot/PILOT-SCORING-PREREG.md BEFORE any pilot
scoring. Reads a capture's events (.jsonl or settled .jsonl.gz), builds
causal 1s aggTrade closes, aggregates causal 1h bars, and scores 4h
breakout-continuation: at each 1h close (after 4h warmup), LONG if close >
prior-4h-high + 10bps, SHORT if close < prior-4h-low - 10bps; 4h time exit
at exit-bar close; no entries after 20:00 UTC (no overnight holds).
Optimistic execution (fills at bar closes, zero latency).

Outputs results JSON to --out plus a human table on stdout.
Exit 0 results written; 2 input/contract error.
"""
from __future__ import annotations

import argparse
import functools
import gzip
import json
import math
from pathlib import Path

EXIT_BLOCKED = 2
RT_COST_BPS = 26.0
WARMUP_H = 4
HOLD_H = 4
ENTRY_BPS = 10.0
LAST_ENTRY_HOUR = 20  # UTC hour; entries at/after -> skip (4h exit in-day)


def load_closes(capture: Path, symbol: str) -> dict[int, float]:
    """sec -> close from causal aggTrade exchange times (no forward-fill)."""
    events = capture / "events.jsonl"
    gz_events = capture / "events.jsonl.gz"
    if events.exists():
        open_fn = functools.partial(events.open, "rb")
    elif gz_events.exists():
        open_fn = functools.partial(gzip.open, gz_events, "rb")
    else:
        raise ValueError(f"{capture}: events.jsonl missing")
    closes: dict[int, float] = {}
    with open_fn() as fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("channel") != "aggTrade":
                continue
            if (ev.get("symbol") or "").upper() != symbol:
                continue
            try:
                ts = int(ev["exchange_ts_ms"])
                px = float(ev["payload"]["price"])
            except (KeyError, TypeError, ValueError):
                continue
            if px > 0:
                closes[ts // 1000] = px
    return closes


def hour_bars(closes: dict[int, float]) -> dict[int, dict]:
    """hour_epoch -> {o,h,l,c} from 1s closes; incomplete hours dropped."""
    agg: dict[int, dict] = {}
    for sec in sorted(closes):
        h = sec - (sec % 3600)
        b = agg.setdefault(h, {"o": closes[sec], "h": closes[sec],
                               "l": closes[sec], "c": closes[sec], "n": 0})
        b["h"] = max(b["h"], closes[sec])
        b["l"] = min(b["l"], closes[sec])
        b["c"] = closes[sec]
        b["n"] += 1
    # Drop thin hours (<50% of seconds) — never impute.
    return {h: b for h, b in agg.items() if b["n"] >= 1800}


def score(bars: dict[int, dict], rt_cost_bps: float) -> dict:
    hours = sorted(bars)
    gross: list[float] = []
    by_side = {"LONG": [], "SHORT": []}
    for i in range(WARMUP_H, len(hours)):
        h = hours[i]
        # Continuity: require consecutive hourly grid.
        if hours[i] - hours[i - 1] != 3600:
            continue
        window = [bars[hours[j]] for j in range(i - WARMUP_H, i)]
        if any(hours[i - WARMUP_H + k + 1] - hours[i - WARMUP_H + k] != 3600
               for k in range(WARMUP_H - 1)):
            continue
        # Exit must land in-day: entry hour + 4h bar must exist.
        if i + HOLD_H >= len(hours) or hours[i + HOLD_H] - h != 4 * 3600:
            continue
        import datetime as _dt
        if _dt.datetime.fromtimestamp(h, _dt.UTC).hour >= LAST_ENTRY_HOUR:
            continue
        hi = max(b["h"] for b in window)
        lo = min(b["l"] for b in window)
        entry = bars[h]["c"]
        side = None
        if entry > hi * (1 + ENTRY_BPS / 1e4):
            side = "LONG"
        elif entry < lo * (1 - ENTRY_BPS / 1e4):
            side = "SHORT"
        if side is None:
            continue
        fwd = bars[hours[i + HOLD_H]]["c"]
        move = (fwd / entry - 1.0) * 1e4
        move = move if side == "LONG" else -move
        gross.append(move)
        by_side[side].append(move)
    out = {}
    for key, legs in (("ALL", gross), ("LONG", by_side["LONG"]),
                      ("SHORT", by_side["SHORT"])):
        n = len(legs)
        if n == 0:
            out[key] = {"n": 0, "gross_mean_bps": None,
                        "gross_std_bps": None, "net_mean_bps": None,
                        "net_hit_rate": None, "net_winners": 0}
            continue
        mean = sum(legs) / n
        var = sum((g - mean) ** 2 for g in legs) / n
        net = [g - rt_cost_bps for g in legs]
        winners = sum(1 for x in net if x > 0)
        out[key] = {"n": n, "gross_mean_bps": round(mean, 2),
                    "gross_std_bps": round(math.sqrt(var), 2),
                    "net_mean_bps": round(sum(net) / n, 2),
                    "net_hit_rate": round(winners / n, 4),
                    "net_winners": winners}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="STUDY-02 P3 swing measurement (read-only)")
    parser.add_argument("--capture", required=True)
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--rt-cost", type=float, default=RT_COST_BPS)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        capture = Path(args.capture)
        if args.rt_cost < 0:
            raise ValueError("rt-cost must be >= 0")
        symbols = [s.strip().upper() for s in args.symbols.split(",")
                   if s.strip()]
        if not symbols:
            raise ValueError("no symbols given")
        cells: dict[str, dict] = {}
        for symbol in symbols:
            bars = hour_bars(load_closes(capture, symbol))
            if len(bars) < WARMUP_H + HOLD_H + 1:
                raise ValueError(f"{symbol}: only {len(bars)} full 1h bars")
            for side, res in score(bars, args.rt_cost).items():
                cells[f"{symbol}|4h-cont|{side}"] = res
    except ValueError as exc:
        print(f"BLOCKED: {exc}")
        return EXIT_BLOCKED
    result = {"capture": str(capture), "rt_cost_bps": args.rt_cost,
              "warmup_h": WARMUP_H, "hold_h": HOLD_H,
              "entry_bps": ENTRY_BPS, "cells": cells}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"STUDY-02 cells -> {args.out} "
          f"(rt_cost={args.rt_cost}bps, optimistic execution)")
    for key in sorted(cells):
        c = cells[key]
        print(f"  {key}: n={c['n']} gross_mean={c['gross_mean_bps']} "
              f"gross_std={c['gross_std_bps']} net_mean={c['net_mean_bps']} "
              f"net_hit={c['net_hit_rate']} winners={c['net_winners']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
