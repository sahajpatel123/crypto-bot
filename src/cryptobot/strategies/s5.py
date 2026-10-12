"""S5 microstructure baseline: signed flow + synced book (Worker 1, Q-005).

Exact rules: ``specs/strategies/S5.md`` v0.1.0. S5 consumes a runtime
:class:`MarketView` (bounded causal bars plus E-007 depth/flow features);
LONG and SHORT are evaluated separately with an agreement gate between
book imbalance and signed trade flow. Missing microstructure stays
missing: ``depth``/``flow`` ``None`` rejects carry the relayed E-007
``depth:``/``flow:`` reason verbatim.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from cryptobot.coordination import (
    DataQuality,
    DecisionRecord,
    ExitPolicy,
    FeatureEvidence,
    Intent,
    Side,
    encode_exit_rule,
)

from .contract import (
    ARM_IDS_S5,
    STRATEGY_VERSION,
    S5_FORECAST_COST,
    build_evidence_ref,
    build_intent,
)
from ._shared import gap_scan
from .s1 import MAX_CONSECUTIVE_MISSING_HALT, EvalLog
from .s1 import S1Decision as S5Decision

if TYPE_CHECKING:  # runtime-only import: s5 never touches runtime at runtime
    from .runtime import MarketView

__all__ = [
    "S5Decision",
    "S5Params",
    "evaluate_side",
    "evaluate_view",
]

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class S5Params:
    """Frozen S5 v0.1.0 parameters (S5.md section 3)."""

    imb_min: float = 0.20
    flow_min: float = 0.58
    flow_min_trades: int = 10
    sync_max_age_s: int = 2
    spread_max_bps: float = 3.0
    depth_spread_max_bps: float = 5.0
    inval_m: int = 30
    inval_buf_bps: float = 1.0
    entry_tol_bps: float = 2.0
    entry_expiry_s: int = 15
    holding_limit_s: int = 120
    take_r: float = 1.5


def _relay_reason(quality_reason: str, prefix: str, fallback: str) -> str:
    """First ``;``-separated token starting with ``prefix`` (E-007 relay)."""
    for token in quality_reason.split(";"):
        if token.startswith(prefix):
            return token
    return fallback


def evaluate_side(
    view: MarketView,
    side: Side,
    arm: str,
    instrument: str,
    params: S5Params | None = None,
) -> S5Decision:
    """Evaluate one side at the newest bar of ``view`` (both via :func:`evaluate_view`)."""
    p = params or S5Params()
    if arm not in ARM_IDS_S5:
        raise ValueError(f"unknown S5 arm {arm!r}; expected one of {ARM_IDS_S5}")
    bars = list(view.bars)

    def _log(
        regime: str,
        features: tuple[FeatureEvidence, ...],
        trigger: str,
        rejects: tuple[str, ...],
        dq: DataQuality,
        reason: str,
        evidence_ts: datetime,
    ) -> S5Decision:
        return S5Decision(
            EvalLog(arm, side, regime, features, trigger, rejects, dq,
                    reason, evidence_ts),
            None,
            None,
        )

    # F1: aligned slots; anchor at the last present bar, never strip.
    t = next((i for i in range(len(bars) - 1, -1, -1)
              if bars[i] is not None), None)
    if t is None:
        return _log("no-microstructure", (), "no-fire", ("history=fail",),
                    DataQuality.CLEAN, "insufficient-history", _EPOCH)
    newest_ts = bars[t].ts_utc  # type: ignore[union-attr]

    if view.quality is DataQuality.HALT:
        reason = view.quality_reason or "halt"
        if ":" not in reason:
            reason = f"quality:{reason}"
        return _log("no-microstructure", (), "no-fire", (f"quality={reason}",),
                    DataQuality.HALT, reason, newest_ts)

    if view.depth is None:
        reason = _relay_reason(view.quality_reason, "depth:", "depth:unavailable")
        return _log("no-microstructure", (), "no-fire",
                    ("quality=pass", f"depth={reason}"),
                    DataQuality.DEGRADED, reason, newest_ts)
    if view.flow is None:
        reason = _relay_reason(view.quality_reason, "flow:", "flow:unavailable")
        return _log("no-microstructure", (), "no-fire",
                    ("quality=pass", "depth=pass", f"flow={reason}"),
                    DataQuality.DEGRADED, reason, newest_ts)

    depth, flow = view.depth, view.flow
    evidence_ts = newest_ts
    base = ("quality=pass", "depth=pass", "flow=pass")
    max_age = timedelta(seconds=p.sync_max_age_s)
    if depth.ts_utc > evidence_ts:
        reason = "sync:depth-from-future"
        return _log("no-microstructure", (), "no-fire", (*base, f"sync={reason}"),
                    DataQuality.DEGRADED, reason, evidence_ts)
    if evidence_ts - depth.ts_utc > max_age:
        reason = "sync:depth-stale"
        return _log("no-microstructure", (), "no-fire", (*base, f"sync={reason}"),
                    DataQuality.DEGRADED, reason, evidence_ts)
    if flow.window_end_utc > evidence_ts:
        reason = "sync:flow-from-future"
        return _log("no-microstructure", (), "no-fire", (*base, f"sync={reason}"),
                    DataQuality.DEGRADED, reason, evidence_ts)
    if evidence_ts - flow.window_end_utc > max_age:
        reason = "sync:flow-stale"
        return _log("no-microstructure", (), "no-fire", (*base, f"sync={reason}"),
                    DataQuality.DEGRADED, reason, evidence_ts)

    n = p.inval_m
    if t < n:
        return _log("no-microstructure", (), "no-fire",
                    (*base, "sync=pass", "history=fail"),
                    DataQuality.CLEAN, "insufficient-history", evidence_ts)
    gap, max_consec, disorder = gap_scan(bars, t - n, t + 1)
    if gap or disorder:
        halt = disorder or max_consec > MAX_CONSECUTIVE_MISSING_HALT
        return _log(
            "no-microstructure", (), "no-fire",
            (*base, "sync=pass", "history=pass", "gap=fail"),
            DataQuality.HALT if halt else DataQuality.DEGRADED,
            "ts-disorder" if disorder else f"gap-{max_consec}",
            evidence_ts,
        )
    window = bars[t - n:t + 1]
    assert all(b is not None for b in window)  # gap gate above

    total = flow.buy_notional + flow.sell_notional
    buy_frac = flow.buy_notional / total if total > 0 else 0.5
    checks: dict[str, str] = {
        "quality": "pass", "depth": "pass", "flow": "pass", "sync": "pass",
        "history": "pass", "gap": "pass",
    }
    checks["flowcount"] = "pass" if flow.trade_count >= p.flow_min_trades else "fail"
    bar = bars[t]
    assert bar is not None  # t anchors at a present bar
    spread_ok = (
        bar.spread_bps <= p.spread_max_bps
        and depth.spread_bps <= p.depth_spread_max_bps
    )
    checks["spread"] = "pass" if spread_ok else "fail"
    is_long = side is Side.LONG
    imb = depth.imbalance
    if is_long:
        signal_ok = imb >= p.imb_min and buy_frac >= p.flow_min
        thresh = f"imb>=+{p.imb_min:.2f} & buyfrac>={p.flow_min:.2f}"
    else:
        signal_ok = imb <= -p.imb_min and buy_frac <= 1.0 - p.flow_min
        thresh = f"imb<=-{p.imb_min:.2f} & buyfrac<={1.0 - p.flow_min:.2f}"
    checks["signal"] = "pass" if signal_ok else "fail"

    feats = [
        FeatureEvidence("book_imbalance", f"topK-synced", thresh.split(" & ")[0],
                        f"{imb:+.4f}"),
        FeatureEvidence("flow_buy_frac",
                        f"{p.sync_max_age_s}s-window", thresh.split(" & ")[1],
                        f"{buy_frac:.4f}"),
        FeatureEvidence("spread", "trigger-bar+book",
                        f"bar<={p.spread_max_bps:.1f} & book<={p.depth_spread_max_bps:.1f}",
                        f"{bar.spread_bps:.2f}&{depth.spread_bps:.2f}"),
    ]
    order = ("quality", "depth", "flow", "sync", "history", "gap",
             "flowcount", "spread", "signal")
    rejects = tuple(f"{k}={checks[k]}" for k in order)
    if not (flow.trade_count >= p.flow_min_trades and spread_ok and signal_ok):
        failed = next(k for k in ("flowcount", "spread", "signal")
                      if checks[k] == "fail")
        return _log("no-microstructure", tuple(feats), "no-fire", rejects,
                    DataQuality.CLEAN, f"{failed}-gate", evidence_ts)

    # Intent construction (S5.md section 6).
    close_t = bar.close
    buf = p.inval_buf_bps / 1e4
    tol = p.entry_tol_bps / 1e4
    ref = window[:-1]
    if is_long:
        entry_low = close_t
        entry_high = close_t * (1.0 + tol)
        inval = min(b.low for b in ref) * (1.0 - buf)
        regime = "microstructure-long"
    else:
        entry_high = close_t
        entry_low = close_t * (1.0 - tol)
        inval = max(b.high for b in ref) * (1.0 + buf)
        regime = "microstructure-short"
    trigger = f"imb={imb:+.3f} & buyfrac={buy_frac:.3f} {thresh}"
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
        data_quality_reason="depth-flow-synced",
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
        data_quality_reason="depth-flow-synced",
        forecast_cost=S5_FORECAST_COST,
    )
    log = EvalLog(arm, side, regime, tuple(feats), trigger, rejects,
                  DataQuality.CLEAN, "fired", evidence_ts)
    return S5Decision(log, intent, record)


def evaluate_view(
    view: MarketView,
    arm: str,
    instrument: str,
    params: S5Params | None = None,
) -> tuple[S5Decision, S5Decision]:
    """Evaluate LONG then SHORT independently on ``view``."""
    return (
        evaluate_side(view, Side.LONG, arm, instrument, params),
        evaluate_side(view, Side.SHORT, arm, instrument, params),
    )
