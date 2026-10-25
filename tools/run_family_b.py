#!/usr/bin/env python3
"""E6.1: frozen Family B DEV evaluation runner (locked before data).

Reads research/configs/B*.toml, expands the 59-cell grid, runs every
cell on the DEV lake, attributes pooled OOS (2021-2023 post-gap),
applies promotion_gates, writes machine dev artifacts. With
--auto-freeze, survivors are vault-frozen in the same unattended run
(D-033 batch semantics: no human between evals and freezes).

Deterministic: fixed seeds, no wall-clock inputs except timestamps.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptobot.research import family_b as FB  # noqa: E402
from cryptobot.research import slow_backtest as BT  # noqa: E402
from cryptobot.research import slow_stats as ST  # noqa: E402
from cryptobot.research.family_b_driver import (  # noqa: E402
    MAX_HOLD_D, TEST_YEARS, cell_key, expand_grid, load_grid_from_toml,
    oos_year_nets, pooled_oos_returns, promotion_gates, rebalance_dates)
from cryptobot.research.lake import load_dev_frames  # noqa: E402
from cryptobot.research.universe import eligible_universe  # noqa: E402

CADENCE = {"B1": "weekly", "B2": "weekly", "B3": "weekly", "B4": "daily",
           "B5": "daily", "B6": "weekly", "B7": "monthly"}
SIGNAL_FN = {"B1": FB.signals_b1, "B2": FB.signals_b2, "B3": FB.signals_b3,
             "B4": FB.signals_b4, "B5": FB.signals_b5, "B6": FB.signals_b6,
             "B7": FB.signals_b7}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config(hypothesis: str) -> tuple[dict, str]:
    path = Path(f"research/configs/{hypothesis}.toml")
    doc = tomllib.loads(path.read_text())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return doc, digest


def build_market_data(lake: Path, *, need_hourly: bool = False) -> FB.MarketData:
    import pandas as pd

    syms = sorted(p.name.split("=", 1)[1] for p in
                  (lake / "klines" / "interval=1d").glob("symbol=*"))
    daily = load_dev_frames(lake, "klines", syms, interval="1d")
    hourly = (load_dev_frames(lake, "klines", syms, interval="1h")
              if need_hourly else {})
    funding = load_dev_frames(lake, "funding", syms)
    oi: dict[str, pd.Series] = {}
    for sym in syms:
        mp = lake / "metrics" / f"symbol={sym}" / "data.parquet"
        if mp.exists():
            df = pd.read_parquet(mp).sort_values("create_time")
            day = df["create_time"].dt.floor("D")
            first = df.groupby(day, sort=True).first()
            oi[sym] = pd.Series(first["sum_open_interest"].to_numpy(),
                                index=pd.DatetimeIndex(first.index, tz="UTC"))
    spot: dict[str, pd.DataFrame] = {}
    for sym in ("BTCUSDT", "ETHUSDT"):
        sp = lake / "spot" / f"symbol={sym}" / "data.parquet"
        if sp.exists():
            import pandas as pd2
            spot[sym] = pd2.read_parquet(sp)
    return FB.MarketData(daily=daily, funding=funding, oi=oi, hourly=hourly,
                         spot=spot)


def evaluate_cell(hypothesis: str, params: dict, data: FB.MarketData,
                  cfg: dict, costs: BT.CostModel, equity: float) -> dict:
    ucfg = cfg["universe"]
    cache = evaluate_cell._universe_cache

    def universe_fn(d):
        import re
        key = str(d)
        if key not in cache:
            cache[key] = eligible_universe(
                d, data.daily, top_n=int(ucfg["top_n"]),
                min_listing_age_days=int(ucfg["min_listing_age_days"]),
                min_quote_volume_30d=float(ucfg["min_quote_volume_30d"]))
        out = list(cache[key])
        if hypothesis == "B4":
            out = [s for s in out if s in ("BTCUSDT", "ETHUSDT")]
        # D-038 tripwire: settlement indices / expired quarterlies were
        # never tradable as USDT perps. The frozen rule stands literally,
        # but if one ever qualifies, abort loudly instead of backtesting
        # fiction. (Zero qualified in DEV; verified in scope step.)
        bad = [s for s in out if "SETTLED" in s or re.search(r"_[0-9]{6}$", s)]
        if bad:
            raise ValueError(f"untradeable symbols in universe at {d}: {bad}")
        return out

    full_params = dict(params)
    for k, v in cfg["grid"].items():
        if not isinstance(v, list) and k not in full_params:
            full_params[k] = v
    dates = sorted({t for df in data.daily.values() for t in df["open_time"]})
    import pandas as pd
    rebal = rebalance_dates(pd.DatetimeIndex(dates), CADENCE[hypothesis])
    targets, info = SIGNAL_FN[hypothesis](data, full_params, rebal,
                                          universe_fn)
    stops_by_day: dict = {}
    if hypothesis == "B5":
        for d, per in (info.get("history", {}) or {}).items():
            rules = {}
            for sym, st in per.items():
                if st.get("side") and st.get("stop"):
                    exp = pd.Timestamp(st.get("expiry") or d)
                    exp = exp.tz_localize("UTC") if exp.tzinfo is None else exp.tz_convert("UTC")
                    rules[sym] = {"stop": st["stop"], "expiry": exp}
            if rules:
                stops_by_day[d] = rules
    res = BT.simulate_vectorized(targets, data.daily, data.funding,
                                 costs=costs, stops_by_day=stops_by_day,
                                 config=BT.SimConfig(
                                     initial_equity=float(equity)),
                                 spot=data.spot, hourly=data.hourly)
    gap = max(35, 2 * MAX_HOLD_D[hypothesis])
    rx = res.equity.pct_change().dropna()
    oos = pooled_oos_returns(rx, gap_days=gap)
    years = oos_year_nets(rx, gap_days=gap)
    return {"result": res, "targets": targets, "oos": oos, "years": years,
            "n_rebalances": sum(1 for d in rebal if targets.get(d))}


evaluate_cell._universe_cache = {}


def evaluate_hypothesis(hypothesis: str, lake: Path, *,
                        equity: float = 1000.0) -> dict:
    cfg, digest = load_config(hypothesis)
    costs = BT.CostModel(
        taker_bps=float(cfg["costs"]["perp_taker_bps"]),
        spot_taker_bps=float(cfg["costs"]["spot_taker_bps"]),
        spread_bps=float(cfg["costs"]["spread_bps_per_side"]),
        slip_floor_bps=float(cfg["costs"]["slip_floor_bps"]),
        slip_k=float(cfg["costs"]["slip_k"]))
    data = build_market_data(lake, need_hourly=(hypothesis == "B5"))
    evaluate_cell._universe_cache = {}
    cells = load_grid_from_toml(hypothesis)
    gap = max(35, 2 * MAX_HOLD_D[hypothesis])
    per_cell: dict[tuple, dict] = {}
    oos_matrix: dict[tuple, list[float]] = {}
    for combo in cells:
        key = cell_key(combo)
        print(f"{hypothesis} cell {key}", flush=True)
        ev = evaluate_cell(hypothesis, combo, data, cfg, costs, equity)
        oos = ev["oos"]
        dd = ST.max_drawdown(list(oos)) if len(oos) else 1.0
        to = ev["result"].turnover_oneway
        per_cell[key] = {"oos": [float(x) for x in oos],
                         "turnover": float(to), "dd": float(dd),
                         "years": ev["years"],
                         "flags": list(ev["result"].flags),
                         "n_rebalances": ev["n_rebalances"]}
        oos_matrix[key] = [float(x) for x in oos]
    # Best cell by pooled OOS Sharpe; 2x-cost rerun decides the adverse leg.
    sharpes = {k: ST.sharpe(v["oos"]) for k, v in per_cell.items()}
    best = max(sharpes, key=lambda k: sharpes[k])
    best_combo = next(c for c in cells if cell_key(c) == best)
    from dataclasses import replace as _replace
    costs2x = _replace(costs, adverse_mult=2.0)
    ev2 = evaluate_cell(hypothesis, best_combo, data, cfg, costs2x, equity)
    oos2 = pooled_oos_returns(ev2["result"].equity.pct_change().dropna(),
                              gap_days=gap)
    pbo = pbo_cscv_safe([oos_matrix[k] for k in sorted(oos_matrix, key=repr)])
    years = [per_cell[best]["years"][y] for y in TEST_YEARS]
    # Backtest flags survive into the gate document (D-042 lesson: a gate
    # must not read clean when the engine warned about the result).
    cell_flags = {str(k): sorted(set(v["flags"])) for k, v in per_cell.items()}
    all_flags = sorted({f for v in cell_flags.values() for f in v})
    gates = promotion_gates(
        hypothesis, {k: {"oos": v["oos"], "turnover": v["turnover"],
                         "dd": v["dd"]} for k, v in per_cell.items()},
        years=years, turnover_budget=float(cfg["grid"]["turnover_budget"]),
        sharpe_2x=ST.sharpe(list(oos2)), pbo=pbo,
        flags=all_flags, hold_days=MAX_HOLD_D[hypothesis])
    gates["cell_flags"] = cell_flags
    gates["best_cell_flags"] = cell_flags.get(str(best), [])
    return {"hypothesis": hypothesis, "config_sha256": digest,
            "n_trials": len(cells), "best_cell": dict(best_combo),
            "gates": gates, "flags": all_flags,
            "cell_sharpes": {str(k): v for k, v in
                             sharpes.items()},
            "cell_turnover": {str(k): v["turnover"] for k, v in
                              per_cell.items()},
            "evaluated_utc": _utc_now(), "equity": equity}


def pbo_cscv_safe(matrix: list[list[float]]) -> float:
    n = min((len(r) for r in matrix), default=0)
    if n < 64 or len(matrix) < 2:
        return 1.0  # too thin to claim anything: fail-safe
    trimmed = [r[:n] for r in matrix]
    return ST.pbo_cscv(trimmed, n_partitions=8, seed=7)


def write_dev_artifact(root: Path, result: dict) -> Path:
    hyp = result["hypothesis"]
    doc = {"hypothesis": hyp, "provenance": "OBSERVED_PUBLIC",
           "promotes": bool(result["gates"]["pass"]),
           "gates": result["gates"], "best_cell": result["best_cell"],
           "n_trials": result["n_trials"],
           "flags": result["gates"].get("flags", []),
           "cell_sharpes": result["cell_sharpes"],
           "cell_turnover": result["cell_turnover"],
           "config_sha256": result["config_sha256"],
           "evaluated_utc": result["evaluated_utc"],
           "vault_frozen": None}
    path = root / "dev" / f"{hyp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    tmp.rename(path)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="run_family_b",
                                 description="Frozen Family B DEV eval (E6.1)")
    ap.add_argument("cmd", choices=("dev", "dev-all", "record-freeze"))
    ap.add_argument("--hypothesis", default=None)
    ap.add_argument("--lake", default="data/lake/dev")
    ap.add_argument("--root", default="research/autopilot_b")
    ap.add_argument("--vault-root", default="data/vault")
    ap.add_argument("--equity", type=float, default=1000.0)
    ap.add_argument("--commit", default="unknown")
    ap.add_argument("--auto-freeze", action="store_true")
    args = ap.parse_args(argv)
    hyps = [args.hypothesis] if args.hypothesis else \
        ["B1", "B2", "B3", "B4", "B5", "B6", "B7"]
    if args.cmd == "record-freeze":
        from cryptobot.data.vault import Vault
        vault = Vault(args.vault_root)
        for hyp in hyps:
            path = Path(args.root) / "dev" / f"{hyp}.json"
            doc = json.loads(path.read_text())
            frozen = vault.registry.get("frozen", {}).get(hyp)
            if frozen is None:
                print(f"{hyp}: NOT FROZEN in vault", file=sys.stderr)
                return 2
            doc["vault_frozen"] = frozen
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
            tmp.rename(path)
            print(f"{hyp}: freeze recorded {frozen['config_sha256'][:16]}")
        return 0
    family_oos: dict[str, list[float]] = {}
    for hyp in hyps:
        result = evaluate_hypothesis(hyp, Path(args.lake), equity=args.equity)
        path = write_dev_artifact(Path(args.root), result)
        print(f"{hyp}: promotes={result['gates']['pass']} "
              f"trials={result['n_trials']} -> {path}")
        best_oos = result["gates"].get("best_oos", [])
        if best_oos:
            family_oos[hyp] = [float(x) for x in best_oos]
    if len(hyps) > 1 and family_oos:
        from cryptobot.research.slow_stats import reality_check_pvalue

        n = min(len(v) for v in family_oos.values())
        mat = [v[:n] for v in family_oos.values()]
        fam = {"report": "family-b/dev", "generated_utc": _utc_now(),
               "hypotheses": sorted(family_oos),
               "reality_check_pvalue": reality_check_pvalue(
                   mat, rounds=500, mean_block=30, seed=7),
               "note": "reported only, not a promotion gate"}
        fpath = Path(args.root) / "dev" / "_family.json"
        tmp = fpath.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(fam, indent=1, sort_keys=True) + "\n")
        tmp.rename(fpath)
        print(f"family RC p={fam['reality_check_pvalue']:.4f} -> {fpath}")
        if args.auto_freeze and result["gates"]["pass"]:
            from cryptobot.data.vault import Vault
            vault = Vault(args.vault_root)
            prereg = {"B1": "research/prereg/B1-vol-scaled-trend.md",
                      "B2": "research/prereg/B2-xsec-momentum.md",
                      "B3": "research/prereg/B3-funding-carry.md",
                      "B4": "research/prereg/B4-delta-neutral-basis.md",
                      "B5": "research/prereg/B5-extreme-move-reversion.md",
                      "B6": "research/prereg/B6-oi-divergence.md",
                      "B7": "research/prereg/B7-low-vol-tilt.md"}[hyp]
            frozen = vault.freeze_hypothesis(
                hyp, config_sha256=result["config_sha256"],
                commit=args.commit, prereg_path=prereg)
            doc = json.loads(path.read_text())
            doc["vault_frozen"] = frozen
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
            tmp.rename(path)
            print(f"{hyp}: FROZEN {args.commit[:8]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
