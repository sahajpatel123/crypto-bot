"""Dev evaluation runner: H1/H2/H3 exactly as preregistered (T5.4).

Usage: .venv/bin/python tools/eval_h123.py
Writes reports/hypotheses/H{1,2,3}.json (hash-bound verdict documents).
Dev data only; the confirmation capture is never touched.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptobot.data_assets import verify_benchmark_inputs  # noqa: E402
from cryptobot.research.h_eval import (  # noqa: E402
    h1_result,
    h2_trades,
    h3_trades,
    hourly_bars,
    load_funding,
    verdict_for,
)
from cryptobot.research.verdict import verdict_document  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "ZECUSDT",
           "NEARUSDT", "STRKUSDT", "XRPUSDT", "WUSDT")


def main() -> int:
    pre = verify_benchmark_inputs(ROOT)
    print(f"H1/H2/H3 data preflight: {pre['sources']} sources, "
          f"manifest={pre.get('manifest_sha')} cache_through={pre.get('last_date')}")
    if not pre["ok"]:
        for problem in pre["problems"][:5]:
            print(f"preflight: FAIL {problem}", file=sys.stderr)
        return 2
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    manifest = hashlib.sha256(
        (ROOT / "datasets/benchmark_30d.toml").read_bytes()).hexdigest()[:16]
    out_dir = ROOT / "reports/hypotheses"
    out_dir.mkdir(parents=True, exist_ok=True)
    docs: dict[str, dict] = {"H1": h1_result()}
    for name, fn in (("H2", "h2"), ("H3", "h3")):
        trades = []
        for symbol in SYMBOLS:
            bars = hourly_bars(symbol, ROOT / "datasets/cache")
            trades += (h2_trades(bars) if fn == "h2"
                       else h3_trades(bars, load_funding(symbol, ROOT / "datasets/cache")))
        docs[name] = verdict_for(f"{name}-prereg", trades)
    prereg = {"H1": "research/prereg/H1-maker-ofi-scalp.md",
              "H2": "research/prereg/H2-trend-vol-regime.md",
              "H3": "research/prereg/H3-funding-skew-tilt.md"}
    for name, doc in docs.items():
        bound = verdict_document(hypothesis=doc.get("hypothesis", name), result=doc,
                                 config_path=ROOT / prereg[name],
                                 data_manifest=f"benchmark_30d:{manifest}",
                                 code_commit=commit)
        (out_dir / f"{name}.json").write_text(json.dumps(bound, indent=1) + "\n")
        print(f"{name}: {bound['verdict']} n={bound.get('n_trades')} "
              f"exp={bound.get('expectancy_bps')} "
              f"per_active_day={bound.get('mean_net_bps_per_active_day')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
