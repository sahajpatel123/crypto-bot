"""Exact per-symbol eligible intervals for research input (READY-DATA A).

Offline market-data analysis (no replay): streams the capture once and
emits the gap ledger (one class per excluded span, never a generic gap
reason), mechanical-warmup vs market-eligibility clocks separately, and
their labeled research-ready intersection. Bounds come from --profile
(live rules by default); the verdict records the profile fingerprint.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cryptobot.app.config import load_config  # noqa: E402
from cryptobot.market_data.eligibility import classify_capture  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Eligible-interval export.")
    ap.add_argument("--capture", required=True, type=Path)
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--profile", default=ROOT / "configs" / "paper.toml",
                    type=Path)
    ap.add_argument("--out", default=None, type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    cfg = load_config(args.profile)
    manifest_path = args.capture / "manifest.json"
    manifest_symbols: list[str] = []
    if manifest_path.exists():
        try:
            manifest_symbols = (
                json.loads(manifest_path.read_text()).get("symbols") or [])
        except ValueError:
            pass
    symbols = (args.symbols.split(",") if args.symbols
               else manifest_symbols)
    if not symbols:
        print("no symbols: manifest lacks symbols and --symbols not given",
              file=sys.stderr)
        return 2
    report = classify_capture(
        args.capture, symbols,
        quote_bound_ms=int(cfg.quote_max_age_s * 1000),
        mark_bound_ms=(int(cfg.risk.max_mark_age_ms)
                       if cfg.risk.max_mark_age_ms is not None else None),
        warmup_bars=cfg.warmup_bars)
    report["profile"] = {"path": str(args.profile),
                         "fingerprint": cfg.fingerprint,
                         "profile_version": cfg.profile_version}
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(text)
    if args.json or args.out is None:
        print(text)
    else:
        for symbol, entry in report["symbols"].items():
            print(f"{symbol}: market_eligible_s={entry['market_eligible_s']:.1f} "
                  f"research_eligible_s={entry['research_eligible_s']:.1f} "
                  f"intervals={len(entry['market_intervals'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
