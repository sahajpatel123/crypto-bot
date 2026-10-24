"""S3 range/VWAP mean-reversion baseline (Worker 1, Q-004).

Implements ``specs/strategies/S3.md`` v0.1.0 exactly: per-side causal
evaluation over 1-second replay bars, fading measured range edges toward
value when momentum stalls. Emits manager-owned
``cryptobot.coordination.Intent`` objects paired with ``DecisionRecord``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptobot.coordination import (
    DataQuality,
    DecisionRecord,
    ExitPolicy,
    FeatureEvidence,
    Side,
    encode_exit_rule,
)
from cryptobot.features.breakout import momentum_bps, ref_high, ref_low
from cryptobot.features.range import edge_touches, vwap_typical

from ._shared import columns, gap_scan
from .contract import (
    ARM_IDS_S3,
    S3_COST,
    S3_FORECAST_COST,
    S3_REGIME,
    STRATEGY_VERSION,
    build_evidence_ref,
    build_intent,
)
from .s1 import Bar, EvalLog
from .s1 import S1Decision as S3Decision

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
WARMUP_N = 120
MAX_CONSECUTIVE_MISSING_HALT = 5

__all__ = [
    "MAX_CONSECUTIVE_MISSING_HALT",
    "WARMUP_N",
    "EvalLog",
    "S3Decision",
    "S3Params",
    "evaluate_bar",
    "evaluate_side",
]


@dataclass(frozen=True)
class S3Params:
    """Frozen S3 v0.1.0 parameters (S3.md section 2)."""

    warmup_n: int = 120
    range_n: int = 120
    width_min_bps: float = 15.0
    width_max_bps: float = 120.0
    vwap_n: int = 60
    stall_m: int = 30
    stall_max_bps: float = 3.0
    edge_tol_bps: float = 4.0
    touch_m: int = 60
    touch_min: int = 2
    cost_cover_bps: float = 26.0
    spread_max_bps: float = 2.0
    entry_tol_bps: float = 2.0
    entry_expiry_s: int = 15
    holding_limit_s: int = 120


def evaluate_side(
    bars: list[Bar | None],
    t: int,
    side: Side,
    arm: str,
    instrument: str,
    params: S3Params | None = None,
) -> S3Decision:
    """Evaluate one side at bar ``t`` (both sides via :func:`evaluate_bar`)."""
    p = params or S3Params()
    if arm not in ARM_IDS_S3:
        raise ValueError(f"unknown S3 arm {arm!r}; expected one of {ARM_IDS_S3}")
    n = p.warmup_n

    def _log(
        regime: str,
        features: tuple[FeatureEvidence, ...],
        trigger: str,
        rejects: tuple[str, ...],
        dq: DataQuality,
        reason: str,
        evidence_ts: datetime,
    ) -> S3Decision:
        return S3Decision(
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

    # Range width.
    high = ref_high(cols["high"], t, p.range_n)
    low = ref_low(cols["low"], t, p.range_n)
    width = (high - low) / low * 1e4 if low > 0 else float("-inf")
    range_ok = width >= p.width_min_bps
    checks["range"] = "pass" if range_ok else "fail"
    feats.append(FeatureEvidence("range", f"{p.range_n}bars",
                                f"width_bps>={p.width_min_bps}",
                                f"{width:.4f}"))

    # Regime filter (S3-R only).
    if arm == S3_REGIME:
        if is_long:
            touches = edge_touches(cols["low"], low, t, p.touch_m,
                                   p.edge_tol_bps, edge="low")
        else:
            touches = edge_touches(cols["high"], high, t, p.touch_m,
                                   p.edge_tol_bps, edge="high")
        regime_ok = width <= p.width_max_bps and touches >= p.touch_min
        checks["regime"] = "pass" if regime_ok else "fail"
        feats.append(FeatureEvidence(
            "regime", f"{p.touch_m}bars",
            f"width<={p.width_max_bps}&touches>={p.touch_min}",
            f"width={width:.4f} touches={touches}"))
    else:
        checks["regime"] = f"na({arm})"
        feats.append(FeatureEvidence("regime", "na", f"arm={arm}", "na"))

    # Edge position (strict side + tolerance).
    if is_long:
        pos_dist = (close_t - low) / low * 1e4 if low > 0 else float("inf")
        pos_ok = close_t > low and pos_dist <= p.edge_tol_bps
        thresh = f"0<dist_bps<={p.edge_tol_bps}"
    else:
        pos_dist = (high - close_t) / high * 1e4 if high > 0 else float("inf")
        pos_ok = close_t < high and pos_dist <= p.edge_tol_bps
        thresh = f"0<dist_bps<={p.edge_tol_bps}"
    checks["position"] = "pass" if pos_ok else "fail"
    feats.append(FeatureEvidence("position", "1bar", thresh, f"{pos_dist:.4f}"))

    # Stall.
    ret = momentum_bps(cols["close"], t, p.stall_m)
    stall_ok = abs(ret) <= p.stall_max_bps
    checks["stall"] = "pass" if stall_ok else "fail"
    feats.append(FeatureEvidence("stall", f"{p.stall_m}bars",
                                f"|ret_bps|<={p.stall_max_bps}",
                                f"{ret:.4f}"))

    # VWAP side.
    vwap = vwap_typical(cols["high"], cols["low"], cols["close"],
                        cols["volume"], t, p.vwap_n)
    if vwap is None:
        vwap_ok = False
        observed = "undefined(zero-volume)"
    else:
        vwap_ok = close_t < vwap if is_long else close_t > vwap
        observed = f"close={close_t:.6f} vwap={vwap:.6f}"
    checks["vwap"] = "pass" if vwap_ok else "fail"
    feats.append(FeatureEvidence("vwap", f"{p.vwap_n}bars",
                                "close<vwap" if is_long else "close>vwap",
                                observed))

    # Cost cover (S3-C only).
    mid = (high + low) / 2
    if arm == S3_COST:
        cover = (mid - close_t) / close_t * 1e4 if is_long else \
            (close_t - mid) / close_t * 1e4
        cost_ok = cover >= p.cost_cover_bps
        checks["cost"] = "pass" if cost_ok else "fail"
        feats.append(FeatureEvidence("costcover", "range",
                                    f"mid_dist_bps>={p.cost_cover_bps}",
                                    f"{cover:.4f}"))
    else:
        checks["cost"] = f"na({arm})"
        feats.append(FeatureEvidence("costcover", "na", f"arm={arm}", "na"))

    order = ("history", "gap", "spread", "range", "regime", "position",
             "stall", "vwap", "cost")
    rejects = tuple(f"{k}={checks[k]}" for k in order)
    fired = all(v == "pass" or v.startswith("na(") for v in checks.values())
    if not fired:
        failed = next(k for k in order if checks[k] == "fail")
        return _log("no-setup", tuple(feats), "no-fire", rejects,
                    DataQuality.CLEAN, f"{failed}-gate", evidence_ts)

    # Intent construction (S3.md section 5).
    tol = p.entry_tol_bps / 1e4
    if is_long:
        entry_low = close_t * (1.0 - tol)
        entry_high = close_t
        inval = low * (1.0 - tol)
        regime = "range-long"
    else:
        entry_high = close_t
        entry_low = close_t * (1.0 - tol)
        inval = high * (1.0 + tol)
        regime = "range-short"
    trigger = f"range({p.range_n})+stall({p.stall_m})+vwap({p.vwap_n})"
    if arm == S3_REGIME:
        trigger += "+regime"
    elif arm == S3_COST:
        trigger += "+costcover"
    exit_wire = encode_exit_rule(ExitPolicy(
        stop_price=inval,
        target_price=mid,
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
        forecast_cost=S3_FORECAST_COST,
    )
    log = EvalLog(arm, side, regime, tuple(feats), trigger, rejects,
                  DataQuality.CLEAN, "fired", evidence_ts)
    return S3Decision(log, intent, record)


def evaluate_bar(
    bars: list[Bar | None],
    t: int,
    arm: str,
    instrument: str,
    params: S3Params | None = None,
) -> tuple[S3Decision, S3Decision]:
    """Evaluate LONG then SHORT independently at bar ``t``."""
    return (
        evaluate_side(bars, t, Side.LONG, arm, instrument, params),
        evaluate_side(bars, t, Side.SHORT, arm, instrument, params),
    )
