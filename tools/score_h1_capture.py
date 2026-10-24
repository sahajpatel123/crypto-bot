"""Score an H1 depth capture (preregistered H1-book-capture.md).

Replays events.jsonl through the bridge books, samples top-5
snapshots every 1s per symbol, runs h1_eval.h1_trades with aggTrade
prints, and writes a hash-bound verdict JSON.
Usage: .venv/bin/python tools/score_h1_capture.py <run_dir> <out.json>
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptobot.market_data.bridge import iter_market_stream  # noqa: E402
from cryptobot.research.h1_eval import Snapshot, h1_trades  # noqa: E402
from cryptobot.research.h_eval import verdict_for  # noqa: E402
from cryptobot.research.verdict import verdict_document  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    run_dir = Path(sys.argv[1])
    snaps: dict[str, list[Snapshot]] = {}
    prints: dict[str, list[tuple[int, float, float]]] = {}
    last_sample: dict[str, int] = {}
    for item in iter_market_stream(run_dir / "events.jsonl",
                                   run_dir / "depth_snapshots.jsonl"):
        record = item.record
        symbol = str(record.get("symbol", ""))
        ts = int(record.get("local_recv_ms", 0))
        if record.get("channel") == "aggTrade":
            payload = record["payload"]
            prints.setdefault(symbol, []).append(
                (ts, float(payload["price"]), float(payload["qty"])))
        book = item.books.get(symbol)
        if book is None or not book.ever_synced:
            continue
        if ts - last_sample.get(symbol, 0) < 1000:
            continue
        last_sample[symbol] = ts
        bids = tuple(sorted(((p, q) for p, q in book.book.bids.items()),
                            reverse=True)[:5])
        asks = tuple(sorted((p, q) for p, q in book.book.asks.items())[:5])
        if bids and asks:
            snaps.setdefault(symbol, []).append(
                Snapshot(ts_ms=ts, bids=bids, asks=asks))
    trades = []
    for symbol, series in snaps.items():
        trades += h1_trades(series, prints.get(symbol, []))
    doc = verdict_for("H1-maker-ofi-scalp", trades)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    bound = verdict_document(
        hypothesis="H1-maker-ofi-scalp", result=doc,
        config_path=ROOT / "research/prereg/H1-book-capture.md",
        data_manifest=f"capture:{run_dir.name}:"
                      f"{hashlib.sha256((run_dir / 'manifest.json').read_bytes()).hexdigest()[:12]}"
                      if (run_dir / "manifest.json").exists() else f"capture:{run_dir.name}",
        code_commit=commit)
    Path(sys.argv[2]).write_text(json.dumps(bound, indent=1) + "\n")
    print(f"H1 {bound['verdict']} n={bound.get('n_trades')} "
          f"exp={bound.get('expectancy_bps')} snapshots="
          f"{ {k: len(v) for k, v in snaps.items()} }")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
