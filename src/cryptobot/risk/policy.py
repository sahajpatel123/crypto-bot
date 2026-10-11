"""Deterministic risk policy (Worker 3, CONTRACTS v0.1.0 risk gate).

Gate order is fixed (first failure wins); the clock is injectable so every
decision is reproducible. Halts, pauses, the profit-protection floor, and
reservations persist to disk atomically; a new accounting day starts
needs-reconciliation until ``reconcile_day`` records the flow-adjusted
starting marked equity.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from cryptobot.accounting.day import accounting_date
from cryptobot.coordination import DataQuality

from .sizing import SizeRejected, plan_size
from .state import Reservation, RiskState, load_state, save_state
from .types import AccountSnapshot, Approved, Rejected, RiskConfig


class RiskPolicy:
    def __init__(
        self,
        config: RiskConfig | None = None,
        *,
        state_path: str | Path,
        now_utc: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config or RiskConfig()
        self.state_path = Path(state_path)
        self._now_utc = now_utc or (lambda: datetime.now(timezone.utc))
        self._state: RiskState = load_state(self.state_path)

    # -- day lifecycle ---------------------------------------------------
    def reconcile_day(self, day_start_equity: float) -> str:
        """Record the flow-adjusted starting marked equity for the current day."""
        today = accounting_date(self._now_utc()).isoformat()
        self._state.current_day = today
        self._state.day_start_equity = float(day_start_equity)
        self._state.needs_reconciliation = False
        if self._state.original_equity is None:
            self._state.original_equity = float(day_start_equity)
        save_state(self.state_path, self._state)
        return today

    # -- gate ------------------------------------------------------------
    def evaluate(self, intent, account: AccountSnapshot) -> Approved | Rejected:
        now = self._now_utc()
        cfg = self.config

        if intent.data_quality == DataQuality.HALT:
            return Rejected("health:data-quality-halt")
        if intent.data_quality == DataQuality.DEGRADED:
            return Rejected("health:data-quality-degraded")
        if intent.entry_expiry_utc < now:
            return Rejected("stale:expired")
        if (now - intent.evidence_ts_utc).total_seconds() > cfg.max_evidence_age_s:
            return Rejected("stale:evidence-age")

        today = accounting_date(now).isoformat()
        if (
            self._state.current_day != today
            or self._state.needs_reconciliation
            or self._state.day_start_equity is None
        ):
            if self._state.current_day != today:
                self._state.current_day = today
                self._state.needs_reconciliation = True
                save_state(self.state_path, self._state)
            return Rejected("health:day-open-needs-reconciliation")
        day_start = self._state.day_start_equity

        if today in self._state.halt_days:
            return Rejected("halt:daily-loss")
        if account.marked_equity <= day_start * (1 - cfg.daily_loss_halt_pct):
            self._state.halt_days[today] = "daily-loss"
            save_state(self.state_path, self._state)
            return Rejected("halt:daily-loss")

        if today in self._state.pause_days:
            return Rejected("pause:daily-target")
        if account.net_liquidation >= day_start * (1 + cfg.daily_target_pct):
            self._state.pause_days[today] = "daily-target"
            save_state(self.state_path, self._state)
            return Rejected("pause:daily-target")

        floor_hit = self._update_profit_protection(account)
        if floor_hit:
            return Rejected("halt:profit-protection")

        if self._purge_expired(now):
            save_state(self.state_path, self._state)
        if account.open_position or self._state.open_position or self._state.reservations:
            return Rejected("exposure:one-position")

        try:
            plan = plan_size(intent, account.reconciled_equity, cfg)
        except SizeRejected as exc:
            return Rejected(exc.reason)

        self._state.seq += 1
        rid = f"r-{self._state.seq:06d}"
        self._state.reservations[rid] = Reservation(
            reservation_id=rid,
            intent_ref=intent.evidence_ref,
            instrument=intent.instrument,
            side=intent.side.value,
            notional=plan.notional_usdt,
            reserved_risk=plan.reserved_risk,
            created_utc=now.isoformat(),
            expires_utc=intent.entry_expiry_utc.isoformat(),
        )
        save_state(self.state_path, self._state)
        return Approved(
            reservation_id=rid,
            reserved_risk=plan.reserved_risk,
            notional_usdt=plan.notional_usdt,
            qty=plan.qty,
        )

    # -- reservation lifecycle -------------------------------------------
    def release(self, reservation_id: str) -> bool:
        if reservation_id not in self._state.reservations:
            return False
        del self._state.reservations[reservation_id]
        save_state(self.state_path, self._state)
        return True

    def note_fill(self, reservation_id: str) -> None:
        self._state.reservations.pop(reservation_id, None)
        self._state.open_position = True
        save_state(self.state_path, self._state)

    def note_flat(self) -> None:
        self._state.open_position = False
        save_state(self.state_path, self._state)

    def live_reservations(self) -> tuple[str, ...]:
        self._purge_expired(self._now_utc())
        return tuple(self._state.reservations)

    # -- internals ---------------------------------------------------------
    def _update_profit_protection(self, account: AccountSnapshot) -> bool:
        """Ratchet the upward-only floor; True when marked equity breaches it."""
        original = self._state.original_equity
        if original is None:
            return False
        changed = False
        if account.net_realised_global > self._state.peak_realised:
            self._state.peak_realised = account.net_realised_global
            changed = True
        if account.net_realised_global >= original * self.config.profit_arm_pct:
            floor = original + self.config.profit_retain_pct * self._state.peak_realised
            if self._state.profit_floor is None or floor > self._state.profit_floor:
                self._state.profit_floor = floor
                changed = True
        if changed:
            save_state(self.state_path, self._state)
        return self._state.profit_floor is not None and account.marked_equity <= self._state.profit_floor

    def _purge_expired(self, now: datetime) -> bool:
        expired = [rid for rid, r in self._state.reservations.items() if r.expired(now)]
        for rid in expired:
            del self._state.reservations[rid]
        return bool(expired)
