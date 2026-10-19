"""M1-slice wiring over the accepted V-001 policy (Worker 3, v0.1.1/v0.2.0).

Drop-in replacement for the slice-local ``risk_stub``: same ``(ok, reason,
notional)`` decision shape, real :class:`RiskPolicy` + accounting
:class:`Ledger` underneath. The manager wires this into
``tools/m1_vertical_slice.py`` at integration; this module never imports
slice code.

Day handling: the slice opens its accounting day explicitly at construction
(``day_start_equity``). If the clock rolls past midnight mid-run, evaluations
report ``risk-policy:rejected:health:day-open-needs-reconciliation`` until
the integrator calls :meth:`SliceRisk.reconcile_day` again.

V-004: snapshots carry lifetime flow totals so halt/target/floor references
are flow-adjusted (F-CEO-06); ``note_fill_delta`` books v0.2.0 fill
increments into both ledger and policy exposure books.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from cryptobot.accounting import Ledger

from .policy import RiskPolicy
from .types import AccountSnapshot, Approved, HealthStatus, Rejected, RiskConfig

LABEL = "risk-policy"


@dataclass(frozen=True)
class SliceDecision:
    ok: bool
    reason: str
    notional_usdt: float
    qty: float
    reservation_id: str | None


class SliceRisk:
    """RiskPolicy + Ledger bound to one M1-slice run (single position)."""

    def __init__(
        self,
        *,
        state_path: str | Path,
        day_start_equity: float,
        config: RiskConfig | None = None,
        now_utc: Callable[[], datetime] | None = None,
    ) -> None:
        self._now_utc = now_utc or (lambda: datetime.now(timezone.utc))
        self.policy = RiskPolicy(config=config, state_path=state_path, now_utc=self._now_utc)
        self.ledger = Ledger(pilot_equity=day_start_equity)
        self.policy.bind_ledger(self.ledger)
        self.policy.reconcile_day(day_start_equity, self.ledger.total_flows())

    def reconcile_day(self, day_start_equity: float) -> str:
        return self.policy.reconcile_day(day_start_equity, self.ledger.total_flows())

    def snapshot(self, ref_price: float, close_cost_bps: float) -> AccountSnapshot:
        marked = self.ledger.marked_equity(ref_price)
        return AccountSnapshot(
            reconciled_equity=marked,
            marked_equity=marked,
            net_liquidation=self.ledger.net_liquidation(ref_price, close_cost_bps),
            net_realised_global=self.ledger.net_realised(),
            open_position=self.ledger.has_position(),
            flows_cumulative=self.ledger.total_flows(),
        )

    def evaluate(self, intent, ref_price: float) -> SliceDecision:
        """Evaluate an M1-shaped intent; mirrors the risk_stub return shape."""
        fc = intent.forecast_cost
        close_cost_bps = fc.fee_bps + fc.spread_bps + fc.slippage_bps + fc.funding_bps
        out = self.policy.evaluate(intent, self.snapshot(ref_price, close_cost_bps))
        if isinstance(out, Approved):
            return SliceDecision(
                ok=True,
                reason=f"{LABEL}:approved:reservation={out.reservation_id}"
                       f":budget={out.reserved_risk:.4f}",
                notional_usdt=out.notional_usdt,
                qty=out.qty,
                reservation_id=out.reservation_id,
            )
        return SliceDecision(
            ok=False,
            reason=f"{LABEL}:rejected:{out.reason}",
            notional_usdt=0.0,
            qty=0.0,
            reservation_id=None,
        )

    def note_slice_fill(
        self, reservation_id: str, side: str, qty: float, price: float, fee: float = 0.0
    ) -> None:
        """Record a slice-venue fill: ledger books it, reservation converts.

        ``fee`` defaults to 0.0 because the slice-local venue models no fees;
        pass measured fees when they exist.
        """
        self.ledger.record_fill(side, qty, price, fee, self._now_utc())
        self.policy.note_fill(reservation_id)

    def release(self, reservation_id: str) -> bool:
        return self.policy.release(reservation_id)

    def note_slice_flat(self) -> None:
        """Clear open-position state after the caller closes the ledger leg."""
        self.policy.note_flat()

    def note_fill_delta(
        self,
        reservation_id: str,
        exec_id: str,
        symbol: str,
        venue_side: str,
        qty: float,
        price: float,
        fee: float,
        ts_utc: str,
    ) -> None:
        """Book one v0.2.0 fill increment (delegates to the bound policy sink).

        The policy validates, books state, and propagates to this bound
        ledger under the same exec_id; both sides stay idempotent.
        """
        self.policy.note_fill_delta(reservation_id, exec_id, symbol, venue_side,
                                    qty, price, fee, ts_utc)

    def monitor(self, ref_price: float, close_cost_bps: float) -> HealthStatus:
        """Intent-free health check over live ledger equity (V-004)."""
        return self.policy.check_health(self.snapshot(ref_price, close_cost_bps))
