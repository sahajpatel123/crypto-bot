"""S2 trend-pullback continuation baseline (Worker 1, Q-002).

Implements ``specs/strategies/S2.md`` v0.1.0 exactly: per-side causal
evaluation over 1-second replay bars, emitting manager-owned
``cryptobot.coordination.Intent`` objects paired with ``DecisionRecord``.
Reuses S1's ``Bar``/``EvalLog``/decision types and the shared gap/column
helpers; only the setup/trigger logic is S2-specific.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from cryptobot.coordination import (
    DataQuality,
    DecisionRecord,
    FeatureEvidence,
    Intent,
    Side,
)
from cryptobot.features.breakout import flow_mean, momentum_bps, volume_z
from cryptobot.features.pullback import (
    pullback_high,
    pullback_low,
    resume_max,
    resume_min,
    swing_high_before,
    swing_low_before,
)

from ._shared import columns, gap_scan
from .contract import (
    ARM_IDS_S2,
    STRATEGY_VERSION,
    S2_BASE,
    S2_FLOW,
    S2_VOLUME,
    S2_FORECAST_COST,
    build_evidence_ref,
    build_intent,
)
from .s1 import S1Decision as S2Decision
from .s1 import Bar, EvalLog

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
WARMUP_N = 120
MAX_CONSECUTIVE_MISSING_HALT = 5

__all__ = [
    "MAX_CONSECUTIVE_MISSING_HALT",
    "WARMUP_N",
    "EvalLog",
    "S2Decision",
    "S2Params",
    "evaluate_bar",
    "evaluate_side",
]


@dataclass(frozen=True)
class S2Params:
    """Frozen S2 v0.1.0 parameters (S2.md section 2)."""

    warmup_n: int = 120
    trend_n: int = 60
    trend_min_bps: float = 25.0
    pull_m: int = 10
    pull_min_bps: float = 8.0
    pull_max_bps: float = 60.0
    resume_k: int = 5
    resume_min_bps: float = 2.0
    vol_v: int = 60
    vol_z_min: float = 1.0
    flow_f: int = 10
    flow_min: float = 0.58
    spread_max_bps: float = 3.0
    entry_tol_bps: float = 2.0
    inval_buf_bps: float = 2.0
    entry_expiry_s: int = 15
    holding_limit_s: int = 120
    exit_rule: str = "S2_EXIT_V1:take_r=1.5,stop_r=1.0"


def evaluate_side(
    bars: list[Bar | None],
    t: int,
    side: Side,
    arm: str,
    instrument: str,
    params: S2Params | None = None,
) -> S2Decision:
    """Evaluate one side at bar ``t`` (both sides via :func:`evaluate_bar`)."""
    p = params or S2Params()
    if arm not in ARM_IDS_S2:
        raise ValueError(f"unknown S2 arm {arm!r}; expected one of {ARM_IDS_S2}")
    n = p.warmup_n

    def _log(
        regime: str,
        features: tuple[FeatureEvidence, ...],
        trigger: str,
        rejects: tuple[str, ...],
        dq: DataQuality,
        reason: str,
        evidence_ts: datetime,
    ) -> S2Decision:
        return S2Decision(
            EvalLog(arm, side, regime, features, trigger, rejects, dq,
                    reason, evidence_ts),
            None,
            None,
        )

    if t < n or t >= len(bars) or bars[t] is None:
        ts = bars[t].ts_utc if 0 <= t < len(bars) and bars[t] else _EPOCH
        return _log("no-setup", (), "no-fire", ("history=fail",),
                    DataQuality.CLEAN, "insufficient-history", ts)
    evidence_ts = bars[t].ts_utc  # type: ignore[union-attr]

    gap, max_consec, disorder = gap_scan(bars, t - n, t + 1)
    if gap or disorder:
        halt = disorder or max_consec > MAX_CONSECUTIVE_MISSING_HALT
        return _log(
            "no-setup", (), "no-fire",
            ("history=pass", "gap=fail"),
            DataQuality.HALT if halt else DataQuality.DEGRADED,
            "ts-disorder" if disorder else f"gap-{max_consec}",
            evidence_ts,
        )

    cols = columns(bars)
    close_t = cols["close"][t]
    assert close_t is not None
    spread_t = bars[t].spread_bps  # type: ignore[union-attr]
    is_long = side == Side.LONG

    feats: list[FeatureEvidence] = []
    checks: dict[str, str] = {"history": "pass", "gap": "pass"}

    spread_ok = spread_t <= p.spread_max_bps
    checks["spread"] = "pass" if spread_ok else "fail"
    feats.append(FeatureEvidence("spread", "1bar",
                                f"spread_bps<={p.spread_max_bps}",
                                f"{spread_t:.4f}"))

    # Swing + sequence, then swing trend from the window base close.
    base = cols["close"][t - p.trend_n - 1]
    assert base is not None and base > 0
    if is_long:
        level, ext_idx = swing_high_before(cols["high"], t, p.trend_n)
        extreme = pullback_low(cols["low"], t - 1, p.pull_m)
        depth = (level - extreme) / level * 1e4
    else:
        level, ext_idx = swing_low_before(cols["low"], t, p.trend_n)
        extreme = pullback_high(cols["high"], t - 1, p.pull_m)
        depth = (extreme - level) / level * 1e4
    seq_ok = ext_idx <= t - (p.pull_m + 1)
    checks["sequence"] = "pass" if seq_ok else "fail"
    feats.append(FeatureEvidence("sequence", f"{p.trend_n}bars",
                                f"swing_idx<=t-{p.pull_m + 1}",
                                f"{ext_idx}"))

    trend = (level / base - 1.0) * 1e4
    trend_ok = trend >= p.trend_min_bps if is_long else trend <= -p.trend_min_bps
    checks["trend"] = "pass" if trend_ok else "fail"
    tsign = ">=" if is_long else "<="
    feats.append(FeatureEvidence("trend", f"{p.trend_n}bars",
                                f"swing_ret_bps{tsign}{p.trend_min_bps:+.1f}",
                                f"{trend:.4f}"))

    pull_ok = p.pull_min_bps <= depth <= p.pull_max_bps
    checks["pullback"] = "pass" if pull_ok else "fail"
    feats.append(FeatureEvidence("pullback", f"{p.pull_m}bars",
                                f"depth in [{p.pull_min_bps},{p.pull_max_bps}]",
                                f"{depth:.4f}"))

    # Resumption trigger + momentum at t.
    if is_long:
        ref = resume_max(cols["close"], t, p.resume_k)
        resume_ok = close_t > ref
        feats.append(FeatureEvidence("resume", f"{p.resume_k}bars",
                                    "close>max(close[-k:-1])",
                                    f"close={close_t:.6f} ref={ref:.6f}"))
    else:
        ref = resume_min(cols["close"], t, p.resume_k)
        resume_ok = close_t < ref
        feats.append(FeatureEvidence("resume", f"{p.resume_k}bars",
                                    "close<min(close[-k:-1])",
                                    f"close={close_t:.6f} ref={ref:.6f}"))
    checks["resume"] = "pass" if resume_ok else "fail"

    mom = momentum_bps(cols["close"], t, p.resume_k)
    mom_ok = mom >= p.resume_min_bps if is_long else mom <= -p.resume_min_bps
    checks["momentum"] = "pass" if mom_ok else "fail"
    msign = ">=" if is_long else "<="
    feats.append(FeatureEvidence("momentum", f"{p.resume_k}bars",
                                f"ret_bps{msign}{p.resume_min_bps:+.1f}",
                                f"{mom:.4f}"))

    # Confirmation gate per arm (same features as S1).
    if arm == S2_BASE:
        confirm_ok = True
        checks["confirm"] = "na(S2)"
        feats.append(FeatureEvidence("confirm", "na", "arm=S2", "na"))
    elif arm == S2_VOLUME:
        z = volume_z(cols["volume"], t, p.vol_v)
        confirm_ok = z >= p.vol_z_min
        checks["confirm"] = "pass" if confirm_ok else "fail"
        feats.append(FeatureEvidence("volume_z", f"{p.vol_v}bars",
                                    f"z>={p.vol_z_min}", f"{z:.4f}"))
    else:  # S2_FLOW
        if is_long:
            fmean = flow_mean(cols["buy_frac"], t, p.flow_f)
            thresh = f"mean_buy>={p.flow_min}"
        else:
            sell = [None if x is None else 1.0 - x for x in cols["buy_frac"]]
            fmean = flow_mean(sell, t, p.flow_f)
            thresh = f"mean_sell>={p.flow_min}"
        confirm_ok = fmean >= p.flow_min
        checks["confirm"] = "pass" if confirm_ok else "fail"
        feats.append(FeatureEvidence("flow", f"{p.flow_f}bars", thresh,
                                    f"{fmean:.4f}"))

    order = ("history", "gap", "spread", "sequence", "trend", "pullback",
             "resume", "momentum", "confirm")
    rejects = tuple(f"{k}={checks[k]}" for k in order)
    fired = all(checks[k] == "pass" or checks[k].startswith("na(") for k in order)
    if not fired:
        failed = next(k for k in order if checks[k] == "fail")
        return _log("no-setup", tuple(feats), "no-fire", rejects,
                    DataQuality.CLEAN, f"{failed}-gate", evidence_ts)

    # Intent construction (S2.md section 5).
    buf = p.inval_buf_bps / 1e4
    tol = p.entry_tol_bps / 1e4
    if is_long:
        entry_low = close_t
        entry_high = close_t * (1.0 + tol)
        inval = extreme * (1.0 - buf)
        regime = "pullback-long"
    else:
        entry_high = close_t
        entry_low = close_t * (1.0 - tol)
        inval = extreme * (1.0 + buf)
        regime = "pullback-short"
    trigger = f"trend({p.trend_n})+pullback({p.pull_m})+resume({p.resume_k})"
    if arm == S2_VOLUME:
        trigger += f"+volz({p.vol_v})"
    elif arm == S2_FLOW:
        trigger += f"+flow({p.flow_f})"
    checks["bounds"] = "pass"
    rejects = tuple(f"{k}={checks[k]}" for k in (*order, "bounds"))

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
        data_quality_reason=f"no-gaps-N={n}",
    )
    intent = build_intent(
        strategy=arm,
        instrument=instrument,
        side=side,
        evidence_ts_utc=evidence_ts,
        entry_low=entry_low,
        entry_high=entry_high,
        entry_expiry_utc=evidence_ts + timedelta(seconds=p.entry_expiry_s),
        invalidation_price=inval,
        exit_rule=p.exit_rule,
        holding_limit_s=p.holding_limit_s,
        evidence_ref=record_id,
        data_quality=DataQuality.CLEAN,
        data_quality_reason=f"no-gaps-N={n}",
        forecast_cost=S2_FORECAST_COST,
    )
    log = EvalLog(arm, side, regime, tuple(feats), trigger, rejects,
                  DataQuality.CLEAN, "fired", evidence_ts)
    return S2Decision(log, intent, record)


def evaluate_bar(
    bars: list[Bar | None],
    t: int,
    arm: str,
    instrument: str,
    params: S2Params | None = None,
) -> tuple[S2Decision, S2Decision]:
    """Evaluate LONG then SHORT independently at bar ``t``."""
    return (
        evaluate_side(bars, t, Side.LONG, arm, instrument, params),
        evaluate_side(bars, t, Side.SHORT, arm, instrument, params),
    )
