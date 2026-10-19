"""Phase A candidate export (READY-01 diagnostics; outputs only).

Mirrors the Session feed loop read-only: per-symbol 1s bar aggregation
over capture events, replay clock, warmup gating, then pure
``get_adapter(...).evaluate(MarketView)`` per ready bar-close.
Imports ONLY market_data + strategies + coordination (never
app.session / research.scoring / research.funnel).

Validates reproduction exactly: emitted evidence_ref set must equal
the recorded store.db intent ids, and per-evaluation strategy rejects
must equal rejections.jsonl strategy-stage rows.

Cost itemization follows cost-contract-v1 (selector lines 49-67):
one-way = fee + spread/2 + slippage; round-trip = 2*one-way + funding
(signed). Spread is the FULL quoted spread, half crossed per leg —
never double-booked. Preset values are labeled conservative-simulation;
measured context (arrival bar spread) is labeled observed, never booked.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptobot.coordination import DataQuality  # noqa: E402
from cryptobot.coordination.exits import decode_exit_rule  # noqa: E402
from cryptobot.coordination.selector import Selector  # noqa: E402
from cryptobot.market_data.bars import (  # noqa: E402
    BarAggregator,
    BarMissing,
    to_s1_bar,
)
from cryptobot.strategies.runtime import MarketView, get_adapter  # noqa: E402

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
WARMUP = 130
DEQUE_MAX = WARMUP + 5
SELECTOR = Selector()  # frozen 1.0x multiple (V0 baseline)


def _itemize(intent) -> dict:
    fc = intent.forecast_cost
    one_way = fc.fee_bps + fc.spread_bps / 2 + fc.slippage_bps
    round_trip = 2.0 * one_way + fc.funding_bps
    return {
        "fee_bps_per_leg": fc.fee_bps,
        "fees_total_bps": 2.0 * fc.fee_bps,
        "spread_full_bps": fc.spread_bps,
        "spread_per_leg_bps": fc.spread_bps / 2,
        "spread_total_bps": fc.spread_bps,
        "slippage_bps_per_leg": fc.slippage_bps,
        "slippage_total_bps": 2.0 * fc.slippage_bps,
        "funding_signed_bps": fc.funding_bps,
        "round_trip_bps": round_trip,
        "label": fc.label,
        "price_ref": fc.price_ref,
        "provenance": {
            "fee": "schedule taker 5bps (simulation-labeled)",
            "spread": "preset 5bps full (conservative-simulation)",
            "slippage": "preset 5bps/leg incl. modeled 50+50ms latency "
                        "(conservative-simulation)",
            "funding": "preset +1bp signed paid "
                        "(conservative-simulation; actual unknown)",
        },
    }


def _export_candidate(intent, bar, now_iso: str) -> dict:
    policy = decode_exit_rule(intent.exit_rule)
    reward = SELECTOR._reward_bps(intent)
    costs = _itemize(intent)
    gap = (reward - costs["round_trip_bps"]
           if reward is not None else None)
    return {
        "evidence_ref": intent.evidence_ref,
        "strategy": intent.strategy,
        "instrument": intent.instrument,
        "side": intent.side.value,
        "evidence_ts_utc": intent.evidence_ts_utc.isoformat(),
        "evaluated_now_utc": now_iso,
        "entry_low": intent.entry_low,
        "entry_high": intent.entry_high,
        "entry_expiry_utc": intent.entry_expiry_utc.isoformat(),
        "invalidation_price": intent.invalidation_price,
        "holding_limit_s": intent.holding_limit_s,
        "exit_rule": intent.exit_rule,
        "stop_price": policy.stop_price,
        "target_price": policy.target_price,
        "time_exit_utc": policy.time_exit_utc.isoformat(),
        "data_quality": intent.data_quality.value,
        "projected_reward_bps": reward,
        "estimated_costs": costs,
        "cost_gap_bps": gap,
        "observed_context": {
            "note": "observed, never booked; preset costs above govern",
            "bar_ts_utc": bar.ts_utc.isoformat(),
            "bar_close": bar.close,
            "bar_spread_bps": bar.spread_bps,
            "bar_trades": bar.trades,
            "bar_volume": bar.volume,
        },
    }


def run_capture(capture_path: Path, strategies: list[str]) -> dict:
    adapters = {name: get_adapter(name) for name in strategies}
    feeds: dict[str, dict] = {}
    now = EPOCH
    candidates: list[dict] = []
    rejects: list[dict] = []
    evals = 0
    with open(capture_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            channel = event.get("channel")
            symbol = event.get("symbol")
            if channel not in ("aggTrade", "bookTicker") or not symbol:
                continue
            try:
                exchange_ms = int(event["exchange_ts_ms"])
            except (KeyError, TypeError, ValueError):
                continue
            moment = EPOCH + timedelta(milliseconds=exchange_ms)
            if moment > now:
                now = moment
            feed = feeds.get(symbol)
            if feed is None:
                feed = {"agg": BarAggregator(symbol),
                        "bars": deque(maxlen=DEQUE_MAX)}
                feeds[symbol] = feed
            closed = []
            if channel == "aggTrade":
                closed = feed["agg"].on_trade(event)
            else:
                payload = event["payload"]
                feed["agg"].on_bbo(float(payload["bid"]),
                                   float(payload["ask"]),
                                   int(event["exchange_ts_ms"]))
            for bar in closed:
                if isinstance(bar, BarMissing):
                    feed["bars"].append(None)
                else:
                    feed["bars"].append(to_s1_bar(bar))
                if len(feed["bars"]) < WARMUP:
                    continue
                bars = list(feed["bars"])
                present = [b for b in bars if b is not None]
                missing = len(bars) - len(present)
                quality = (DataQuality.CLEAN if missing == 0
                           else DataQuality.DEGRADED)
                reasons = ([f"gap:missing-windows:{missing}"]
                           if missing else [])
                view = MarketView(
                    instrument=symbol, bars=tuple(bars), now_utc=now,
                    depth=None, flow=None, quality=quality,
                    quality_reason=";".join(reasons))
                for name, adapter in adapters.items():
                    evals += 1
                    outcome = adapter.evaluate(view)
                    if outcome.intent is not None:
                        candidates.append(_export_candidate(
                            outcome.intent, present[-1], now.isoformat()))
                    else:
                        rejects.append({
                            "ts_utc": now.isoformat(),
                            "strategy": name,
                            "reason": f"strategy:{outcome.reject_reason}",
                        })
    return {"candidates": candidates, "rejects": rejects, "evals": evals}


def _recorded_intent_ids(store_path: Path) -> set[str]:
    con = sqlite3.connect(f"file:{store_path}?mode=ro", uri=True)
    try:
        rows = con.execute("select intent_id from intents").fetchall()
    finally:
        con.close()
    return {row[0] for row in rows}


def _recorded_strategy_rejects(rej_path: Path) -> list[dict]:
    rows = []
    for line in rej_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("stage") == "strategy":
            rows.append({"ts_utc": row["ts_utc"],
                         "strategy": row["strategy"],
                         "reason": row["reason"]})
    return rows


def validate(export: dict, store_path: Path, rej_path: Path) -> dict:
    emitted = {c["evidence_ref"] for c in export["candidates"]}
    recorded = _recorded_intent_ids(store_path)
    rec_rej = _recorded_strategy_rejects(rej_path)
    got_rej = export["rejects"]
    key = lambda r: (r["ts_utc"], r["strategy"], r["reason"])  # noqa: E731
    from collections import Counter
    missing_rej = list((Counter(map(key, rec_rej))
                        - Counter(map(key, got_rej))).elements())
    extra_rej = list((Counter(map(key, got_rej))
                      - Counter(map(key, rec_rej))).elements())
    return {
        "emitted_intents": len(emitted),
        "recorded_intents": len(recorded),
        "missing_intents": sorted(recorded - emitted),
        "extra_intents": sorted(emitted - recorded),
        "recorded_strategy_rejects": len(rec_rej),
        "reproduced_strategy_rejects": len(got_rej),
        "missing_rejects": missing_rej[:5],
        "extra_rejects": extra_rej[:5],
        "intents_exact": emitted == recorded,
        "rejects_exact": not missing_rej and not extra_rej,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", required=True)
    ap.add_argument("--store", required=True)
    ap.add_argument("--rejections", required=True)
    ap.add_argument("--strategies", required=True,
                    help="comma-separated, e.g. S1,S3")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    export = run_capture(Path(args.capture),
                         [s.strip() for s in args.strategies.split(",")])
    report = validate(export, Path(args.store), Path(args.rejections))
    out = {"export": export, "validation": report}
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not (report["intents_exact"] and report["rejects_exact"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
