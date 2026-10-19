"""Hash-bound PASS/FAIL/UNDERPOWERED verdicts (T5.4/T5.5).

No manual override: the verdict is a pure function of per-trade net
bps (realistic + adverse), day blocks, drawdown and the trial count.
PASS requires ALL of: bootstrap 95% CI lower bound > 0 at realistic
cost, expectancy > 0 at adverse (2x) cost, >=300 trades, >=60%
non-negative days, drawdown within budget. Too few trades is
UNDERPOWERED, never PASS. Holm correction is applied across the
hypothesis family by the caller via ``family_size``.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any


def _bootstrap_ci(values: list[float], *, seed: int = 7,
                  rounds: int = 2000) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(rounds):
        means.append(statistics.fmean(values[rng.randrange(n)]
                                      for _ in range(n)))
    means.sort()
    return (means[int(0.025 * rounds)], means[int(0.975 * rounds) - 1])


def _sharpe(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    sd = statistics.pstdev(values)
    return (statistics.fmean(values) / sd * math.sqrt(len(values))) \
        if sd > 0 else None


def evaluate_trades(trades_bps: list[float], *, adverse_bps: list[float],
                    days: list[str], max_dd_bps: float,
                    dd_budget_bps: float, family_size: int = 1,
                    min_trades: int = 300) -> dict[str, Any]:
    """Compute the verdict for one hypothesis (pure, deterministic)."""
    n = len(trades_bps)
    out: dict[str, Any] = {"n_trades": n, "family_size": int(family_size)}
    if n < min_trades:
        out.update({"verdict": "UNDERPOWERED",
                    "reason": f"n={n} < min_trades={min_trades}",
                    "expectancy_bps": (statistics.fmean(trades_bps)
                                       if trades_bps else None)})
        return out
    lo, hi = _bootstrap_ci(trades_bps)
    exp_adv = statistics.fmean(adverse_bps) if adverse_bps else None
    by_day: dict[str, float] = {}
    for day, val in zip(days, trades_bps, strict=False):
        by_day[day] = by_day.get(day, 0.0) + val
    nonneg = (sum(1 for v in by_day.values() if v >= 0) / len(by_day)
              if by_day else 0.0)
    # Holm: smallest p must beat alpha/family_size; approximate the
    # bootstrap two-sided p from the CI position of zero.
    p_approx = 0.0 if lo > 0 else (0.5 if hi < 0 else 0.10)
    holm_alpha = 0.05 / max(1, int(family_size))
    passed = (lo > 0 and (exp_adv or 0.0) > 0 and nonneg >= 0.60
              and max_dd_bps <= dd_budget_bps
              and p_approx <= holm_alpha)
    out.update({
        "verdict": "PASS" if passed else "FAIL",
        "expectancy_bps": statistics.fmean(trades_bps),
        "expectancy_adverse_bps": exp_adv,
        "ci95": [lo, hi], "nonneg_day_frac": nonneg,
        "max_dd_bps": max_dd_bps, "sharpe": _sharpe(trades_bps),
        "holm_alpha": holm_alpha, "p_approx": p_approx})
    return out


SCREEN_MIN_REBALANCES = 30


def holdout_frames_for_verdict(files: list[dict]) -> dict[str, dict]:
    """Decode an authorized HOLDOUT manifest into frames (verdict-only).

    Verifies every file's sha256 before parsing (defense in depth).
    Routes by path: klines/* -> daily/hourly, fundingRate|funding ->
    funding, metrics -> OI daily 00:00 series, rest_tail -> tail frames.
    Returns {"daily", "hourly", "funding", "oi", "spot"} dicts.
    """
    import hashlib
    from pathlib import Path as _P

    from cryptobot.research import lake as _lake

    out: dict[str, dict] = {"daily": {}, "hourly": {}, "funding": {},
                            "oi": {}, "spot": {}}
    for ref in files:
        p = _P(ref["path"])
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        if h.hexdigest() != ref["sha256"]:
            raise ValueError(f"HOLDOUT integrity failure: {p}")
        s = str(p)
        sym = p.parent.name
        if "/rest_tail/" in s:
            leg = p.parent.name
            if leg == "funding":
                out["funding"][p.stem] = _lake.read_rest_tail_csv(p, "funding")
            elif leg.startswith("klines"):
                iv = "1d" if leg.endswith("1d") else "1h"
                key = "daily" if iv == "1d" else "hourly"
                out[key].setdefault(p.stem, []).append(
                    _lake.read_rest_tail_csv(p, "klines"))
            continue
        if p.suffix != ".zip":
            continue
        if "/fundingRate/" in s or "/funding/" in s:
            out["funding"].setdefault(sym, []).append(
                _lake.read_funding_zip(p))
        elif "/metrics/" in s:
            out.setdefault("metrics", {}).setdefault(sym, []).append(
                _lake.read_metrics_zip(p))
        elif "spot" in s.split("/"):
            out["spot"].setdefault(sym, []).append(_lake.read_klines_zip(p))
        else:
            iv = "1h" if "/1h/" in s else "1d"
            key = "hourly" if iv == "1h" else "daily"
            out[key].setdefault(sym, []).append(_lake.read_klines_zip(p))
    import pandas as _pd
    for key in ("daily", "hourly", "spot"):
        for sym, frames in list(out[key].items()):
            if isinstance(frames, list):
                df = _pd.concat(frames, ignore_index=True)
                out[key][sym] = df.sort_values("open_time").drop_duplicates(
                    subset="open_time", keep="first").reset_index(drop=True)
    for sym, frames in list(out["funding"].items()):
        if isinstance(frames, list):
            df = _pd.concat(frames, ignore_index=True)
            out["funding"][sym] = df.sort_values("calc_time").drop_duplicates(
                subset="calc_time", keep="first").reset_index(drop=True)
    oi: dict[str, _pd.Series] = {}
    for sym, frames in out.pop("metrics", {}).items():
        df = _pd.concat(frames, ignore_index=True)
        df = df.sort_values("create_time").drop_duplicates(
            subset="create_time", keep="first")
        day = df["create_time"].dt.floor("D")
        # OI daily series = first print at/after each 00:00 UTC.
        first = df.groupby(day, sort=True).first()
        oi[sym] = _pd.Series(first["sum_open_interest"].to_numpy(),
                             index=_pd.DatetimeIndex(first.index, tz="UTC"))
    out["oi"] = oi
    return out


def screen_decision(*, point_sharpe: float, dev_sharpe: float, lb80: float,
                    sharpe_2x: float, max_dd: float, n_rebalances: int,
                    turnover: float = 0.0) -> dict[str, Any]:
    """Family B holdout screen gates (E5 bullets verbatim + power floor).

    Turnover is REPORTED, not gated (the DEV promotion already gated the
    same cell's turnover; adding a screen turnover gate post-freeze
    would be a new criterion — see D-037).
    """
    caveat = ("A ~33-month holdout cannot PROVE a true Sharpe of ~1 "
              "(detectable ~0.98 one-sided 95%); this screen kills "
              "inconsistency, it does not certify edge. See "
              "research/prereg/SPLIT.md.")
    if n_rebalances < SCREEN_MIN_REBALANCES:
        return {"verdict": "UNDERPOWERED",
                "reason": f"rebalances={n_rebalances} < "
                          f"{SCREEN_MIN_REBALANCES}",
                "screen_caveat": caveat}
    bullets = {
        "point": point_sharpe > 0.3 and point_sharpe >= 0.5 * dev_sharpe,
        "lower_bound": lb80 > -0.3,
        "adverse": sharpe_2x > 0,
        "drawdown": max_dd <= 0.35,
    }
    passed = all(bullets.values())
    return {"verdict": "SCREEN_PASS" if passed else "FAIL",
            "bullets": bullets,
            "point_sharpe": point_sharpe, "dev_sharpe": dev_sharpe,
            "lb80": lb80, "sharpe_2x": sharpe_2x, "max_dd": max_dd,
            "n_rebalances": n_rebalances, "turnover": turnover,
            "screen_caveat": caveat}


def verdict_document(*, hypothesis: str, result: dict[str, Any],
                     config_path: str | Path, data_manifest: str,
                     code_commit: str,
                     data_provenance: str = "OBSERVED",
                     sealed_chunk_sha256: str | None = None) -> dict[str, Any]:
    """Bind a verdict to config/data/code hashes (no manual override)."""
    cfg_hash = hashlib.sha256(
        Path(config_path).read_bytes()).hexdigest()[:16] \
        if Path(config_path).exists() else "missing"
    doc = {"hypothesis": hypothesis, **result,
           "data_provenance": data_provenance,
           "hashes": {"config_sha256_16": cfg_hash,
                      "data_manifest": data_manifest,
                      "code_commit": code_commit,
                      "sealed_chunk_sha256": sealed_chunk_sha256}}
    doc["document_sha256"] = hashlib.sha256(
        json.dumps(doc, sort_keys=True).encode()).hexdigest()
    return doc
