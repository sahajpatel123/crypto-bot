"""Deterministic risk policy (Worker 3, CONTRACTS v0.1.x + v0.2.0 deltas).

Gate order is fixed (first failure wins); the clock is injectable so every
decision is reproducible. Halts, pauses, the profit-protection floor,
reservations, and unresolved exposure persist atomically; a new accounting
day starts needs-reconciliation until ``reconcile_day`` records the starting
marked equity plus flow baselines.

V-004 corrections: input validation (F-CEO-07), expired reservations retained
as unresolved until reconciled (F-CEO-03), flow-adjusted day/global refs
(F-CEO-06), intent-free monitoring, and the v0.2.0 fill-delta sink
(idempotent exec_id booking, exposure-gated release/flat).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from cryptobot.accounting.day import accounting_date
from cryptobot.accounting.ledger import Ledger
from cryptobot.coordination import DataQuality, Side

from .sizing import SizeRejected, plan_size
from .state import Reservation, RiskState, load_state, save_state
from .types import AccountSnapshot, Approved, HealthStatus, Rejected, RiskConfig

# Booking dust below any venue precision reads as flat (F-CEO-02/03 seam).
BOOKED_ZERO_EPS = 1e-9


def _finite(value: float) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


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
        self._ledger: Ledger | None = None
        # READY-§5 executable narrowing (runtime-only, position-scoped like
        # Session._position — intentionally unpersisted): reservation id ->
        # venue-snapped executable qty reported by the Session from the
        # engine-recorded order. Approved (reservation.qty) is the
        # risk-budgeted request; executable is what was actually submitted;
        # booked/fill ledger is what executed. Popped on lifecycle end.
        self._executable: dict[str, float] = {}

    # -- day lifecycle ---------------------------------------------------
    def reconcile_day(self, day_start_equity: float, flows_cumulative: float = 0.0) -> str:
        """Record starting marked equity plus lifetime-flows baselines."""
        if not _finite(day_start_equity):
            raise ValueError(f"day_start_equity must be finite, got {day_start_equity!r}")
        if not _finite(flows_cumulative):
            raise ValueError(f"flows_cumulative must be finite, got {flows_cumulative!r}")
        today = accounting_date(self._now_utc()).isoformat()
        self._state.current_day = today
        self._state.day_start_equity = float(day_start_equity)
        self._state.flow_baseline_day = float(flows_cumulative)
        self._state.needs_reconciliation = False
        if self._state.original_equity is None:
            self._state.original_equity = float(day_start_equity)
        if self._state.flow_baseline_inception is None:
            # Fresh ledgers and migrated v1 states: absorb flow history now.
            self._state.flow_baseline_inception = float(flows_cumulative)
        save_state(self.state_path, self._state)
        return today

    # -- gate ------------------------------------------------------------
    def evaluate(self, intent, account: AccountSnapshot) -> Approved | Rejected:
        now = self._now_utc()
        cfg = self.config

        invalid = self._validate_inputs(intent, account, now)
        if invalid is not None:
            return invalid
        if intent.data_quality == DataQuality.HALT:
            return Rejected("health:data-quality-halt")
        if intent.data_quality == DataQuality.DEGRADED:
            return Rejected("health:data-quality-degraded")

        today = accounting_date(now).isoformat()
        if (
            self._state.current_day != today
            or self._state.needs_reconciliation
            or self._state.day_start_equity is None
        ):
            self._roll_day_if_needed(now, today)
            return Rejected("health:day-open-needs-reconciliation")
        day_start = self._state.day_start_equity

        netliq_adj = self._adjust_day(account.net_liquidation, account.flows_cumulative)
        # W3-24H §4 stops key on flow-adjusted net liquidation (net of
        # costs) vs the reconciled day start. Emergency dominates.
        stop, _ = self._check_stops(netliq_adj, day_start, today, now)
        if stop is not None:
            return Rejected(stop)

        if today in self._state.pause_days:
            return Rejected("pause:daily-target")
        if netliq_adj >= day_start * (1 + cfg.daily_target_pct):
            self._state.pause_days[today] = "daily-target"
            save_state(self.state_path, self._state)
            return Rejected("pause:daily-target")

        if self._update_profit_protection(account):
            return Rejected("halt:profit-protection")

        if self._settle_expired(now):
            save_state(self.state_path, self._state)
        if account.open_position or self._state.open_position or self._state.reservations:
            return Rejected("exposure:one-position")
        if self._state.unresolved:
            return Rejected("exposure:unresolved")
        if self._booked_nonzero_global():
            return Rejected("exposure:booked")

        filters_block = self._check_filters(intent, now)
        if filters_block is not None:
            return filters_block
        # F-W5R1 (directive section 4): reserve against the SMALLEST of
        # per-position, remaining-daily, floor-cushion and margin budgets.
        # Stops above already passed, so the daily remainder is positive;
        # the floor cushion nets the modeled close cost (fee buffer)
        # before it can be spent. Margin + venue minimums stay gates
        # inside plan_size (unaffordable size skips, never rounds up).
        remaining_daily = netliq_adj - day_start * (1 - cfg.operating_stop_pct)
        cap = remaining_daily
        if self._state.profit_floor is not None:
            marked_adj = self._adjust_inception(
                account.marked_equity, account.flows_cumulative)
            cushion = (marked_adj - self._state.profit_floor
                       - (account.fee_buffer_usdt or 0.0))
            cap = min(cap, cushion)
        try:
            plan = plan_size(
                intent, account.reconciled_equity, cfg,
                available_margin_usdt=account.available_margin_usdt,
                fee_buffer_usdt=account.fee_buffer_usdt,
                inflight_exposure_usdt=account.inflight_exposure_usdt,
                risk_budget_cap_usdt=cap,
            )
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
            qty=plan.qty,
        )
        save_state(self.state_path, self._state)
        return Approved(
            reservation_id=rid,
            reserved_risk=plan.reserved_risk,
            notional_usdt=plan.notional_usdt,
            qty=plan.qty,
            required_stop_qty=plan.qty,
        )

    # -- intent-free monitoring --------------------------------------------
    def check_health(self, account: AccountSnapshot) -> HealthStatus:
        """Latch halt/pause/floor/rollover state without requiring an intent."""
        return self.monitor_tick(self._now_utc(), account)

    def monitor_tick(self, now: datetime | None = None,
                     account: AccountSnapshot | None = None) -> HealthStatus:
        """Timer-driven oversight tick; never depends on market traffic.

        With an account snapshot, evaluates and latches halt/pause/floor. With
        account=None, still rolls the day, settles expiries, and reports
        latched blocks — a quiet feed, stalled book, or blocked REST call
        cannot suspend oversight. Records the tick time in persisted state so
        the runtime can detect a dead monitor loop.
        """
        now = now or self._now_utc()
        cfg = self.config
        today = accounting_date(now).isoformat()
        reasons: list[str] = []
        latched: list[str] = []
        if self._roll_day_if_needed(now, today):
            latched.append("day-rolled")
        if account is not None and not self._validate_account(account):
            return HealthStatus(False, ("health:nonfinite-account",), ())
        if self._state.needs_reconciliation or self._state.day_start_equity is None:
            self._record_tick(now)
            save_state(self.state_path, self._state)
            return HealthStatus(False, ("health:day-open-needs-reconciliation",),
                                tuple(latched))
        if account is None:
            if self._state.emergency_latched:
                reasons.append("halt:emergency")
            if today in self._state.operating_stop_days:
                reasons.append("halt:operating-stop")
            if today in self._state.pause_days:
                reasons.append("pause:daily-target")
            if self._settle_expired(now):
                latched.append("expiry-settled")
            self._record_tick(now)
            save_state(self.state_path, self._state)
            return HealthStatus(not reasons, tuple(reasons), tuple(latched))
        mark_block = self._check_mark_age(account)
        if mark_block is not None:
            self._record_tick(now)
            save_state(self.state_path, self._state)
            return HealthStatus(False, (mark_block,), tuple(latched))
        day_start = self._state.day_start_equity
        netliq_adj = self._adjust_day(account.net_liquidation, account.flows_cumulative)
        stop, just_latched = self._check_stops(netliq_adj, day_start, today, now)
        if just_latched:
            latched.append("emergency" if stop == "halt:emergency"
                           else "operating-stop")
        if stop is not None:
            reasons.append(stop)
        if today not in self._state.pause_days and netliq_adj >= day_start * (1 + cfg.daily_target_pct):
            self._state.pause_days[today] = "daily-target"
            latched.append("pause")
        if today in self._state.pause_days:
            reasons.append("pause:daily-target")
        floor_before = self._state.profit_floor
        if self._update_profit_protection(account):
            reasons.append("halt:profit-protection")
        if self._state.profit_floor != floor_before:
            latched.append("floor")
        if self._settle_expired(now):
            latched.append("expiry-settled")
        self._record_tick(now)
        save_state(self.state_path, self._state)
        return HealthStatus(not reasons, tuple(reasons), tuple(latched))

    def _record_tick(self, now: datetime) -> None:
        self._state.last_tick_utc = now.isoformat()

    # -- v0.2.0 outcome sink (risk implements, execution calls) -------------
    def bind_ledger(self, ledger: Ledger) -> None:
        """Bind the paired ledger for delta propagation (runtime-only).

        Set by SliceRisk at construction; never persisted. Rebinding
        replaces the previous binding.
        """
        self._ledger = ledger

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
        """Book one fill increment idempotently; first nonzero marks exposure.

        Policy state books first (validation rejects before any mutation);
        a bound ledger then books the same increment under the same exec_id
        (idempotent both sides, so redelivery is safe end to end). Bare
        policies with no bound ledger book state only.
        """
        if not reservation_id or not isinstance(reservation_id, str):
            raise ValueError("reservation_id must be a non-empty string")
        if not exec_id or not isinstance(exec_id, str):
            raise ValueError("exec_id must be a non-empty string")
        if not symbol or not isinstance(symbol, str):
            raise ValueError("symbol must be a non-empty string")
        if venue_side not in ("BUY", "SELL"):
            raise ValueError(f"venue_side must be BUY or SELL, got {venue_side!r}")
        if not _finite(qty) or qty <= 0:
            raise ValueError(f"qty must be finite and > 0, got {qty!r}")
        if not _finite(price) or price <= 0:
            raise ValueError(f"price must be finite and > 0, got {price!r}")
        if not _finite(fee) or fee < 0:
            raise ValueError(f"fee must be finite and >= 0, got {fee!r}")
        if self.config.run_mode and fee <= 0:
            raise ValueError("fee must be > 0 in run mode (fee=0.0 is fault-test-only)")
        try:
            ts = datetime.fromisoformat(ts_utc)
        except (TypeError, ValueError):
            raise ValueError(f"ts_utc must be ISO-8601, got {ts_utc!r}") from None
        if ts.tzinfo is None or ts.utcoffset() is None or ts.utcoffset().total_seconds() != 0:
            raise ValueError(f"ts_utc must carry a UTC offset, got {ts_utc!r}")
        entry = self._state.booked.setdefault(
            reservation_id, {"net_qty": 0.0, "exec_ids": [], "symbol": symbol})
        if exec_id in entry["exec_ids"]:
            return  # at-least-once redelivery: ignore, never double-book.
        entry["exec_ids"].append(exec_id)
        entry["net_qty"] = entry["net_qty"] + qty if venue_side == "BUY" else entry["net_qty"] - qty
        save_state(self.state_path, self._state)
        if self._ledger is not None:
            # Validated above: ledger inputs are implied valid, booking cannot fail.
            self._ledger.note_fill(exec_id, symbol, venue_side, qty, price, fee, ts_utc)

    def note_funding(self, event_id: str, amount: float, ts_utc: str) -> None:
        """Route one engine funding event to the bound ledger (V-006, S4).

        Fail-closed: raises when no ledger is bound (funding must never
        vanish silently). In run mode the amount must be nonzero.
        """
        if self._ledger is None:
            raise ValueError("note_funding requires a bound ledger")
        if not event_id or not isinstance(event_id, str):
            raise ValueError("event_id must be a non-empty string")
        if not _finite(amount):
            raise ValueError(f"amount must be finite, got {amount!r}")
        if self.config.run_mode and amount == 0:
            raise ValueError("funding amount must be nonzero in run mode")
        try:
            ts = datetime.fromisoformat(ts_utc)
        except (TypeError, ValueError):
            raise ValueError(f"ts_utc must be ISO-8601, got {ts_utc!r}") from None
        if ts.tzinfo is None or ts.utcoffset() is None or ts.utcoffset().total_seconds() != 0:
            raise ValueError(f"ts_utc must carry a UTC offset, got {ts_utc!r}")
        self._ledger.record_funding(amount, ts, event_id)

    def release(self, reservation_id: str) -> bool:
        """Free a reservation only when its booked exposure reconciles zero.

        True only when a live reservation was actually freed. An unresolved
        id with zero booked exposure is lifted (reconciliation accepted) but
        reports False; nonzero booked exposure retains the block either way.
        Lifecycle end pops executable narrowing in both freed branches.
        """
        if reservation_id in self._state.reservations:
            if self._booked_net(reservation_id) != 0.0:
                self._move_to_unresolved(reservation_id, self._now_utc())
                save_state(self.state_path, self._state)
                return False
            del self._state.reservations[reservation_id]
            self._executable.pop(reservation_id, None)
            save_state(self.state_path, self._state)
            return True
        if reservation_id in self._state.unresolved:
            if self._booked_net(reservation_id) != 0.0:
                return False
            del self._state.unresolved[reservation_id]
            self._executable.pop(reservation_id, None)
            save_state(self.state_path, self._state)
            return False
        return False

    def note_executable_qty(self, reservation_id: str, qty: float) -> bool:
        """Narrow a reservation to the venue-snapped executable quantity.

        Called by the Session from the engine-recorded order qty (the
        authoritative submitted quantity after venue flooring). False for
        unknown ids (caller fails closed); last-wins on repeats (the
        recorded qty is immutable, so repeats agree). Survives note_fill
        (conversion) so protection need stays narrowed after the first
        fill; popped by release at lifecycle end.
        """
        if not _finite(qty) or qty <= 0:
            return False
        known = (reservation_id in self._state.reservations
                 or reservation_id in self._state.unresolved
                 or reservation_id in self._executable)
        if not known:
            return False
        self._executable[reservation_id] = float(qty)
        return True

    def note_fill(self, reservation_id: str) -> None:
        """First-nonzero-fill transition: reservation converts to exposure.

        Idempotent (duplicate-tolerant). Never treated as terminal-full:
        booked deltas keep blocking until flat booking + reconciliation.
        """
        self._state.reservations.pop(reservation_id, None)
        self._state.open_position = True
        save_state(self.state_path, self._state)

    def note_flat(self) -> None:
        """Clear open-position state only when booked exposure nets to zero."""
        if self._booked_nonzero_global():
            return
        self._state.open_position = False
        save_state(self.state_path, self._state)

    def live_reservations(self) -> tuple[str, ...]:
        if self._settle_expired(self._now_utc()):
            save_state(self.state_path, self._state)
        return tuple(self._state.reservations)

    def unresolved_ids(self) -> tuple[str, ...]:
        return tuple(self._state.unresolved)

    def booked_net(self, reservation_id: str) -> float:
        return self._booked_net(reservation_id)

    def booked_total_qty(self) -> float:
        """Sum of booked nets across reservations (V-008 one-budget input).

        Single-position scope: at most one nonzero entry. Callers price
        the excess over ledger-shown exposure, never the raw sum twice.
        """
        total = sum(self._booked_net(rid) for rid in self._state.booked)
        return 0.0 if abs(total) <= BOOKED_ZERO_EPS else total

    def required_stop_qty(self, reservation_id: str) -> float | None:
        """Position quantity the protective stop must cover (V-007 B8).

        The manager compares the engine-acknowledged stop quantity against
        this before flipping `protected`. READY-§5: executable narrowing
        wins over approved qty (a canceled/unsubmitted remainder is never
        demanded). None means unknown (legacy record or unknown id) and
        must never count as verified.
        """
        if reservation_id in self._executable:
            return self._executable[reservation_id]
        reservation = self._state.reservations.get(reservation_id)
        if reservation is not None:
            return reservation.qty
        unresolved = self._state.unresolved.get(reservation_id)
        if unresolved is not None:
            return unresolved["reservation"].get("qty")
        return None

    # -- internals ---------------------------------------------------------
    def _validate_inputs(self, intent, account: AccountSnapshot, now: datetime) -> Rejected | None:
        if not isinstance(intent.side, Side):
            return Rejected("health:invalid-enum")
        if not isinstance(intent.data_quality, DataQuality):
            return Rejected("health:invalid-enum")
        if not all(_finite(v) for v in (intent.entry_low, intent.entry_high,
                                        intent.invalidation_price)):
            return Rejected("health:nonfinite-price")
        if intent.entry_low <= 0 or intent.entry_high <= 0 or intent.invalidation_price <= 0:
            return Rejected("health:nonpositive-price")
        fc = intent.forecast_cost
        if not all(_finite(v) for v in (fc.fee_bps, fc.spread_bps, fc.slippage_bps, fc.funding_bps)):
            return Rejected("health:nonfinite-cost")
        if not isinstance(intent.holding_limit_s, int) or intent.holding_limit_s <= 0:
            return Rejected("health:invalid-holding")
        if intent.evidence_ts_utc.tzinfo is None or intent.entry_expiry_utc.tzinfo is None:
            return Rejected("stale:naive-timestamp")
        if intent.entry_expiry_utc <= now:
            return Rejected("stale:expired")
        if (now - intent.evidence_ts_utc).total_seconds() > self.config.max_evidence_age_s:
            return Rejected("stale:evidence-age")
        if (intent.evidence_ts_utc - now).total_seconds() > self.config.max_clock_skew_s:
            return Rejected("stale:future-evidence")
        if not self._validate_account(account):
            return Rejected("health:nonfinite-account")
        mark_block = self._check_mark_age(account)
        if mark_block is not None:
            return Rejected(mark_block)
        return None

    def _validate_account(self, account: AccountSnapshot) -> bool:
        if not isinstance(account.open_position, bool):
            return False
        if not all(_finite(v) for v in (account.reconciled_equity, account.marked_equity,
                                        account.net_liquidation, account.net_realised_global,
                                        account.flows_cumulative, account.fee_buffer_usdt,
                                        account.inflight_exposure_usdt)):
            return False
        if account.fee_buffer_usdt < 0 or account.inflight_exposure_usdt < 0:
            return False
        margin = account.available_margin_usdt
        if margin is not None and not (_finite(margin) and margin >= 0):
            return False
        age = account.mark_age_ms
        return age is None or (_finite(age) and age >= 0)

    def _check_mark_age(self, account: AccountSnapshot) -> str | None:
        """W3-24H stale-mark block (fail closed when configured)."""
        limit = self.config.max_mark_age_ms
        if limit is None:
            return None
        if account.mark_age_ms is None:
            return "health:mark-age-unknown"
        if account.mark_age_ms > limit:
            return "health:stale-mark"
        return None

    def _check_stops(self, netliq_adj: float, day_start: float, today: str,
                     now: datetime) -> tuple[str | None, bool]:
        """Latch/check operating + emergency stops. Returns (reason, latched-now).

        Emergency dominates and persists across day rolls; the operating
        stop is per-day. Both persist immediately (the emergency persist
        requirement is structural — every latch saves state).
        """
        cfg = self.config
        if self._state.emergency_latched:
            return "halt:emergency", False
        if netliq_adj <= day_start * (1 - cfg.emergency_stop_pct):
            self._state.emergency_latched = True
            self._state.emergency_since_utc = now.isoformat()
            save_state(self.state_path, self._state)
            return "halt:emergency", True
        if today in self._state.operating_stop_days:
            return "halt:operating-stop", False
        if netliq_adj <= day_start * (1 - cfg.operating_stop_pct):
            self._state.operating_stop_days[today] = "operating-stop"
            save_state(self.state_path, self._state)
            return "halt:operating-stop", True
        return None, False

    def emergency_active(self) -> bool:
        """True while the emergency latch stands (any day)."""
        return self._state.emergency_latched

    def operating_stopped(self, today: str | None = None) -> bool:
        """True while today's operating stop stands."""
        day = today or accounting_date(self._now_utc()).isoformat()
        return day in self._state.operating_stop_days

    def pending_stop_actions(
            self, account: AccountSnapshot | None = None) -> tuple[str, ...]:
        """Stop ACTION demands for the session to execute (W3-24H §4).

        Entries are already blocked by the matching halt reasons; this is
        the ACTION side: cancel pending orders and reduce/close exposure
        while any exposure remains, plus the emergency operator alert.
        Derived from live exposure every call — the list empties itself
        as the session flattens (no handshake to desync).
        """
        today = accounting_date(self._now_utc()).isoformat()
        emergency = self._state.emergency_latched
        operating = today in self._state.operating_stop_days
        if not (emergency or operating):
            return ()
        exposure = (self._state.open_position or self._state.reservations
                    or self._state.unresolved or self._booked_nonzero_global()
                    or (account is not None and account.open_position))
        actions: list[str] = []
        if emergency:
            actions.append("alert_operator")
        if exposure:
            actions.extend(("cancel_pending_orders", "reduce_exposure"))
        return tuple(actions)

    def recover_from_emergency(self, account: AccountSnapshot) -> bool:
        """Clear the emergency latch only on reconciled flat (W3-24H §4).

        True when no latch stands or when the book proves flat (no live
        reservations, no unresolved, booked zero, no open position on
        either side). False refuses — time alone never recovers.
        """
        if not self._state.emergency_latched:
            return True
        if (self._state.reservations or self._state.unresolved
                or self._booked_nonzero_global()
                or self._state.open_position or account.open_position):
            return False
        self._state.emergency_latched = False
        self._state.emergency_since_utc = None
        save_state(self.state_path, self._state)
        return True

    def _roll_day_if_needed(self, now: datetime, today: str) -> bool:
        if self._state.current_day == today:
            return False
        self._state.current_day = today
        self._state.needs_reconciliation = True
        save_state(self.state_path, self._state)
        return True

    def _adjust_day(self, value: float, flows_cumulative: float) -> float:
        baseline = self._state.flow_baseline_day
        if baseline is None:
            baseline = 0.0
        return value - (flows_cumulative - baseline)

    def _adjust_inception(self, value: float, flows_cumulative: float) -> float:
        baseline = self._state.flow_baseline_inception
        if baseline is None:
            baseline = 0.0
        return value - (flows_cumulative - baseline)

    def _update_profit_protection(self, account: AccountSnapshot) -> bool:
        """Ratchet the upward-only floor; True when adjusted marked breaches it."""
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
        marked_adj = self._adjust_inception(account.marked_equity, account.flows_cumulative)
        return self._state.profit_floor is not None and marked_adj <= self._state.profit_floor

    def _check_filters(self, intent, now: datetime) -> Rejected | None:
        filters = self.config.instrument_filters
        if self.config.run_mode:
            if not filters:
                return Rejected("filters:required-in-run-mode")
            filt = filters.get(intent.instrument)
            if filt is None:
                return Rejected("filters:unknown-instrument")
            if not filt.complete():
                return Rejected("filters:incomplete")
        elif not filters:
            return None
        elif intent.instrument not in filters:
            return Rejected("filters:unknown-instrument")
        asof = self.config.filters_asof_utc
        if asof is None or (now - asof).total_seconds() > self.config.filters_max_age_s:
            return Rejected("filters:stale-metadata")
        return None

    def _settle_expired(self, now: datetime) -> bool:
        """Move expired reservations to unresolved (never silently purged)."""
        expired = [rid for rid, r in self._state.reservations.items() if r.expired(now)]
        for rid in expired:
            self._move_to_unresolved(rid, now)
        return bool(expired)

    def _move_to_unresolved(self, reservation_id: str, now: datetime) -> None:
        reservation = self._state.reservations.pop(reservation_id, None)
        if reservation is None:
            return
        self._state.unresolved[reservation_id] = {
            "reservation": reservation.to_dict(),
            "unresolved_since_utc": now.isoformat(),
        }

    def _booked_net(self, reservation_id: str) -> float:
        entry = self._state.booked.get(reservation_id)
        if entry is None:
            return 0.0
        net = entry["net_qty"]
        return 0.0 if abs(net) <= BOOKED_ZERO_EPS else net

    def _booked_nonzero_global(self) -> bool:
        return any(
            abs(entry["net_qty"]) > BOOKED_ZERO_EPS
            for entry in self._state.booked.values()
        )
