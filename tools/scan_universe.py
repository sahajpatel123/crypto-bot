"""Bounded universe scan + max-2 subscription selection (REL-W3-DATA 1).

Runs one bounded scan (3 REST calls + depth for top-K, cached) and
prints the ranking table with the selected subscriptions. Public
market-data endpoints only; run under tools/run_budget.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cryptobot.app.config import load_config  # noqa: E402
from cryptobot.market_data.discovery import urllib_json_get  # noqa: E402
from cryptobot.market_data.universe import scan_and_select  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    from cryptobot import netguard  # opt-in DNS-sinkhole fallback (CRYPTOBOT_DOH=1)

    netguard.install_from_env()
    ap = argparse.ArgumentParser(description="Universe scan + selection.")
    ap.add_argument("--config", default=ROOT / "configs" / "paper.toml",
                    type=Path)
    ap.add_argument("--position-symbol", default=None)
    ap.add_argument("--no-depth", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default=None, type=Path)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    cache = Path(cfg.storage_dir) / "universe_cache.json"
    report = scan_and_select(
        urllib_json_get, cache_path=cache,
        max_min_notional_usdt=cfg.min_notional_usdt,
        max_active=cfg.max_hf_subscriptions,
        position_symbol=args.position_symbol,
        enrich_depth=not args.no_depth)
    report["profile"] = {"path": str(args.config),
                         "fingerprint": cfg.fingerprint}
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(text)
    if args.json or args.out is None:
        print(text)
    else:
        print(f"universe={report['universe']} "
              f"feasible={report['feasible']} picks={report['picks']} "
              f"rest_calls={report['rest_calls']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
