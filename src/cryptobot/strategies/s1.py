"""S1 breakout-momentum baseline (Worker 1, Q-001).

Implements ``specs/strategies/S1.md`` v0.1.0 exactly: per-side causal
evaluation over 1-second replay bars, emitting manager-owned
``cryptobot.coordination.Intent`` objects paired with ``DecisionRecord``.
Long and short sides are evaluated independently with separate evidence.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

from cryptobot.coordination import (
    DataQuality,
    DecisionRecord,
    FeatureEvidence,
    Intent,
    Side,
)
from cryptobot.features.breakout import (
    flow_mean,
    momentum_bps,
    ref_high,
    ref_low,
    swing_high,
    swing_low,
    volume_z,
)

from .contract import (
    ARM_BASE,
    ARM_FLOW,
    ARM_IDS_S1,
    ARM_VOLUME,
    STRATEGY_VERSION,
    S1_FORECAST_COST,
    build_evidence_ref,
    build_intent,
)
from ._shared import columns, gap_scan

MAX_CONSECUTIVE_MISSING_HALT = 5

__all__ = [
    "MAX_CONSECUTIVE_MISSING_HALT",
    "Bar",
    "EvalLog",
    "S1Decision",
    "S1Params",
    "evaluate_bar",
    "evaluate_side",
]


@dataclass(frozen=True)
class Bar:
    """One 1-second replay bar (synthetic, labelled)."""

    ts_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    trades: int
    buy_frac: float
    spread_bps: float
    source: str = "synthetic"

    def __post_init__(self) -> None:
        if not isinstance(self.ts_utc, datetime) or self.ts_utc.tzinfo is None:
            raise ValueError("ts_utc must be a tz-aware datetime")
        for name in ("open", "high", "low", "close", "volume", "spread_bps"):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"{name} must be finite")
        if self.high < self.low:
            raise ValueError("high must be >= low")
        if not self.low <= self.open <= self.high:
            raise ValueError("open must lie within [low, high]")
        if not self.low <= self.close <= self.high:
            raise ValueError("close must lie within [low, high]")
        if self.close <= 0:
            raise ValueError("close must be > 0")
        if self.volume < 0:
            raise ValueError("volume must be >= 0")
        if self.trades < 0:
            raise ValueError("trades must be >= 0")
        if not 0.0 <= self.buy_frac <= 1.0:
            raise ValueError("buy_frac must lie within [0, 1]")
        if self.spread_bps < 0:
            raise ValueError("spread_bps must be >= 0")

    def to_dict(self) -> dict:
        return {
            "ts_utc": self.ts_utc.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "trades": self.trades,
            "buy_frac": self.buy_frac,
            "spread_bps": self.spread_bps,
            "source": self.source,
        }

    @staticmethod
    def from_dict(d: dict) -> "Bar":
        return Bar(
            ts_utc=datetime.fromisoformat(d["ts_utc"]),
            open=d["open"],
            high=d["high"],
            low=d["low"],
            close=d["close"],
            volume=d["volume"],
            trades=d["trades"],
            buy_frac=d["buy_frac"],
            spread_bps=d["spread_bps"],
            source=d.get("source", "synthetic"),
        )


@dataclass(frozen=True)
class S1Params:
    """Frozen S1 v0.1.0 parameters (S1.md section 3)."""

    breakout_n: int = 120
    mom_m: int = 30
    mom_min_bps: float = 5.0
    vol_v: int = 60
    vol_z_min: float = 1.0
    flow_f: int = 10
    flow_min: float = 0.58
    spread_max_bps: float = 3.0
    entry_tol_bps: float = 2.0
    entry_expiry_s: int = 15
    holding_limit_s: int = 120
    inval_m: int = 30
    exit_rule: str = "S1_EXIT_V1:take_r=1.5,stop_r=1.0"


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
class S1Decision:
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


def evaluate_side(
    bars: list[Bar | None],
    t: int,
    side: Side,
    arm: str,
    instrument: str,
    params: S1Params | None = None,
) -> S1Decision:
    """Evaluate one side at bar ``t`` (both sides via :func:`evaluate_bar`)."""
    p = params or S1Params()
    if arm not in ARM_IDS_S1:
        raise ValueError(f"unknown S1 arm {arm!r}; expected one of {ARM_IDS_S1}")
    n = p.breakout_n

    def _log(
        regime: str,
        features: tuple[FeatureEvidence, ...],
        trigger: str,
        rejects: tuple[str, ...],
        dq: DataQuality,
        reason: str,
        evidence_ts: datetime,
    ) -> S1Decision:
        return S1Decision(
            EvalLog(arm, side, regime, features, trigger, rejects, dq,
                    reason, evidence_ts),
            None,
            None,
        )

    if t < n or t >= len(bars) or bars[t] is None:
        ts = bars[t].ts_utc if 0 <= t < len(bars) and bars[t] else _EPOCH
        return _log("no-breakout", (), "no-fire", ("history=fail",),
                    DataQuality.CLEAN, "insufficient-history", ts)
    evidence_ts = bars[t].ts_utc  # type: ignore[union-attr]

    gap, max_consec, disorder = gap_scan(bars, t - n, t + 1)
    if gap or disorder:
        halt = disorder or max_consec > MAX_CONSECUTIVE_MISSING_HALT
        return _log(
            "no-breakout", (), "no-fire",
            ("history=pass", "gap=fail"),
            DataQuality.HALT if halt else DataQuality.DEGRADED,
            "ts-disorder" if disorder else f"gap-{max_consec}",
            evidence_ts,
        )

    cols = columns(bars)
    close_t = cols["close"][t]
    assert close_t is not None
    spread_t = bars[t].spread_bps  # type: ignore[union-attr]

    feats: list[FeatureEvidence] = []
    checks: dict[str, str] = {"history": "pass", "gap": "pass"}

    # Spread gate.
    spread_ok = spread_t <= p.spread_max_bps
    checks["spread"] = "pass" if spread_ok else "fail"
    feats.append(FeatureEvidence("spread", "1bar",
                                f"spread_bps<={p.spread_max_bps}",
                                f"{spread_t:.4f}"))

    # Breakout + momentum + confirmation per side.
    is_long = side == Side.LONG
    if is_long:
        level = ref_high(cols["high"], t, n)
        breakout_ok = close_t > level
        feats.append(FeatureEvidence("breakout", f"{n}bars",
                                    "close>donchian_high",
                                    f"close={close_t:.6f} ref={level:.6f}"))
    else:
        level = ref_low(cols["low"], t, n)
        breakout_ok = close_t < level
        feats.append(FeatureEvidence("breakout", f"{n}bars",
                                    "close<donchian_low",
                                    f"close={close_t:.6f} ref={level:.6f}"))
    checks["breakout"] = "pass" if breakout_ok else "fail"

    ret_bps = momentum_bps(cols["close"], t, p.mom_m)
    mom_ok = ret_bps >= p.mom_min_bps if is_long else ret_bps <= -p.mom_min_bps
    checks["momentum"] = "pass" if mom_ok else "fail"
    mom_sign = ">=" if is_long else "<="
    feats.append(FeatureEvidence("momentum", f"{p.mom_m}bars",
                                f"ret_bps{mom_sign}{p.mom_min_bps:+.1f}",
                                f"{ret_bps:.4f}"))

    if arm == ARM_BASE:
        confirm_ok = True
        checks["confirm"] = "na(S1)"
        feats.append(FeatureEvidence("confirm", "na", "arm=S1", "na"))
    elif arm == ARM_VOLUME:
        z = volume_z(cols["volume"], t, p.vol_v)
        confirm_ok = z >= p.vol_z_min
        checks["confirm"] = "pass" if confirm_ok else "fail"
        feats.append(FeatureEvidence("volume_z", f"{p.vol_v}bars",
                                    f"z>={p.vol_z_min}", f"{z:.4f}"))
    else:  # ARM_FLOW
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

    order = ("history", "gap", "spread", "breakout", "momentum", "confirm")
    rejects = tuple(f"{k}={checks[k]}" for k in order)
    fired = spread_ok and breakout_ok and mom_ok and confirm_ok
    if not fired:
        failed = next(k for k in order if checks[k] == "fail")
        return _log("no-breakout", tuple(feats), "no-fire", rejects,
                    DataQuality.CLEAN, f"{failed}-gate", evidence_ts)

    # Intent construction (S1.md section 6).
    tol = p.entry_tol_bps / 1e4
    if is_long:
        entry_low = close_t
        entry_high = close_t * (1.0 + tol)
        inval = swing_low(cols["low"], t, p.inval_m)
        regime = "breakout-long"
        trigger = f"close>donchian_high({n})+momentum({p.mom_m})"
    else:
        entry_high = close_t
        entry_low = close_t * (1.0 - tol)
        inval = swing_high(cols["high"], t, p.inval_m)
        regime = "breakout-short"
        trigger = f"close<donchian_low({n})+momentum({p.mom_m})"
    if arm == ARM_VOLUME:
        trigger += f"+volz({p.vol_v})"
    elif arm == ARM_FLOW:
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
        forecast_cost=S1_FORECAST_COST,
    )
    log = EvalLog(arm, side, regime, tuple(feats), trigger, rejects,
                  DataQuality.CLEAN, "fired", evidence_ts)
    return S1Decision(log, intent, record)


def evaluate_bar(
    bars: list[Bar | None],
    t: int,
    arm: str,
    instrument: str,
    params: S1Params | None = None,
) -> tuple[S1Decision, S1Decision]:
    """Evaluate LONG then SHORT independently at bar ``t``."""
    return (
        evaluate_side(bars, t, Side.LONG, arm, instrument, params),
        evaluate_side(bars, t, Side.SHORT, arm, instrument, params),
    )
