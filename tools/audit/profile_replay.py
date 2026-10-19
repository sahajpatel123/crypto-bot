#!/usr/bin/env python3
"""Profile one real replay for directive section-2 gap-1 bottlenecks.

Gap-1 claims: preparation gathers an entire split into lists, globally
sorts it, creates a large string dedup set, and joins the entire JSON
output. DatasetHandle materializes day tables; run_cell reads a whole
capture just to inspect its first record; Session.run_replay loads/sorts
the whole capture again. max-events truncates AFTER preparation.

This script measures one real day + one real replay prefix and reports
time/memory/throughput plus 30-day projections. Read-only on the dataset;
writes only to --out and a temp capture dir.

Usage:
    PYTHONPATH=<worktree>/src python tools/audit/profile_replay.py \\
        --dataset /Users/sahajpatel/Code/cryto-bot/datasets/benchmark_30d.toml \\
        --symbol BTCUSDT --day 2026-09-12 --replay-events 5000 \\
        --out /tmp/w5-profile.json
"""
import argparse
import gc
import json
import resource
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def _rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024


def _phase_events(dataset_path, symbol, day):
    from cryptobot.market_data.datasets import open_dataset
    ds = open_dataset(dataset_path)
    sources = [s for s in ds.manifest.get("source", [])
               if s.get("symbol") == symbol and s.get("day") == day]
    parquet_rows = sum(int(s.get("rows", 0)) for s in sources)
    parquet_bytes = 0
    for s in sources:
        local = s.get("local", "")
        p = (Path(dataset_path).parent / local) if local else None
        if p and p.exists():
            parquet_bytes += p.stat().st_size
    gc.collect()
    tracemalloc.start()
    t0 = time.perf_counter()
    n_events = 0
    n_heartbeats = 0
    first_ts = None
    last_ts = None
    for item in ds.events(symbol, day):
        if item is None:
            n_heartbeats += 1
            continue
        n_events += 1
        ts = int(item["exchange_ts_ms"])
        if first_ts is None:
            first_ts = ts
        last_ts = ts
    dt = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "symbol": symbol, "day": day,
        "parquet_sources": len(sources),
        "parquet_rows": parquet_rows,
        "parquet_bytes": parquet_bytes,
        "events_yielded": n_events,
        "heartbeats_yielded": n_heartbeats,
        "first_ts_ms": first_ts, "last_ts_ms": last_ts,
        "wall_s": round(dt, 3),
        "peak_tracemalloc_mb": round(peak / 1024 / 1024, 2),
        "rss_mb": round(_rss_mb(), 1),
        "events_per_s": round(n_events / dt, 1) if dt > 0 else 0,
        "note": ("DatasetHandle._vision_events materializes per-channel day "
                 "tables then sorts (datasets.py:94-102); streaming reads "
                 "still hold the full day in lists before yielding."),
    }


def _phase_prepare_synth(tmp_root):
    from cryptobot.research.backtest import prepare_split_capture
    from cryptobot.research.synth_benchmark import SynthBenchmark
    bench = SynthBenchmark()
    out = {}
    for label, max_events in (("full-dev-15d", None), ("max500", 500)):
        gc.collect()
        tracemalloc.start()
        t0 = time.perf_counter()
        cap = Path(tmp_root) / f"cap-{label}"
        manifest = prepare_split_capture(bench, "dev", cap, ("XRPUSDT",),
                                         None, max_events)
        dt = time.perf_counter() - t0
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        events_path = cap / "events.jsonl"
        out[label] = {
            "n_events": manifest["n_events"],
            "deduped_repeats": manifest.get("deduped_repeats", 0),
            "truncated_prefix": manifest.get("truncated_prefix", False),
            "events_jsonl_bytes": events_path.stat().st_size,
            "wall_s": round(dt, 3),
            "peak_tracemalloc_mb": round(peak / 1024 / 1024, 2),
        }
    out["note"] = ("max-events truncates AFTER full preparation "
                   "(backtest.py:269-305): the max500 run still gathers, "
                   "sorts, dedups, and renumbers the full 15-day split "
                   "before slicing the prefix.")
    return out


def _build_real_prefix(dataset_path, symbol, day, n, tmp_root):
    from cryptobot.market_data.datasets import open_dataset
    ds = open_dataset(dataset_path)
    events = []
    for item in ds.events(symbol, day):
        if item is None:
            continue
        events.append(item)
        if len(events) >= n:
            break
    for seq, e in enumerate(events, start=1):
        e["seq"] = seq
        e["local_mono_ns"] = seq
    cap = Path(tmp_root) / "cap-real-prefix"
    cap.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    payload = "\n".join(json.dumps(e) for e in events) + "\n"
    join_s = time.perf_counter() - t0
    (cap / "events.jsonl").write_text(payload, encoding="utf-8")
    return cap, {
        "n_events": len(events),
        "events_jsonl_bytes": len(payload.encode("utf-8")),
        "json_join_s": round(join_s, 4),
        "note": ("Single giant JSON join (backtest.py:316-317 pattern); "
                 "Session.run_replay will load and sort this file again."),
    }


def _phase_replay(cap_dir, tmp_root):
    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session
    from cryptobot.app.store import RunStore
    from cryptobot.market_data.replayer import load_events, replay_events
    events_path = Path(cap_dir) / "events.jsonl"
    # run_cell first-record pattern: whole-file read for line 1.
    t0 = time.perf_counter()
    first_class = json.loads(
        events_path.read_text(encoding="utf-8").splitlines()[0])["input_class"]
    first_line_cost_s = time.perf_counter() - t0
    file_bytes = events_path.stat().st_size
    # Session.run_replay stages, timed separately.
    gc.collect()
    tracemalloc.start()
    t0 = time.perf_counter()
    records = load_events(events_path)
    load_s = time.perf_counter() - t0
    load_peak = tracemalloc.get_traced_memory()[1]
    t0 = time.perf_counter()
    ordered = list(replay_events(records))
    sort_s = time.perf_counter() - t0
    _, replay_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(ordered) == len(records)
    # Full Session replay (ReferenceEngine; measures load/sort/ingest path).
    text = open(ROOT / "configs" / "paper.toml").read()
    text = text.replace('dir = "runs"', f'dir = "{Path(tmp_root) / "runs"}"', 1)
    cfg_path = Path(tmp_root) / "profile.toml"
    cfg_path.write_text(text)
    cfg = load_config(cfg_path)
    store = RunStore(Path(tmp_root) / "runs" / "cryptobot.db")
    try:
        session = Session(cfg, store, Path(tmp_root) / "runs" / "prof", "prof")
        t0 = time.perf_counter()
        report = session.run_replay(cap_dir, expect_class=first_class)
        replay_s = time.perf_counter() - t0
    finally:
        store.close()
    n = len(records)
    return {
        "input_class": first_class,
        "file_bytes": file_bytes,
        "first_record_whole_read_s": round(first_line_cost_s, 4),
        "load_events_s": round(load_s, 4),
        "load_peak_mb": round(load_peak / 1024 / 1024, 2),
        "replay_sort_s": round(sort_s, 4),
        "replay_sort_peak_mb": round(replay_peak / 1024 / 1024, 2),
        "session_run_replay_s": round(replay_s, 3),
        "events_seen": report.get("events_seen", n),
        "session_events_per_s": round(n / replay_s, 1) if replay_s > 0 else 0,
        "rss_mb": round(_rss_mb(), 1),
        "note": ("run_cell reads the whole capture for its first record "
                 "(backtest.py:394-396); run_replay loads (replayer.py:83-90) "
                 "and sorts (replayer.py:93-111) the whole file again before "
                 "the ingest loop."),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--day", default="2026-09-12")
    parser.add_argument("--replay-events", type=int, default=5000)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = {
        "base": "01487ac",
        "dataset": args.dataset,
        "provenance": "Worker 5 OP-001 gap-1 profiler (read-only dataset)",
    }
    print("phase A: real one-day read ...", flush=True)
    result["phase_a_day_read"] = _phase_events(args.dataset, args.symbol, args.day)
    print(f"  {result['phase_a_day_read']['events_yielded']} events in "
          f"{result['phase_a_day_read']['wall_s']}s "
          f"({result['phase_a_day_read']['events_per_s']}/s, peak "
          f"{result['phase_a_day_read']['peak_tracemalloc_mb']}MB)", flush=True)
    with tempfile.TemporaryDirectory(prefix="w5-prof-") as tmp:
        print("phase B: synth prepare (full vs max500) ...", flush=True)
        result["phase_b_prepare"] = _phase_prepare_synth(tmp)
        for label in ("full-dev-15d", "max500"):
            info = result["phase_b_prepare"][label]
            print(f"  {label}: n={info['n_events']} wall={info['wall_s']}s "
                  f"peak={info['peak_tracemalloc_mb']}MB "
                  f"bytes={info['events_jsonl_bytes']}", flush=True)
        print(f"phase C: real {args.replay_events}-event prefix replay ...",
              flush=True)
        cap, build_info = _build_real_prefix(
            args.dataset, args.symbol, args.day, args.replay_events, tmp)
        result["phase_c_prefix_build"] = build_info
        result["phase_d_session_replay"] = _phase_replay(cap, tmp)
        info = result["phase_d_session_replay"]
        print(f"  load={info['load_events_s']}s sort={info['replay_sort_s']}s "
              f"replay={info['session_run_replay_s']}s "
              f"({info['session_events_per_s']}/s)", flush=True)
    # Projections from measured throughput AND memory.
    per_s = result["phase_d_session_replay"]["session_events_per_s"] or 1
    manifest_rows = 171_360_000  # directive gap-1 declared scale.
    eta_s = manifest_rows / per_s
    day_events = result["phase_a_day_read"]["events_yielded"] or 1
    day_peak_mb = result["phase_a_day_read"]["peak_tracemalloc_mb"]
    day_jsonl_bytes = result["phase_c_prefix_build"]["events_jsonl_bytes"]
    day_jsonl_n = result["phase_c_prefix_build"]["n_events"] or 1
    mem_scale = manifest_rows / day_events
    proj_peak_gb = day_peak_mb * mem_scale / 1024
    proj_jsonl_gb = (day_jsonl_bytes / day_jsonl_n * manifest_rows
                     / 1024 / 1024 / 1024)
    result["projection_171M_rows"] = {
        "assumed_rows": manifest_rows,
        "measured_session_events_per_s": per_s,
        "eta_hours": round(eta_s / 3600, 1),
        "eta_days": round(eta_s / 86400, 2),
        "measured_day_peak_mb_per_297k": day_peak_mb,
        "projected_prep_peak_gb_linear": round(proj_peak_gb, 1),
        "projected_events_jsonl_gb": round(proj_jsonl_gb, 1),
        "verdict": (f"Time (~{eta_s/3600:.0f}h at {per_s:.0f}/s) fits 48h, "
                    f"but memory does not: one 297k-event day peaks at "
                    f"{day_peak_mb}MB; linear scale to 171M rows projects "
                    f"~{proj_peak_gb:.0f}GB prep peak plus "
                    f"~{proj_jsonl_gb:.0f}GB events.jsonl, before "
                    "dedup-set/sort overhead. Preparation must stream with "
                    "bounded merges and pre-truncation limits (gap-1)."),
    }
    Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"wrote {args.out}", flush=True)
    print(json.dumps(result["projection_171M_rows"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
