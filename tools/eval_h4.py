"""H4 fresh-only scorer (prereg H4-vol-ranked-trend.md).

Refuses to score any day before FRESH_FROM (the preregistration
commit date). Run daily after tools/extend_benchmark.py lands new
archived days; writes reports/hypotheses/H4.json.
Usage: .venv/bin/python tools/eval_h4.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptobot.data_assets import verify_benchmark_inputs  # noqa: E402
from cryptobot.research.h_eval import h4_trades, hourly_bars, verdict_for  # noqa: E402
from cryptobot.research.verdict import verdict_document  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FRESH_FROM = "2026-10-20"  # first full day after H4 prereg commit
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "ZECUSDT",
           "NEARUSDT", "STRKUSDT", "XRPUSDT", "WUSDT")


def main() -> int:
    pre = verify_benchmark_inputs(ROOT)
    print(f"H4 data preflight: {pre['sources']} sources, "
          f"manifest={pre.get('manifest_sha')} cache_through={pre.get('last_date')}")
    if not pre["ok"]:
        for problem in pre["problems"][:5]:
            print(f"H4 preflight: FAIL {problem}", file=sys.stderr)
        return 2
    if (pre.get("last_date") or "") < FRESH_FROM:
        print(f"H4 preflight: no fresh day >= {FRESH_FROM}; "
              "the verdict will be UNDERPOWERED (n=0).")
    bars = {s: [b for b in hourly_bars(s, ROOT / "datasets/cache")
                if b.ts_ms >= 1792454400000]  # 2026-10-19 warmup start
            for s in SYMBOLS}
    trades = [t for t in h4_trades(bars) if t.day >= FRESH_FROM]
    doc = verdict_for("H4-vol-ranked-trend", trades)
    doc["family_size"] = 4
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    bound = verdict_document(
        hypothesis="H4-vol-ranked-trend", result=doc,
        config_path=ROOT / "research/prereg/H4-vol-ranked-trend.md",
        data_manifest="fresh>=" + FRESH_FROM + ":" + hashlib.sha256(
            (ROOT / "datasets/benchmark_30d.toml").read_bytes()).hexdigest()[:12],
        code_commit=commit)
    out = ROOT / "reports/hypotheses/H4.json"
    out.write_text(json.dumps(bound, indent=1) + "\n")
    print(f"H4 {bound['verdict']} n={bound.get('n_trades')} "
          f"exp={bound.get('expectancy_bps')} fresh_from={FRESH_FROM}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
