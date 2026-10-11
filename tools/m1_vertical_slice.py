"""M1 runnable vertical slice on SYNTHETIC data (manager-owned scaffold).

Flow: SYNTH_V1 synthetic fixture -> real S1 baseline intent (ARM_BASE) ->
coordinator -> risk stub -> fake-venue execution -> reconciled ledger -> report.

Includes one demonstrably rejected trade (stale/expired) and one fault-recovery
path (ambiguous order reconciled before retry, no duplicate exposure).

Risk gate is still a labelled stub until V-001 lands. Not a validated trading
system. Every input here is synthetic.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptobot.coordination import Coordinator, DataQuality, ForecastCost, Intent, Side
from cryptobot.research.synthetic import SCENARIO_LONG, generate_fixture
from cryptobot.strategies.contract import ARM_BASE
from cryptobot.strategies.s1 import Bar, evaluate_side


@dataclass
class FakeFill:
    client_id: str
    price: float
    qty: float


class FakeVenue:
    def __init__(self) -> None:
        self.orders: dict[str, str] = {}
        self.fills: list[FakeFill] = []
        self._ambiguous_once = True

    def submit(self, client_id: str, price: float, qty: float) -> str:
        if client_id in self.orders:
            return self.orders[client_id]
        # Inject one ambiguous timeout on first submission; reconcile before retry.
        if self._ambiguous_once:
            self._ambiguous_once = False
            self.orders[client_id] = "ambiguous"
            return "ambiguous"
        self.orders[client_id] = "filled"
        self.fills.append(FakeFill(client_id, price, qty))
        return "filled"

    def reconcile(self, client_id: str) -> str:
        state = self.orders.get(client_id, "unknown")
        if state == "ambiguous":
            # Recovery: query venue; order never reached matching engine, safe to retry once.
            self.orders[client_id] = "cancelled-unknown"
            return "cancelled-unknown"
        return state


def risk_stub(intent: Intent, equity_usdt: float) -> tuple[bool, str, float]:
    if intent.data_quality == DataQuality.HALT:
        return False, "risk-stub:halt-data-quality", 0.0
    if intent.entry_expiry_utc < datetime.now(timezone.utc):
        return False, "risk-stub:expired", 0.0
    budget = equity_usdt * 0.0025
    stop_dist = abs((intent.entry_low + intent.entry_high) / 2 - intent.invalidation_price)
    ref = (intent.entry_low + intent.entry_high) / 2
    stop_pct = stop_dist / ref if ref else 1.0
    cost_pct = (intent.forecast_cost.fee_bps + intent.forecast_cost.spread_bps) / 10000
    denom = stop_pct + cost_pct
    notional = budget / denom if denom > 0 else 0.0
    return True, f"risk-stub:approved:budget={budget:.4f}", notional


def main() -> int:
    parser = argparse.ArgumentParser(description="M1 synthetic vertical slice")
    parser.add_argument("--out", default="reports/m1_report.json")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    # Real S1 baseline on a labelled synthetic fixture. The fixture clock is
    # fixed, so bars are truncated at the first LONG fire and shifted so the
    # evidence bar sits 5s in the past (1s spacing preserved, no future bars).
    fixture = generate_fixture(seed=11, scenario=SCENARIO_LONG)
    fire_t = next(
        (t for t in range(120, len(fixture.bars))
         if evaluate_side(list(fixture.bars), t, Side.LONG, ARM_BASE,
                           "BTCUSDT").intent is not None),
        None,
    )
    assert fire_t is not None, "SYNTH_V1 long-breakout must fire S1 LONG"
    shift = (now - timedelta(seconds=5)) - fixture.bars[fire_t].ts_utc
    shifted = [
        Bar(ts_utc=b.ts_utc + shift, open=b.open, high=b.high, low=b.low,
            close=b.close, volume=b.volume, trades=b.trades,
            buy_frac=b.buy_frac, spread_bps=b.spread_bps, source=b.source)
        if b is not None else None
        for b in fixture.bars[:fire_t + 1]
    ]
    s1 = evaluate_side(shifted, fire_t, Side.LONG, ARM_BASE, "BTCUSDT")
    assert s1.intent is not None and s1.record is not None, "shifted S1 must re-fire"
    good = s1.intent
    assert good.evidence_ref == s1.record.record_id, "intent must point at its decision record"
    forecast = ForecastCost(fee_bps=5, spread_bps=5, slippage_bps=5, funding_bps=0)
    stale = Intent("S1", "0.1.0-stub", "BTCUSDT", Side.LONG, now - timedelta(seconds=120),
                   67000.0, 67010.0, now - timedelta(seconds=1), 66850.0,
                   "invalidation-or-300s", 300, forecast, "synthetic-decision-2",
                   DataQuality.CLEAN)
    coord = Coordinator()
    decision = coord.select([good, stale], now)
    assert decision.accepted is good, "coordinator must pick the valid intent"
    assert stale in decision.rejected, "stale intent must be rejected"

    equity = 100.0  # synthetic USDT
    ok, reason, notional = risk_stub(decision.accepted, equity)
    assert ok, f"risk stub should approve good intent: {reason}"

    venue = FakeVenue()
    mid = (good.entry_low + good.entry_high) / 2
    qty = notional / mid
    cid = "m1-0001"
    first = venue.submit(cid, mid, qty)
    assert first == "ambiguous", "fault injection must trigger once"
    rec = venue.reconcile(cid)
    assert rec == "cancelled-unknown", "reconcile must resolve ambiguity before retry"
    cid2 = "m1-0002"
    final = venue.submit(cid2, mid, qty)
    assert final == "filled", "retry with new client ID must fill once"
    assert len(venue.fills) == 1, "no duplicate exposure after recovery"

    report = {
        "slice": "M1",
        "synthetic": True,
        "s1_source": "SYNTH_V1:long-breakout:seed11:ARM_BASE",
        "evidence_bar": fire_t,
        "coordinator_reason": decision.reason,
        "rejected_count": len(decision.rejected),
        "risk": reason,
        "notional": notional,
        "fills": len(venue.fills),
        "recovery": "ambiguous-reconciled-no-duplicate",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
