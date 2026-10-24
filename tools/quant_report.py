"""Apply research.quant to the C2 evidence (descriptive; issues no verdict).

  .venv/bin/python tools/quant_report.py      # writes reports/quant/C2-quant.json

Reads only data already scored (DEV, holdout, 2020-21 replication); it
re-derives the daily series to measure what the verdicts did not:
deflated Sharpe, track-record needs, sizing, drawdown odds, break-even
cost, and how long a forward test needs (fixed-sample and anytime-valid).
"""
from __future__ import annotations

import json
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import eval_c_family as ecf  # noqa: E402
import forward_c2  # noqa: E402

from cryptobot.research import c_family, quant  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/quant/C2-quant.json"
# Every strategy cell scored in this project (RESEARCH_VERDICTS.md):
# S 14 + X1 24 + H-R2 1 + H1..H5 5 + B1..B7 7 + Family C 4 + H2-HIST 1.
N_TRIALS = 56
E_BOUND_BPS = 2000.0  # above the worst historical C2 day (-1,619 bps)
E_LAM_CAP = 0.5
HORIZON = 3 * 365
SIMS = 400
PERIODS = {"DEV": ecf.DEV, "HOLDOUT": ecf.HOLDOUT, "REPLICATION": ecf.REPLICATION}
PUBLISHED_P = {"DEV": 0.0195, "HOLDOUT": 0.154, "REPLICATION": 0.080}


def _series() -> dict[str, list[c_family.DayResult]]:
    closes, funding = ecf.load(replication=True)
    return {k: c_family.run(c_family.SPECS["C2"], closes, funding, start=a, end=b)
            for k, (a, b) in PERIODS.items()}


def _describe(rows: list[c_family.DayResult]) -> dict:
    net = [r.net_bps for r in rows]
    m = quant.moments(net)
    gross = statistics.fmean(r.gross_bps for r in rows)
    turn = statistics.fmean(r.turnover for r in rows)
    frac_mu, frac_sd = m.mean / 1e4, m.sd / 1e4
    return {
        "n_days": m.n, "mean_bps": m.mean, "sd_bps": m.sd, "skew": m.skew,
        "kurtosis": m.kurt, "worst_day_bps": min(net), "best_day_bps": max(net),
        "sharpe_annual": quant.annualize_sharpe(m.sharpe),
        "psr_vs_0": quant.probabilistic_sharpe(m),
        "deflated_sharpe": quant.deflated_sharpe(m, N_TRIALS),
        "min_track_record_days": quant.min_track_record(m),
        "breakeven_cost_bps_per_side": quant.breakeven_cost(
            gross + turn * c_family.COST_BPS_PER_SIDE, turn),
        "kelly_leverage_raw": quant.kelly_leverage(frac_mu, frac_sd),
        "kelly_leverage_lcb_1sd": quant.kelly_leverage(frac_mu, frac_sd, m.n, 1.0),
        "p_dd_25pct_at_1x": quant.prob_drawdown(frac_mu, frac_sd, 0.25),
        "p_dd_50pct_at_1x": quant.prob_drawdown(frac_mu, frac_sd, 0.50),
        # sizing: P(ever losing 20% from a peak) <= 5%, on the 1-sd lower-bound mean
        "leverage_for_p_dd20_le_5pct_lcb": quant.drawdown_capped_leverage(
            frac_mu - frac_sd / m.n ** 0.5, frac_sd, 0.20, 0.05),
    }


def _time_to_reject(pool: list[float], shift: float, seed: int) -> list[int | None]:
    """Week-block bootstrap paths of `pool` with mean moved by `shift`."""
    rng = random.Random(seed)
    blocks = [pool[i:i + 7] for i in range(0, len(pool) - 6, 7)]
    out: list[int | None] = []
    for _ in range(SIMS):
        ep, hit = quant.EProcess(bound=E_BOUND_BPS, lam_cap=E_LAM_CAP), None
        while ep.n < HORIZON and hit is None:
            for x in rng.choice(blocks):
                ep.update(x + shift)
                if ep.rejected():
                    hit = ep.n
                    break
        out.append(hit)
    return out


def _summ(times: list[int | None]) -> dict:
    hits = sorted(t for t in times if t is not None)
    return {"p_reject_within_3y": len(hits) / len(times),
            "median_days_if_rejected": hits[len(hits) // 2] if hits else None}


def main() -> int:
    series = _series()
    doc: dict = {"strategy": "C2-XSMOM", "n_trials_in_project": N_TRIALS,
                 "note": "descriptive only; no verdict changes", "periods": {}}
    for k, rows in series.items():
        doc["periods"][k] = _describe(rows)
    pooled = [r.net_bps for rows in series.values() for r in rows]
    doc["pooled"] = _describe([r for rows in series.values() for r in rows])
    doc["stouffer_p_three_periods_EXPLORATORY"] = quant.stouffer(PUBLISHED_P.values())
    sr = doc["pooled"]["sharpe_annual"]
    doc["fixed_sample"] = {
        "power_180d_at_pooled_sharpe": quant.power_at(sr, 180),
        "power_365d": quant.power_at(sr, 365),
        "power_1095d": quant.power_at(sr, 1095),
        "days_for_80pct_power": quant.required_periods(sr),
        "days_for_80pct_power_half_edge": quant.required_periods(sr / 2),
    }
    looks = list(forward_c2.LOOKS)
    doc["group_sequential"] = {
        "looks_days": looks, "obf_bounds": list(forward_c2.OBF_BOUNDS),
        "power_at_pooled_sharpe": quant.sequential_power(sr, looks, forward_c2.OBF_BOUNDS),
        "power_at_half_sharpe": quant.sequential_power(sr / 2, looks, forward_c2.OBF_BOUNDS),
        "power_if_vol_managed_sharpe_1_25": quant.sequential_power(
            1.25, looks, forward_c2.OBF_BOUNDS),
    }
    doc["vol_managed_EXPLORATORY"] = {}
    for k, rows in series.items():
        vm = quant.moments(forward_c2.vol_managed([r.net_bps for r in rows]))
        doc["vol_managed_EXPLORATORY"][k] = {
            "mean_bps": vm.mean, "sharpe_annual": quant.annualize_sharpe(vm.sharpe),
            "base_sharpe_annual": doc["periods"][k]["sharpe_annual"]}
    mu = statistics.fmean(pooled)
    doc["e_process"] = {
        "bound_bps": E_BOUND_BPS, "lam_cap": E_LAM_CAP, "horizon_days": HORIZON,
        "sims": SIMS, "pooled_mean_bps": mu,
        "edge_as_measured": _summ(_time_to_reject(pooled, 0.0, 1)),
        "half_edge": _summ(_time_to_reject(pooled, -mu / 2, 2)),
        "no_edge_false_positive": _summ(_time_to_reject(pooled, -mu, 3)),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1, default=str) + "\n")
    print(json.dumps(doc, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
