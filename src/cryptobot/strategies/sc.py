"""SC micro-breakout scalp (specs/strategies/SC.md v0.1.1).

Pure causal evaluation. The constants below are the spec's freeze.
Nothing here reads a tape or a measurement report.
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

from ._shared import columns, gap_scan
from .contract import (
    SC_BASE,
    SC_FORECAST_COST,
    STRATEGY_VERSION,
    build_evidence_ref,
    build_intent,
)
from .s1 import Bar, EvalLog

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# Frozen SC v0.1.0. Round trip is NET_S1_V1 on the shared cost preset.
WARMUP_N = 60
RANGE_N = 20
MOM_M = 20
EXTENSION_MIN_BPS = 8.0
MOM_MIN_BPS = 8.0
SPREAD_MAX_BPS = 4.0
STOP_MIN_BPS = 8.0
STOP_MAX_BPS = 20.0
TARGET_BPS = 40.0
ENTRY_TOL_BPS = 2.0
ENTRY_EXPIRY_S = 5
HOLDING_LIMIT_S = 90
MAX_CONSECUTIVE_MISSING_HALT = 5
MIN_RANGE_PRINTS = 10
ROUND_TRIP_BPS = 2.0 * (5.0 + 5.0 / 2.0 + 5.0) + 1.0  # 26.0


@dataclass(frozen=True)
class SCParams:
    """Frozen SC v0.1.0 parameters (SC.md section 3)."""

    warmup_n: int = WARMUP_N
    range_n: int = RANGE_N
    mom_m: int = MOM_M
    extension_min_bps: float = EXTENSION_MIN_BPS
    mom_min_bps: float = MOM_MIN_BPS
    spread_max_bps: float = SPREAD_MAX_BPS
    stop_min_bps: float = STOP_MIN_BPS
    stop_max_bps: float = STOP_MAX_BPS
    target_bps: float = TARGET_BPS
    entry_tol_bps: float = ENTRY_TOL_BPS
    entry_expiry_s: int = ENTRY_EXPIRY_S
    holding_limit_s: int = HOLDING_LIMIT_S
    min_range_prints: int = MIN_RANGE_PRINTS


@dataclass(frozen=True)
class SCDecision:
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


def _distance_bps(price: float, other: float) -> float:
    return abs(price - other) / price * 1e4


def _present(values: list[float | None], lo: int, hi: int) -> list[float]:
    """Present finite prints in ``[lo, hi)``. Quiet ``None`` slots are skipped."""
    out: list[float] = []
    for i in range(max(0, lo), min(len(values), hi)):
        value = values[i]
        if value is not None:
            out.append(value)
    return out


def _momentum_base(closes: list[float | None], t: int, mom_m: int,
                   warmup_n: int) -> float | None:
    """Latest present close at index ``<= t-mom_m`` inside the warmup."""
    floor = t - warmup_n
    for i in range(t - mom_m, floor - 1, -1):
        if i < 0:
            break
        value = closes[i]
        if value is not None and value > 0:
            return value
    return None


def evaluate_side(
    bars: list[Bar | None],
    t: int,
    side: Side,
    arm: str,
    instrument: str,
    params: SCParams | None = None,
) -> SCDecision:
    """Evaluate one side at bar ``t``."""
    p = params or SCParams()
    if arm != SC_BASE:
        raise ValueError(f"unknown SC arm {arm!r}; expected {SC_BASE!r}")

    def _log(
        reason: str,
        evidence_ts: datetime,
        features: tuple[FeatureEvidence, ...] = (),
        rejects: tuple[str, ...] = (),
        dq: DataQuality = DataQuality.CLEAN,
        regime: str = "no-scalp",
    ) -> SCDecision:
        return SCDecision(
            EvalLog(arm, side, regime, features, "no-fire", rejects, dq,
                    reason, evidence_ts),
            None,
            None,
        )

    if t < p.warmup_n or t >= len(bars) or bars[t] is None:
        ts = bars[t].ts_utc if 0 <= t < len(bars) and bars[t] else _EPOCH
        return _log("insufficient-history", ts, rejects=("history=fail",))
    evidence_ts = bars[t].ts_utc  # type: ignore[union-attr]
    # Quiet seconds are None. They are not a veto. Disorder, and a run
    # of missing seconds longer than the halt, still stop the side.
    _quiet, max_consec, disorder = gap_scan(bars, t - p.warmup_n, t + 1)
    if disorder or max_consec > MAX_CONSECUTIVE_MISSING_HALT:
        return _log(
            "ts-disorder" if disorder else f"outage-{max_consec}",
            evidence_ts,
            rejects=("history=pass", "gap=fail"),
            dq=DataQuality.HALT,
        )

    cols = columns(bars)
    close_t = cols["close"][t]
    assert close_t is not None and close_t > 0
    spread_t = bars[t].spread_bps  # type: ignore[union-attr]
    is_long = side == Side.LONG
    highs = _present(cols["high"], t - p.range_n, t)
    lows = _present(cols["low"], t - p.range_n, t)
    prints = min(len(highs), len(lows))
    if prints < p.min_range_prints:
        return _log("insufficient-prints", evidence_ts,
                    rejects=("history=pass", "gap=pass", "prints=fail"))
    ref = max(highs) if is_long else min(lows)
    extension = ((close_t - ref) if is_long else (ref - close_t)) / close_t * 1e4
    base = _momentum_base(cols["close"], t, p.mom_m, p.warmup_n)
    if base is None:
        return _log("insufficient-prints", evidence_ts,
                    rejects=("history=pass", "gap=pass", "momentum=fail"))
    mom = (close_t / base - 1.0) * 1e4
    stop_level = min(lows) if is_long else max(highs)
    stop_bps = _distance_bps(close_t, stop_level)
    feats = (
        FeatureEvidence("spread", "1bar", f"spread_bps<={p.spread_max_bps}",
                        f"{spread_t:.4f}"),
        FeatureEvidence("extension", f"{p.range_n}bars",
                        f"extension_bps>={p.extension_min_bps}",
                        f"{extension:.4f}"),
        FeatureEvidence("momentum", f"{p.mom_m}bars",
                        f"ret_bps>={p.mom_min_bps}", f"{mom:.4f}"),
        FeatureEvidence("stop", f"{p.range_n}bars",
                        f"stop_bps in [{p.stop_min_bps},{p.stop_max_bps}]",
                        f"{stop_bps:.4f}"),
    )
    checks = {
        "history": "pass",
        "gap": "pass",
        "spread": "pass" if spread_t <= p.spread_max_bps else "fail",
        "breakout": "pass" if extension >= p.extension_min_bps else "fail",
        "momentum": "pass" if (
            mom >= p.mom_min_bps if is_long else mom <= -p.mom_min_bps
        ) else "fail",
        "stop": "pass" if p.stop_min_bps <= stop_bps <= p.stop_max_bps else "fail",
    }
    order = ("history", "gap", "spread", "breakout", "momentum", "stop")
    if any(checks[k] == "fail" for k in order):
        failed = next(k for k in order if checks[k] == "fail")
        rejects = tuple(f"{k}={checks[k]}" for k in order)
        return _log(f"{failed}-gate", evidence_ts, feats, rejects)

    tol = p.entry_tol_bps / 1e4
    target_frac = p.target_bps / 1e4
    if is_long:
        entry_low = close_t
        entry_high = close_t * (1.0 + tol)
        target = close_t * (1.0 + target_frac)
        reward = (target - entry_high) / entry_high * 1e4
        regime = "scalp-long"
    else:
        entry_high = close_t
        entry_low = close_t * (1.0 - tol)
        target = close_t * (1.0 - target_frac)
        reward = (entry_low - target) / entry_low * 1e4
        regime = "scalp-short"
    if reward < ROUND_TRIP_BPS:
        rejects = tuple(f"{k}=pass" for k in order) + (
            f"reward={reward:.4f}",)
        return _log("reward-below-cost", evidence_ts, feats, rejects)
    exit_wire = encode_exit_rule(ExitPolicy(
        stop_price=stop_level,
        target_price=target,
        time_exit_utc=evidence_ts + timedelta(seconds=p.holding_limit_s),
        policy_id=f"{arm}:stop+target+time",
    ))
    record_id = build_evidence_ref(
        arm, STRATEGY_VERSION, instrument, side, evidence_ts)
    record = DecisionRecord(
        record_id=record_id,
        side=side,
        regime=regime,
        features=feats,
        trigger=f"micro-breakout {side.value} +{p.target_bps:.0f}bps",
        rejects_evaluated=tuple(f"{k}=pass" for k in order) + (
            f"reward={reward:.4f}",),
        data_quality=DataQuality.CLEAN,
        data_quality_reason=f"no-gaps-N={p.warmup_n}",
    )
    intent = build_intent(
        strategy=arm,
        instrument=instrument,
        side=side,
        evidence_ts_utc=evidence_ts,
        entry_low=entry_low,
        entry_high=entry_high,
        entry_expiry_utc=evidence_ts + timedelta(seconds=p.entry_expiry_s),
        invalidation_price=stop_level,
        exit_rule=exit_wire,
        holding_limit_s=p.holding_limit_s,
        evidence_ref=record_id,
        data_quality=DataQuality.CLEAN,
        data_quality_reason=f"no-gaps-N={p.warmup_n}",
        forecast_cost=SC_FORECAST_COST,
    )
    log = EvalLog(arm, side, regime, feats, record.trigger,
                  record.rejects_evaluated, DataQuality.CLEAN, "fired",
                  evidence_ts)
    return SCDecision(log, intent, record)


def evaluate_bar(
    bars: list[Bar | None],
    t: int,
    arm: str,
    instrument: str,
    params: SCParams | None = None,
) -> tuple[SCDecision, SCDecision]:
    """Evaluate LONG then SHORT independently at bar ``t``."""
    return (
        evaluate_side(bars, t, Side.LONG, arm, instrument, params),
        evaluate_side(bars, t, Side.SHORT, arm, instrument, params),
    )
