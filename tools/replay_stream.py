"""Replay a capture through the real event boundary + build the DQ report (Worker 2, E-006).

Modes:
  replay: load events.jsonl, verify determinism (two independent hashes),
          rebuild 1s bars from arrival-order replayed trades+BBO, and assert
          the rebuilt (symbol, window, kind) set equals the captured bars.
  report: emit the latency/DQ report (JSON + Markdown) from run_stats.json:
          event counts, coverage, disconnects, dup/ooo/gap counts, spread and
          depth summaries, and p50/p95/p99 with n + channel + window +
          definitions. REST RTT, event age, and decision latency are kept
          distinct; NOTHING here measures order execution latency.

Examples:
  python tools/replay_stream.py replay --run-dir .captures/cap-20261012T000000Z
  python tools/replay_stream.py report --run-dir .captures/cap-20261012T000000Z
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptobot.market_data.bars import BarAggregator, BarMissing
from cryptobot.market_data.replayer import assert_input_class, events_hash, load_events, replay_events


def _percentile(sorted_samples: list[float], pct: float) -> float | None:
    if not sorted_samples:
        return None
    rank = math.ceil(pct / 100 * len(sorted_samples))
    return sorted_samples[max(0, min(rank - 1, len(sorted_samples) - 1))]


def _timing_block(name: str, entry: dict, definition: str, window: str) -> dict:
    samples = entry.get("sample", [])
    return {
        "metric": name,
        "definition": definition,
        "window": window,
        "n_total": entry.get("n", 0),
        "n_sampled": len(samples),
        "method": "bounded uniform reservoir (Vitter R, cap 20000); nearest-rank percentiles",
        "p50_ms": _percentile(samples, 50),
        "p95_ms": _percentile(samples, 95),
        "p99_ms": _percentile(samples, 99),
        "max_ms": max(samples) if samples else None,
    }


def cmd_replay(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    records = load_events(run_dir / "events.jsonl")
    for record in records:
        assert_input_class({"input_class": record["input_class"]}, args.expect_class)
    first = events_hash(records)
    second = events_hash(load_events(run_dir / "events.jsonl"))
    # Rebuild bars from the replayed stream through the real aggregator.
    aggregators: dict[str, BarAggregator] = {}
    replayed: set[tuple[str, int, str]] = set()

    def _note(symbol: str, closed) -> None:
        for bar in closed:
            kind = "missing" if isinstance(bar, BarMissing) else "bar"
            replayed.add((symbol, bar.window_start_ms, kind))

    for event in replay_events(records):
        symbol = event["symbol"]
        agg = aggregators.setdefault(symbol, BarAggregator(symbol))
        if event["channel"] == "aggTrade":
            _note(symbol, agg.on_trade(event))
        elif event["channel"] == "bookTicker":
            payload = event["payload"]
            agg.on_bbo(payload["bid"], payload["ask"], event["exchange_ts_ms"])
    for symbol, agg in aggregators.items():
        _note(symbol, agg.flush())
    captured = [json.loads(line) for line in (run_dir / "bars.jsonl").read_text().splitlines() if line.strip()]
    captured_set = {(b.get("symbol"), b.get("window_start_ms"), b.get("type")) for b in captured}
    n_bar = sum(1 for b in captured if b.get("type") == "bar")
    n_missing = sum(1 for b in captured if b.get("type") == "missing")
    agree = replayed == captured_set
    print(json.dumps({"run_dir": str(run_dir), "input_class": args.expect_class,
                      "events": len(records), "deterministic": first == second,
                      "events_sha256": first, "replayed_windows": len(replayed),
                      "captured_bar_records": n_bar, "captured_missing_records": n_missing,
                      "bar_rebuild_agrees": agree,
                      "only_replayed": sorted(replayed - captured_set)[:10],
                      "only_captured": sorted(captured_set - replayed)[:10]}, indent=2))
    return 0 if first == second and agree else 1


def cmd_report(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    stats = json.loads((run_dir / "run_stats.json").read_text())
    manifest = json.loads((run_dir / "manifest.json").read_text())
    window = f"{manifest.get('started_utc', '?')}..{manifest.get('ended_utc', '?')}"
    age = _timing_block(
        "event_age_ms", stats.get("event_age_ms", {}),
        "exchange event time -> local wall-clock receipt (uncorrected for clock offset; "
        "see clock_offset_start/end for the measured offset and RTT uncertainty). "
        "Includes venue fan-out + network transit; NOT order latency.",
        window)
    proc = _timing_block(
        "decision_latency_ms", stats.get("proc_latency_ms", {}),
        "local receipt -> finished processing one event, monotonic clock "
        "(parse + book/bar update + write buffering). Local pipeline cost only.",
        window)
    report = {
        "run_id": stats.get("run_id"), "input_class": "observed-public",
        "window_utc": window, "stop_reason": stats.get("stop_reason"),
        "symbols": manifest.get("symbols"), "capture_set_rule": manifest.get("capture_set_rule"),
        "events_total": stats.get("events_total"), "malformed": stats.get("malformed"),
        "per_channel": stats.get("per_channel"),
        "duplicates": stats.get("duplicates"), "out_of_order": stats.get("out_of_order"),
        "gaps": stats.get("gaps"), "disconnects": stats.get("disconnects"),
        "reconnects": stats.get("reconnects"),
        "depth": {"resyncs": stats.get("depth_resyncs"), "applied": stats.get("depth_applied"),
                  "books": stats.get("books")},
        "bars": stats.get("bars"),
        "clock_offset_start": stats.get("clock_offset_start"),
        "clock_offset_end": stats.get("clock_offset_end"),
        "timings": [age, proc],
        "latency_claim_boundary": ("REST RTT, event age, and decision latency are distinguished "
                                   "above. NOTHING in this report measures order execution/ack "
                                   "latency, which a public-only collector cannot observe."),
        "files": manifest.get("files"),
    }
    (run_dir / "report.json").write_text(json.dumps(report, indent=2))
    lines = [f"# Capture report {report['run_id']}", "",
             f"Window (UTC): {window} — stop: {report['stop_reason']}",
             f"Symbols: {', '.join(manifest.get('symbols', []))} ({manifest.get('capture_set_rule')})",
             f"Events: {report['events_total']} total, {report['malformed']} malformed; "
             f"dup {report['duplicates']}, ooo {report['out_of_order']}; "
             f"gaps {report['gaps']}; disconnects {report['disconnects']} "
             f"({report['reconnects']} reconnects); depth resyncs {report['depth']['resyncs']}.",
             ""]
    for block in report["timings"]:
        lines += [f"## {block['metric']} (n={block['n_total']}, sampled={block['n_sampled']})", "",
                  block["definition"], "",
                  f"p50 {block['p50_ms']} ms; p95 {block['p95_ms']} ms; "
                  f"p99 {block['p99_ms']} ms; max {block['max_ms']} ms.",
                  f"Method: {block['method']}.", ""]
    lines += ["## Claim boundary", "", report["latency_claim_boundary"], ""]
    (run_dir / "report.md").write_text("\n".join(lines))
    print(json.dumps({"report_json": str(run_dir / "report.json"),
                      "report_md": str(run_dir / "report.md"),
                      "events_total": report["events_total"],
                      "p50_age_ms": age["p50_ms"], "p99_age_ms": age["p99_ms"],
                      "p50_proc_ms": proc["p50_ms"]}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Event replay + capture reports")
    sub = parser.add_subparsers(dest="mode", required=True)
    p_replay = sub.add_parser("replay")
    p_replay.add_argument("--run-dir", required=True)
    p_replay.add_argument("--expect-class", default="observed-public")
    p_replay.set_defaults(func=cmd_replay)
    p_report = sub.add_parser("report")
    p_report.add_argument("--run-dir", required=True)
    p_report.set_defaults(func=cmd_report)
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
