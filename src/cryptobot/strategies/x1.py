"""X1 leader-laggard baseline (Worker 4, DEEP-W4-D4).

Implements ``specs/strategies/X1.md`` v0.1.0 exactly: per-side causal
evaluation over an aligned 1-second bar PAIR (BTCUSDT leader,
ETHUSDT traded laggard), emitting manager-owned
``cryptobot.coordination.Intent`` objects paired with
``DecisionRecord``. Long and short sides are evaluated
independently with separate evidence.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptobot.coordination import (
    DataQuality,
    DecisionRecord,
    ExitPolicy,
    FeatureEvidence,
    Intent,
    Side,
    encode_exit_rule,
)
from cryptobot.features.breakout import flow_mean, momentum_bps

from ._shared import columns, gap_scan
from .contract import (
    ARM_IDS_X1,
    STRATEGY_VERSION,
    X1_FLOW,
    X1_FORECAST_COST,
    X1_STRICT,
    X1_TIMED,
    build_evidence_ref,
    build_intent,
)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Dual-symbol feed declaration (X1.md §4): Session reads these to
# attach the leader feed + frozen beta to X1 evaluations.
DUAL_REF_SYMBOL = "BTCUSDT"
DUAL_LAGGARD = "ETHUSDT"

MAX_CONSECUTIVE_MISSING_HALT = 5

__all__ = [
    "DUAL_LAGGARD",
    "DUAL_REF_SYMBOL",
    "MAX_CONSECUTIVE_MISSING_HALT",
    "EvalLog",
    "X1Decision",
    "X1Params",
    "align_leader",
    "evaluate_bar",
    "evaluate_side",
]


@dataclass(frozen=True)
class X1Params:
    """Frozen X1 v0.1.0 parameters (X1.md section 3)."""

    move_n: int = 60
    move_min_bps: float = 35.0
    gap_min_bps: float = 35.0
    strict_move_bps: float = 50.0
    flow_f: int = 10
    flow_min: float = 0.58
    spread_max_bps: float = 3.0
    entry_tol_bps: float = 2.0
    entry_expiry_s: int = 10
    holding_limit_s: int = 120
    timed_holding_s: int = 60
    retrace_frac: float = 0.50
    widen_bps: float = 10.0
    target_gap_frac: float = 0.50


@dataclass(frozen=True)
class EvalLog:
    """Full per-side evaluation record (fires and non-fires)."""

    arm: str
    side: Side
    regime: str
    features: tuple[FeatureEvidence, ...]
    trigger: str
    rejects: tuple[str, ...]
    data_quality: DataQuality
    reason: str
    evidence_ts: datetime


@dataclass(frozen=True)
class X1Decision:
    """One side's decision: always a log, plus intent+record on fire."""

    evaluation: EvalLog
    intent: Intent | None
    record: DecisionRecord | None

    def __post_init__(self) -> None:
        if (self.intent is None) != (self.record is None):
            raise ValueError("intent and record must be present together")
        if self.intent is not None and self.record is not None:
            if self.intent.evidence_ref != self.record.record_id:
                raise ValueError("intent must point at its decision record")
            if self.intent.side != self.evaluation.side:
                raise ValueError("intent side must match evaluated side")


def align_leader(ref_bars: list, evidence_ts: datetime) -> int | None:
    """Largest leader index with ts <= evidence (None if none).

    X1.md §4: the caller additionally requires exact-ts equality;
    this helper only locates the causal candidate (never looks
    ahead of the evidence instant).
    """
    best: int | None = None
    for i, bar in enumerate(ref_bars):
        if bar is None:
            continue
        if bar.ts_utc <= evidence_ts:
            best = i
    return best


def evaluate_side(
    bars: list,
    t: int,
    side: Side,
    arm: str,
    instrument: str,
    params: X1Params | None = None,
    *,
    ref_bars: list | None = None,
    beta: float | None = None,
) -> X1Decision:
    """Evaluate one side at laggard bar ``t`` (both via :func:`evaluate_bar`)."""
    p = params or X1Params()
    if arm not in ARM_IDS_X1:
        raise ValueError(f"unknown X1 arm {arm!r}; expected one of {ARM_IDS_X1}")
    n = p.move_n

    def _log(
        regime: str,
        features: tuple[FeatureEvidence, ...],
        trigger: str,
        rejects: tuple[str, ...],
        dq: DataQuality,
        reason: str,
        evidence_ts: datetime,
    ) -> X1Decision:
        return X1Decision(
            EvalLog(arm, side, regime, features, trigger, rejects, dq,
                    reason, evidence_ts),
            None,
            None,
        )

    # -- history (§5.4.1): t >= 60, leader alignable, u >= 60.
    if t < n or t >= len(bars) or bars[t] is None:
        ts = bars[t].ts_utc if 0 <= t < len(bars) and bars[t] else _EPOCH
        return _log("no-impulse", (), "no-fire", ("history=fail",),
                    DataQuality.CLEAN, "insufficient-history", ts)
    evidence_ts = bars[t].ts_utc
    u = align_leader(ref_bars or [], evidence_ts)
    if u is None or u < n:
        return _log("no-impulse", (), "no-fire",
                    ("history=fail",), DataQuality.CLEAN,
                    "insufficient-history", evidence_ts)
    assert ref_bars is not None and ref_bars[u] is not None

    # -- symbol (§5.4.2): the laggard only.
    if instrument != DUAL_LAGGARD:
        return _log("no-impulse", (), "no-fire",
                    ("history=pass", "symbol=not-laggard"),
                    DataQuality.CLEAN, "not-laggard", evidence_ts)

    # -- beta (§5.4.3): frozen beta present and finite positive.
    if beta is None or not isinstance(beta, (int, float)) \
            or not math.isfinite(beta) or beta <= 0:
        return _log("no-impulse", (), "no-fire",
                    ("history=pass", "symbol=pass", "beta=unfrozen"),
                    DataQuality.CLEAN, "beta-unfrozen", evidence_ts)

    # -- gap (§5.4.4): both sides scanned; halt takes the max run.
    gap_lag, consec_lag, dis_lag = gap_scan(bars, t - n, t + 1)
    gap_ref, consec_ref, dis_ref = gap_scan(ref_bars, u - n, u + 1)
    if gap_lag or gap_ref or dis_lag or dis_ref:
        consec = max(consec_lag, consec_ref)
        halt = dis_lag or dis_ref or consec > MAX_CONSECUTIVE_MISSING_HALT
        return _log(
            "no-impulse", (), "no-fire",
            ("history=pass", "symbol=pass", "beta=pass", "gap=fail"),
            DataQuality.HALT if halt else DataQuality.DEGRADED,
            "ts-disorder" if (dis_lag or dis_ref) else f"gap-{consec}",
            evidence_ts,
        )

    # -- leader (§5.4.5): exact-ts alignment (X1.md §4).
    if ref_bars[u].ts_utc != evidence_ts:
        return _log("no-impulse", (), "no-fire",
                    ("history=pass", "symbol=pass", "beta=pass",
                     "gap=pass", "leader=fail"),
                    DataQuality.CLEAN, "leader-missing-bar", evidence_ts)

    lag = columns(bars)
    ref = columns(ref_bars)
    eth_t = lag["close"][t]
    assert eth_t is not None
    spread_t = bars[t].spread_bps

    feats: list[FeatureEvidence] = []
    checks: dict[str, str] = {"history": "pass", "symbol": "pass",
                              "beta": "pass", "gap": "pass",
                              "leader": "pass"}

    # -- spread gate (§5.4.6).
    spread_ok = spread_t <= p.spread_max_bps
    checks["spread"] = "pass" if spread_ok else "fail"
    feats.append(FeatureEvidence("spread", "1bar",
                                f"spread_bps<={p.spread_max_bps}",
                                f"{spread_t:.4f}"))

    # -- move + gap (§5.4.7): BTC60, ETH60, raw gap G.
    is_long = side == Side.LONG
    thr = p.strict_move_bps if arm == X1_STRICT else p.move_min_bps
    btc60 = momentum_bps(ref["close"], u, n)
    eth60 = momentum_bps(lag["close"], t, n)
    gap_bps = btc60 - eth60
    feats.append(FeatureEvidence("move", f"{n}bars",
                                f"BTC60>=+{thr:.1f}" if is_long
                                else f"BTC60<=-{thr:.1f}",
                                f"{btc60:.4f}"))
    feats.append(FeatureEvidence("lagmove", f"{n}bars", "ETH60 observed",
                                f"{eth60:.4f}"))
    feats.append(FeatureEvidence("gapmove", f"{n}bars",
                                f"G>=+{thr:.1f}" if is_long
                                else f"G<=-{thr:.1f}",
                                f"{gap_bps:.4f}"))
    if is_long:
        move_ok = btc60 >= thr
        gap_ok = gap_bps >= thr
    else:
        move_ok = btc60 <= -thr
        gap_ok = gap_bps <= -thr
    checks["move"] = "pass" if move_ok else "fail"
    checks["gapmove"] = "pass" if gap_ok else "fail"

    # -- confirm (§5.4.7): flow gate on X1-F only.
    if arm == X1_FLOW:
        if is_long:
            fmean = flow_mean(lag["buy_frac"], t, p.flow_f)
            thresh = f"mean_buy>={p.flow_min}"
        else:
            sell = [None if x is None else 1.0 - x
                    for x in lag["buy_frac"]]
            fmean = flow_mean(sell, t, p.flow_f)
            thresh = f"mean_sell>={p.flow_min}"
        confirm_ok = fmean >= p.flow_min
        checks["confirm"] = "pass" if confirm_ok else "fail"
        feats.append(FeatureEvidence("flow", f"{p.flow_f}bars", thresh,
                                    f"{fmean:.4f}"))
    else:
        confirm_ok = True
        checks["confirm"] = f"na({arm})"
        feats.append(FeatureEvidence("confirm", "na", f"arm={arm}", "na"))

    order = ("history", "symbol", "beta", "gap", "leader", "spread",
             "move", "gapmove", "confirm")
    rejects = tuple(f"{k}={checks[k]}" for k in order)
    fired = spread_ok and move_ok and gap_ok and confirm_ok
    if not fired:
        failed = next(k for k in order if checks[k] == "fail")
        return _log("no-impulse", tuple(feats), "no-fire", rejects,
                    DataQuality.CLEAN, f"{failed}-gate", evidence_ts)

    # -- Intent construction (X1.md section 6).
    tol = p.entry_tol_bps / 1e4
    horizon = p.timed_holding_s if arm == X1_TIMED else p.holding_limit_s
    if is_long:
        entry_low = eth_t
        entry_high = eth_t * (1.0 + tol)
        stop_btc = eth_t * (1.0 + beta * (-p.retrace_frac * btc60) / 1e4)
        stop_gap = eth_t * (1.0 - p.widen_bps / 1e4)
        stop = max(stop_btc, stop_gap)
        target = eth_t * (1.0 + p.target_gap_frac * gap_bps / 1e4)
        regime = "leader-lag-long"
        bounds_ok = stop < entry_low and target > entry_high
    else:
        entry_high = eth_t
        entry_low = eth_t * (1.0 - tol)
        stop_btc = eth_t * (1.0 + beta * (-p.retrace_frac * btc60) / 1e4)
        stop_gap = eth_t * (1.0 + p.widen_bps / 1e4)
        stop = min(stop_btc, stop_gap)
        target = eth_t * (1.0 - p.target_gap_frac * abs(gap_bps) / 1e4)
        regime = "leader-lag-short"
        bounds_ok = stop > entry_high and target < entry_low
    checks["bounds"] = "pass" if bounds_ok else "fail"
    rejects = tuple(f"{k}={checks[k]}" for k in (*order, "bounds"))
    if not bounds_ok:
        return _log("no-impulse", tuple(feats), "no-fire", rejects,
                    DataQuality.CLEAN, "bounds-gate", evidence_ts)

    if is_long:
        trigger = f"btc60>={thr:.0f}&gap>={thr:.0f}"
    else:
        trigger = f"btc60<=-{thr:.0f}&gap<=-{thr:.0f}"
    if arm == X1_FLOW:
        trigger += f"+flow({p.flow_f})"
    exit_wire = encode_exit_rule(ExitPolicy(
        stop_price=stop,
        target_price=target,
        time_exit_utc=evidence_ts + timedelta(seconds=horizon),
        policy_id=f"{arm}:stop+target+time",
    ))
    record_id = build_evidence_ref(arm, STRATEGY_VERSION, instrument, side,
                                   evidence_ts)
    record = DecisionRecord(
        record_id=record_id,
        side=side,
        regime=regime,
        features=tuple(feats),
        trigger=trigger,
        rejects_evaluated=rejects,
        data_quality=DataQuality.CLEAN,
        data_quality_reason="no-gaps-N=60x2",
    )
    intent = build_intent(
        strategy=arm,
        instrument=instrument,
        side=side,
        evidence_ts_utc=evidence_ts,
        entry_low=entry_low,
        entry_high=entry_high,
        entry_expiry_utc=evidence_ts + timedelta(seconds=p.entry_expiry_s),
        invalidation_price=stop,
        exit_rule=exit_wire,
        holding_limit_s=horizon,
        evidence_ref=record_id,
        data_quality=DataQuality.CLEAN,
        data_quality_reason="no-gaps-N=60x2",
        forecast_cost=X1_FORECAST_COST,
    )
    log = EvalLog(arm, side, regime, tuple(feats), trigger, rejects,
                  DataQuality.CLEAN, "fired", evidence_ts)
    return X1Decision(log, intent, record)


def evaluate_bar(
    bars: list,
    t: int,
    arm: str,
    instrument: str,
    params: X1Params | None = None,
    *,
    ref_bars: list | None = None,
    beta: float | None = None,
) -> tuple[X1Decision, X1Decision]:
    """Evaluate LONG then SHORT independently at laggard bar ``t``."""
    return (
        evaluate_side(bars, t, Side.LONG, arm, instrument, params,
                      ref_bars=ref_bars, beta=beta),
        evaluate_side(bars, t, Side.SHORT, arm, instrument, params,
                      ref_bars=ref_bars, beta=beta),
    )
