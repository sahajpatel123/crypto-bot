"""M1 runnable vertical slice on SYNTHETIC data (manager-owned scaffold).

Flow: synthetic metadata -> synthetic replay -> S1 stub intent -> coordinator ->
risk stub -> fake-venue execution -> reconciled ledger -> report.

Includes one demonstrably rejected trade (stale/expired) and one fault-recovery
path (ambiguous order reconciled before retry, no duplicate exposure).

Not a validated trading system. Every input here is synthetic.
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
        return False, "halt-data-quality", 0.0
    if intent.entry_expiry_utc < datetime.now(timezone.utc):
        return False, "expired", 0.0
    budget = equity_usdt * 0.0025
    stop_dist = abs((intent.entry_low + intent.entry_high) / 2 - intent.invalidation_price)
    ref = (intent.entry_low + intent.entry_high) / 2
    stop_pct = stop_dist / ref if ref else 1.0
    cost_pct = (intent.forecast_cost.fee_bps + intent.forecast_cost.spread_bps) / 10000
    denom = stop_pct + cost_pct
    notional = budget / denom if denom > 0 else 0.0
    return True, f"approved:budget={budget:.4f}", notional


def main() -> int:
    parser = argparse.ArgumentParser(description="M1 synthetic vertical slice")
    parser.add_argument("--out", default="reports/m1_report.json")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    forecast = ForecastCost(fee_bps=5, spread_bps=5, slippage_bps=5, funding_bps=0)
    good = Intent("S1", "0.1.0-stub", "BTCUSDT", Side.LONG, now - timedelta(seconds=5),
                  67000.0, 67010.0, now + timedelta(seconds=60), 66850.0,
                  "invalidation-or-300s", 300, forecast, "synthetic-decision-1",
                  DataQuality.CLEAN)
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
    cid = "m1-0001"
    first = venue.submit(cid, 67005.0, 0.001)
    assert first == "ambiguous", "fault injection must trigger once"
    rec = venue.reconcile(cid)
    assert rec == "cancelled-unknown", "reconcile must resolve ambiguity before retry"
    cid2 = "m1-0002"
    final = venue.submit(cid2, 67005.0, 0.001)
    assert final == "filled", "retry with new client ID must fill once"
    assert len(venue.fills) == 1, "no duplicate exposure after recovery"

    report = {
        "slice": "M1",
        "synthetic": True,
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
