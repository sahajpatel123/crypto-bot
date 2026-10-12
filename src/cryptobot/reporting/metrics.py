"""Metric calculations + independent reconciliation (V-007, metric table).

Every number rebuilds from episodes/fills/funding/cash. Cross-checks compare
independently rebuilt totals against the persisted ledger; ANY mismatch
raises :class:`ReconciliationError` listing all diffs — never silently
adjusted. Undefined quantities (zero-loss profit factor, tiny samples) are
labeled, never faked.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
REL_TOL = 1e-9
ABS_TOL = 1e-6


class ReconciliationError(ValueError):
    """Rebuilt metrics disagree with persisted books. Lists every diff."""


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL)


@dataclass
class Metrics:
    dataset: str
    window_start_utc: str
    window_end_utc: str
    mode: str
    starting_equity: float
    n_fills: int
    n_episodes: int
    labels: list = field(default_factory=list)
    net_return: dict = field(default_factory=dict)
    expectancy: dict = field(default_factory=dict)
    drawdown: dict = field(default_factory=dict)
    win_loss: dict = field(default_factory=dict)
    behavior: dict = field(default_factory=dict)
    costs: dict = field(default_factory=dict)
    daily: dict = field(default_factory=dict)
    splits: dict = field(default_factory=dict)
    reliability: dict = field(default_factory=dict)
    speed_resources: dict = field(default_factory=dict)
    reconciliation: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in (
            "dataset", "window_start_utc", "window_end_utc", "mode",
            "starting_equity", "n_fills", "n_episodes", "labels", "net_return",
            "expectancy", "drawdown", "win_loss", "behavior", "costs", "daily",
            "reliability", "speed_resources", "splits", "reconciliation")}


def compute_metrics(run, episodes: list) -> Metrics:
    """Rebuild every metric from run files + episodes (pure function)."""
    from cryptobot.reporting.episodes import Episode
    cfg = run.config.get("run", {})
    starting = float(cfg["starting_equity"])
    ledger = run.ledger
    journal = ledger.to_dict()["journal"]
    fills = run.fills
    equity = run.equity
    funding_total = sum(e["amount"] for e in journal if e["kind"] == "funding")
    flows_total = sum(e["amount"] for e in journal if e["kind"] == "flow")
    fee_total = sum(f.fee for f in fills)

    m = Metrics(
        dataset=str(cfg.get("dataset", "unknown")),
        window_start_utc=str(cfg["window_start_utc"]),
        window_end_utc=str(cfg["window_end_utc"]),
        mode=str(cfg.get("mode", "unknown")),
        starting_equity=starting,
        n_fills=len(fills),
        n_episodes=len(episodes),
    )
    if not episodes:
        m.labels.append("no-trades: zero completed episodes in window")

    # Net account return (flow-adjusted; open exposure shown, not liquidated).
    end_marked = equity[-1].marked_equity if equity else starting
    end_exposure = equity[-1].marked_equity - equity[-1].cash if equity else 0.0
    net_ret = (end_marked - flows_total - starting) / starting if starting else 0.0
    m.net_return = {
        "net_return": net_ret,
        "end_marked_equity": end_marked,
        "flows_total": flows_total,
        "open_exposure_end_usdt": end_exposure,
        "close_cost_assumption": "open exposure marked, not liquidated; "
                                 "close costs excluded from return",
    }

    # Expectancy with uncertainty; tiny samples labeled insufficient.
    nets = [e.net for e in episodes]
    n = len(nets)
    if n == 0:
        m.expectancy = {"mean_net": None, "n": 0, "label": "insufficient: no episodes"}
    else:
        mean = sum(nets) / n
        std = (sum((x - mean) ** 2 for x in nets) / (n - 1)) ** 0.5 if n > 1 else 0.0
        m.expectancy = {
            "mean_net": mean, "n": n, "std": std,
            "ci95_half_width": 1.96 * std / math.sqrt(n) if n > 1 else None,
            "label": "insufficient: n<30" if n < 30 else "ok",
        }

    # Drawdown from the marked curve (open losses included).
    peak, max_dd, trough_ts, peak_ts = -math.inf, 0.0, None, None
    dd_pct, dd_peak_ts = 0.0, None
    cur_peak_ts = None
    for row in equity:
        if row.marked_equity > peak:
            peak, cur_peak_ts = row.marked_equity, row.ts_utc
        dd = peak - row.marked_equity
        if dd > max_dd:
            max_dd, trough_ts, peak_ts = dd, row.ts_utc, cur_peak_ts
        pct = dd / peak if peak else 0.0
        if pct > dd_pct:
            dd_pct, dd_peak_ts = pct, cur_peak_ts
    m.drawdown = {
        "max_drawdown_usdt": max_dd,
        "max_drawdown_pct": dd_pct,
        "trough_ts_utc": trough_ts.isoformat() if trough_ts else None,
        "peak_ts_utc": peak_ts.isoformat() if peak_ts else None,
    }

    # Win rate / profit factor (undefined denominators labeled).
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x < 0]
    gross_win, gross_loss = sum(wins), sum(losses)
    m.win_loss = {
        "wins": len(wins), "losses": len(losses), "flats": n - len(wins) - len(losses),
        "win_rate": len(wins) / n if n else None,
        "profit_factor": (gross_win / abs(gross_loss)) if gross_loss else None,
        "profit_factor_label": None if gross_loss else "undefined: no losing episodes",
    }

    # Behavior.
    holdings = sorted(e.holding_s for e in episodes)
    exits = Counter(e.exit_reason for e in episodes)
    by_strategy: dict[str, dict] = {}
    for e in episodes:
        s = by_strategy.setdefault(e.strategy, {"n": 0, "net": 0.0, "wins": 0})
        s["n"] += 1
        s["net"] += e.net
        s["wins"] += 1 if e.net > 0 else 0
    n_legs = sum(len(e.legs) for e in episodes)
    m.behavior = {
        "completed_episodes": n,
        "fills": len(fills),
        "episode_legs": n_legs,
        "episodes_with_partials": sum(1 for e in episodes if len(e.legs) > 2),
        "exposure_time_s": sum(holdings),
        "holding_p50_s": _pct(holdings, 50),
        "holding_p95_s": _pct(holdings, 95),
        "exit_reasons": dict(exits),
        "long_episodes": sum(1 for e in episodes if e.side == "LONG"),
        "short_episodes": sum(1 for e in episodes if e.side == "SHORT"),
        "end_of_data_episodes": sum(1 for e in episodes if e.end_of_data),
        "per_strategy": by_strategy,
    }

    # Cost burden (entry/exit split replayed from episode direction).
    entry_fees = exit_fees = 0.0
    for e in episodes:
        is_long = e.side == "LONG"
        for leg in e.legs:
            if (leg.side == "BUY") == is_long:
                entry_fees += leg.fee
            else:
                exit_fees += leg.fee
    m.costs = {
        "entry_fees": entry_fees,
        "exit_fees": exit_fees,
        "total_fees": fee_total,
        "funding_total": funding_total,
        "execution_effects": "unmodeled: run files carry no quote reference; "
                             "slippage vs arrival is not observable here",
    }

    m.daily = _daily_metrics(equity, journal, episodes, cfg)
    m.reliability = _reliability(run)
    m.speed_resources = {
        "status": "not recorded: run files carry no timing/counters payload",
        "events": {"fills": len(fills), "equity_rows": len(equity),
                   "rejections": len(run.rejections), "risk_events": len(run.risk_events)},
    }
    m.splits = _split_metrics(episodes, run.splits)
    m.reconciliation = reconcile(run, episodes)
    return m


def _pct(xs: list[float], pct: float):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * pct / 100
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _daily_metrics(equity, journal, episodes, cfg: dict) -> dict:
    """Per-day returns over ALL full accounting days (IST), no-trade incl."""
    start = datetime.fromisoformat(str(cfg["window_start_utc"]))
    end = datetime.fromisoformat(str(cfg["window_end_utc"]))
    starting = float(cfg["starting_equity"])
    flows = [(datetime.fromisoformat(e["ts_utc"]), e["amount"])
             for e in journal if e["kind"] == "flow"]
    closes_by_day: dict[str, int] = {}
    for e in episodes:
        closes_by_day[e.close_ts_utc.astimezone(IST).date().isoformat()] = \
            closes_by_day.get(e.close_ts_utc.astimezone(IST).date().isoformat(), 0) + 1
    days = []
    day = start.astimezone(IST).date()
    last = end.astimezone(IST).date()
    rows = sorted(equity, key=lambda r: r.ts_utc)
    while day <= last:
        day_start = datetime(day.year, day.month, day.day, tzinfo=IST)
        day_end = day_start + timedelta(days=1)
        full = day_start >= start and day_end <= end
        opens = [r for r in rows if r.ts_utc < day_start]
        closes = [r for r in rows if r.ts_utc < day_end]
        if not closes:
            label = "no-coverage"
            days.append({"date": day.isoformat(), "ret": None, "label": label,
                         "full_day": full, "n_episodes": 0})
        else:
            start_eq = opens[-1].marked_equity if opens else starting
            end_eq = closes[-1].marked_equity
            day_flows = sum(a for ts, a in flows if day_start <= ts < day_end)
            ret = (end_eq - start_eq - day_flows) / start_eq if start_eq else 0.0
            n_ep = closes_by_day.get(day.isoformat(), 0)
            days.append({"date": day.isoformat(), "ret": ret,
                         "label": "trade" if n_ep else "no-trade",
                         "full_day": full, "n_episodes": n_ep})
        day += timedelta(days=1)
    covered_full = [d for d in days if d["full_day"] and d["ret"] is not None]
    rets = [d["ret"] for d in covered_full]
    return {
        "days": days,
        "full_covered_days": len(covered_full),
        "mean": sum(rets) / len(rets) if rets else None,
        "median": _pct(rets, 50),
        "best": max(rets) if rets else None,
        "worst": min(rets) if rets else None,
        "fraction_ge_2pct": sum(1 for r in rets if r >= 0.02) / len(rets) if rets else None,
        "fraction_ge_3pct": sum(1 for r in rets if r >= 0.03) / len(rets) if rets else None,
    }


def _reliability(run) -> dict:
    gaps: list[float] = []
    eq = run.equity
    if len(eq) >= 3:
        gaps_sorted = sorted((b.ts_utc - a.ts_utc).total_seconds()
                             for a, b in zip(eq, eq[1:]))
        median = _pct(gaps_sorted, 50) or 1.0
        gaps = [g for g in gaps_sorted if g > 2 * median]
    stages: dict[str, dict[str, int]] = {}
    for r in run.rejections:
        stages.setdefault(r.stage, {}).setdefault(r.reason, 0)
        stages[r.stage][r.reason] += 1
    kinds = Counter(e.kind for e in run.risk_events)
    transitions = Counter((e.kind, e.from_state, e.to_state) for e in run.risk_events)
    restarts = sum(c for e, c in kinds.items()
                   if e in ("resume", "live-resume", "restart", "recovering")
                   or e.startswith("resume"))
    # V-008 §7: mark provenance shared by risk and reports. Open rows
    # valued without any mark are counted loudly, never papered over.
    by_source: dict[str, int] = {}
    ages = [r.mark_age_ms for r in eq if r.mark_age_ms is not None]
    open_unmarked = 0
    for r in eq:
        by_source[r.mark_source] = by_source.get(r.mark_source, 0) + 1
        if r.position_qty != 0 and r.mark_source in ("none", "unrecorded"):
            open_unmarked += 1
    return {
        "equity_gaps": {"count": len(gaps), "total_s": sum(gaps),
                        "max_s": max(gaps) if gaps else 0.0},
        "mark_provenance": {
            "by_source": by_source,
            "max_age_ms": max(ages) if ages else None,
            "open_rows_without_mark": open_unmarked,
        },
        "rejections_by_stage_reason": stages,
        "risk_kinds": dict(kinds),
        "risk_transitions": {f"{k}|{a}|{b}": c for (k, a, b), c in transitions.items()},
        "restarts": restarts,
        "lost_events": "not recorded: run files carry no loss counter",
    }


def _split_metrics(episodes, splits: dict) -> dict:
    """Per-bucket aggregates for declared splits; never blended.

    A split value is either a list of IST day strings or a
    {"start": ts, "end": ts} window; episodes bucket by close time.
    """
    if not splits:
        return {"status": "unassigned: no splits declared; results are one window",
                "buckets": {}}
    buckets: dict[str, dict] = {}
    for name, spec in splits.items():
        if isinstance(spec, dict):
            start = datetime.fromisoformat(spec["start"])
            end = datetime.fromisoformat(spec["end"])
            subset = [e for e in episodes if start <= e.close_ts_utc < end]
        else:
            dayset = set(spec)
            subset = [e for e in episodes
                      if e.close_ts_utc.astimezone(IST).date().isoformat() in dayset]
        buckets[name] = {"n": len(subset),
                         "net": sum(e.net for e in subset),
                         "wins": sum(1 for e in subset if e.net > 0)}
    return {"status": "ok", "buckets": buckets,
            "note": "buckets are reported separately; no blended splits"}


def reconcile(run, episodes: list) -> dict:
    """Cross-check rebuilt totals vs the persisted ledger (fail loudly)."""
    ledger = run.ledger
    diffs = []
    fee_sum = sum(f.fee for f in run.fills)
    if not _close(fee_sum, ledger.paid_costs()):
        diffs.append(f"fees: fills sum {fee_sum} != ledger paid {ledger.paid_costs()}")
    journal = ledger.to_dict()["journal"]
    funding_sum = sum(e["amount"] for e in journal if e["kind"] == "funding")
    if not _close(funding_sum, ledger.funding_net()):
        diffs.append(f"funding: journal {funding_sum} != ledger {ledger.funding_net()}")
    attributed = sum(e.funding for e in episodes)
    orphan = funding_sum - attributed
    synthetic = sum(e.gross for e in episodes if e.end_of_data)
    nets = sum(e.net for e in episodes)
    if not _close(nets - synthetic + orphan, ledger.net_realised()):
        diffs.append(f"realised: episodes {nets} - synthetic {synthetic} + orphan "
                     f"{orphan} != ledger {ledger.net_realised()}")
    ep_fees = sum(e.fees for e in episodes)
    if not _close(ep_fees, fee_sum):
        diffs.append(f"episode fees {ep_fees} != fills fees {fee_sum}")
    cash = ledger.to_dict()["snapshot"]
    pilot = ledger.to_dict()["pilot_equity"]
    implied = pilot + funding_sum + sum(e["amount"] for e in journal if e["kind"] == "flow")
    for f in run.fills:
        signed = f.qty if f.side == "BUY" else -f.qty
        implied += -signed * f.price - f.fee
    if not _close(implied, cash["cash"]):
        diffs.append(f"cash: rebuilt {implied} != ledger {cash['cash']}")
    if run.equity:
        if not _close(run.equity[-1].cash, cash["cash"]):
            diffs.append(f"equity cash {run.equity[-1].cash} != ledger {cash['cash']}")
        if not _close(run.equity[-1].position_qty, ledger.position_qty()):
            diffs.append(f"equity position {run.equity[-1].position_qty} != "
                         f"ledger {ledger.position_qty()}")
    if diffs:
        raise ReconciliationError("; ".join(diffs))
    return {"status": "agree",
            "checks": ["fees", "funding", "realised", "episode-fees", "cash"]
                      + (["equity-cash", "equity-position"] if run.equity else [])}
