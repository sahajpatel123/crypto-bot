"""E6.1: DEV evaluation of Family B. Never reads HOLDOUT bytes.

Promotion uses the frozen config thresholds and stats_edge gates.
SYNTHETIC provenance cannot promote. A path containing a ``holdout``
component is refused before any signal is computed.
"""
from __future__ import annotations

import itertools
from pathlib import Path

import pandas as pd

from cryptobot.research.family_b import (
    MarketData, signals_b1, signals_b2, signals_b3, signals_b4,
    signals_b5, signals_b6, signals_b7)
from cryptobot.research.slow_backtest import (
    CostModel, SimConfig, simulate_vectorized)
from cryptobot.research.stats_edge import (
    anchored_yearly_folds, bootstrap_sharpe_bounds, calendar_year_table,
    deflated_sharpe_ratio, hansen_spa, hamming_neighbors, max_drawdown,
    period_sharpe, plateau_fraction, positive_year_count,
    probability_backtest_overfitting, promotion_failures,
    regime_sharpe, sharpe_ratio, tail_metrics)
from cryptobot.research.universe import eligible_universe

EXPECTED_CELLS = {"B1": 12, "B2": 6, "B3": 8, "B4": 9, "B5": 8, "B6": 8,
                  "B7": 8}
SIGNALS = {"B1": signals_b1, "B2": signals_b2, "B3": signals_b3,
           "B4": signals_b4, "B5": signals_b5, "B6": signals_b6,
           "B7": signals_b7}


def assert_dev_paths(paths: list[str | Path]) -> None:
    for raw in paths:
        parts = {p.lower() for p in Path(raw).parts}
        if "holdout" in parts or "holdout_raw" in parts:
            raise RuntimeError(f"DEV eval refused holdout path: {raw}")


def _cells_from(name: str, grid: dict) -> list[dict]:
    if name == "B1":
        axes = ("lookbacks_d", "vol_windows_d", "target_vols")
        keys = ("lookback_d", "vol_window_d", "target_vol")
    elif name == "B2":
        axes, keys = ("formations_d", "quantiles"), ("formation_d", "quantiles")
    elif name == "B3":
        axes = ("funding_lookbacks_d", "thresholds_k", "neutral")
        keys = ("lookback_d", "k", "neutral")
    elif name == "B4":
        axes, keys = ("thresholds_k", "max_holds_d"), ("k", "max_hold_d")
    elif name == "B5":
        axes = ("windows_h", "thresholds_sigma", "oi_confirm")
        keys = ("window_h", "threshold", "oi_confirm")
    elif name == "B6":
        axes = ("windows_d", "thresholds_sigma", "modes")
        keys = ("window_d", "threshold", "mode")
    elif name == "B7":
        axes = ("vol_windows_d", "selections", "weightings")
        keys = ("vol_window_d", "selection", "weighting")
    else:
        raise ValueError(f"unknown hypothesis {name}")
    cells = []
    for values in itertools.product(*(grid[a] for a in axes)):
        params = dict(zip(keys, values, strict=True))
        if name == "B3":
            params["max_hold_d"] = grid.get("max_hold_d", 28)
        if name == "B5":
            params["hold_h"] = grid.get("hold_h", 24)
            params["stop_mult"] = grid.get("stop_mult", 2.0)
        ident = "-".join(f"{k}={v}" for k, v in params.items())
        cells.append({"id": ident, **params})
    if len(cells) != EXPECTED_CELLS[name]:
        raise RuntimeError(
            f"{name} grid produced {len(cells)} cells, "
            f"prereg expects {EXPECTED_CELLS[name]}")
    return cells


def rebalance_dates(index: pd.DatetimeIndex, schedule: str) -> list[pd.Timestamp]:
    index = pd.DatetimeIndex(index).sort_values()
    if schedule in ("daily", "daily-check"):
        return list(index)
    if schedule == "weekly":
        return [d for d in index if int(d.dayofweek) == 0]
    if schedule == "monthly":
        seen: set[tuple[int, int]] = set()
        out = []
        for d in index:
            key = (int(d.year), int(d.month))
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    raise ValueError(f"unknown rebalance schedule {schedule}")


def _cost(cfg: dict, *, adverse: bool) -> CostModel:
    c = cfg["costs"]
    return CostModel(
        taker_bps=float(c["perp_taker_bps"]),
        spot_taker_bps=float(c["spot_taker_bps"]),
        spread_bps=float(c["spread_bps_per_side"]),
        slip_floor_bps=float(c["slip_floor_bps"]),
        slip_k=float(c["slip_k"]),
        adverse_mult=float(c["adverse_mult"]) if adverse else 1.0)


def _stops_by_day(info: dict) -> dict:
    history = info.get("history") if isinstance(info, dict) else None
    if not history:
        return {}
    out = {}
    for day, names in history.items():
        rules = {}
        for sym, rec in names.items():
            if rec.get("side") and rec.get("stop") is not None:
                rules[sym] = {"stop": rec["stop"], "expiry": rec.get("expiry", day)}
        if rules:
            out[day] = rules
    return out


def _oos_returns(equity: pd.Series, folds) -> pd.Series:
    if equity.empty:
        return equity
    rets = equity.pct_change()
    parts = [rets.reindex(fold.test).dropna() for fold in folds]
    parts = [p for p in parts if len(p)]
    if not parts:
        return pd.Series(dtype=float)
    return pd.concat(parts).sort_index()


def evaluate_hypothesis(name: str, data: MarketData, cfg: dict, *,
                        provenance: str = "OBSERVED_PUBLIC",
                        paths: list[str | Path] | None = None,
                        equity: float = 10_000.0,
                        sweep: bool = False) -> dict:
    """Run every preregistered cell. Counts all trials. Does not promote
    SYNTHETIC results.
    """
    assert_dev_paths(list(paths or []))
    if name not in SIGNALS:
        raise ValueError(name)
    cells = _cells_from(name, cfg["grid"])
    index = pd.DatetimeIndex(sorted(
        {t for df in data.daily.values() for t in df["open_time"]}))
    dates = rebalance_dates(index, cfg["grid"]["rebalance"])
    univ_kw = dict(cfg["universe"])
    cache: dict = {}

    def universe_fn(d):
        key = pd.Timestamp(d)
        if key not in cache:
            cache[key] = eligible_universe(key, data.daily, **univ_kw)
        return cache[key]

    wfo = cfg["wfo"]
    folds = anchored_yearly_folds(
        index, list(wfo["test_years"]),
        purge_days=int(wfo["purge_days"]),
        embargo_days=int(wfo["embargo_days"]),
        train_start=str(wfo["train_start"]))
    signal = SIGNALS[name]
    rows = []
    oos_map: dict[str, pd.Series] = {}
    for cell in cells:
        params = {k: v for k, v in cell.items() if k != "id"}
        targets, info = signal(data, params, dates, universe_fn)
        stops = _stops_by_day(info if isinstance(info, dict) else {})
        base = simulate_vectorized(
            targets, data.daily, data.funding,
            costs=_cost(cfg, adverse=False),
            config=SimConfig(initial_equity=equity,
                             gross_cap=float(cfg["risk"]["gross_cap"])),
            spot=data.spot, hourly=data.hourly, stops_by_day=stops)
        adverse = simulate_vectorized(
            targets, data.daily, data.funding,
            costs=_cost(cfg, adverse=True),
            config=SimConfig(initial_equity=equity,
                             gross_cap=float(cfg["risk"]["gross_cap"])),
            spot=data.spot, hourly=data.hourly, stops_by_day=stops)
        oos = _oos_returns(base.equity, folds)
        oos_adv = _oos_returns(adverse.equity, folds)
        oos_map[cell["id"]] = oos
        rows.append({
            "id": cell["id"], "params": params,
            "oos_sharpe": sharpe_ratio(oos.to_numpy()) if len(oos) else 0.0,
            "adverse_sharpe": sharpe_ratio(oos_adv.to_numpy()) if len(oos_adv) else 0.0,
            "max_dd": max_drawdown(oos.to_numpy()) if len(oos) else 0.0,
            "turnover": base.turnover_oneway,
            "period_sharpe": period_sharpe(oos.to_numpy()) if len(oos) else 0.0,
            "flags": list(base.flags),
            "final_equity": base.final_equity,
        })
    if not rows:
        raise RuntimeError(f"{name} produced no cells")
    best = max(rows, key=lambda r: (r["oos_sharpe"], r["id"]))
    matrix = pd.DataFrame(oos_map).dropna(how="all").fillna(0.0)
    trial_srs = [r["period_sharpe"] for r in rows]
    dsr = deflated_sharpe_ratio(matrix[best["id"]].to_numpy(), trial_srs) \
        if best["id"] in matrix.columns and len(matrix) else 0.0
    pbo = probability_backtest_overfitting(matrix.to_numpy(), n_splits=8) \
        if matrix.shape[0] >= 16 and matrix.shape[1] >= 2 else 1.0
    neigh = hamming_neighbors(cells)
    scores = {r["id"]: r["oos_sharpe"] for r in rows}
    plateau = plateau_fraction(scores, neigh, best["id"])
    best_oos = oos_map[best["id"]]
    years = positive_year_count(best_oos, list(wfo["test_years"])) \
        if len(best_oos) else 0
    anchors = {
        "oos_sharpe": float(cfg["promotion"]["oos_sharpe"]),
        "adverse_sharpe": float(cfg["promotion"]["adverse_sharpe"]),
        "dsr": float(cfg["promotion"]["dsr"]),
        "pbo": float(cfg["promotion"]["pbo"]),
        "min_positive_years": int(cfg["promotion"]["oos_years"]),
        "plateau": float(cfg["promotion"]["plateau"]),
        "max_drawdown": float(cfg["risk"]["dd_budget"]),
    }
    fails = promotion_failures(
        oos_sharpe=best["oos_sharpe"], adverse_sharpe=best["adverse_sharpe"],
        dsr=dsr, pbo=pbo, positive_years=years, plateau=plateau,
        max_dd=best["max_dd"], turnover=best["turnover"],
        turnover_budget=float(cfg["grid"]["turnover_budget"]),
        anchors=anchors)
    if provenance.upper() == "SYNTHETIC":
        fails = ["SYNTHETIC provenance cannot promote", *fails]
    spa = hansen_spa(matrix.to_numpy(), n_boot=80, block=10, seed=1) \
        if matrix.shape[0] >= 30 and matrix.shape[1] >= 2 else \
        {"spa_pvalue": 1.0, "white_pvalue": 1.0}
    bench = None
    if "BTCUSDT" in data.daily:
        b = data.daily["BTCUSDT"].set_index("open_time")["close"].pct_change()
        bench = regime_sharpe(best_oos, b) if len(best_oos) else None
    report = {
        "hypothesis": name,
        "provenance": provenance,
        "n_trials": len(rows),
        "cells": rows,
        "best_id": best["id"],
        "oos_sharpe": best["oos_sharpe"],
        "adverse_sharpe": best["adverse_sharpe"],
        "dsr": dsr,
        "pbo": pbo,
        "plateau": plateau,
        "positive_years": years,
        "max_dd": best["max_dd"],
        "turnover": best["turnover"],
        "spa": spa,
        "years": calendar_year_table(best_oos) if len(best_oos) else {},
        "tail": tail_metrics(best_oos.to_numpy()) if len(best_oos) else {},
        "regime": bench,
        "failures": fails,
        "promoted": not fails,
        "screen_not_proof": (
            "A holdout of this length cannot prove a true Sharpe near 1. "
            "See research/prereg/SPLIT.md. Promotion here is DEV only."),
    }
    if sweep and best["id"] in oos_map:
        # Recompute targets once for the capital sweep of the best cell.
        params = next(c for c in cells if c["id"] == best["id"])
        params = {k: v for k, v in params.items() if k != "id"}
        targets, _info = signal(data, params, dates, universe_fn)
        from cryptobot.research.slow_backtest import capital_sweep
        report["capital"] = capital_sweep(
            targets, data.daily, data.funding, costs=_cost(cfg, adverse=False))
    if len(best_oos) >= 40:
        report["bootstrap"] = bootstrap_sharpe_bounds(
            best_oos.to_numpy(), n_boot=80, block=10, seed=1)
    return report


def load_config(path: str | Path) -> dict:
    import tomllib
    return tomllib.loads(Path(path).read_text(encoding="utf-8"))


__all__ = ["EXPECTED_CELLS", "assert_dev_paths", "evaluate_hypothesis",
           "load_config", "rebalance_dates"]
