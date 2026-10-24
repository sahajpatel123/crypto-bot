"""H2-HIST: score frozen H2 rules on multi-year archive data (prereg).

Preregistration: research/prereg/H2-history-falsification.md (committed
before any download). Downloads Binance USD-M monthly markPriceKlines 1h
for 2022-01..2026-08 into datasets/history_1h/ (untracked cache), runs
research.h_eval.h2_trades unchanged, and writes
reports/hypotheses/H2-history.json with the kill-criteria outcome.

Usage: .venv/bin/python tools/eval_h2_history.py [--offline]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import statistics
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptobot.research.h_eval import Bar, equity_bps, h2_trades_fast, max_drawdown_bps  # noqa: E402
from cryptobot.research.verdict import evaluate_trades  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "datasets/history_1h"
UNIVERSE_A = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "ZECUSDT",
              "NEARUSDT", "STRKUSDT", "XRPUSDT", "WUSDT")
UNIVERSE_B = UNIVERSE_A + tuple(f"{s}USDT" for s in (
    "BNB", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT", "BCH", "TRX", "ATOM",
    "FIL", "ETC", "OP", "ARB", "APT", "INJ", "SUI", "TIA", "SEI", "UNI"))
MONTHS = [f"{y}-{m:02d}" for y in range(2022, 2027) for m in range(1, 13)
          if (y, m) <= (2026, 8)]
YEARS = ("2022", "2023", "2024", "2025", "2026")
URL = ("https://data.binance.vision/data/futures/um/monthly/"
       "markPriceKlines/{s}/1h/{s}-1h-{m}.zip")
FAMILY_SIZE = 4


def _fetch(symbol: str, month: str) -> Path | None:
    out = CACHE / symbol / f"{month}.csv"
    missing = CACHE / symbol / f"{month}.absent"
    if out.exists():
        return out
    if missing.exists():
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(URL.format(s=symbol, m=month),
                                 headers={"User-Agent": "cryptobot-h2-hist"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            blob = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # not listed that month
            missing.write_text("404\n")
            return None
        raise
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        text = zf.read(zf.namelist()[0]).decode()
    tmp = out.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(out)
    return out


def load_bars(symbol: str) -> list[Bar]:
    bars: dict[int, Bar] = {}
    for month in MONTHS:
        path = CACHE / symbol / f"{month}.csv"
        if not path.exists():
            continue
        for row in csv.reader(io.StringIO(path.read_text())):
            if not row or not row[0].isdigit():
                continue  # header
            ts = int(row[0])
            bars[ts] = Bar(ts_ms=ts, open=float(row[1]), high=float(row[2]),
                           low=float(row[3]), close=float(row[4]))
    return [bars[k] for k in sorted(bars)]


def _summary(trades) -> dict:
    if not trades:
        return {"n_trades": 0}
    net = [t.net_bps for t in trades]
    result = evaluate_trades(net, adverse_bps=[t.adverse_bps for t in trades],
                             days=[t.day for t in trades], max_dd_bps=0.0,
                             dd_budget_bps=1.0, family_size=FAMILY_SIZE,
                             min_trades=1)
    sized = equity_bps(trades)
    days = len({t.day for t in trades})
    by_year = {}
    for year in YEARS:
        sub = [t.net_bps for t in trades if t.day.startswith(year)]
        by_year[year] = {"n": len(sub),
                         "mean_net_bps": statistics.fmean(sub) if sub else None}
    return {
        "n_trades": len(trades),
        "mean_net_bps": result["expectancy_bps"],
        "mean_adverse_bps": result["expectancy_adverse_bps"],
        "ci95_day_block": result["ci95"],
        "p_value": result["p_value"],
        "holm_alpha": result["holm_alpha"],
        "nonneg_day_frac": result["nonneg_day_frac"],
        "mean_gross_bps": statistics.fmean(t.gross_bps for t in trades),
        "sized_equity_bps_total": sum(sized),
        "sized_equity_bps_per_trading_day": sum(sized) / days,
        "sized_max_dd_bps": max_drawdown_bps(
            [type(t)(day=t.day, gross_bps=v, net_bps=v, adverse_bps=v)
             for t, v in zip(trades, sized, strict=True)]),
        "by_year": by_year,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true",
                    help="score the existing cache only (no downloads)")
    args = ap.parse_args()
    if not args.offline:
        jobs = [(s, m) for s in UNIVERSE_B for m in MONTHS]
        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(lambda job: _fetch(*job), jobs))
    trades_by_symbol = {}
    for symbol in UNIVERSE_B:
        bars = load_bars(symbol)
        trades_by_symbol[symbol] = h2_trades_fast(bars) if len(bars) > 60 else []
        print(f"{symbol}: bars={len(bars)} trades={len(trades_by_symbol[symbol])}")

    def pooled(universe):
        return sorted((t for s in universe for t in trades_by_symbol[s]),
                      key=lambda t: t.day)

    a, b = _summary(pooled(UNIVERSE_A)), _summary(pooled(UNIVERSE_B))
    negative_years = [y for y, v in a.get("by_year", {}).items()
                      if v["mean_net_bps"] is not None and v["mean_net_bps"] <= 0]
    kills = []
    if not a["n_trades"] or a["ci95_day_block"][0] <= 0:
        kills.append("1: CI95 lower bound <= 0 at 1x cost")
    if not a["n_trades"] or a["mean_adverse_bps"] <= 0:
        kills.append("2: expectancy <= 0 at 2x adverse cost")
    if len(negative_years) >= 3:
        kills.append(f"3: non-positive in {len(negative_years)} years {negative_years}")
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    doc = {
        "hypothesis": "H2-HIST",
        "prereg": "research/prereg/H2-history-falsification.md",
        "data": "binance-vision um monthly markPriceKlines 1h 2022-01..2026-08",
        "code_commit": commit,
        "outcome": "KILLED" if kills else "SURVIVES-HISTORY",
        "kill_reasons": kills,
        "selection_dependent": bool(b.get("n_trades"))
        and (b.get("mean_net_bps") or 0) <= 0,
        "universe_A": a, "universe_B": b,
        "per_symbol": {s: _summary(t) for s, t in trades_by_symbol.items()},
    }
    out = ROOT / "reports/hypotheses/H2-history.json"
    out.write_text(json.dumps(doc, indent=1) + "\n")
    print(json.dumps({k: doc[k] for k in ("outcome", "kill_reasons",
                                            "selection_dependent")}, indent=1))
    for name in ("universe_A", "universe_B"):
        s = doc[name]
        print(name, {k: s.get(k) for k in ("n_trades", "mean_net_bps",
                                            "mean_adverse_bps", "ci95_day_block",
                                            "p_value")})
        print("  by_year", {y: (v["n"], None if v["mean_net_bps"] is None
                                else round(v["mean_net_bps"], 2))
                             for y, v in s.get("by_year", {}).items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
