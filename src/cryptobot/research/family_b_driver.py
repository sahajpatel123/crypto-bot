"""E6.1: Family B evaluation driver (grid, walk-forward, promotion gates).

Frozen BEFORE any DEV evaluation (reviewer risk 1+3 mitigation):
- Grids expand from research/configs/B*.toml (59 cells total).
- Fixed rules => walk-forward is segmented OOS attribution (no fitting):
  continuous DEV backtest, P&L attributed to post-gap test years.
- promotion_gates implements the 7 prereg bullets verbatim; nothing else
  can promote. Bootstrap blocks are uniformly 30d (pre-committed).
"""
from __future__ import annotations

import itertools
import tomllib
from pathlib import Path

import pandas as pd

from cryptobot.research.slow_stats import deflated_sharpe, plateau_fraction, sharpe

GRID_AXES = {
    "B1": [("lookback_d", [20, 60, 120]), ("vol_window_d", [20, 60]),
           ("target_vol", [0.15, 0.25])],
    "B2": [("formation_d", [5, 20, 60]),
           ("quantiles", ["tercile", "quintile"])],
    "B3": [("lookback_d", [7, 30]), ("k", [1, 2]),
           ("neutral", [True, False])],
    "B4": [("k", [1.5, 2.0, 3.0]), ("max_hold_d", [7, 14, 30])],
    "B5": [("window_h", [4, 24]), ("threshold", [2, 3]),
           ("oi_confirm", [True, False])],
    "B6": [("window_d", [7, 30]), ("threshold", [1, 2]),
           ("mode", ["plain", "trendfilter"])],
    "B7": [("vol_window_d", [60, 120]),
           ("selection", ["tercile", "quintile"]),
           ("weighting", ["equal", "invvol"])],
}
MAX_HOLD_D = {"B1": 7, "B2": 7, "B3": 28, "B4": 30, "B5": 1, "B6": 7,
              "B7": 30}
BOOTSTRAP_BLOCK_D = 30
TEST_YEARS = (2021, 2022, 2023)


def expand_grid(hypothesis: str) -> list[dict]:
    axes = GRID_AXES[hypothesis]
    names = [a[0] for a in axes]
    return [dict(zip(names, combo, strict=True)) for combo in
            itertools.product(*[a[1] for a in axes])]


def cell_key(params: dict) -> tuple:
    return tuple(sorted(params.items()))


def rebalance_dates(index: pd.DatetimeIndex, cadence: str):
    index = pd.DatetimeIndex(sorted(index))
    if cadence == "daily":
        return list(index)
    if cadence == "weekly":
        return [d for d in index if d.weekday() == 0]
    if cadence == "monthly":
        return [d for d in index if d.day == 1]
    raise ValueError(f"unknown cadence {cadence!r}")


def pooled_oos_returns(full: pd.Series, *, gap_days: int) -> pd.Series:
    """Post-gap test-year P&L concatenated (2021-2023)."""
    parts = []
    for year in TEST_YEARS:
        start = pd.Timestamp(f"{year}-01-01", tz=full.index.tz) + \
            pd.Timedelta(days=gap_days)
        stop = pd.Timestamp(f"{year + 1}-01-01", tz=full.index.tz)
        parts.append(full[(full.index >= start) & (full.index < stop)])
    return pd.concat(parts)


def oos_year_nets(full: pd.Series, *, gap_days: int) -> dict[int, float]:
    """Net simple return per OOS year (post-gap compounding)."""
    out = {}
    for year in TEST_YEARS:
        start = pd.Timestamp(f"{year}-01-01", tz=full.index.tz) + \
            pd.Timedelta(days=gap_days)
        stop = pd.Timestamp(f"{year + 1}-01-01", tz=full.index.tz)
        seg = full[(full.index >= start) & (full.index < stop)]
        out[year] = float((1.0 + seg).prod() - 1.0) if len(seg) else 0.0
    return out


def promotion_gates(hypothesis: str, cells: dict, *, years: list[float],
                    turnover_budget: float, sharpe_2x: float, pbo: float,
                    seed: int = 7) -> dict:
    """The 7 prereg dev-promotion bullets. ALL must pass (AND)."""
    sharpes = {k: sharpe(v["oos"]) for k, v in cells.items()}
    best = max(sharpes, key=lambda k: sharpes[k])
    best_oos = list(cells[best]["oos"])
    trial_sr = [sharpes[k] for k in sorted(sharpes, key=repr)]
    dsr = deflated_sharpe(best_oos, trial_sr)
    plateau = plateau_fraction(sharpes)
    bullets = {
        "oos_sharpe": sharpes[best] >= 0.7,
        "adverse_sharpe": sharpe_2x > 0.3,
        "dsr": dsr >= 0.8,
        "pbo": pbo <= 0.3,
        "years": sum(1 for y in years if y > 0) >= 2,
        "plateau": plateau >= 0.7,
        "drawdown": cells[best]["dd"] <= 0.35,
        "turnover": cells[best]["turnover"] <= turnover_budget,
    }
    detail = {"best_cell": best, "best_oos_sharpe": sharpes[best],
              "best_oos": [float(x) for x in best_oos],
              "sharpe_2x": sharpe_2x, "dsr": dsr, "pbo": pbo,
              "years": years, "plateau": plateau,
              "drawdown": cells[best]["dd"],
              "turnover": cells[best]["turnover"], "bullets": bullets,
              "n_trials": len(cells)}
    return {"pass": bool(all(bullets.values())), **detail}


def load_grid_from_toml(hypothesis: str,
                        path: str | Path | None = None) -> list[dict]:
    """Cross-check: TOML grid matches the frozen GRID_AXES."""
    path = Path(path or f"research/configs/{hypothesis}.toml")
    doc = tomllib.loads(path.read_text())
    grid = doc.get("grid", {})
    axes = GRID_AXES[hypothesis]
    names = [a[0] for a in axes]
    toml_axes = []
    key_map = {"lookbacks_d": "lookback_d", "vol_windows_d": "vol_window_d",
               "target_vols": "target_vol", "formations_d": "formation_d",
               "funding_lookbacks_d": "lookback_d", "thresholds_k": "k",
               "thresholds_sigma": "threshold", "windows_h": "window_h",
               "windows_d": "window_d", "max_holds_d": "max_hold_d",
               "modes": "mode",
               "selections": "selection", "weightings": "weighting"}
    for name in names:
        vals = None
        for tk, tv in grid.items():
            if key_map.get(tk, tk) == name:
                vals = list(tv)
        if vals is None:
            raise ValueError(f"{hypothesis}: TOML missing axis {name}")
        toml_axes.append(vals)
    combos = [dict(zip(names, c, strict=True))
              for c in itertools.product(*toml_axes)]
    mine = expand_grid(hypothesis)
    if {cell_key(c) for c in combos} != {cell_key(c) for c in mine}:
        raise ValueError(f"{hypothesis}: TOML grid != GRID_AXES")
    return mine


def run_holdout_screen(hypothesis: str, cell: dict, *,
                       dev_frames: dict, sealed_frames: dict,
                       dev_sharpe: float, costs, equity: float = 1000.0,
                       holdout_start: str = "2024-01-01") -> dict:
    """Screen ONE frozen cell on sealed holdout (E6.2 orchestration).

    DEV frames supply indicator/universe history only; positions start
    FLAT at holdout_start (a real deployment starts flat — inherited
    DEV winners must not flatter the screen). Returns screen metrics;
    the PASS/FAIL decision itself lives in verdict.screen_decision.
    """
    from cryptobot.research import family_b as _fb
    from cryptobot.research import slow_backtest as _bt
    from cryptobot.research import slow_stats as _st
    from cryptobot.research.universe import eligible_universe

    start = pd.Timestamp(holdout_start, tz="UTC")
    merged: dict[str, dict] = {}
    for key in ("daily", "hourly", "funding", "spot"):
        merged[key] = {}
        syms = set(dev_frames.get(key, {})) | set(sealed_frames.get(key, {}))
        for sym in syms:
            parts = [f for f in (dev_frames.get(key, {}).get(sym),
                                 sealed_frames.get(key, {}).get(sym))
                     if f is not None]
            df = pd.concat(parts, ignore_index=True)
            tcol = "calc_time" if key == "funding" else "open_time"
            merged[key][sym] = df.sort_values(tcol).drop_duplicates(
                tcol, keep="first").reset_index(drop=True)
    merged_oi = dict(dev_frames.get("oi", {}))
    for sym, ser in sealed_frames.get("oi", {}).items():
        base = merged_oi.get(sym)
        merged_oi[sym] = ser if base is None else pd.concat(
            [base, ser]).sort_index().loc[~pd.concat(
                [base, ser]).sort_index().index.duplicated(keep="first")]
    data = _fb.MarketData(daily=merged["daily"], funding=merged["funding"],
                          oi=merged_oi, hourly=merged["hourly"],
                          spot=merged["spot"])
    all_dates = sorted({t for df in merged["daily"].values()
                        for t in df["open_time"] if t >= start})
    cadence = {"B1": "weekly", "B2": "weekly", "B3": "weekly",
               "B4": "daily", "B5": "daily", "B6": "weekly",
               "B7": "monthly"}[hypothesis]
    rebal = rebalance_dates(pd.DatetimeIndex(all_dates), cadence)
    def univ(d):
        return eligible_universe(d, merged["daily"], top_n=30,
                                 min_listing_age_days=90,
                                 min_quote_volume_30d=1e7)
    sig = getattr(_fb, f"signals_{hypothesis.lower()}")
    targets, info = sig(data, cell, rebal, univ)
    res = _bt.simulate_vectorized(targets, merged["daily"], merged["funding"],
                                  costs=costs,
                                  config=_bt.SimConfig(
                                      initial_equity=float(equity)),
                                  spot=merged["spot"])
    rx = res.equity.pct_change().dropna()
    rx = rx[rx.index >= start]
    lo, _ = _st.stationary_bootstrap_ci(
        list(rx), lambda v: _st.sharpe(v), mean_block=BOOTSTRAP_BLOCK_D,
        rounds=1000, alpha=0.20, lower_q=0.20, seed=7)
    from dataclasses import replace as _replace
    costs2x = _replace(costs, adverse_mult=2.0)
    res2 = _bt.simulate_vectorized(
        targets, merged["daily"], merged["funding"], costs=costs2x,
        config=_bt.SimConfig(initial_equity=float(equity)),
        spot=merged["spot"])
    rx2 = res2.equity.pct_change().dropna()
    rx2 = rx2[rx2.index >= start]
    held = sum(1 for d in rebal if d >= start and targets.get(d))
    return {"point_sharpe": _st.sharpe(list(rx)), "dev_sharpe": dev_sharpe,
            "lb80": lo, "sharpe_2x": _st.sharpe(list(rx2)),
            "max_dd": _st.max_drawdown(list(rx)),
            "n_rebalances": held,
            "turnover": res.turnover_oneway,
            "final_equity": float(res.equity.iloc[-1])}


__all__ = ["GRID_AXES", "MAX_HOLD_D", "BOOTSTRAP_BLOCK_D", "TEST_YEARS",
           "expand_grid", "cell_key", "rebalance_dates", "pooled_oos_returns",
           "oos_year_nets", "promotion_gates", "load_grid_from_toml",
           "run_holdout_screen"]
