"""SC development-window measurement (specs/strategies/SC.md §5–§6).

Runs the shipped bench on the predeclared dev slice, then writes the
ledger average and the qualification verdict into that report. The
window, the cost preset, and the band are constants. This module does
not edit them from a result.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from cryptobot.bench_run import main as bench_main

# SC.md §5. Full IST day of deep-split idx 1 (2026-09-12), not the
# 15-minute prefix. One accounting date. The two UTC files are how
# that IST day is stored.
WINDOW_START_MS = 1789151400000
WINDOW_END_MS = 1789237800000
UTC_DAYS = "2026-09-11,2026-09-12"
SYMBOL = "BTCUSDT"
ACCOUNTING_DATES = 1
WALL_BUDGET_S = 3600
BAND_LO = 1.5
BAND_HI = 2.0
RECONCILE_TICK_USDT = 1e-4

CONFIG = "configs/sc-dev.toml"
DATASET = "datasets/benchmark_30d.toml"
FILTERS = "filters/x1_bench_filters.json"


def net_return_pct(equity_open: float, equity_close: float) -> float:
    if equity_open <= 0:
        raise ValueError("equity_open must be > 0")
    return (equity_close / equity_open - 1.0) * 100.0


def average_daily_net_pct(net_return: float, accounting_dates: int) -> float:
    """Window return divided by dates touched. Never scaled by 1440/minutes."""
    if accounting_dates < 1:
        raise ValueError("accounting_dates must be >= 1")
    return net_return / accounting_dates


def reconcile_book(booked: dict[str, Any]) -> dict[str, Any]:
    """Flat-book identity: equity_close == equity_open + realised.

    Funding is already inside realised. Adding funding_net again would
    count an unpriced or priced settlement twice, so it is not added.
    """
    equity_open = float(booked["equity_open"])
    equity_close = booked.get("equity_close")
    realised = float(booked["realised"])
    funding = float(booked["funding"])
    paid = float(booked["commissions"])
    if equity_close is None:
        return {"ok": False, "reason": "equity_close missing",
                "paid_costs": paid, "funding_net": funding,
                "net_return_pct": None}
    equity_close = float(equity_close)
    expected = equity_open + realised
    gap = equity_close - expected
    return {
        "ok": abs(gap) <= RECONCILE_TICK_USDT,
        "gap_usdt": gap,
        "expected_close": expected,
        "paid_costs": paid,
        "funding_net": funding,
        "net_return_pct": net_return_pct(equity_open, equity_close),
        "funding_note": (
            "funding_net is not added into the return; a booked 0 is "
            "not a profit"),
    }


def verdict(report: dict[str, Any], *,
            accounting_dates: int = ACCOUNTING_DATES,
            validation_net_pct: float | None = None) -> dict[str, Any]:
    """Band check. Validation that was not run is not strictly positive."""
    recon = reconcile_book(report["booked"])
    net = recon["net_return_pct"]
    avg = None if net is None else average_daily_net_pct(net, accounting_dates)
    in_band = avg is not None and BAND_LO <= avg <= BAND_HI
    validation_positive = (
        validation_net_pct is not None and validation_net_pct > 0.0)
    ledger_positive = net is not None and net > 0.0
    qualified = bool(in_band and ledger_positive and validation_positive
                     and recon["ok"])
    if qualified:
        reason = "inside 1.5-2% with positive validation net"
    else:
        failed: list[str] = []
        if not in_band:
            failed.append("average daily net is outside 1.5-2%")
        if not ledger_positive:
            failed.append("ledger net is not strictly positive")
        if not validation_positive:
            failed.append("validation net is not strictly positive")
        if not recon["ok"]:
            failed.append("ledger did not reconcile")
        reason = "; ".join(failed)
    return {
        "avg_daily_net_pct": avg,
        "band": [BAND_LO, BAND_HI],
        "inside_band": in_band,
        "validation_net_pct": validation_net_pct,
        "qualified_for_real_capital": qualified,
        "reason": reason,
        "reconcile": recon,
        "accounting_dates": accounting_dates,
    }


def annotate(report: dict[str, Any], *,
             validation_net_pct: float | None = None) -> dict[str, Any]:
    """Return the report plus the SC verdict. Does not change costs."""
    out = dict(report)
    out["sc"] = verdict(report, validation_net_pct=validation_net_pct)
    out["paid_costs"] = out["sc"]["reconcile"]["paid_costs"]
    out["net_return_pct"] = out["sc"]["reconcile"]["net_return_pct"]
    out["funding_net"] = out["sc"]["reconcile"]["funding_net"]
    return out


def bench_argv(checkpoint_dir: str, report_out: str, run_id: str) -> list[str]:
    """Frozen bench command for one dev-window run."""
    return [
        "--config", CONFIG,
        "--dataset", DATASET,
        "--symbol", SYMBOL,
        "--days", UTC_DAYS,
        "--start-ms", str(WINDOW_START_MS),
        "--end-ms", str(WINDOW_END_MS),
        "--spread-bps",
        "--filters-file", FILTERS,
        "--wall-budget-s", str(WALL_BUDGET_S),
        "--checkpoint-dir", checkpoint_dir,
        "--report-out", report_out,
        "--run-id", run_id,
        "--engine-seed", "42",
    ]


def measure(checkpoint_dir: str, report_out: str, run_id: str) -> int:
    """Run the bench, then write the annotated report over report_out.

    A nonzero bench status is preserved. The file is annotated only
    when the bench wrote JSON. A missing file is not replaced with a
    made-up return.
    """
    code = bench_main(bench_argv(checkpoint_dir, report_out, run_id))
    path = Path(report_out)
    if not path.is_file():
        return code if code else 1
    report = json.loads(path.read_text(encoding="utf-8"))
    annotated = annotate(report, validation_net_pct=None)
    path.write_text(json.dumps(annotated, indent=1) + "\n", encoding="utf-8")
    return code


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="SC dev-window measurement")
    parser.add_argument("--checkpoint-dir", required=True)
    parser.add_argument("--report-out", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    return measure(args.checkpoint_dir, args.report_out, args.run_id)


if __name__ == "__main__":
    sys.exit(main())
