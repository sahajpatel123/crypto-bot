"""S4 failed-breakout reclaim reversal baseline (Worker 1, Q-004).

Implements ``specs/strategies/S4.md`` v0.1.0 exactly: per-side causal
evaluation over 1-second replay bars, fading shallow breakout pierces that
are reclaimed within a few bars. No hidden-liquidity claims. Emits
manager-owned ``cryptobot.coordination.Intent`` objects paired with
``DecisionRecord``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from cryptobot.coordination import (
    DataQuality,
    DecisionRecord,
    ExitPolicy,
    FeatureEvidence,
    Intent,
    Side,
    encode_exit_rule,
)
from cryptobot.features.breakout import momentum_bps
from cryptobot.features.pullback import (
    resume_max,
    resume_min,
    swing_high_before,
    swing_low_before,
)

from ._shared import columns, gap_scan
from .contract import (
    ARM_IDS_S4,
    STRATEGY_VERSION,
    S4_BASE,
    S4_SIMPLE,
    S4_FORECAST_COST,
    build_evidence_ref,
    build_intent,
)
from .s1 import S1Decision as S4Decision
from .s1 import Bar, EvalLog

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
WARMUP_N = 120
MAX_CONSECUTIVE_MISSING_HALT = 5

__all__ = [
    "MAX_CONSECUTIVE_MISSING_HALT",
    "WARMUP_N",
    "EvalLog",
    "S4Decision",
    "S4Params",
    "evaluate_bar",
    "evaluate_side",
]


@dataclass(frozen=True)
class S4Params:
    """Frozen S4 v0.1.0 parameters (S4.md section 2)."""

    warmup_n: int = 120
    ref_n: int = 114
    pierce_lb: int = 6
    pierce_max_bps: float = 6.0
    reclaim_k: int = 5
    mom_m: int = 10
    mom_min_bps: float = 4.0
    spread_max_bps: float = 3.0
    entry_tol_bps: float = 2.0
    entry_expiry_s: int = 15
    holding_limit_s: int = 120
    take_r: float = 1.5


def evaluate_side(
    bars: list[Bar | None],
    t: int,
    side: Side,
    arm: str,
    instrument: str,
    params: S4Params | None = None,
) -> S4Decision:
    """Evaluate one side at bar ``t`` (both sides via :func:`evaluate_bar`)."""
    p = params or S4Params()
    if arm not in ARM_IDS_S4:
        raise ValueError(f"unknown S4 arm {arm!r}; expected one of {ARM_IDS_S4}")
    n = p.warmup_n

    def _log(
        regime: str,
        features: tuple[FeatureEvidence, ...],
        trigger: str,
        rejects: tuple[str, ...],
        dq: DataQuality,
        reason: str,
        evidence_ts: datetime,
    ) -> S4Decision:
        return S4Decision(
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

    # Reference level over [t-120..t-7] (excludes the pierce lookback).
    if is_long:
        level, _ = swing_low_before(cols["low"], t - p.pierce_lb, p.ref_n)
    else:
        level, _ = swing_high_before(cols["high"], t - p.pierce_lb, p.ref_n)
    feats.append(FeatureEvidence("level", f"{p.ref_n}bars", "reference",
                                f"{level:.6f}"))

    # Pierce (S4 only; na on the simple arm).
    if arm == S4_BASE:
        if is_long:
            extreme = resume_min(cols["low"], t, p.pierce_lb)
            pierced = extreme < level
            depth = (level - extreme) / level * 1e4 if level > 0 else float("inf")
        else:
            extreme = resume_max(cols["high"], t, p.pierce_lb)
            pierced = extreme > level
            depth = (extreme - level) / level * 1e4 if level > 0 else float("inf")
        pierce_ok = pierced and depth <= p.pierce_max_bps
        checks["pierce"] = "pass" if pierce_ok else "fail"
        feats.append(FeatureEvidence("pierce", f"{p.pierce_lb}bars",
                                    f"pierced&depth_bps<={p.pierce_max_bps}",
                                    f"{depth:.4f}"))
    else:
        checks["pierce"] = f"na({arm})"
        feats.append(FeatureEvidence("pierce", "na", f"arm={arm}", "na"))

    # Reclaim at t.
    if is_long:
        ref = resume_max(cols["close"], t, p.reclaim_k)
        reclaim_ok = close_t > level and close_t > ref
        feats.append(FeatureEvidence("reclaim", f"{p.reclaim_k}bars",
                                    "close>level&close>max(close[-k:-1])",
                                    f"close={close_t:.6f} ref={ref:.6f}"))
    else:
        ref = resume_min(cols["close"], t, p.reclaim_k)
        reclaim_ok = close_t < level and close_t < ref
        feats.append(FeatureEvidence("reclaim", f"{p.reclaim_k}bars",
                                    "close<level&close<min(close[-k:-1])",
                                    f"close={close_t:.6f} ref={ref:.6f}"))
    checks["reclaim"] = "pass" if reclaim_ok else "fail"

    # Reversal momentum.
    mom = momentum_bps(cols["close"], t, p.mom_m)
    mom_ok = mom >= p.mom_min_bps if is_long else mom <= -p.mom_min_bps
    checks["momentum"] = "pass" if mom_ok else "fail"
    msign = ">=" if is_long else "<="
    feats.append(FeatureEvidence("momentum", f"{p.mom_m}bars",
                                f"ret_bps{msign}{p.mom_min_bps:+.1f}",
                                f"{mom:.4f}"))

    order = ("history", "gap", "spread", "pierce", "reclaim", "momentum")
    rejects = tuple(f"{k}={checks[k]}" for k in order)
    fired = all(v == "pass" or v.startswith("na(") for v in checks.values())
    if not fired:
        failed = next(k for k in order if checks[k] == "fail")
        return _log("no-setup", tuple(feats), "no-fire", rejects,
                    DataQuality.CLEAN, f"{failed}-gate", evidence_ts)

    # Intent construction (S4.md section 5).
    tol = p.entry_tol_bps / 1e4
    if is_long:
        entry_low = close_t
        entry_high = close_t * (1.0 + tol)
        inval = resume_min(cols["low"], t + 1, p.pierce_lb + 1) * (1.0 - tol)
        regime = "failed-breakout-long"
        trigger = f"pierce({p.pierce_lb})+reclaim({p.reclaim_k})+momentum({p.mom_m})"
    else:
        entry_high = close_t
        entry_low = close_t * (1.0 - tol)
        inval = resume_max(cols["high"], t + 1, p.pierce_lb + 1) * (1.0 + tol)
        regime = "failed-breakout-short"
        trigger = f"pierce({p.pierce_lb})+reclaim({p.reclaim_k})+momentum({p.mom_m})"
    if arm == S4_SIMPLE:
        trigger = f"reclaim({p.reclaim_k})+momentum({p.mom_m})"
    risk = abs(close_t - inval)
    target = close_t + p.take_r * risk if is_long else close_t - p.take_r * risk
    exit_wire = encode_exit_rule(ExitPolicy(
        stop_price=inval,
        target_price=target,
        time_exit_utc=evidence_ts + timedelta(seconds=p.holding_limit_s),
        policy_id=f"{arm}:stop+target+time",
    ))
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
        exit_rule=exit_wire,
        holding_limit_s=p.holding_limit_s,
        evidence_ref=record_id,
        data_quality=DataQuality.CLEAN,
        data_quality_reason=f"no-gaps-N={n}",
        forecast_cost=S4_FORECAST_COST,
    )
    log = EvalLog(arm, side, regime, tuple(feats), trigger, rejects,
                  DataQuality.CLEAN, "fired", evidence_ts)
    return S4Decision(log, intent, record)


def evaluate_bar(
    bars: list[Bar | None],
    t: int,
    arm: str,
    instrument: str,
    params: S4Params | None = None,
) -> tuple[S4Decision, S4Decision]:
    """Evaluate LONG then SHORT independently at bar ``t``."""
    return (
        evaluate_side(bars, t, Side.LONG, arm, instrument, params),
        evaluate_side(bars, t, Side.SHORT, arm, instrument, params),
    )
