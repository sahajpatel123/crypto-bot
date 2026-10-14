"""Autonomous session: lifecycle, replay loop, exits, recovery (manager-owned).

Replay and paper share the strategy/selector/exit/risk path; they differ
only in the event source (capture file vs live bridge) and the clock (event
time vs wall time). The engine is injected (reference for replay/tests,
Nautilus for paper via E-007).
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from cryptobot.accounting.day import accounting_date
from cryptobot.accounting.ledger import Ledger
from cryptobot.coordination.exits import decode_exit_rule
from cryptobot.coordination.selector import (Candidate, Selector,
                                             SelectorConfig)
from cryptobot.market_data.bars import (BarAggregator, BarMissing,
                                        to_s1_bar)
from cryptobot.market_data.bridge import load_snapshots
from cryptobot.market_data.replayer import assert_input_class
from cryptobot.market_data.views import DepthStore, book_flow_for
from cryptobot.risk.policy import RiskPolicy
from cryptobot.risk.rounding import ceil_to_tick, floor_to_step, floor_to_tick
from cryptobot.risk.types import AccountSnapshot, Approved, RiskConfig

from .config import AppConfig
from .engine import EngineEvent, EngineOrder
from .producer import TIMEOUT, AsyncCall, BoundedProducer, deadline_remaining_s
from .reference import ReferenceEngine
from .store import RunStore

__all__ = ["Session", "ReplayClock", "WallClock", "STRATEGY_ARMS"]

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class _SessionEngineHandler:
    """bind_sink target routing every adapter emission into the Session.

    Contract v1 §2/§3 (W1): push-style EngineEvents (__call__) AND the
    legacy risk-sink call (note_fill_delta, used by pre-migration
    adapters during continuous integration) both land in the ONE
    idempotent Session booking path. The legacy call carries no client
    id, so its delta is staged for the matching poll event (which
    carries the client id); deltas with no matching event flush at
    drain end with an adopted marker. Same execution_id on both paths
    books exactly once.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def __call__(self, event: EngineEvent) -> None:
        return self._session._apply_engine_event(event)

    def note_fill_delta(self, reservation_id: str, exec_id: str,
                        symbol: str, venue_side: str, qty: float,
                        price: float, fee: float, ts_utc: str) -> None:
        self._session._stage_sink_delta(
            reservation_id, exec_id, symbol, venue_side, qty, price,
            fee, ts_utc)

def _map_b4_views(book: Any, flow: Any, reason: str) -> tuple[Any, Any, list[str]]:
    """Map E-008 views onto MarketView depth/flow (S5 card B4 contract).

    Present views map field-for-field; absent views stay None with the
    precise book:/flow: reason verbatim. Stale books and unmeasured tops
    count as absent. Modeled BBO never enters here (DepthStore ignores
    bookTicker), so S5 can never mistake an estimate for an observation.
    """
    from cryptobot.strategies.runtime import DepthView, FlowView
    tokens = [t for t in reason.split(";") if t]
    depth_reason = next(
        (t for t in tokens if t.startswith(("book:", "depth:"))), "")
    flow_reason = next((t for t in tokens if t.startswith("flow:")), "")
    depth = None
    if book is not None:
        if book.quality != "clean":
            depth_reason = "book:stale-book"
        elif book.imbalance_top1 is None:
            depth_reason = "book:empty-book"
        else:
            bid, ask = book.bids[0], book.asks[0]
            depth = DepthView(
                best_bid=bid[0], best_ask=ask[0], bid_qty=bid[1],
                ask_qty=ask[1], spread_bps=book.spread_bps or 0.0,
                bid_notional=sum(p * q for p, q in book.bids),
                ask_notional=sum(p * q for p, q in book.asks),
                levels=book.levels, imbalance=book.imbalance_top1,
                ts_utc=datetime.fromtimestamp(book.ts_ms / 1000,
                                              tz=timezone.utc))
            depth_reason = ""
    flow_view = None
    if flow is not None:
        flow_view = FlowView(
            buy_notional=flow.buy_notional,
            sell_notional=flow.sell_notional, buy_count=flow.buy_count,
            sell_count=flow.sell_count, vwap=flow.vwap or 0.0,
            trade_count=flow.buy_count + flow.sell_count,
            window_start_utc=datetime.fromtimestamp(
                flow.window_start_ms / 1000, tz=timezone.utc),
            window_end_utc=datetime.fromtimestamp(
                flow.window_end_ms / 1000, tz=timezone.utc))
        flow_reason = ""
    return depth, flow_view, [r for r in (depth_reason, flow_reason) if r]


STRATEGY_ARMS = {
    "S1": ("S1", ("S1", "S1-V", "S1-F")),
    "S2": ("S2", ("S2", "S2-V", "S2-F")),
    "S3": ("S3", ("S3", "S3-R", "S3-C")),
    "S4": ("S4", ("S4", "S4-S")),
    "X1": ("X1", ("X1", "X1-S", "X1-T", "X1-F")),
}


def _pct(sorted_samples: list[float], pct: float) -> float | None:
    if not sorted_samples:
        return None
    rank = math.ceil(pct / 100 * len(sorted_samples))
    return sorted_samples[max(0, min(rank - 1, len(sorted_samples) - 1))]


def _summarize(samples: list[float]) -> dict[str, Any]:
    ordered = sorted(samples)
    return {"n": len(ordered), "p50_ms": _pct(ordered, 50),
            "p95_ms": _pct(ordered, 95), "p99_ms": _pct(ordered, 99),
            "max_ms": max(ordered) if ordered else None}


class ReplayClock:
    """Settable causal clock for replay (event-time driven)."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or _EPOCH

    def set_ms(self, ts_ms: int) -> None:
        moment = _EPOCH + timedelta(milliseconds=ts_ms)
        if moment > self._now:
            self._now = moment

    def now(self) -> datetime:
        return self._now


class _SymbolFeed:
    def __init__(self, symbol: str, warmup: int) -> None:
        self.agg = BarAggregator(symbol)
        self.bars: deque = deque(maxlen=warmup + 5)
        # W3-P1: parallel per-window gap cause (None for real bars,
        # "id-jump"/"quiet-window" for BarMissing) so strategy-visible
        # quality separates causes. Same maxlen: evicts with bars.
        self.missing_cause: deque = deque(maxlen=warmup + 5)
        self.mark: float | None = None
        self.mark_ts: datetime | None = None
        self.missing = 0

    def ready(self, warmup: int) -> bool:
        return len(self.bars) >= warmup


class WallClock:
    """Wall-time clock for live paper sessions."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class Session:
    def __init__(self, config: AppConfig, store: RunStore, workdir: str | Path,
                 run_id: str, *, pid: int | None = None,
                 clock: Any | None = None, engine: Any | None = None) -> None:
        self.config = config
        self.store = store
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.clock = clock or ReplayClock()
        self.now_utc: Callable[[], datetime] = self.clock.now
        self.ledger = Ledger(config.paper_capital_usdt)
        self.policy = RiskPolicy(RiskConfig(**config.to_risk_kwargs()),
                                 state_path=self.workdir / "risk_state.json",
                                 now_utc=self.now_utc)
        self.policy.bind_ledger(self.ledger)
        self.selector = Selector(SelectorConfig(
            min_reward_multiple=config.min_reward_multiple,
            cooldown_s=config.cooldown_s,
            allow_legacy_exit_rules=config.allow_legacy_exit_rules))
        if engine is not None:
            self.engine = engine
        else:
            if config.mode == "paper":
                raise ValueError("paper mode requires an injected Nautilus "
                                 "engine (reference engine is replay-only)")
            self.engine = ReferenceEngine(
                log_path=self.workdir / "order_manager.jsonl",
                outcome_sink=None, taker_bps=config.taker_bps,
                now_utc=self.now_utc, submit_delay_ms=config.submit_delay_ms)
        self._feeds: dict[str, _SymbolFeed] = {}
        self._depth_store = DepthStore()
        self._saw_exchange_marks = False
        self._resyncs_seen: dict[str, int] = {}
        self._stop_alerted = False
        self.event_gate: Any | None = None
        self.protection: Any | None = None
        self._freshness: Any | None = None
        self._exchange_errors = 0
        if config.events_enabled:
            self._build_event_gate()
        self._position: dict[str, Any] | None = None
        self._day: str | None = None
        self._reject_counts: dict[str, int] = {}
        self._admitted = 0
        self._eval_ms: list[float] = []
        self._decide_ms: list[float] = []
        self._age_ms: list[float] = []
        self._dispatch_ms: list[float] = []
        self._submit_ts: dict[str, datetime] = {}
        self._events_seen = 0
        self._flatten_pending = False
        self._orphan_close_ids: list[str] = []  # pos-less flatten closes.
        # Contract v1 §3 (W1): idempotent booking state. Applied
        # execution ids (durable in execution_events; rebuilt on
        # resume), max-applied cumulative qty per order (never rolls
        # back), staged legacy sink deltas awaiting their poll event.
        self._applied_exec: set[str] = set()
        self._order_cum: dict[str, float] = {}
        self._staged_deltas: dict[str, dict[str, Any]] = {}
        self._dup_events = 0
        self._stale_status = 0
        # Contract v1 §2 (W1): last-applied order-status version per
        # order + cached status. Version 0 reads bypass the cache (no
        # observed transition yet, or a legacy double: nothing to roll
        # back from, so always current).
        self._status_version: dict[str, int] = {}
        self._status_cache: dict[str, Any] = {}
        # Fail-closed booking blocks (surfaced via _admission_hold).
        self._booking_blocked: str | None = None
        # Reentrancy guards (contract push delivery): an adapter may
        # emit synchronously inside a Session-initiated call (e.g. a
        # sizing lookup adopting a fill inside attach_protection).
        # Nested order-issuing passes return early; the outer frame
        # always re-reads fresh truth before acting.
        self._in_ensure = False
        self._in_flatten = False
        # Session-owned exit-only reasons (R3 halt independence).
        self._exit_only_reasons: set[str] = set()
        self._user_stream_attachment: Any | None = None
        self._known_reservations: set[str] = set()
        self._cmd_seq = 0
        # Bind the ONE booking handler (contract v1 §1/§2). Adapters
        # without bind_sink stay drain-driven into the same handler.
        self._engine_handler = _SessionEngineHandler(self)
        bind_sink = getattr(self.engine, "bind_sink", None)
        if callable(bind_sink):
            bind_sink(self._engine_handler)
        # W3-P2: native replay milestones (export_warmup probes, made
        # native): first-event/bar/ready/eval/intent/gate per symbol.
        self._milestones: dict[str, Any] = {
            "first_event": None, "first_bar": {}, "ready": {},
            "first_eval": {}, "first_intent": {}, "gate_ready": {},
            "capture_end": None}
        self._ms_t0_ms: int | None = None
        self._warmed = False
        self._last_seq = 0
        self._last_equity_sample: datetime | None = None
        self._equity_dirty = True
        self._run_start_utc: datetime | None = None
        self._crash_after: int | None = None
        self._stop_flag: str | None = None
        self._pid = pid
        # W3-30MIN §4 runtime controls.
        self._reconciled = True  # _resume_live clears until recovery lands.
        self._tick_ms: deque[float] = deque(maxlen=10000)
        self._prime_call: Any | None = None  # in-flight async resync prime.
        self._tick_ctx: dict[str, Any] | None = None  # control_tick pacing.
        self._filter_call: Any | None = None  # in-flight async filter fetch.
        self._dropped_feed = 0  # producer overflow count (loud).

    # -- lifecycle ---------------------------------------------------------
    def _set_state(self, state: str, reason: str = "") -> None:
        try:
            row = self.store.get_run(self.run_id) or {}
            old = row.get("state", "")
        except Exception:
            old = ""
            row = {}
        if not row:
            # Pre-run supervision (control_tick before create_run):
            # register the run row so the transition is recorded,
            # not lost. A concurrent create falls through to set_state.
            try:
                self.store.create_run(self.run_id, self.config.mode,
                                      self.config.fingerprint,
                                      str(self.workdir), self._pid)
            except Exception:
                pass
        self.store.set_state(self.run_id, state, reason)
        self._append_run_file("risk.jsonl", {
            "ts_utc": self.now_utc().isoformat(),
            "wall_ts_utc": datetime.now(timezone.utc).isoformat(),
            "kind": "run-state",
            "from_state": old, "to_state": state, "reason": reason})

    # -- run-mode filter arming (paper only) -----------------------------------
    def arm_run_mode(self, symbols: list[str], *, http_get: Any = None) -> None:
        """Fetch live venue filters and arm strict run mode. Fail-closed."""
        from .filters import build_run_filters
        filters, asof = build_run_filters(
            symbols,
            max_notional_cap_usdt=self.config.max_notional_cap_usdt,
            http_get=http_get)
        self._apply_run_filters(filters, asof)

    def arm_replay_filters(self, filters: dict[str, dict[str, Any]],
                         origin: str, *,
                         asof_utc: datetime | None = None) -> None:
        """Arm sizing filters for replay from a manifest/frozen profile.

        Offline equivalent of arm_run_mode: risk sizes on the venue
        step/min instead of the 1e-8 fallback, so dust is rejected
        honestly (skip:min-notional) instead of crashing the submit (F3).
        Shapes accepted per symbol: manifest-frozen
        {tick_size, step_size, min_qty, min_notional, ...} or the frozen
        fallback {tick_size, step_size, min_notional, ...}.
        ``asof_utc`` is the honest filters-known-as-of time (manifest
        build); it defaults to wall-now when unknown (synth).
        """
        from dataclasses import replace

        from cryptobot.risk.types import InstrumentFilter
        built: dict[str, InstrumentFilter] = {}
        for symbol, filt in filters.items():
            declared = float(filt.get("min_notional", 0.0))
            built[symbol] = InstrumentFilter(
                # Unknown venue minimum (0.0) keeps the operator default
                # floor; only a declared venue fact overrides it.
                min_notional_usdt=declared or self.config.min_notional_usdt,
                qty_step=float(filt.get("step_size", 1e-8)),
                min_qty=float(filt.get("min_qty", 0.0)),
                tick_size=filt.get("tick_size"),
            )
        merged = dict(self.policy.config.instrument_filters)
        merged.update(built)
        asof = asof_utc or datetime.now(timezone.utc)
        self.policy.config = replace(
            self.policy.config, instrument_filters=merged,
            filters_asof_utc=asof)
        self.store.checkpoint(self.run_id, "filters-armed",
                              {"origin": origin, "asof_utc": asof.isoformat(),
                               "symbols": sorted(built)})

    def _ensure_symbol_filters(self, symbol: str) -> bool:
        """Arm filters for a newly seen paper symbol. False when blocked."""
        if self.config.mode != "paper":
            return True
        if symbol in self.policy.config.instrument_filters:
            return True
        from .filters import FilterError
        try:
            self.arm_run_mode([symbol])
        except (FilterError, ValueError, OSError) as exc:
            self._halt_entries(f"filters:{exc}")
            self._set_state("halted", f"filters:unavailable:{symbol}")
            self.store.checkpoint(self.run_id, "filters-blocked",
                                  {"symbol": symbol, "reason": str(exc)})
            return False
        return True

    def _symbol_executable_age_ms(self, symbol: str) -> float | None:
        """Age of a symbol's OWN executable observation (CORR-DATA).

        None when the symbol has no usable observation (fail closed
        downstream); never substitutes another symbol's timestamp.
        """
        feed = self._feeds.get(symbol)
        ts = feed.mark_ts if feed is not None and feed.mark else None
        now = self.now_utc()
        if not isinstance(ts, datetime) or ts.tzinfo is None:
            return None
        if now.tzinfo is None:
            return None
        return max(0.0, (now - ts).total_seconds() * 1000.0)

    def _snapshot_account(self, symbol: str | None = None) -> AccountSnapshot:
        mark = self._reference_mark()
        close_bps = self.config.taker_bps
        # V-008 admission inputs: available margin from the engine account
        # (None skips the margin gate), a round-trip fee buffer in margin
        # space, and the one-budget in-flight exposure figure.
        available: float | None = None
        account_margin = getattr(self.engine, "account_margin", None)
        if callable(account_margin):
            try:
                margins = account_margin()
            except (ValueError, KeyError, AttributeError):
                margins = None
            if margins is not None:
                available = float(margins[0])
        fee_buffer = 0.0
        if available is not None and available > 0:
            fee_buffer = 2 * available * close_bps / 1e4
        # W3-24H P3: mark age rides the snapshot; the policy fails closed
        # when max_mark_age_ms is configured (None = unrecorded here).
        # CORR-DATA: admission snapshots carry the CANDIDATE symbol's
        # own executable age; books/health snapshots keep valuation age.
        if symbol is not None:
            mark_age = self._symbol_executable_age_ms(symbol)
        else:
            _m, _s, _ts = self._reference_mark_full()
            mark_age = None
            if _ts is not None:
                mark_age = max(
                    0.0, (self.now_utc() - _ts).total_seconds() * 1000.0)
        return AccountSnapshot(
            reconciled_equity=self.ledger.marked_equity(mark),
            marked_equity=self.ledger.marked_equity(mark),
            net_liquidation=self.ledger.net_liquidation(mark, close_bps),
            net_realised_global=self.ledger.net_realised(),
            open_position=self.ledger.has_position() or self._position is not None,
            flows_cumulative=self.ledger.total_flows(),
            available_margin_usdt=available,
            fee_buffer_usdt=fee_buffer,
            inflight_exposure_usdt=self._inflight_exposure_usdt(mark),
            mark_age_ms=mark_age)

    def _inflight_exposure_usdt(self, mark: float) -> float:
        """One budget across pending/open/unresolved exposure (V-008).

        Pending entry-role unfilled qty x mark, plus |ledger| x mark, plus
        the excess of booked-over-ledger x mark (never double-counted).
        Reduce-only legs excluded; 0 when unpriced.
        """
        if mark <= 0:
            return 0.0
        pending = 0.0
        try:
            statuses = self.engine.open_orders()
        except (ValueError, KeyError, AttributeError):
            statuses = []
        for status in statuses:
            role = getattr(status, "role", "entry")
            if role != "entry":
                continue
            state = getattr(status, "state", "open")
            if state in ("filled", "rejected", "cancelled", "expired"):
                continue
            qty = getattr(status, "qty", 0.0) or 0.0
            filled = getattr(status, "filled_qty", 0.0) or 0.0
            if qty > filled:
                pending += (qty - filled) * mark
        ledger_qty = abs(self.ledger.position_qty())
        booked = abs(self.policy.booked_total_qty())
        excess = max(0.0, booked - ledger_qty) * mark
        return pending + ledger_qty * mark + excess

    def _sample_equity(self, source: str, *, force: bool = False) -> None:
        """Append an equity curve point (periodic + on fills + on day roll)."""
        now = self.now_utc()
        if not force and not self._equity_dirty:
            if self._last_equity_sample is not None and (
                    now - self._last_equity_sample).total_seconds() < \
                    self.config.equity_sample_s:
                return
        mark, mark_source, mark_ts = self._reference_mark_full()
        qty = self.ledger.position_qty()
        basis = self.ledger.entry_basis()
        open_pnl = qty * (mark - basis) if basis is not None and mark > 0 else 0.0
        cash = self.ledger.marked_equity(mark) - qty * mark if mark > 0 else \
            self.ledger.marked_equity(0.0)
        mark_age_ms: float | None = None
        if mark_ts is not None:
            mark_age_ms = max(
                0.0, (now - mark_ts).total_seconds() * 1000.0)
        self._append_run_file("equity.jsonl", {
            "ts_utc": now.isoformat(),
            "marked_equity": self.ledger.marked_equity(mark),
            "cash": cash, "position_qty": qty,
            "position_symbol": self._position_symbol() or "",
            "open_pnl": open_pnl, "source": source,
            "mark_source": mark_source, "mark_age_ms": mark_age_ms})
        self._last_equity_sample = now
        self._equity_dirty = False

    def _reference_mark_full(self) -> tuple[float, str, datetime | None]:
        """Valuation mark with provenance (V-008 mark preference).

        Exchange mark first (engine observation time), feed mark second,
        0.0/"none" when neither exists. Trade-only replays are unaffected
        (feed fallback, same values); markPrice replays move valuation to
        the exchange mark.
        """
        symbols: list[str] = []
        if self._position is not None:
            symbols.append(self._position["instrument"])
        symbols.extend(s for s in self._feeds if s not in symbols)
        # Engine marks count as "exchange" only when markPrice records
        # actually flowed; otherwise they are our own feed echo.
        use_exchange = self._saw_exchange_marks and hasattr(
            self.engine, "note_event")
        valuation_mark = getattr(self.engine, "valuation_mark", None)
        valuation_ts = getattr(self.engine, "valuation_mark_ts", None)
        for symbol in symbols:
            if use_exchange and callable(valuation_mark):
                try:
                    mark = valuation_mark(symbol)
                except (ValueError, KeyError, AttributeError):
                    mark = None
                if mark:
                    ts = valuation_ts(symbol) if callable(valuation_ts) \
                        else None
                    return float(mark), "exchange", ts
        if self._position is not None:
            feed = self._feeds.get(self._position["instrument"])
            if feed is not None and feed.mark:
                return feed.mark, "feed", feed.mark_ts
        for feed in self._feeds.values():
            if feed.mark:
                return feed.mark, "feed", feed.mark_ts
        return 0.0, "none", None

    def _reference_mark(self) -> float:
        return self._reference_mark_full()[0]

    # -- strategy evaluation -----------------------------------------------
    def _strategy_adapters(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Runtime adapters (base arms, incl. S5) + modules (variant arms)."""
        import importlib
        from cryptobot.strategies.runtime import get_adapter
        adapters: dict[str, Any] = {}
        modules: dict[str, Any] = {}
        allow = self.config.strategies_arms_allowlist
        allowed = set(allow) if allow is not None else None
        for name in self.config.strategies_enabled:
            if allowed is None or name in allowed:
                try:
                    adapters[name] = get_adapter(name)
                except KeyError:
                    continue
            if name == "S5":
                continue  # S5 has no evaluate_bar variant path.
            if allowed is not None and not any(
                    a in allowed for a in STRATEGY_ARMS[name][1]
                    if a != name):
                continue  # no allowlisted variant in this family.
            try:
                modules[name] = importlib.import_module(
                    f"cryptobot.strategies.{name.lower()}")
            except ImportError:
                continue
        return adapters, modules

    def _evaluate_symbol(self, symbol: str, adapters: dict[str, Any],
                         modules: dict[str, Any]) -> list[Candidate]:
        from cryptobot.coordination import DataQuality
        from cryptobot.strategies.runtime import MarketView
        feed = self._feeds[symbol]
        bars = list(feed.bars)
        t = len(bars) - 1
        out: list[Candidate] = []
        present = [b for b in bars if b is not None]
        if present:
            # Strategies-side bars carry the window start; evidence is
            # the newest bar's close.
            evidence_ms = int(present[-1].ts_utc.timestamp() * 1000) + 1000
        else:
            evidence_ms = int(self.now_utc().timestamp() * 1000)
        book, flow, reason = book_flow_for(
            symbol, evidence_ms, self._depth_store)
        depth, flow_view, reasons = _map_b4_views(book, flow, reason)
        missing = len(bars) - len(present)
        quality = (DataQuality.CLEAN if missing == 0
                   else DataQuality.DEGRADED)
        if missing:
            reasons = list(reasons) + [
                f"gap:missing-windows:{missing}"]
            # W3-P1: separate id-jump gaps from quiet windows so strategy
            # rejects attribute by cause (cause deque evicts with bars in
            # production; tests building bars directly just undercount).
            causes = [c for c in getattr(feed, "missing_cause", [])
                      if c is not None]
            jumps = sum(1 for c in causes if c == "id-jump")
            quiets = sum(1 for c in causes if c == "quiet-window")
            if jumps:
                reasons = list(reasons) + [f"gap:id-jump:{jumps}"]
            if quiets:
                reasons = list(reasons) + [f"gap:quiet-window:{quiets}"]
        # Dual-symbol reference leg (X1.md §4): when an enabled
        # family declares DUAL_REF_SYMBOL and the leader feed exists,
        # attach its aligned slots + the frozen beta for EVERY
        # evaluated symbol; the evaluator's symbol gate attributes
        # non-laggard evaluations (other families ignore the fields).
        ref_bars: tuple | None = None
        ref_instrument: str | None = None
        ref_beta: float | None = None
        for _module in modules.values():
            _ref_sym = getattr(_module, "DUAL_REF_SYMBOL", None)
            if _ref_sym is None:
                continue
            _ref_feed = self._feeds.get(_ref_sym)
            if _ref_feed is None:
                continue
            ref_bars = tuple(_ref_feed.bars)
            ref_instrument = _ref_sym
            ref_beta = self.config.x1_beta
            break
        view = MarketView(
            instrument=symbol, bars=tuple(bars), now_utc=self.now_utc(),
            depth=depth, flow=flow_view, quality=quality,
            quality_reason=";".join(reasons),
            ref_bars=ref_bars, ref_instrument=ref_instrument,
            ref_beta=ref_beta)
        for name, adapter in adapters.items():
            start = time.perf_counter()
            try:
                outcome = adapter.evaluate(view)
            except Exception as exc:  # strategy must never kill the loop.
                out.append(Candidate(f"{name}:LONG", None,
                                     f"strategy:error:{type(exc).__name__}"))
                out.append(Candidate(f"{name}:SHORT", None,
                                     f"strategy:error:{type(exc).__name__}"))
                continue
            finally:
                self._eval_ms.append((time.perf_counter() - start) * 1000)
            key = f"{name}/{symbol}"
            if key not in self._milestones["first_eval"]:
                iso, rel = self._ms_stamp()
                self._milestones["first_eval"][key] = {
                    "ts_utc": iso, "rel_ms": rel,
                    "reject": outcome.reject_reason,
                    "fired": outcome.intent is not None}
            if outcome.intent is not None:
                out.append(Candidate(outcome.intent.strategy, outcome.intent))
                if key not in self._milestones["first_intent"]:
                    iso, rel = self._ms_stamp()
                    self._milestones["first_intent"][key] = {
                        "ts_utc": iso, "rel_ms": rel}
            else:
                out.append(Candidate(adapter.strategy_id, None,
                                     f"strategy:{outcome.reject_reason}"))
        if self.config.strategies_arms == "all":
            allow = self.config.strategies_arms_allowlist
            for name, module in modules.items():
                base, all_arms = STRATEGY_ARMS[name]
                for arm in all_arms:
                    if arm == base:
                        continue  # base covered by the adapter above.
                    if allow is not None and arm not in allow:
                        continue  # W4-CORR: allowlisted out.
                    start = time.perf_counter()
                    try:
                        if getattr(module, "DUAL_REF_SYMBOL", None) is not None:
                            decisions = module.evaluate_bar(
                                bars, t, arm, symbol,
                                ref_bars=list(ref_bars)
                                if ref_bars is not None else None,
                                beta=ref_beta)
                        else:
                            decisions = module.evaluate_bar(bars, t, arm, symbol)
                    except Exception as exc:
                        out.append(Candidate(
                            f"{arm}:LONG", None,
                            f"strategy:error:{type(exc).__name__}"))
                        out.append(Candidate(
                            f"{arm}:SHORT", None,
                            f"strategy:error:{type(exc).__name__}"))
                        continue
                    finally:
                        self._eval_ms.append((time.perf_counter() - start) * 1000)
                    for decision in decisions:
                        if decision.intent is not None:
                            out.append(Candidate(decision.intent.strategy,
                                                 decision.intent))
                        else:
                            ev = decision.evaluation
                            out.append(Candidate(
                                f"{ev.arm}:{ev.side.value}", None,
                                f"strategy:no-fire:{ev.reason}"))
        return out

    # -- exit derivation ----------------------------------------------------
    def _derive_exits(self, intent: Any) -> tuple[float, float | None, datetime, bool]:
        try:
            policy = decode_exit_rule(intent.exit_rule)
            return policy.stop_price, policy.target_price, policy.time_exit_utc, False
        except ValueError:
            if not self.config.allow_legacy_exit_rules:
                raise
            return (intent.invalidation_price, None,
                    self.now_utc() + timedelta(
                        seconds=intent.holding_limit_s), True)

    # -- position management --------------------------------------------------
    @staticmethod
    def _split_ref(ref: str) -> tuple[str, str, str]:
        """evidence_ref -> (strategy, instrument, side); bare ids pass through."""
        parts = ref.split(":")
        if len(parts) >= 4:
            return parts[0], parts[2], parts[3]
        return ref, "", ""

    def _age_verdict(self, ts: Any, bound_s: float, kind: str,
                     now: datetime) -> str | None:
        """One observation age check. Never raises on malformed input."""
        if not isinstance(ts, datetime) or ts.tzinfo is None:
            return f"gate:{kind}-age-unknown"
        if now.tzinfo is None:
            return f"gate:{kind}-age-unknown"
        age = (now - ts).total_seconds()
        if age < -self.config.max_clock_skew_s:
            return f"gate:clock-future-{kind}"
        if age > bound_s:
            return f"gate:stale-{kind}"
        return None

    def _exchange_mark_ts_for(self, symbol: str) -> tuple[bool, Any]:
        """(required, ts) for the candidate symbol's exchange mark.

        Required exactly when valuation would use the engine mark for
        this symbol (same conditions as _reference_mark_full): exchange
        marks flowed this run, the engine exposes a mark, and it has
        one for this symbol. Otherwise valuation falls back to the
        feed and no mark observation is required.
        """
        use_exchange = self._saw_exchange_marks and hasattr(
            self.engine, "note_event")
        valuation_mark = getattr(self.engine, "valuation_mark", None)
        if not (use_exchange and callable(valuation_mark)):
            return False, None
        try:
            mark = valuation_mark(symbol)
        except (ValueError, KeyError, AttributeError):
            return False, None
        if not mark:
            return False, None
        valuation_ts = getattr(self.engine, "valuation_mark_ts", None)
        if not callable(valuation_ts):
            return True, None
        try:
            return True, valuation_ts(symbol)
        except (ValueError, KeyError, AttributeError):
            return True, None

    def _quote_age_gate(self, symbol: str) -> str | None:
        """Symbol-scoped freshness gate for new entries (CORR-DATA).

        The candidate symbol's OWN executable observation (last
        BBO/trade exchange time) must be present, sane, and within
        quote_max_age_s; when exchange valuation marks are the
        valuation source for this symbol, the mark observation must
        additionally be within max_mark_age_ms. No cross-symbol
        substitution: another symbol's freshness never admits this one.
        Returns a rejection reason, or None when admission may proceed.
        """
        feed = self._feeds.get(symbol)
        now = self.now_utc()
        exec_ts = feed.mark_ts if feed is not None and feed.mark else None
        verdict = self._age_verdict(exec_ts, self.config.quote_max_age_s,
                                    "quote", now)
        if verdict is not None:
            return verdict
        required, mark_ts = self._exchange_mark_ts_for(symbol)
        if not required:
            return None
        limit_ms = self.config.risk.max_mark_age_ms
        if limit_ms is None:
            # Unconfigured bound: mark age unenforced, mirroring the
            # risk layer's opt-in (policy._check_mark_age skips too).
            return None
        return self._age_verdict(mark_ts, limit_ms / 1000.0, "mark", now)

    def _admission_hold(self) -> str | None:
        """Hard admission holds: prod default-off, reconcile, unknowns."""
        if self.config.mode == "prod" and not self.config.allow_live_submission:
            return "config:prod-submission-disabled"
        if not self._reconciled or self._flatten_pending:
            return "reconcile:restart-pending"
        if self._booking_blocked is not None:
            return f"booking:{self._booking_blocked}"
        stream = self._user_stream_attachment
        if stream is not None and stream.halted:
            return "stream:{}".format(",".join(stream.halt_reasons()))
        try:
            pending_cmds = self.store.open_commands(self.run_id)
        except (ValueError, KeyError):
            pending_cmds = []
        if any(c.get("status") == "unknown" for c in pending_cmds):
            return "reconcile:unknown-commands"
        unknown = getattr(self.engine, "unknown_ids", lambda: ())()
        if unknown:
            return "reconcile:unknown-outcomes"
        return None

    def _maybe_admit(self, candidates: list[Candidate], *,
                     symbol: str | None = None) -> None:
        # W2-P1: intent-less (strategy-stage) rejects carry the evaluated
        # symbol when the caller knows it, so rejections attribute.
        hold = self._admission_hold()
        if hold is not None:
            for cand in candidates:
                ref = cand.intent.evidence_ref if cand.intent else cand.strategy_id
                if cand.intent is not None:
                    self._note_reject(hold, cand.intent.strategy,
                                      cand.intent.instrument,
                                      cand.intent.side.value)
                else:
                    strat, _, _ = self._split_ref(cand.strategy_id)
                    self._note_reject(hold, strat, symbol or "")
                self.store.record_intent(
                    self.run_id, ref, cand.strategy_id,
                    cand.intent.instrument if cand.intent else "",
                    cand.intent.side.value if cand.intent else "",
                    "rejected", hold, self.now_utc().isoformat())
            return
        # CORR-DATA: freshness is per-candidate-symbol. Each intent is
        # gated on its OWN symbol's observations; a stale symbol never
        # rides another symbol's freshness (and vice versa). Intent-less
        # no-fire signals carry no entry and flow to selection as before.
        passing: list[Candidate] = []
        for cand in candidates:
            if cand.intent is None:
                passing.append(cand)
                continue
            gate = self._quote_age_gate(cand.intent.instrument)
            if gate is not None:
                self._note_reject(gate, cand.intent.strategy,
                                  cand.intent.instrument,
                                  cand.intent.side.value)
                self.store.record_intent(
                    self.run_id, cand.intent.evidence_ref,
                    cand.strategy_id, cand.intent.instrument,
                    cand.intent.side.value, "rejected", gate,
                    self.now_utc().isoformat())
            else:
                passing.append(cand)
        candidates = passing
        if self._position is not None:
            for cand in candidates:
                ref = cand.intent.evidence_ref if cand.intent else cand.strategy_id
                reason = cand.reject_reason if cand.intent is None else "selection:position-busy"
                if cand.intent is not None:
                    self._note_reject(reason, cand.intent.strategy,
                                      cand.intent.instrument,
                                      cand.intent.side.value)
                else:
                    strat, _, _ = self._split_ref(cand.strategy_id)
                    self._note_reject(reason, strat, symbol or "")
                self.store.record_intent(
                    self.run_id, ref, cand.strategy_id,
                    cand.intent.instrument if cand.intent else "",
                    cand.intent.side.value if cand.intent else "",
                    "rejected", reason, self.now_utc().isoformat())
            return
        start = time.perf_counter()
        decision = self.selector.select(candidates, now_utc=self.now_utc(),
                                        position_busy=False)
        self._decide_ms.append((time.perf_counter() - start) * 1000)
        for ref, reason in decision.rejections:
            strat, inst, side = self._split_ref(ref)
            self._note_reject(reason, strat, inst or (symbol or ""), side)
        for cand in candidates:
            if cand.intent is None:
                continue
            admitted = decision.admitted is cand.intent
            self.store.record_intent(
                self.run_id, cand.intent.evidence_ref, cand.intent.strategy,
                cand.intent.instrument, cand.intent.side.value,
                "selected" if admitted else "rejected",
                "selection:admitted" if admitted else next(
                    (r for ref2, r in decision.rejections
                     if ref2 == cand.intent.evidence_ref), "selection:rejected"),
                self.now_utc().isoformat())
        if decision.admitted is None:
            return
        intent = decision.admitted
        # Expired opportunities never reach submit: the selector rejects
        # them first (selection:expired), so anything admitted here is
        # inside its entry window.
        if self.protection is not None:
            reading, baseline = self._protection_reading(intent.instrument)
            verdict = self.protection.check_entry(
                self.now_utc(), reading, baseline)
            if verdict.blocked:
                self._note_reject(verdict.reason, intent.strategy,
                                  intent.instrument, intent.side.value)
                self.store.record_intent(
                    self.run_id, intent.evidence_ref, intent.strategy,
                    intent.instrument, intent.side.value, "rejected",
                    verdict.reason, self.now_utc().isoformat())
                return
        # READY-§5 inv 1: size on the ACTUAL venue step. Policy filters
        # armed via arm_run_mode/arm_replay_filters win; otherwise pull the
        # engine's armed step so approval never sizes on the 1e-8 fallback
        # while the venue floors to its real LOT_SIZE (0.33293226 vs 0.332).
        self._sync_venue_filters(intent.instrument)
        snapshot = self._snapshot_account(symbol=intent.instrument)
        verdict = self.policy.evaluate(intent, snapshot)
        if not isinstance(verdict, Approved):
            self._note_reject(f"risk:{verdict.reason}", intent.strategy,
                              intent.instrument, intent.side.value)
            self._append_run_file("risk.jsonl", {
                "ts_utc": self.now_utc().isoformat(),
                "wall_ts_utc": datetime.now(timezone.utc).isoformat(),
                "kind": "risk-decision",
                "from_state": "", "to_state": "rejected",
                "reason": verdict.reason})
            self.store.record_intent(
                self.run_id, intent.evidence_ref, intent.strategy,
                intent.instrument, intent.side.value, "rejected",
                f"risk:{verdict.reason}", self.now_utc().isoformat())
            if verdict.reason.startswith("halt:"):
                self._halt_entries(verdict.reason)
                self._set_state("halted", verdict.reason)
            return
        # READY-§5 inv 1: snap the approved qty to the venue step BEFORE
        # submitting and recheck risk, margin and minimums after rounding.
        # Approved = risk-budgeted request; executable = submitted; fills =
        # booked. A snap that breaks minimums rejects loudly (hold freed).
        executable = self._snap_qty(intent.instrument, verdict.qty)
        recheck = self._recheck_executable(intent, snapshot, executable,
                                           verdict.reserved_risk)
        if recheck is not None:
            self.policy.release(verdict.reservation_id)
            reason = f"risk:{recheck}"
            self._note_reject(reason, intent.strategy, intent.instrument,
                              intent.side.value)
            self.store.record_intent(
                self.run_id, intent.evidence_ref, intent.strategy,
                intent.instrument, intent.side.value, "rejected",
                reason, self.now_utc().isoformat())
            return
        try:
            stop, target, time_exit, legacy = self._derive_exits(intent)
        except ValueError:
            self._note_reject("selection:exit-undecodable", intent.strategy,
                              intent.instrument, intent.side.value)
            self.store.record_intent(
                self.run_id, intent.evidence_ref, intent.strategy,
                intent.instrument, intent.side.value, "rejected",
                "selection:exit-undecodable", self.now_utc().isoformat())
            return
        side = "BUY" if intent.side.value == "LONG" else "SELL"
        # Directive L76: entries are price-protected marketable IOC, capped
        # at the intent's entry band (side-aware: LONG pays at most the
        # band top, SHORT accepts at least the band floor). The IOC cancels
        # anything the venue cannot fill at-or-better on the next tick —
        # rejected opportunities expire, partial exposure stays bounded,
        # and exits still cross with realistic cost/latency. The reference
        # engine has no protected IOC (non-economic tool): it keeps MARKET.
        cap = self._entry_cap(intent)
        order = EngineOrder(
            instrument=intent.instrument, side=side, qty=executable,
            kind="MARKET", reservation_id=verdict.reservation_id,
            expire_at_utc=intent.entry_expiry_utc)
        submit_protected = getattr(self.engine, "submit_protected", None)
        cmd_id = self._new_command("submit", {
            "role": "entry", "instrument": intent.instrument,
            "side": side, "qty": executable,
            "reservation_id": verdict.reservation_id,
            "evidence_ref": intent.evidence_ref})
        try:
            if submit_protected is None:
                pre_id = self.engine.submit(order)
            else:
                try:
                    pre_id = submit_protected(order, cap)
                except NotImplementedError:
                    pre_id = self.engine.submit(order)
        except (ValueError, PermissionError, OverflowError) as exc:
            # B2/F3: an unsubmittable opportunity (dust below the venue
            # step, full queue, exit-only race) is rejected, never fatal.
            # The risk hold is freed (zero booked: actually freed).
            try:
                self.store.update_command(cmd_id, "failed")
            except (ValueError, KeyError):
                pass
            self.policy.release(verdict.reservation_id)
            reason = f"execution:submit-rejected:{type(exc).__name__}"
            self._note_reject(reason, intent.strategy, intent.instrument,
                              intent.side.value)
            self.store.record_intent(
                self.run_id, intent.evidence_ref, intent.strategy,
                intent.instrument, intent.side.value, "rejected",
                reason, self.now_utc().isoformat())
            return
        self._submit_ts[pre_id] = self.now_utc()
        try:
            self.store.update_command(cmd_id, "submitted",
                                      engine_client_id=pre_id)
        except (ValueError, KeyError):
            pass
        self._known_reservations.add(verdict.reservation_id)
        self._position = {"reservation_id": verdict.reservation_id,
                          "instrument": intent.instrument,
                          "side": intent.side.value,
                          "entry_pre_id": pre_id, "entry_id": None,
                          "legs": [], "stop": stop, "target": target,
                          "time_exit": time_exit, "legacy_exit": legacy,
                          "protected": False, "protect_attempts": 0,
                          "entry_cap": cap,
                          "approved_qty": verdict.qty,
                          "executable_qty": executable,
                          "exposure_noted": False,
                          "executable_noted": False,
                          "close_ids": [],
                          "emergency_latched": False,
                          "strategy": intent.strategy,
                          "admit_snapshot": snapshot,
                          "admit_budget": verdict.reserved_risk,
                          "admit_intent": intent}
        self._admitted += 1
        self._set_state("holding", f"admitted:{intent.evidence_ref}")
        self.store.checkpoint(self.run_id, "admit", {
            "reservation_id": verdict.reservation_id, "qty": verdict.qty,
            "executable_qty": executable,
            "notional": verdict.notional_usdt, "legacy_exit": legacy,
            "entry_cap": cap,
            "entry_band": [intent.entry_low, intent.entry_high]})

    def _entry_cap(self, intent: Any) -> float:
        # Side-aware band cap with side-aware tick rounding: a BUY cap
        # rounds DOWN (never pay above the band top), a SELL floor rounds
        # UP (never accept below the band floor). Unknown tick = raw band.
        raw = (intent.entry_high if intent.side.value == "LONG"
               else intent.entry_low)
        filt = self.policy.config.instrument_filters.get(intent.instrument)
        tick = getattr(filt, "tick_size", None) if filt is not None else None
        if not tick:
            return raw
        if intent.side.value == "LONG":
            return floor_to_tick(raw, float(tick))
        return ceil_to_tick(raw, float(tick))

    def _engine_venue_filters(self, symbol: str) -> dict[str, float] | None:
        """Best-effort read of the engine's armed venue filters (READY-§5).

        The paper engine auto-registers LOT_SIZE/tick/mins from venue data
        while the policy may never have been armed (bench arms the engine
        only), so the Session pulls the true step here to size on it.
        Guarded: anything missing/malformed returns None and the caller
        falls back to policy filters, then to post-submit narrowing.
        """
        raw = getattr(self.engine, "_filters", None)
        if not isinstance(raw, dict):
            return None
        entry = raw.get(symbol.upper())
        if not isinstance(entry, dict):
            return None
        try:
            out = {"tick": float(entry["tick"]), "step": float(entry["step"]),
                   "min_qty": float(entry["min_qty"]),
                   "min_notional": float(entry["min_notional"])}
        except (KeyError, TypeError, ValueError):
            return None
        if not all(math.isfinite(v) for v in out.values()):
            return None
        if out["step"] <= 0:
            return None
        return out

    def _sync_venue_filters(self, symbol: str) -> bool:
        """Ensure policy sizes on the actual venue step (READY-§5 inv 1).

        Armed policy filters (arm_run_mode/arm_replay_filters) always win;
        otherwise the engine's armed step is pulled in. True when the
        policy now holds a symbol record (from either source).
        """
        if symbol in self.policy.config.instrument_filters:
            return True
        eng = self._engine_venue_filters(symbol)
        if eng is None:
            return False
        from dataclasses import replace

        from cryptobot.risk.types import InstrumentFilter
        merged = dict(self.policy.config.instrument_filters)
        merged[symbol] = InstrumentFilter(
            min_notional_usdt=eng["min_notional"]
            or self.config.min_notional_usdt,
            qty_step=eng["step"], min_qty=eng["min_qty"],
            tick_size=eng["tick"] or None)
        asof = self.now_utc()
        self.policy.config = replace(
            self.policy.config, instrument_filters=merged,
            filters_asof_utc=asof)
        self.store.checkpoint(self.run_id, "filters-synced",
                              {"symbol": symbol, "step": eng["step"],
                               "min_qty": eng["min_qty"],
                               "asof_utc": asof.isoformat()})
        return True

    def _snap_qty(self, symbol: str, qty: float) -> float:
        """Floor a risk-approved qty to the known venue step (READY-§5)."""
        filt = self.policy.config.instrument_filters.get(symbol)
        step = filt.qty_step if filt is not None else 1e-8
        return floor_to_step(qty, step)

    def _recheck_executable(self, intent: Any, snapshot: Any,
                            qty: float, budget: float) -> str | None:
        """Recheck risk, margin and minimums after venue rounding (READY-§5).

        Same arithmetic as RiskPolicy.evaluate's cap plus plan_size's
        within_budget/affordable/minimum gates, applied to the ROUNDED
        qty (not the raw approval). Returns a rejection reason or None.
        """
        cfg = self.policy.config
        filt = cfg.instrument_filters.get(intent.instrument)
        min_qty = filt.min_qty if filt is not None else 0.0
        min_notional = (filt.min_notional_usdt if filt is not None
                        else cfg.min_notional_usdt)
        if qty <= 0 or qty < min_qty:
            return "skip:min-notional"
        long = intent.side.value == "LONG"
        adverse = intent.entry_high if long else intent.entry_low
        if qty * adverse < min_notional:
            return "skip:min-notional"
        stop_dist = abs(adverse - intent.invalidation_price)
        fc = intent.forecast_cost
        stressed = ((fc.fee_bps + fc.spread_bps + fc.slippage_bps
                     + fc.funding_bps) / 10000 * cfg.stress_multiplier)
        if qty * stop_dist + qty * adverse * stressed > budget * (1 + 1e-9):
            return "sizing:budget-exceeded"
        notional = qty * adverse
        avail = snapshot.available_margin_usdt
        if avail is not None:
            affordable = ((avail - snapshot.fee_buffer_usdt)
                          * cfg.leverage_cap
                          - snapshot.inflight_exposure_usdt)
            if notional > affordable:
                return "margin:insufficient"
        if notional > cfg.leverage_cap * snapshot.reconciled_equity:
            return "leverage:cap-exceeded"
        return None

    def _narrow_entry_executable(self, pos: dict[str, Any],
                                 statuses: dict[str, Any]) -> None:
        """Narrow the reservation to the engine-recorded qty (READY-§5).

        Runs when the entry first appears in tracked order truth (covers queued
        submits): the recorded order qty is the authoritative submitted
        quantity after venue flooring. Rechecks minimums/risk/margin on
        the recorded qty; on failure cancels the entry, frees the hold
        and clears loudly (fail closed, never silently undersized).
        Idempotent via executable_noted.
        """
        if pos.get("executable_noted"):
            return
        entry_id = pos.get("entry_id") or pos.get("entry_pre_id") or ""
        status = statuses.get(entry_id)
        if status is None:
            return  # not recorded yet (queued); retry on a later pass.
        recorded = float(status.qty or 0.0)
        if not self.policy.note_executable_qty(pos["reservation_id"],
                                               recorded):
            if not pos.get("narrow_failed"):
                pos["narrow_failed"] = True
                self.store.checkpoint(self.run_id, "executable-unknown",
                                      {"reservation_id":
                                       pos["reservation_id"]})
            return
        pos["executable_noted"] = True
        pos["executable_qty"] = recorded
        self.store.checkpoint(self.run_id, "executable-narrowed", {
            "reservation_id": pos["reservation_id"],
            "approved_qty": pos.get("approved_qty"),
            "executable_qty": recorded})
        snapshot = pos.get("admit_snapshot")
        budget = pos.get("admit_budget")
        if snapshot is None or budget is None:
            return  # legacy/test-built position: minimums enforced at submit.
        recheck = self._recheck_executable(
            pos.get("admit_intent"), snapshot, recorded, budget) \
            if pos.get("admit_intent") is not None else None
        if recheck is not None:
            try:
                self.engine.cancel(entry_id, f"executable-recheck:{recheck}")
            except Exception:
                pass
            self.policy.release(pos["reservation_id"])
            self._note_reject(f"risk:{recheck}", pos.get("strategy", ""),
                              pos.get("instrument", ""), pos.get("side", ""))
            self._position = None
            self._set_state("ready", f"executable-recheck:{recheck}")

    def _note_reject(self, reason: str, strategy: str = "",
                     instrument: str = "", side: str = "") -> None:
        self._reject_counts[reason] = self._reject_counts.get(reason, 0) + 1
        stage = reason.split(":")[0] if ":" in reason else "unknown"
        # B9 strict readers need non-empty attribution: unattributed
        # rejects (warmup/data stages) are labeled "unknown", not blank.
        self._append_run_file("rejections.jsonl", {
            "ts_utc": self.now_utc().isoformat(), "stage": stage,
            "reason": reason, "strategy": strategy or "unknown",
            "instrument": instrument or "unknown", "side": side or "unknown"})

    def _drain_engine(self, *, bounded: bool = False) -> int:
        # Bounded live drain (watchdog review): a fill burst must not
        # starve the strategy loop; the remainder drains next wake.
        # Replay keeps the unbounded drain for exact accounting.
        if bounded and hasattr(self.engine, "pop_events"):
            events = self.engine.pop_events()
        else:
            events = self.engine.poll()
        for event in events:
            self._apply_engine_event(event)
        # Staged legacy sink deltas with no matching poll event flush
        # here (recovery-adopted; the live ones were consumed above).
        self._flush_staged_deltas()
        return len(events)

    def _advance_engine_clock(self) -> None:
        # Engine time must track wall time on EVERY live wake, including
        # idle heartbeats (watchdog review): latency-delayed submissions
        # only become due when the native clock advances, and without
        # this a quiet market stalls queued orders indefinitely.
        advance = getattr(self.engine, "advance_to", None)
        if advance is None:  # reference engine: wall clock, nothing to do.
            return
        try:
            now = self.now_utc()
            engine_now = self.engine.now_utc
            if now > engine_now:
                advance(now)
        except ValueError:
            pass  # backward step: keep engine time, never move it back.

    def _append_run_file(self, name: str, record: dict[str, Any]) -> None:
        """Append one JSON record to a per-run result file (B9 reporting).

        Schemas (stable, consumed by reporting/build):
        - fills.jsonl: {execution_id, client_order_id, instrument, side, qty,
          price, fee, liquidity, ts_utc}
        - rejections.jsonl: {ts_utc, stage, reason, strategy, instrument, side}
        - risk.jsonl: {ts_utc, kind, from_state, to_state, reason}
        - equity.jsonl: {ts_utc, marked_equity, cash, position_qty,
          position_symbol, open_pnl, source, mark_source, mark_age_ms}
        """
        with (self.workdir / name).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    def _init_run_files(self) -> None:
        """Create empty run files so strict loaders pass on quiet runs."""
        for name in ("fills.jsonl", "equity.jsonl", "rejections.jsonl",
                     "risk.jsonl"):
            path = self.workdir / name
            if not path.exists():
                path.write_text("", encoding="utf-8")

    def _on_engine_event(self, event: EngineEvent) -> Any:
        """Legacy entry point: every engine event lands in the ONE handler."""
        return self._apply_engine_event(event)

    def _apply_engine_event(self, event: EngineEvent) -> str:
        """THE one idempotent booking handler (contract v1 §1, name fixed).

        Every adapter emission — user-stream fills, lookup-adopted and
        recovery-adopted fills, simulated callbacks, push or drained —
        is applied here, keyed by namespaced execution_id. Persist
        first (durable anchor), then book; stale/duplicate events are
        no-ops. Unknown event kinds fall through to position
        supervision only.

        Returns the application outcome (R2 ack): applied | duplicate |
        unbooked | rejected | recorded | ignored. Adapters ACK a fill
        (drop it from the recoverable set) on every outcome EXCEPT
        unbooked/rejected — and on handler exceptions, which propagate
        and therefore never ack.
        """
        payload = event.payload
        outcome = "ignored"
        if event.kind == "fill":
            submitted = self._submit_ts.pop(payload.client_order_id, None)
            if submitted is None:
                # Fill arrived before the submit-time id resolved; match
                # via the engine's own mapping (protocol-only).
                for key in list(self._submit_ts):
                    try:
                        resolved = self.engine.resolve(key)
                    except (ValueError, KeyError, AttributeError):
                        continue
                    if resolved == payload.client_order_id:
                        submitted = self._submit_ts.pop(key)
                        break
            if submitted is not None:
                try:
                    self._dispatch_ms.append(
                        (payload.ts_utc - submitted).total_seconds() * 1000)
                except (TypeError, AttributeError):
                    pass
            outcome = self._apply_fill(
                client_order_id=payload.client_order_id,
                execution_id=payload.execution_id,
                instrument=payload.instrument, side=payload.side,
                qty=payload.qty, price=payload.price, fee=payload.fee,
                ts_utc=payload.ts_utc, liquidity=payload.liquidity)
        elif event.kind in ("cancel", "reject", "expire"):
            if self.store.record_event(
                    self.run_id, payload.client_order_id, event.kind,
                    {"instrument": payload.instrument,
                     "reason": payload.reason},
                    payload.ts_utc.isoformat()):
                self._resolve_command_by_engine_id(payload.client_order_id)
                outcome = "recorded"
            else:
                self._dup_events += 1
                outcome = "duplicate"
        elif event.kind == "funding":
            # Engine-settled funding reaches the ledger (idempotent by
            # event_id); without this backtests silently book funding 0.
            if not self.store.record_event(
                    self.run_id, payload.event_id, "funding",
                    {"instrument": payload.instrument,
                     "amount": payload.amount},
                    payload.ts_utc.isoformat()):
                self._dup_events += 1
                outcome = "duplicate"
            else:
                try:
                    self.policy.note_funding(payload.event_id, payload.amount,
                                             payload.ts_utc.isoformat())
                except ValueError as exc:
                    self._block_booking(f"funding-rejected:{exc}")
                    outcome = "rejected"
                else:
                    self._equity_dirty = True
                    self._reconcile_funding()
                    outcome = "applied"
        self._update_position(event)
        self._reconcile_commands()
        return outcome

    def _stage_sink_delta(self, reservation_id: str, exec_id: str,
                          symbol: str, venue_side: str, qty: float,
                          price: float, fee: float, ts_utc: str) -> None:
        """Stage a legacy sink delta for its poll event (contract v1 §3).

        Pre-migration adapters call note_fill_delta without a client
        id; the matching poll EngineEvent (same execution_id, with the
        client id) performs the booking. Deltas with no matching event
        flush at drain end as recovery-adopted. Persist-first: a
        redelivered delta is a duplicate no-op, never double-staged.
        """
        if exec_id in self._applied_exec or exec_id in self._staged_deltas:
            self._dup_events += 1
            return
        # Distinct kind from the event row: the matching poll event
        # persists its own "fill" anchor; a crash between the two
        # replays the staged row as adopted (same execution_id).
        if not self.store.record_event(
                self.run_id, exec_id, "fill-staged",
                {"client_order_id": "", "reservation_id": reservation_id,
                 "instrument": symbol, "side": venue_side, "qty": qty,
                 "price": price, "fee": fee, "liquidity": "taker"}, ts_utc):
            self._dup_events += 1
            return
        self._staged_deltas[exec_id] = {
            "reservation_id": reservation_id, "symbol": symbol,
            "side": venue_side, "qty": qty, "price": price, "fee": fee,
            "ts_utc": ts_utc}

    def _apply_fill(self, *, client_order_id: str, execution_id: str,
                    instrument: str, side: str, qty: float, price: float,
                    fee: float, ts_utc: Any, liquidity: str) -> str:
        """Book one fill increment exactly once (contract v1 §3).

        Returns applied|duplicate|unbooked|rejected. A staged legacy
        sink delta for the same execution_id is consumed (its client
        id comes from this event). Max-applied cumulative qty per
        order never rolls back.
        """
        self._staged_deltas.pop(execution_id, None)
        ts_iso = ts_utc.isoformat() if hasattr(ts_utc, "isoformat") else str(ts_utc)
        if execution_id in self._applied_exec:
            self._dup_events += 1
            return "duplicate"
        reservation_id = self._fill_reservation(client_order_id)
        if not self.store.record_event(
                self.run_id, execution_id, "fill",
                {"client_order_id": client_order_id,
                 "reservation_id": reservation_id or "",
                 "instrument": instrument, "side": side,
                 "qty": qty, "price": price, "fee": fee,
                 "liquidity": liquidity}, ts_iso):
            self._dup_events += 1
            return "duplicate"
        if reservation_id is None:
            self.store.checkpoint(self.run_id, "fill-unbooked", {
                "exec_id": execution_id, "client_order_id": client_order_id,
                "instrument": instrument, "qty": qty})
            self._block_booking(f"unknown-fill:{client_order_id}")
            return "unbooked"
        try:
            self.policy.note_fill_delta(
                reservation_id, execution_id, instrument, side, qty,
                price, fee, ts_iso)
        except ValueError as exc:
            self.store.checkpoint(self.run_id, "booking-rejected", {
                "exec_id": execution_id, "reason": str(exc)})
            self._block_booking(f"booking-rejected:{execution_id}")
            return "rejected"
        self._applied_exec.add(execution_id)
        self._order_cum[client_order_id] = self._order_cum.get(
            client_order_id, 0.0) + float(qty or 0.0)
        self._append_run_file("fills.jsonl", {
            "execution_id": execution_id,
            "client_order_id": client_order_id,
            "instrument": instrument, "side": side,
            "qty": qty, "price": price, "fee": fee,
            "liquidity": liquidity, "ts_utc": ts_iso})
        self._equity_dirty = True
        self._note_fill_exposure(client_order_id, execution_id)
        status = self._tracked_status(client_order_id)
        if status is not None and getattr(status, "state", "") in (
                "filled", "rejected", "cancelled", "expired"):
            self._resolve_command_by_engine_id(client_order_id)
        return "applied"

    def _flush_staged_deltas(self) -> None:
        """Book staged deltas with no matching poll event (adopted).

        Recovery-adopted fills arrive only via the legacy sink call,
        without a client id; they book under their reservation with an
        adopted marker so fills.jsonl stays strictly valid.
        """
        for exec_id, delta in list(self._staged_deltas.items()):
            self._staged_deltas.pop(exec_id)
            if exec_id in self._applied_exec:
                self._dup_events += 1
                continue
            reservation_id = delta["reservation_id"]
            if reservation_id not in self._known_reservations:
                self.store.checkpoint(self.run_id, "fill-unbooked", {
                    "exec_id": exec_id, "adopted": True,
                    "instrument": delta["instrument"], "qty": delta["qty"]})
                self._block_booking(f"unknown-fill:{exec_id}")
                continue
            try:
                self.policy.note_fill_delta(
                    reservation_id, exec_id, delta["symbol"],
                    delta["side"], delta["qty"], delta["price"],
                    delta["fee"], delta["ts_utc"])
            except ValueError as exc:
                self.store.checkpoint(self.run_id, "booking-rejected", {
                    "exec_id": exec_id, "reason": str(exc)})
                self._block_booking(f"booking-rejected:{exec_id}")
                continue
            self._applied_exec.add(exec_id)
            self._order_cum[f"adopted:{reservation_id}"] = \
                self._order_cum.get(f"adopted:{reservation_id}", 0.0) + float(
                    delta["qty"] or 0.0)
            self._append_run_file("fills.jsonl", {
                "execution_id": exec_id,
                "client_order_id": f"adopted:{reservation_id}",
                "instrument": delta["symbol"], "side": delta["side"],
                "qty": delta["qty"], "price": delta["price"],
                "fee": delta["fee"], "liquidity": "taker",
                "ts_utc": delta["ts_utc"]})
            self._equity_dirty = True
            pos = self._position
            if pos is not None and pos.get("reservation_id") == reservation_id:
                self._convert_reservation(pos, exec_id)

    def _block_booking(self, reason: str) -> None:
        """Latch a fail-closed booking block (new entries stop)."""
        if self._booking_blocked is None:
            self._booking_blocked = reason

    # -- exit-only halts (R3: Session owns its reasons) --------------------
    def _halt_entries(self, reason: str) -> None:
        """Halt entries under a Session-owned reason (R3).

        Mirrored to the engine's reason-keyed exit-only (adapter
        refuses entry submits); other subsystems' reasons survive.
        Engines without the seam (doubles) keep the Session record.
        """
        if not reason:
            return
        self._exit_only_reasons.add(reason)
        setter = getattr(self.engine, "set_exit_only", None)
        if callable(setter):
            setter(True, reason)

    def _release_exit_only(self, reason: str) -> None:
        """Lift one Session-owned reason (R3: others survive)."""
        self._exit_only_reasons.discard(reason)
        setter = getattr(self.engine, "set_exit_only", None)
        if callable(setter):
            setter(False, reason)

    def _release_all_exit_only(self, why: str) -> None:
        """Lift every Session-owned reason (recovery points only).

        Stream/adapter reasons are never touched (R3); level-evaluated
        Session reasons re-assert on their next tick if still true.
        """
        for reason in sorted(self._exit_only_reasons):
            setter = getattr(self.engine, "set_exit_only", None)
            if callable(setter):
                setter(False, reason)
        self._exit_only_reasons.clear()
        self.store.checkpoint(self.run_id, "exit-only-released",
                              {"why": why})

    # -- command intentions (contract v1 §4) -------------------------------
    def _new_command(self, kind: str, payload: dict[str, Any]) -> str:
        """Persist a command intention BEFORE it is issued."""
        cmd_id = f"{self.run_id}:cmd:{self._cmd_seq:06d}"
        self._cmd_seq += 1
        self.store.record_command(self.run_id, cmd_id, kind, payload)
        return cmd_id

    def _resolve_command_by_engine_id(self, engine_id: str) -> None:
        """Mark submitted commands terminally resolved by engine outcome."""
        if not engine_id:
            return
        try:
            pending = self.store.open_commands(self.run_id)
        except (ValueError, KeyError):
            return
        for cmd in pending:
            eid = cmd.get("engine_client_id")
            if not eid:
                continue
            match = eid == engine_id
            if not match:
                try:
                    match = self.engine.resolve(eid) == engine_id
                except (ValueError, KeyError, AttributeError):
                    continue
            if match:
                try:
                    self.store.update_command(cmd["cmd_id"], "resolved")
                except (ValueError, KeyError):
                    pass

    def _reconcile_commands(self) -> None:
        """Reconcile open commands against tracked order truth (v1 §4).

        Terminal orders resolve their commands; live ones stay
        submitted (adopted-known); commands with no engine id (crash
        inside submit: possibly executed) go unknown and block new
        entries until their outcome is proven by id.
        """
        try:
            pending = self.store.open_commands(self.run_id)
        except (ValueError, KeyError):
            return
        for cmd in pending:
            eid = cmd.get("engine_client_id")
            if not eid:
                if cmd.get("status") != "unknown":
                    try:
                        self.store.update_command(cmd["cmd_id"], "unknown")
                    except (ValueError, KeyError):
                        pass
                continue
            real = eid
            try:
                resolved = self.engine.resolve(eid)
            except (ValueError, KeyError, AttributeError):
                resolved = None
            if resolved:
                real = resolved
            status = self._tracked_status(real)
            if status is None:
                status = self._tracked_status(eid)
            if status is not None and getattr(status, "state", "") in (
                    "filled", "rejected", "cancelled", "expired"):
                try:
                    self.store.update_command(cmd["cmd_id"], "resolved")
                except (ValueError, KeyError):
                    pass

    def _fill_reservation(self, client_order_id: str) -> str | None:
        """Reservation a fill books under, or None when foreign/unknown.

        Tracked orders (entry, legs, closes, orphan closes, incl.
        submit-time aliases) book under the live position reservation
        — or, for orphan closes, the order's own recorded reservation.
        Anything else is foreign exposure: never booked, always
        flagged (contract v1 §3: no touching foreign exposure).
        """
        pos = self._position
        if pos is not None:
            tracked = [pos.get("entry_pre_id"), pos.get("entry_id")]
            tracked += list(pos.get("legs") or [])
            tracked += list(pos.get("close_ids") or [])
            if client_order_id in tracked:
                return pos["reservation_id"]
            for tid in tracked:
                if not tid:
                    continue
                try:
                    if self.engine.resolve(tid) == client_order_id:
                        return pos["reservation_id"]
                except (ValueError, KeyError, AttributeError):
                    continue
            return None
        if client_order_id in self._orphan_close_ids:
            return self._order_recorded_reservation(client_order_id)
        return None

    def _order_recorded_reservation(self, client_order_id: str) -> str | None:
        """Read back the reservation an order was submitted under."""
        status = self._tracked_status(client_order_id)
        rid = getattr(status, "reservation_id", None) if status else None
        if rid and rid in self._known_reservations:
            return rid
        return None

    def _convert_reservation(self, pos: dict[str, Any],
                             execution_id: str) -> None:
        """First-nonzero-fill reservation→exposure conversion (READY-§5).

        Exactly once per position: narrows executable from the recorded
        entry first (authoritative submitted qty), then converts via
        policy.note_fill (idempotent).
        """
        if pos.get("exposure_noted"):
            return
        statuses = self._tracked_statuses_for(pos)
        self._narrow_entry_executable(pos, statuses)
        if self._position is None:
            return  # narrow failed closed (recheck): hold freed, cleared.
        self.policy.note_fill(pos["reservation_id"])
        pos["exposure_noted"] = True
        self.store.checkpoint(self.run_id, "exposure-noted", {
            "reservation_id": pos["reservation_id"],
            "exec_id": execution_id})

    def _note_fill_exposure(self, client_order_id: str,
                             execution_id: str) -> None:
        """First-nonzero-fill reservation→exposure transition (READY-§5).

        Called only for fills already booked under this position's
        reservation (foreign fills never reach here); converts exactly
        once via _convert_reservation.
        """
        del client_order_id
        pos = self._position
        if pos is None:
            return
        self._convert_reservation(pos, execution_id)

    def _tracked_status(self, client_id: str) -> Any | None:
        """Tracked truth for one id: order_status, version-gated.

        None when never seen. Reads with a version strictly newer
        than last applied win; stale versions keep the cached status
        (cumulative filled quantity never rolls back). Version 0
        bypasses the cache (no transition observed yet: always
        current). Pre-migration adapters without order_status fall
        back to the open_orders snapshot (compat; declared in
        W1-REL: no terminal inference beyond what it carries).
        """
        if not client_id:
            return None
        query = getattr(self.engine, "order_status", None)
        if callable(query):
            try:
                status = query(client_id)
            except (ValueError, KeyError, AttributeError, TypeError):
                return None
            if status is None:
                return None
            if hasattr(status, "state") and hasattr(status, "filled_qty"):
                return self._gate_status_version(client_id, status)
            # Non-contract shape (e.g. pre-migration str): snapshot.
        try:
            for status in self.engine.open_orders():
                if status.client_order_id == client_id:
                    return status
        except (ValueError, KeyError, AttributeError):
            pass
        return None

    def _gate_status_version(self, client_id: str, status: Any) -> Any:
        """Apply version gating to one contract status read."""
        version = getattr(status, "version", 0) or 0
        version = getattr(status, "version", 0) or 0
        if version <= 0:
            return status
        last = self._status_version.get(client_id, -1)
        if version > last:
            self._status_version[client_id] = version
            self._status_cache[client_id] = status
            return status
        self._stale_status += 1
        return self._status_cache.get(client_id, status)

    def _tracked_statuses_for(self, pos: dict[str, Any] | None) -> dict[str, Any]:
        """Tracked truth for every id the Session follows (v1 §2).

        Entry handles, legs, retired, in-flight closes and orphan
        closes resolve via order_status (never via open_orders
        absence). Missing ids are simply absent: unknown, never
        terminal-by-absence.
        """
        ids: list[str] = list(self._orphan_close_ids)
        if pos is not None:
            ids += [pos.get("entry_pre_id") or "", pos.get("entry_id") or ""]
            ids += list(pos.get("legs") or [])
            ids += list(pos.get("retired") or [])
            ids += list(pos.get("close_ids") or [])
        out: dict[str, Any] = {}
        for cid in ids:
            if not cid:
                continue
            status = self._tracked_status(cid)
            if status is not None:
                out[cid] = status
        return out

    def _update_position(self, event: EngineEvent) -> None:
        pos = self._position
        if pos is None:
            return
        if pos["entry_id"] is None:
            real = self.engine.resolve(pos["entry_pre_id"])
            if real is not None:
                pos["entry_id"] = real
                if pos["entry_pre_id"] in self._submit_ts:
                    self._submit_ts[real] = self._submit_ts[pos["entry_pre_id"]]
        statuses = self._tracked_statuses_for(pos)
        self._mark_seen(pos, statuses)
        self._narrow_entry_executable(pos, statuses)
        if self._position is None:
            return  # narrow failed closed (recheck): hold freed, cleared.
        pos = self._position
        entry = statuses.get(pos["entry_id"] or "")
        # Sibling settling + terminal pruning (ids tracked to terminal).
        self._settle_leg_terminals(pos, statuses)
        # Coverage supervision: verify until protected, re-verify on growth.
        if entry is not None and entry.filled_qty > 1e-12 \
                and not pos["protected"]:
            self._ensure_protection(pos)
        elif pos["protected"]:
            self._reverify_protection(pos, statuses)
        # Time exit: cancel legs, flatten the remainder at market.
        if (self._position is not None
                and self.ledger.has_position()
                and self.now_utc() >= pos["time_exit"]):
            self._flatten("time-exit")
        # Flat inference: release ONLY on full agreement (ledger, booked,
        # engine/venue, pending commands, children, risk state).
        if self._position is not None and self._release_agrees(
                pos, statuses, entry):
            # Booked exposure nets zero, so this frees the reservation (or
            # lifts a zero-net unresolved leftover). Without it the next
            # approval blocks on exposure:unresolved forever (Q-007 finding).
            self.policy.note_flat()
            self.policy.release(pos["reservation_id"])
            self._position = None
            self._set_state("ready", "position-flat")
            return
        # Entry died with zero fills: cancel tracked children, then free
        # the risk hold and clear once nothing tracked is live.
        if self._position is not None and entry is not None \
                and entry.filled_qty <= 1e-12 and entry.state in (
                    "rejected", "cancelled", "expired"):
            outcomes = [self._request_cancel(
                pos, lid, statuses, "entry-dead-cleanup")
                for lid in list(pos.get("legs") or [])
                + list(pos.get("retired") or [])
                + list(pos.get("close_ids") or [])]
            if any(o in ("sent", "failed", "unknown") for o in outcomes):
                return  # retry once cancels confirm; hold retained.
            self.policy.release(pos["reservation_id"])
            self._position = None
            self._set_state("ready", f"entry-dead:{entry.state}")

    def _protection_need(self, pos: dict[str, Any],
                         statuses: dict[str, Any]) -> float:
        """Quantity the live stop must cover (READY-§5 inv 3).

        Confirmed ledger net always; plus approved-but-unfilled remainder
        ONLY when the entry outcome is unknown (absent: conservative
        coverable demand). A terminal entry retires its unfilled remainder
        (IOC cancel included) — never demanded. A live entry's pending
        remainder is covered by resize-on-fill, not demanded up front
        (legs can only attach to filled qty).
        """
        net = abs(self.ledger.position_qty())
        coverable = self.policy.required_stop_qty(pos["reservation_id"])
        entry = statuses.get(pos.get("entry_id") or "")
        if entry is None:
            if pos.get("entry_dropped"):
                return net  # dropped pre-record: zero fills possible.
            return max(net, coverable if coverable is not None else net)
        if entry.state in ("filled", "rejected", "cancelled", "expired"):
            return net
        return net

    def _pending_fillable(self, pos: dict[str, Any],
                          statuses: dict[str, Any]) -> float:
        """Entry qty that can still fill (0 once retired/dropped)."""
        coverable = self.policy.required_stop_qty(pos["reservation_id"])
        base = coverable if coverable is not None \
            else abs(self.ledger.position_qty())
        entry = statuses.get(pos.get("entry_id") or "")
        if entry is None:
            return 0.0 if pos.get("entry_dropped") else base
        if entry.state in ("filled", "rejected", "cancelled", "expired"):
            return 0.0
        return max(0.0, base - float(entry.filled_qty or 0.0))

    def _settle_leg_terminals(self, pos: dict[str, Any],
                              statuses: dict[str, Any]) -> None:
        """Settle siblings on leg fills; prune confirmed terminals (inv 4).

        A filled tracked leg settles its siblings (cancel requests; ids
        stay tracked until terminal confirmation). Only CONFIRMED terminal
        ids are pruned — absent/unknown ids are never dropped.
        """
        for key in ("legs", "retired"):
            for lid in list(pos.get(key) or []):
                st = statuses.get(lid)
                if st is None:
                    continue  # unknown: keep tracking, never prune.
                if st.state == "filled" and key == "legs":
                    for sib in list(pos.get("legs") or []) \
                            + list(pos.get("retired") or []):
                        if sib != lid:
                            self._request_cancel(pos, sib, statuses,
                                                 "sibling-settled")
                if st.state in ("filled", "rejected", "cancelled",
                                "expired"):
                    # Membership-guarded: a sibling cancel above can
                    # push a terminal event synchronously, and the
                    # nested supervision pass may prune first.
                    if lid in pos[key]:
                        pos[key].remove(lid)

    def _mark_seen(self, pos: dict[str, Any],
                   statuses: dict[str, Any]) -> None:
        """Record tracked ids observed in engine state (READY-§5 inv 4).

        Distinguishes queue-dropped ids (never seen: terminal, prune on
        KeyError) from engine amnesia (seen before, now unknown: keep
        blocking) after cancel requests.
        """
        seen = pos.setdefault("seen_ids", set())
        for lid in list(pos.get("legs") or []) \
                + list(pos.get("retired") or []) \
                + list(pos.get("close_ids") or []) \
                + [pos.get("entry_pre_id"), pos.get("entry_id")]:
            if lid and lid in statuses:
                seen.add(lid)

    def _request_cancel(self, pos: dict[str, Any], lid: str,
                        statuses: dict[str, Any], reason: str) -> str:
        """Single cancel path: send, or resolve already-gone (READY-§5).

        Returns sent/failed/dropped/unknown/terminal. A KeyError for a
        never-seen id means the venue queue dropped it (terminal outcome:
        the order will never exist) — pruned from tracking. A KeyError
        for a previously-seen id means engine amnesia — kept blocking.
        """
        st = statuses.get(lid)
        if st is not None and st.state not in ("open", "partial"):
            return "terminal"
        try:
            self.engine.cancel(lid, reason)
        except KeyError:
            if lid not in pos.get("seen_ids", set()):
                for key in ("legs", "retired", "close_ids"):
                    tracked = pos.get(key) or []
                    if lid in tracked:
                        tracked.remove(lid)
                return "dropped"
            return "unknown"
        except Exception:
            return "failed"
        return "sent"

    def _cancel_tracked(self, pos: dict[str, Any],
                        statuses: dict[str, Any], reason: str,
                        ids: list[str] | None = None) -> bool:
        """Request cancel on tracked children (default all). True if sent."""
        if ids is None:
            ids = list(pos.get("legs") or []) \
                + list(pos.get("retired") or []) \
                + list(pos.get("close_ids") or [])
        sent = False
        for lid in ids:
            if self._request_cancel(pos, lid, statuses, reason) == "sent":
                sent = True
        return sent

    def _ensure_protection(self, pos: dict[str, Any]) -> None:
        """Attach + VERIFY required stop cover (READY-§5 inv 3/4).

        protected flips True only when a tracked stop is live with
        covering quantity over the computed need. Child ids are NEVER
        dropped until terminal confirmation: short/dead cover is
        REPLACED (old pair retired with cancel requested, fresh pair
        attached), terminals pruned on confirmation. Attach attempts are
        bounded (3, reset on verify success or new entry fills); then a
        latched emergency close converges via idempotent flatten.
        Never falsely protected.
        """
        if self._in_ensure:
            return  # push reentrancy: the outer pass verifies fresh.
        self._in_ensure = True
        try:
            self._ensure_protection_inner(pos)
        finally:
            self._in_ensure = False

    def _ensure_protection_inner(self, pos: dict[str, Any]) -> None:
        """Attach + verify body (see _ensure_protection)."""
        statuses = self._tracked_statuses_for(pos)
        self._mark_seen(pos, statuses)
        self._settle_leg_terminals(pos, statuses)
        need = self._protection_need(pos, statuses)
        if need <= 1e-9:
            # Vacuous: nothing to cover — cancel live tracked legs and
            # stay quiet (flat inference clears; no checkpoint spam).
            self._cancel_tracked(pos, statuses, "protection-vacuous")
            return
        stop = statuses.get((pos.get("legs") or [None])[0] or "")
        if stop is not None and stop.state in ("open", "partial") \
                and stop.qty - stop.filled_qty + 1e-9 >= need:
            if not pos["protected"]:
                pos["protected"] = True
                pos["protect_attempts"] = 0
                self.store.checkpoint(self.run_id, "protection-verified",
                                      {"legs": list(pos["legs"]),
                                       "need": need})
                fillable = self._pending_fillable(pos, statuses)
                if fillable > 1e-9:
                    # Resize armed: pending entry remainder is explicitly
                    # tracked and covered by replace-on-fill, not by this
                    # pair (legs attach to filled qty only).
                    self.store.checkpoint(
                        self.run_id, "protection-partial",
                        {"need": need, "fillable_pending": fillable})
            return
        # No covering stop: replace the pair (retire with cancel requested,
        # attach fresh). Attempts bound attach calls; new entry fills reset.
        entry = statuses.get(pos.get("entry_id") or "")
        entry_filled = float(entry.filled_qty or 0.0) \
            if entry is not None else 0.0
        if entry_filled > pos.get("attach_filled", 0.0):
            pos["protect_attempts"] = 0
        if pos["protect_attempts"] >= 3:
            if not pos.get("emergency_latched"):
                pos["emergency_latched"] = True
                self.store.checkpoint(self.run_id, "protection-emergency",
                                      {"attempts": pos["protect_attempts"],
                                       "need": need})
            self._flatten("protection-emergency-close")
            self._drain_engine()
            return
        if pos.get("legs"):
            self._cancel_tracked(pos, statuses, "protection-replace",
                                 ids=list(pos["legs"]))
            for lid in list(pos["legs"]):
                # _request_cancel may already have pruned queue-dropped
                # ids; the rest retire with cancel requested.
                if lid in pos["legs"]:
                    pos.setdefault("retired", []).append(lid)
                    pos["legs"].remove(lid)
        pos["protect_attempts"] += 1
        pos["attach_filled"] = entry_filled
        try:
            pos["legs"] = self.engine.attach_protection(
                pos["entry_id"] or "", pos["stop"], pos["target"])
        except (ValueError, KeyError) as exc:
            self.store.checkpoint(self.run_id, "protection-failed",
                                  {"attempt": pos["protect_attempts"],
                                   "reason": str(exc)})
            return
        # Acknowledgement gate: queued legs resolve on a later drain.
        try:
            resolved = [self.engine.resolve(lid) for lid in pos["legs"]]
        except (ValueError, KeyError, AttributeError):
            return
        if any(rid is None for rid in resolved):
            return
        pos["legs"] = resolved
        # Verify the fresh pair against FRESH tracked truth.
        statuses = self._tracked_statuses_for(pos)
        need = self._protection_need(pos, statuses)
        stop = statuses.get((pos.get("legs") or [None])[0] or "")
        if stop is None or stop.state not in ("open", "partial"):
            self.store.checkpoint(self.run_id, "protection-unverified",
                                  {"leg": (pos.get("legs") or [None])[0],
                                   "state": stop.state if stop else "missing"})
            # Prune newly-confirmed terminals (live/unknown stay tracked).
            self._settle_leg_terminals(pos, statuses)
            return
        if stop.qty - stop.filled_qty + 1e-9 < need:
            self.store.checkpoint(self.run_id, "protection-unverified",
                                  {"leg": pos["legs"][0], "reason": "qty-short",
                                   "open_qty": stop.qty - stop.filled_qty,
                                   "need": need,
                                   "required_stop_qty":
                                   self.policy.required_stop_qty(
                                       pos["reservation_id"])})
            self._settle_leg_terminals(pos, statuses)
            return
        if not pos["protected"]:
            pos["protected"] = True
            pos["protect_attempts"] = 0
            self.store.checkpoint(self.run_id, "protection-verified",
                                  {"legs": list(pos["legs"]), "need": need})
            self._settle_leg_terminals(pos, statuses)

    def _reverify_protection(self, pos: dict[str, Any],
                             statuses: dict[str, Any]) -> None:
        """Ongoing supervision of verified cover (READY-§5 inv 4).

        Additional entry fills grow need past the verified pair: unprotect
        and replace (resize). Lost cover (dead/settled stop) likewise.
        Vacuous need cancels tracked legs quietly; flat inference clears.
        """
        need = self._protection_need(pos, statuses)
        if need <= 1e-9:
            self._cancel_tracked(pos, statuses, "protection-vacuous")
            return
        stop = statuses.get((pos.get("legs") or [None])[0] or "")
        if stop is not None and stop.state in ("open", "partial") \
                and stop.qty - stop.filled_qty + 1e-9 >= need:
            return  # still covered.
        pos["protected"] = False
        self.store.checkpoint(self.run_id, "protection-unverified",
                              {"reason": "cover-lost", "need": need})
        self._ensure_protection(pos)

    def _release_agrees(self, pos: dict[str, Any],
                        statuses: dict[str, Any], entry: Any) -> bool:
        """Full-agreement gate for releasing a position (READY-§5 inv 5).

        Ledger, booked, engine/venue, pending commands, children and risk
        state must ALL agree flat/settled. Unknown (absent) tracked ids
        block — they are not agreement.
        """
        if entry is None:
            if not pos.get("entry_dropped"):
                return False  # entry never recorded: submit still pending.
        elif entry.state in ("open", "partial"):
            return False  # fillable remainder pending.
        if self.ledger.has_position():
            return False
        if self.policy.booked_net(pos["reservation_id"]) != 0.0:
            return False
        # entry_pre_id is an alias superseded once entry_id resolves —
        # only the unresolved handle blocks.
        if pos.get("entry_id"):
            tracked = [pos.get("entry_id")]
        else:
            tracked = [pos.get("entry_pre_id")]
        tracked += list(pos.get("legs") or [])
        tracked += list(pos.get("retired") or [])
        tracked += list(pos.get("close_ids") or [])
        for tid in tracked:
            if not tid:
                continue
            st = statuses.get(tid)
            if st is None:
                if pos.get("entry_dropped") and tid in (
                        pos.get("entry_pre_id"), pos.get("entry_id")):
                    continue  # queue-dropped entry: terminal, zero fills.
                return False  # unknown outcome: blocks (inv 2).
            if st.state in ("open", "partial"):
                return False
        for st in statuses.values():
            if getattr(st, "reservation_id", None) == pos["reservation_id"] \
                    and st.state in ("open", "partial"):
                return False  # live reservation-linked order (any role).
        if getattr(self.engine, "_submit_queue", []):
            return False  # pending commands not yet submitted.
        if getattr(self.engine, "_pending", []):
            return False  # unconsumed execution events.
        if not self._venue_positions_agree(pos):
            return False
        unknown = getattr(self.engine, "unknown_ids", None)
        if callable(unknown):
            try:
                if unknown():
                    return False
            except Exception:
                return False
        return True

    def _venue_positions_agree(self, pos: dict[str, Any]) -> bool:
        """Venue-position leg of flat agreement (contract v1 §2, W1).

        A complete AccountSnapshot must agree with the flat ledger:
        any nonzero reported position blocks (foreign exposure is
        never touched, only disagreed-with). An attempted snapshot
        with complete=False/None is unknown: never flat. A None
        snapshot (adapter models no venue account) or a
        pre-migration shape (raw dict) leaves the leg to order truth
        plus the legacy simulator-cache read below.
        """
        snap_fn = getattr(self.engine, "account_snapshot", None)
        if callable(snap_fn):
            try:
                snap = snap_fn()
            except Exception:
                return False  # unreadable venue position: not agreed.
            if snap is not None and hasattr(snap, "complete") \
                    and hasattr(snap, "positions"):
                if snap.complete is False or snap.complete is None:
                    self.store.checkpoint(
                        self.run_id, "flat-blocked",
                        {"reason": "venue-snapshot-incomplete"})
                    return False
                try:
                    positions = list(snap.positions or ())
                except TypeError:
                    return False
                for position in positions:
                    qty = getattr(position, "qty", 0.0) or 0.0
                    if abs(float(qty)) > 1e-9:
                        self.store.checkpoint(
                            self.run_id, "flat-blocked",
                            {"reason": "venue-position-divergence",
                             "instrument": getattr(
                                 position, "instrument", "?"),
                             "qty": float(qty)})
                        return False
                return True
        cache = getattr(self.engine, "_cache", None)
        if cache is not None:
            try:
                if cache.positions_open():
                    return False
            except Exception:
                return False  # unreadable venue position: not agreed.
        return True

    def _retry_pending_flatten(self, reason: str) -> None:
        if not self.ledger.has_position():
            self._flatten_pending = False
            return
        try:
            self._flatten(reason)
            self._drain_engine()
        except Exception as exc:
            self.store.checkpoint(self.run_id, "flatten-retry",
                                  {"reason": str(exc)})
        if not self.ledger.has_position():
            self._flatten_pending = False

    def _position_symbol(self) -> str | None:
        """Instrument of the current ledger exposure (last fill's symbol)."""
        if self._position is not None:
            return self._position["instrument"]
        for entry in reversed(self.ledger.to_dict().get("journal", [])):
            if entry.get("kind") == "fill" and entry.get("symbol"):
                return entry["symbol"]
        return None

    def _flatten(self, reason: str) -> None:
        """Idempotent tracked close (READY-§5 inv 5).

        Cancels every tracked live child (entry, legs, retired — closes
        in flight are left to work), then submits ONE reduce-only close
        sized exactly to the ledger net when no close is already in
        flight. Unknown (absent) closes count as in flight: reconcile
        before retry, never duplicate. Checkpoints only when it ACTS, so
        repeated empty calls are silent instead of looping.
        """
        if self.config.mode == "prod" and not self.config.allow_live_submission:
            raise ValueError("config:prod-submission-disabled")
        if self._in_flatten:
            return  # push reentrancy: the outer pass already converges.
        self._in_flatten = True
        try:
            self._flatten_inner(reason)
        finally:
            self._in_flatten = False

    def _flatten_inner(self, reason: str) -> None:
        """Tracked-close body (see _flatten)."""
        # No drain here: callers drain around flatten (_update_position runs
        # post-drain; others drain after), and draining would recurse via
        # time-exit. Retries always observe drained state. Statuses below
        # are read fresh from engine state regardless.
        pos = self._position
        try:
            statuses = self._tracked_statuses_for(pos)
        except (ValueError, KeyError, AttributeError):
            statuses = {}
        acted = False
        requested = pos.setdefault("cancel_requested", set()) \
            if pos is not None else set()
        if pos is not None:
            self._mark_seen(pos, statuses)
            # Own in-flight closes are left to work (canceling them
            # would self-sabotage); legs/retired/entry must die first.
            for lid in list(pos.get("legs") or []) \
                    + list(pos.get("retired") or []):
                if self._request_cancel(pos, lid, statuses, reason) \
                        == "sent" and lid not in requested:
                    requested.add(lid)
                    acted = True
            entry_id = pos.get("entry_id") or pos.get("entry_pre_id") or ""
            entry = statuses.get(entry_id)
            if entry is None or entry.state in ("open", "partial"):
                # Live (or unrecorded) entry must die too, or it refills
                # behind the close. Absent ids cancel via queue drop.
                outcome = self._request_cancel(pos, entry_id, statuses,
                                               reason)
                if outcome == "sent" and entry_id not in requested:
                    requested.add(entry_id)
                    acted = True
                elif outcome == "dropped":
                    # Queue-dropped before ever recording: terminal outcome
                    # (zero fills possible) — release may proceed past it.
                    pos["entry_dropped"] = True
            closes = list(pos.get("close_ids") or [])
        else:
            closes = list(self._orphan_close_ids)
        close_live = False
        for cid in closes:
            st = statuses.get(cid)
            if st is None or st.state in ("open", "partial"):
                close_live = True  # unknown counts as in flight.
                break
        net = self.ledger.position_qty()
        if abs(net) > 1e-12 and not close_live:
            symbol = pos["instrument"] if pos is not None else self._position_symbol()
            if symbol is None:
                raise ValueError("cannot flatten: exposure without instrument")
            side = "SELL" if net > 0 else "BUY"
            if pos is not None:
                close_rid = pos["reservation_id"]
            else:
                # Orphan close: attribute to the single surviving
                # unresolved reservation when unambiguous, so its
                # fills book and net out (else reservation-less,
                # adapter-skipped as before).
                unresolved = self.policy.unresolved_ids()
                close_rid = unresolved[0] if len(unresolved) == 1 else None
            # Reduce-only + exact-net sizing: never opens or reverses.
            close_cmd = self._new_command("submit", {
                "role": "close", "instrument": symbol, "side": side,
                "qty": abs(net), "reservation_id": close_rid,
                "reason": reason})
            pre_id = self.engine.submit_immediate(EngineOrder(
                instrument=symbol, side=side, qty=abs(net),
                kind="MARKET", reduce_only=True,
                reservation_id=close_rid, role="target"))
            try:
                self.store.update_command(close_cmd, "submitted",
                                          engine_client_id=pre_id)
            except (ValueError, KeyError):
                pass
            if pos is not None:
                pos.setdefault("close_ids", []).append(pre_id)
            else:
                self._orphan_close_ids.append(pre_id)
            acted = True
        if acted:
            self.store.checkpoint(self.run_id, "flatten",
                                  {"reason": reason, "net": net})

    # -- replay --------------------------------------------------------------
    def _prime_replay_books(
            self, capture_dir: Path
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Load persisted depth snapshots for CAUSAL replay install (P1).

        Snapshots are returned pending (sorted by exchange clock), NOT
        installed: the replay loop installs each one only when its clock
        reaches it, so a future snapshot can never leak into earlier
        queries. A missing depth_snapshots.jsonl (captures predating
        E-007) yields no pending snaps — books stay unsynced ever.
        """
        from cryptobot.market_data.bridge import snapshot_ms
        path = capture_dir / "depth_snapshots.jsonl"
        pending = sorted(load_snapshots(path), key=snapshot_ms)
        summary: dict[str, Any] = {
            "source": "depth_snapshots.jsonl", "present": path.exists(),
            "mode": "causal-stream", "total": len(pending),
            "applied": 0, "synced": [], "failed": {}, "errors": 0,
            "unreached": 0}
        return summary, pending

    def _install_due_snapshots(
            self, pending: list[dict[str, Any]], clock_ms: int,
            summary: dict[str, Any]) -> None:
        """Install snapshots the replay clock has reached (P1, in-loop).

        Consumes from the head of the clock-sorted pending list. Each
        install ALSO passes as_of_ms with the same tolerance bound
        (defense in depth: a merge bug yielding too early refuses with
        "future" instead of leaking). Unreached snapshots (newer than
        every event) are never installed.
        """
        from cryptobot.market_data.bridge import snapshot_ms
        while pending:
            snap = pending[0]
            tol = 0 if snap.get("exchange_ts_ms") else 1000
            if snapshot_ms(snap) - tol > clock_ms:
                break
            pending.pop(0)
            try:
                outcome = self._depth_store.apply_snapshot_record(
                    snap, as_of_ms=clock_ms + tol)
            except (KeyError, TypeError, ValueError):
                summary["errors"] += 1
                continue
            if outcome == "future":
                summary["unreached"] += 1
                continue
            summary["applied"] += 1
            if outcome == "synced":
                symbol = str(snap.get("symbol", ""))
                if symbol not in summary["synced"]:
                    summary["synced"].append(symbol)
            else:
                summary["failed"][str(snap.get("symbol", "?"))] = outcome

    def _rest_timeout(self, default: float = 15.0) -> float:
        """REST timeout bounded by the remaining job budget (W3-30MIN §4)."""
        remaining = deadline_remaining_s()
        if remaining is None:
            return default
        return max(1.0, min(default, remaining))

    def _fetch_depth_snapshots(self) -> dict[str, Any]:
        """Pure-REST depth fetch (no session state; safe off-thread).

        Returns {symbol: payload-or-error}; the control thread installs.
        """
        import urllib.request
        fetched: dict[str, Any] = {}
        timeout = self._rest_timeout()
        for symbol in self.config.symbols:
            url = ("https://fapi.binance.com/fapi/v1/depth"
                   f"?symbol={symbol}&limit=1000")
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "cryptobot-paper/0.1"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    fetched[symbol] = json.loads(resp.read().decode("utf-8"))
            except Exception as exc:  # noqa: BLE001 - recorded, not raised.
                fetched[symbol] = exc
        return fetched

    def _install_depth_snapshots(self, fetched: dict[str, Any]) -> dict[str, Any]:
        """Install fetched snapshots on the control thread (single owner)."""
        summary: dict[str, Any] = {"source": "rest:fapi/v1/depth",
                                   "applied": 0, "synced": [],
                                   "primed": [], "failed": {}}
        recv_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        for symbol, payload in fetched.items():
            if isinstance(payload, BaseException):
                summary["failed"][symbol] = {
                    "stage": "fetch",
                    "error": f"{type(payload).__name__}",
                    "sync": self._depth_store.sync_report(symbol)}
                continue
            try:
                # P2: report the ACTUAL install outcome, never the fetch.
                outcome = self._depth_store.apply_snapshot_record({
                    "symbol": symbol, "bids": payload["bids"],
                    "asks": payload["asks"],
                    "last_update_id": int(payload["lastUpdateId"]),
                    "rest_recv_ms": recv_ms,
                    "exchange_ts_ms": payload.get("T")})
            except Exception as exc:  # noqa: BLE001 - priming never aborts.
                summary["failed"][symbol] = {
                    "stage": "install",
                    "error": f"{type(exc).__name__}",
                    "sync": self._depth_store.sync_report(symbol)}
                continue
            summary["primed"].append(symbol)
            summary["applied"] += 1
            if outcome == "synced":
                summary["synced"].append(symbol)
            else:
                summary["failed"][symbol] = {
                    "stage": "install", "outcome": outcome,
                    "sync": self._depth_store.sync_report(symbol)}
        return summary

    def _prime_live_books(self) -> dict[str, Any]:
        """REST depth snapshot per configured symbol at live start.

        Dynamic discovery (empty symbols) cannot prime upfront: recorded
        as skipped. A failed fetch never aborts the run; the symbol is
        recorded unprimed and its book stays unsynced. Synchronous (used
        at startup); stall-resync uses the async fetch+install split.
        """
        if not self.config.symbols:
            return {"source": "rest:fapi/v1/depth", "applied": 0,
                    "synced": [], "primed": [], "failed": {},
                    "skipped": "dynamic-symbols"}
        return self._install_depth_snapshots(self._fetch_depth_snapshots())

    def run_replay(self, capture_dir: str | Path, *,
                   expect_class: str = "observed-public",
                   resume: bool = False,
                   crash_after: int | None = None) -> dict[str, Any]:
        # Streaming replay (W1-24H): single O(1)-memory pass over the
        # capture — no load_events list, no full-list sort. Local import
        # keeps this shared-file-queue patch inside this method.
        from cryptobot.market_data.replayer import RollingEventHash, stream_events

        # Single-instance lock (contract v1 §4): held until close().
        self.store.acquire_lock()
        capture_dir = Path(capture_dir)
        events_path = capture_dir / "events.jsonl"
        if not events_path.exists():
            raise FileNotFoundError(f"no events.jsonl in {capture_dir}")
        self._crash_after = crash_after
        if resume:
            self._resume_state()
        else:
            self.store.create_run(self.run_id, "replay", self.config.fingerprint,
                                  str(self.workdir), self._pid)
            opening = self.ledger.marked_equity(0.0)
            self.store.checkpoint(self.run_id, "open",
                                  {"equity": opening, "capture": str(capture_dir)})
        self._init_run_files()
        prime, pending_snaps = self._prime_replay_books(capture_dir)
        self.store.checkpoint(self.run_id, "depth-prime", prime)
        events = stream_events(events_path)
        first = next(events, None)
        if first is None:
            raise ValueError(f"no events in {events_path}")
        assert_input_class({"input_class": first["input_class"]}, expect_class)
        adapters, modules = self._strategy_adapters()
        if self.protection is not None:
            # ReplayCutoff at the first event instant (W4-24H §12):
            # future-knowledge events must not gate a historical replay.
            from cryptobot.events.profiles import ReplayCutoff
            first_dt = datetime.fromtimestamp(
                int(first["exchange_ts_ms"]) / 1000.0, tz=timezone.utc)
            filtered, counts = ReplayCutoff.apply(
                self.protection.store, first_dt)
            self.protection.store = filtered
            self.protection.gate.store = filtered
            self.store.checkpoint(self.run_id, "event-cutoff", counts)
        if not resume:
            # Day baseline at first event time (causal).
            self.clock.set_ms(int(first["exchange_ts_ms"]))
            self.policy.reconcile_day(self.config.paper_capital_usdt, 0.0)
            self._day = accounting_date(self.now_utc()).isoformat()
        self._set_state("warming", "replay-start")
        rolling = RollingEventHash()
        first_ms: int | None = None
        last_ms: int | None = None
        skipped_prefix = 0
        snap_clock: int | None = None
        from itertools import chain as _chain

        for event in _chain((first,), events):
            assert_input_class({"input_class": event["input_class"]},
                               expect_class)
            rolling.update(event)
            ts = int(event["exchange_ts_ms"])
            first_ms = ts if first_ms is None else min(first_ms, ts)
            last_ms = ts if last_ms is None else max(last_ms, ts)
            # Causal snapshot install (P1): the clock advances on EVERY
            # event including the skipped resume prefix, so resume
            # installs identically to a fresh run. Snapshots install
            # BEFORE the first event at/after their time.
            snap_clock = ts if snap_clock is None else max(snap_clock, ts)
            self._install_due_snapshots(pending_snaps, snap_clock, prime)
            if int(event.get("seq", 0)) <= self._last_seq:
                skipped_prefix += 1
                continue
            self._ingest(event, adapters, modules)
            if self._milestones["first_event"] is None:
                iso, rel = self._ms_stamp()
                self._milestones["first_event"] = {
                    "ts_utc": iso, "rel_ms": rel,
                    "channel": event.get("channel"),
                    "symbol": event.get("symbol")}
            self._last_seq = int(event.get("seq", 0))
            self._events_seen += 1
            if self._events_seen % 500 == 0:
                self.store.heartbeat(self.run_id, self._pid)
                self.store.checkpoint(self.run_id, "cursor",
                                      {"last_seq": self._last_seq})
            if self._crash_after is not None and self._events_seen >= self._crash_after:
                self.store.checkpoint(self.run_id, "cursor",
                                      {"last_seq": self._last_seq})
                self._persist_local_state()
                raise RuntimeError(f"test-hook crash after {self._events_seen} events")
            stop = self._stop_flag or self.store.stop_requested(self.run_id)
            if stop is not None:
                if stop == "flatten":
                    self._flatten("operator-stop-flatten")
                    self._drain_engine()
                self._set_state("stopping", f"operator-stop:{stop}")
                break
        else:
            # Natural end of capture: manage any open exposure, then stop.
            if self._position is not None:
                self._flatten("capture-end")
                self._drain_engine()
            self._set_state("stopping", "capture-end")
        self._drain_engine()
        self._persist_local_state()
        self._sample_equity("run-end", force=True)
        prime["unreached"] += len(pending_snaps)
        self.store.checkpoint(self.run_id, "depth-prime-final", prime)
        if first_ms is not None and last_ms is not None:
            w0 = _EPOCH + timedelta(milliseconds=first_ms)
            w1 = _EPOCH + timedelta(milliseconds=last_ms)
        else:
            w0 = w1 = self.now_utc()
        digest = hashlib.sha256()
        with open(events_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        self._write_run_identity(
            dataset=capture_dir.name, window_start_utc=w0, window_end_utc=w1,
            manifest_extra={"manifest_sha": digest.hexdigest(),
                            "input_class": expect_class,
                            "capture": str(capture_dir)})
        self._set_state("stopped", "run-complete")
        iso, rel = self._ms_stamp()
        self._milestones["capture_end"] = {"ts_utc": iso, "rel_ms": rel}
        report = self._build_report(str(capture_dir), expect_class)
        report["replay_stream"] = {
            "mode": "streaming-v1",
            "events_hashed": rolling.count,
            "events_hash": rolling.hexdigest(),
            "skipped_prefix": skipped_prefix,
            "first_ms": first_ms,
            "last_ms": last_ms,
            "snapshots_installed": prime["applied"],
            "snapshots_unreached": prime["unreached"],
        }
        (self.workdir / "report.json").write_text(json.dumps(report, indent=2))
        (self.workdir / "report.md").write_text(self._render_report(report))
        self._stop_refresh()
        return report

    def _ingest(self, event: dict[str, Any], adapters: dict[str, Any],
                modules: dict[str, Any]) -> None:
        channel = event.get("channel")
        symbol = event.get("symbol")
        if event.get("gap_kind"):
            # Socket gap marker (P4): tell the live adapter its stream
            # re-converged so UNKNOWNs re-resolve; no-op elsewhere.
            reconnected = getattr(self.engine, "stream_reconnected", None)
            if callable(reconnected):
                try:
                    reconnected()
                except Exception:
                    pass
        if channel in ("aggTrade", "bookTicker", "depth", "markPrice") and symbol:
            # Engine + views see every market channel (depth/markPrice used
            # to be dropped here, which starved funding terms and book/flow
            # views on the Session path). Null/malformed payloads fail
            # closed with a LOUD count (W5 READY note): they can neither
            # age a mark nor admit an entry — dropped, never raised.
            if not self._market_payload_ok(channel, event.get("payload")):
                self._reject_counts["event-malformed-payload"] = (
                    self._reject_counts.get("event-malformed-payload", 0) + 1)
                return
            if hasattr(self.engine, "note_event"):
                self.engine.note_event(event)
            if channel == "markPrice" and isinstance(
                    event.get("payload"), dict) \
                    and event["payload"].get("mark"):
                self._saw_exchange_marks = True
            try:
                outcome = self._depth_store.apply_record(event)
            except (KeyError, TypeError, ValueError):
                pass  # malformed depth/trade: views degrade to absent.
            else:
                # P3: a chain break stops the sync claim immediately; the
                # book buffers until a fresh snapshot installs. Live
                # re-fetch sequencing rides the supervision tick (never a
                # blocking fetch here); replay records the break honestly.
                if outcome == "resync":
                    self._depth_store.resync_symbol(symbol, "chain-break")
                    self._resyncs_seen[symbol] = (
                        self._resyncs_seen.get(symbol, 0) + 1)
        if channel not in ("aggTrade", "bookTicker") or not symbol:
            return
        try:
            exchange_ms = int(event["exchange_ts_ms"])
        except (KeyError, TypeError, ValueError):
            # Fail-closed (W3-30MIN §4): a market event without usable
            # exchange timestamps can neither age a mark nor admit an
            # entry — drop it loudly instead of crashing the loop.
            self._reject_counts["event-no-timestamp"] = (
                self._reject_counts.get("event-no-timestamp", 0) + 1)
            return
        if hasattr(self.clock, "set_ms"):
            self.clock.set_ms(exchange_ms)  # replay: event time.
        try:
            recv_ms = int(event.get("local_recv_ms", exchange_ms))
        except (TypeError, ValueError):
            recv_ms = exchange_ms
        age = recv_ms - exchange_ms
        if len(self._age_ms) < 20000:
            self._age_ms.append(float(age))
        feed = self._feeds.get(symbol)
        if feed is None:
            if self.config.symbols and symbol not in self.config.symbols:
                return
            if len(self._feeds) >= self.config.max_symbols:
                return
            if not self._ensure_symbol_filters(symbol):
                return
            feed = _SymbolFeed(symbol, self.config.warmup_bars)
            self._feeds[symbol] = feed
        closed: list = []
        # CORR-DATA: executable observations are stamped with EXCHANGE
        # event time, never receipt/clock time — a late stale event must
        # keep its true old age so the gate sees it as stale.
        event_ts = _EPOCH + timedelta(milliseconds=exchange_ms)
        if channel == "aggTrade":
            payload = event["payload"]
            feed.mark = float(payload["price"])
            feed.mark_ts = event_ts
            closed = feed.agg.on_trade(event)
        else:
            payload = event["payload"]
            bid, ask = float(payload["bid"]), float(payload["ask"])
            if bid > 0 and ask >= bid:
                feed.mark = (bid + ask) / 2
                feed.mark_ts = event_ts
            feed.agg.on_bbo(bid, ask, int(event["exchange_ts_ms"]))
        # Once exchange marks flow, stop echoing the feed mark into the
        # engine: the engine keeps the exchange mark (with its age) instead
        # of our echo. Reference-engine runs always echo (its marks are
        # simulation inputs; it has no event path).
        if feed.mark and (not self._saw_exchange_marks
                          or not hasattr(self.engine, "note_event")):
            self.engine.note_mark(symbol, feed.mark)
        self._drain_engine()
        if self._flatten_pending:
            self._retry_pending_flatten("resume-reconcile-retry")
        self._roll_day_if_needed()
        if self._position is not None:
            # Time exits and flat inference run on market traffic too.
            self._update_position(EngineEvent("mark", None, self.now_utc()))
        for bar in closed:
            if isinstance(bar, BarMissing):
                feed.missing += 1
                feed.bars.append(None)
                feed.missing_cause.append(
                    "id-jump" if bar.gap_before else "quiet-window")
            else:
                feed.bars.append(to_s1_bar(bar))
                feed.missing_cause.append(None)
            n_bars = len(feed.bars)
            if symbol not in self._milestones["first_bar"]:
                iso, rel = self._ms_stamp()
                self._milestones["first_bar"][symbol] = {
                    "ts_utc": iso, "rel_ms": rel, "bars": n_bars}
            if symbol not in self._milestones["ready"] \
                    and feed.ready(self.config.warmup_bars):
                iso, rel = self._ms_stamp()
                self._milestones["ready"][symbol] = {
                    "ts_utc": iso, "rel_ms": rel, "bars": n_bars}
            if symbol not in self._milestones["gate_ready"] \
                    and symbol in self._milestones["ready"]:
                if self._quote_age_gate(symbol) is None:
                    iso, rel = self._ms_stamp()
                    self._milestones["gate_ready"][symbol] = {
                        "ts_utc": iso, "rel_ms": rel}
            if feed.ready(self.config.warmup_bars):
                if not self._warmed:
                    self._warmed = True
                    self._set_state("ready", "warmup-complete")
                self._maybe_admit(
                    self._evaluate_symbol(symbol, adapters, modules),
                    symbol=symbol)
        if closed:
            self._sample_equity("bar")
            # W3-P3: per-bar-close gap-class counters for eligibility joins.
            causes = list(getattr(feed, "missing_cause", []))
            with open(self.workdir / "gap_windows.jsonl", "a") as fh:
                fh.write(json.dumps({
                    "symbol": symbol,
                    "ts_utc": self.now_utc().isoformat(),
                    "window_bars": len(feed.bars),
                    "quiet": sum(1 for c in causes if c == "quiet-window"),
                    "id_jump": sum(1 for c in causes if c == "id-jump"),
                }) + "\n")
            self._event_prepare_flat()
            if self.protection is not None and symbol is not None:
                # Fold one reading per bar-close (bounded, causal):
                # anomaly state advances even with no candidates.
                try:
                    reading, baseline = self._protection_reading(symbol)
                    self.protection.observe(self.now_utc(), reading, baseline)
                except (KeyError, TypeError, ValueError):
                    pass
        health = self.policy.check_health(self._snapshot_account())
        if not health.ok:
            self._halt_entries(";".join(health.reasons))
            self._set_state("halted", ";".join(health.reasons))
        self._run_stop_actions()

    @staticmethod
    def _market_payload_ok(channel: str, payload: Any) -> bool:
        """Structural payload check for market channels (fail-closed)."""
        if not isinstance(payload, dict):
            return False
        if channel == "aggTrade":
            need = ("price",)
        elif channel == "bookTicker":
            need = ("bid", "ask")
        else:
            return True  # depth/markPrice carry their own guards downstream.
        for key in need:
            try:
                value = float(payload[key])
            except (KeyError, TypeError, ValueError):
                return False
            if not math.isfinite(value):
                return False
        return True

    def _ms_stamp(self) -> tuple[str, int]:
        """Millisecond timeline stamp relative to first call (W3-P2)."""
        now = self.now_utc()
        cur = int(now.timestamp() * 1000)
        if self._ms_t0_ms is None:
            self._ms_t0_ms = cur
        return now.isoformat(), cur - self._ms_t0_ms

    def _run_stop_actions(self) -> None:
        """Execute stop ACTION demands: cancel, reduce, alert, recover.

        W3-24H P1: entries are already blocked by halt reasons; this is
        the action side. Cancel requests never clear policy bookings
        (the reservation stands until the venue confirms). The operator
        alert fires once per latch. Emergency clears only through
        reconciled flat — time alone never recovers.
        """
        snapshot = self._snapshot_account()
        actions = self.policy.pending_stop_actions(snapshot)
        if "alert_operator" in actions and not self._stop_alerted:
            self._stop_alerted = True
            self._append_run_file("risk.jsonl", {
                "ts_utc": self.now_utc().isoformat(),
                "wall_ts_utc": datetime.now(timezone.utc).isoformat(),
                "kind": "operator-alert",
                "from_state": "", "to_state": "emergency",
                "reason": "halt:emergency:exposure-reduction"})
        if "cancel_pending_orders" in actions:
            try:
                orders = self.engine.open_orders()
            except (ValueError, KeyError, AttributeError):
                orders = []
            for status in orders:
                if getattr(status, "role", "entry") != "entry":
                    continue
                state = getattr(status, "state", "open")
                if state in ("filled", "rejected", "cancelled", "expired"):
                    continue
                try:
                    self.engine.cancel(status.client_order_id, "stop-action")
                except Exception:
                    pass  # cancel requested; booking stands till confirmed.
        if "reduce_exposure" in actions:
            try:
                self._flatten("stop-action")
            except (ValueError, KeyError, RuntimeError):
                pass  # reduction retried next tick; exposure retained.
        if self._stop_alerted or self.policy.emergency_active():
            # A latch stood: probe reconciled recovery only when no
            # exposure actions remain (cheap bool gate off the hot path).
            if "cancel_pending_orders" not in actions \
                    and "reduce_exposure" not in actions:
                if self.policy.recover_from_emergency(
                        self._snapshot_account()):
                    self._stop_alerted = False
                    self._release_all_exit_only("emergency-recovered")
                    self._set_state("ready", "emergency-recovered")

    def _stop_refresh(self) -> None:
        """Stop the background official-source refresher, if running."""
        tracker = self._freshness
        if tracker is not None:
            try:
                tracker.stop()
            except (RuntimeError, OSError):
                pass

    def _drain_unknown_outcomes(self) -> None:
        """Resolve unknown order outcomes via lookup (W3-24H P4).

        Live adapter only (capability-guarded): every unknown/cancel-
        unknown id is re-queried each supervision tick until resolved.
        Failures map through the adapter error contract: lookup errors
        stay blocking (never auto-cleared), retry-safe faults retry
        next tick, aborts surface as operator alerts. No-ops on paper
        engines without the live surface.
        """
        unknown_ids = getattr(self.engine, "unknown_ids", None)
        lookup = getattr(self.engine, "lookup", None)
        if not callable(unknown_ids) or not callable(lookup):
            return
        try:
            from cryptobot.adapters import caller_action
        except ImportError:
            caller_action = None  # type: ignore[assignment]
        for cid in unknown_ids():
            try:
                lookup(cid)
            except Exception as exc:
                action = caller_action(exc) if caller_action else "retry"
                self._append_run_file("risk.jsonl", {
                    "ts_utc": self.now_utc().isoformat(),
                    "wall_ts_utc": datetime.now(timezone.utc).isoformat(),
                    "kind": "unknown-drain",
                    "from_state": cid, "to_state": action,
                    "reason": f"{type(exc).__name__}:still-blocking"})

    def _build_event_gate(self) -> None:
        """Build the calendar/anomaly protection runtime (W4-24H §12).

        Protected posture (paper + protected profile): local fixture
        load (never a fetch), one blocking official-source verify, then
        a background refresher; entries require verified freshness and
        pass gate + anomaly. Research posture (replay, or any profile
        without [events] protection keys): advisory only — would-block
        is logged, entries flow. Replay additionally applies
        ReplayCutoff at the first event instant in run_replay.
        """
        from cryptobot.events.freshness import (
            FreshnessTracker, default_http_get)
        from cryptobot.events.profiles import load_profile
        from cryptobot.events.runtime import ProtectionRuntime
        from cryptobot.events.sources import (
            CpiSource, FomcSource, adapters_for)
        from cryptobot.events.store import EventStore
        now = self.now_utc()
        try:
            profile = load_profile(self.config.source_path)
        except (ValueError, OSError):
            profile = None
        # W5 blocking fix (release): honor advisory_only, never the
        # posture string. profile.posture is "protected-operational"
        # vs "research-only", so the old == "protected" compare never
        # matched and every Session ran advisory (fail-open). Unknown
        # profile shapes default advisory: nothing is force-blocked on
        # an unreadable profile (availability), while the protected
        # profile now genuinely enforces.
        protected = (
            profile is not None
            and not getattr(profile, "advisory_only", True)
            and self.config.mode == "paper")
        # Release (W3 banked wiring, corrected): construct adapters from
        # the profile gate's required_sources so the built set can never
        # skew from the required set. adapters_for returns constructed
        # adapters and raises ValueError on unknown names (fail-closed);
        # the fallback preserves availability on unreadable profiles and
        # the gate then blocks honestly with an explicit stale-source
        # reason for the missing name.
        required = getattr(getattr(profile, "gate", None),
                           "required_sources", ("fomc", "cpi"))
        try:
            srcs = adapters_for(required)
        except (TypeError, ValueError):
            srcs = [FomcSource(), CpiSource()]
        tracker = FreshnessTracker(
            self.workdir / "event_source_state.json", srcs)
        store = EventStore()
        tracker.local_load(store, now)
        results = None
        if protected:
            # One blocking verify at startup; entries stay blocked
            # until a refresh succeeds (gate requires fresh sources).
            results = tracker.refresh_once(store, default_http_get, now)
        runtime = ProtectionRuntime(
            store,
            getattr(profile, "gate", None),
            getattr(profile, "anomaly", None),
            self.workdir / "protection_evidence.jsonl",
            advisory_only=not protected)
        if results is not None:
            # Release: pass RefreshResult objects through; log_refresh
            # serializes them. (The old dict projection never fired while
            # the posture fail-open kept results None.)
            runtime.log_refresh(now, results)
        self.protection = runtime
        self.event_gate = runtime.gate  # pre-window sweep compat.
        self._freshness = tracker
        if protected:
            interval = float(profile.refresh_interval_s)
            tracker.start(store, default_http_get, interval_s=interval,
                          now_utc=self.now_utc,
                          on_result=lambda res: runtime.log_refresh(
                              self.now_utc(), res))

    def _protection_reading(self, symbol: str):
        """Measured anomaly inputs for one symbol (W4-24H §12).

        Unmeasured inputs stay None (policy skips them); only observed
        quantities feed decisions. Returns (reading, baseline).
        """
        from cryptobot.events.anomaly import AnomalyBaseline, AnomalyReading
        spread = depth_ratio = abs_ret = latency = None
        try:
            book, _, _ = book_flow_for(
                symbol, int(self.now_utc().timestamp() * 1000),
                self._depth_store)
            if book is not None:
                spread = float(book.spread_bps)
        except (KeyError, TypeError, ValueError):
            pass
        feed = self._feeds.get(symbol)
        bars = list(getattr(feed, "bars", []) or [])
        closes = [b.close for b in bars[-2:] if b is not None
                  and getattr(b, "close", 0) > 0]
        if len(closes) == 2:
            abs_ret = abs(closes[1] / closes[0] - 1.0) * 1e4
        if self._age_ms:
            latency = float(self._age_ms[-1])
        unknown = getattr(self.engine, "unknown_ids", None)
        errors = self._exchange_errors
        if callable(unknown):
            try:
                errors += len(unknown())
            except Exception:
                pass
        return (AnomalyReading(
            spread_bps=spread, book_depth_ratio=depth_ratio,
            abs_return_bps=abs_ret, latency_ms=latency,
            exchange_error_count=errors), AnomalyBaseline())

    def _event_prepare_flat(self) -> None:
        """Pre-window sweep: cancel unfilled entries ahead of event windows.

        Acts when a window opens within 120s. Filled positions keep their
        protection (stops still guard); only unfilled entry orders are
        cancelled and their holds released.
        """
        if self.event_gate is None or self._position is None:
            return
        upcoming = self.event_gate.upcoming(self.now_utc(), 120)
        if not upcoming:
            return
        pos = self._position
        entry_id = pos.get("entry_id") or pos.get("entry_pre_id")
        if entry_id is None:
            return
        entry = self._tracked_status(entry_id)
        if entry is not None and entry.filled_qty > 1e-12:
            return  # filled: protection stays on.
        try:
            self.engine.cancel(entry_id, "event-prepare-flat")
        except (ValueError, KeyError):
            pass  # already gone; clear + release below still apply.
        # NOTE (READY-§5 scope): clear-on-request is the pinned EV-001
        # contract. A fill landing between the cancel request and this
        # clear is the genuine sub-latency cancel/fill race: it still
        # books to ledger+booked and blocks new entries (fail-closed
        # direction), but resurrection tracking is out of scope here.
        self.policy.release(pos["reservation_id"])
        self._position = None
        self._set_state("ready", "event-prepare-flat")
        self.store.checkpoint(
            self.run_id, "event-prepare-flat",
            {"event_ids": [u.event.event_id for u in upcoming]})

    def _reconcile_funding(self) -> None:
        """Compare engine-settled vs ledger funding totals (V-008 §7).

        Agree -> "funding-reconciled" checkpoint. Mismatch -> loud
        "funding-mismatch" checkpoint + exit-only halt (entries blocked,
        never silent). Engines without settled totals skip silently.
        """
        settled_total = getattr(self.engine, "settled_funding_total", None)
        if not callable(settled_total):
            return
        try:
            engine_total = float(settled_total())
        except (ValueError, KeyError, AttributeError, TypeError):
            return
        ledger_total = self.ledger.funding_net()
        if abs(engine_total - ledger_total) <= 1e-9:
            self.store.checkpoint(
                self.run_id, "funding-reconciled",
                {"engine_total": engine_total, "ledger_total": ledger_total})
            return
        self.store.checkpoint(
            self.run_id, "funding-mismatch",
            {"engine_total": engine_total, "ledger_total": ledger_total})
        self._halt_entries("funding-mismatch")
        self._set_state("halted", "funding-mismatch")

    def _roll_day_if_needed(self) -> None:
        today = accounting_date(self.now_utc()).isoformat()
        if self._day is not None and today != self._day:
            marked = self.ledger.marked_equity(self._reference_mark())
            self.policy.reconcile_day(marked, self.ledger.total_flows())
            self._release_all_exit_only("day-reconciled")
            self._set_state("ready", "day-reconciled")
            self._sample_equity("day-roll", force=True)
            self.store.checkpoint(self.run_id, "day-roll",
                                  {"day": today, "marked": marked})
        self._day = today

    def _refresh_filters_if_stale(self) -> None:
        """Re-arm paper filters when the record outlives its max age.

        The REST fetch runs off-thread (AsyncCall); the control thread
        only installs a finished fetch (single owner preserved).
        """
        if self._filter_call is not None:
            done, result = self._filter_call.poll()
            if not done:
                return
            self._filter_call = None
            from .filters import FilterError
            try:
                if isinstance(result, BaseException):
                    raise result
                self._apply_run_filters(*result)
            except (FilterError, ValueError, OSError) as exc:
                self._halt_entries(f"filters-refresh:{exc}")
                self._set_state("halted", "filters:refresh-failed")
            return
        if self.config.mode != "paper" or not self.policy.config.run_mode:
            return
        asof = self.policy.config.filters_asof_utc
        if asof is None:
            return
        age = (self.now_utc() - asof).total_seconds()
        if age < self.config.filters_max_age_s:
            return
        symbols = sorted(self._feeds)
        if not symbols:
            return
        from .filters import build_run_filters
        cap = self.config.max_notional_cap_usdt
        self._filter_call = AsyncCall(
            lambda: build_run_filters(symbols, max_notional_cap_usdt=cap),
            name="filters")

    def _apply_run_filters(self, filters: dict, asof: Any) -> None:
        """Install fetched venue filters on the control thread."""
        from dataclasses import replace
        merged = dict(self.policy.config.instrument_filters)
        merged.update(filters)
        self.policy.config = replace(
            self.policy.config, instrument_filters=merged,
            filters_asof_utc=asof, run_mode=True)
        self.store.checkpoint(self.run_id, "filters-armed",
                              {"symbols": sorted(filters),
                               "asof_utc": asof.isoformat()})

    # -- persistence / recovery -------------------------------------------------
    def _write_run_identity(self, *, dataset: str, window_start_utc: datetime,
                            window_end_utc: datetime,
                            manifest_extra: dict[str, Any] | None = None) -> None:
        """Write run-identity files for the reporting package (B6/B9).

        ``config.toml`` snapshots [run] identity (dataset, window,
        starting equity, mode, strategy when exactly one is enabled) and
        ``dataset_manifest.json`` carries the dataset manifest. Identity
        resolves config-first, manifest-second in
        ``cryptobot.reporting.load_run``; both files are rewritten at run
        end so resume runs stay accurate.
        """
        def toml_str(value: str) -> str:
            return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
        run_lines = [
            "[run]",
            f"dataset = {toml_str(dataset)}",
            f"window_start_utc = {toml_str(window_start_utc.isoformat())}",
            f"window_end_utc = {toml_str(window_end_utc.isoformat())}",
            f"starting_equity = {self.config.paper_capital_usdt!r}",
            f"mode = {toml_str(self.config.mode)}",
        ]
        enabled = list(self.config.strategies_enabled)
        if len(enabled) == 1:
            run_lines.append(f"strategy = {toml_str(enabled[0])}")
        (self.workdir / "config.toml").write_text(
            "\n".join(run_lines) + "\n", encoding="utf-8")
        manifest: dict[str, Any] = {
            "dataset": dataset,
            "window": (f"{window_start_utc.isoformat()}"
                       f"..{window_end_utc.isoformat()}"),
        }
        if manifest_extra:
            manifest.update(manifest_extra)
        (self.workdir / "dataset_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    def _persist_local_state(self) -> None:
        self.ledger.save(self.workdir / "ledger.json")
        self.store.checkpoint(self.run_id, "local-state",
                              {"last_seq": self._last_seq,
                               "position": self._position is not None,
                               "events_seen": self._events_seen,
                               "intents_admitted": self._admitted,
                               "reject_counts": dict(self._reject_counts)})

    def _rebuild_booking_state(self) -> None:
        """Rebuild idempotency + replay unbooked anchors (v1 §4).

        Applied execution ids and per-order cumulative quantities come
        from persisted execution events (immutable anchor). Rows the
        crash left persisted-but-unbooked replay now through the same
        exec-gated booking (policy + ledger converge; fills.jsonl rows
        append only when absent). Command seq continues past existing
        rows; known reservations seed from policy recovery state.
        """
        for rid in self.policy.live_reservations():
            self._known_reservations.add(rid)
        for rid in self.policy.unresolved_ids():
            self._known_reservations.add(rid)
        for rid in self.policy.booked_reservations():
            self._known_reservations.add(rid)
        try:
            for cmd in self.store.open_commands(self.run_id):
                rid = (cmd.get("payload") or {}).get("reservation_id")
                if rid:
                    self._known_reservations.add(rid)
        except (ValueError, KeyError):
            pass
        try:
            rows = self.store.read_events(self.run_id)
        except (ValueError, KeyError):
            rows = []
        fills_have: set[str] = set()
        fills_path = self.workdir / "fills.jsonl"
        if fills_path.exists():
            try:
                for line in fills_path.read_text(
                        encoding="utf-8").splitlines():
                    if line.strip():
                        fills_have.add(json.loads(line).get("execution_id"))
            except (OSError, ValueError):
                pass
        for row in rows:
            payload = row.get("payload") or {}
            if row.get("kind") in ("fill", "fill-staged"):
                exec_id = row.get("execution_id")
                rid = payload.get("reservation_id") or ""
                self._applied_exec.add(exec_id)
                cid = payload.get("client_order_id") or ""
                try:
                    qty = float(payload.get("qty") or 0.0)
                except (TypeError, ValueError):
                    qty = 0.0
                if cid:
                    self._order_cum[cid] = self._order_cum.get(cid, 0.0) + qty
                if rid and rid in self._known_reservations:
                    try:
                        self.policy.note_fill_delta(
                            rid, exec_id, payload.get("instrument", ""),
                            payload.get("side", ""), payload.get("qty", 0.0),
                            payload.get("price", 0.0), payload.get("fee", 0.0),
                            row.get("ts_utc", ""))
                    except ValueError:
                        pass  # already booked, or invalid row: gates decide.
                    try:
                        # The policy gate returns before the ledger when
                        # policy already booked: heal the ledger
                        # explicitly (exec-gated: no double-book).
                        self.ledger.note_fill(
                            exec_id, payload.get("instrument", ""),
                            payload.get("side", ""), payload.get("qty", 0.0),
                            payload.get("price", 0.0), payload.get("fee", 0.0),
                            row.get("ts_utc", ""))
                    except ValueError:
                        pass
                    if exec_id not in fills_have:
                        self._append_run_file("fills.jsonl", {
                            "execution_id": exec_id,
                            "client_order_id": cid or f"adopted:{rid}",
                            "instrument": payload.get("instrument", ""),
                            "side": payload.get("side", ""),
                            "qty": payload.get("qty", 0.0),
                            "price": payload.get("price", 0.0),
                            "fee": payload.get("fee", 0.0),
                            "liquidity": payload.get("liquidity", "taker"),
                            "ts_utc": row.get("ts_utc", "")})
                        fills_have.add(exec_id)
                elif cid:
                    # Persisted-but-never-booked foreign fill: the
                    # pre-crash block restarts with the session.
                    self._block_booking(f"unknown-fill:{cid}")
            elif row.get("kind") == "funding":
                try:
                    self.policy.note_funding(
                        row.get("execution_id"), payload.get("amount", 0.0),
                        row.get("ts_utc", ""))
                except ValueError:
                    pass  # already booked, or invalid row: gates decide.
        try:
            self._cmd_seq = self.store.command_count(self.run_id)
        except (ValueError, KeyError):
            pass

    def _resume_state(self) -> None:
        run = self.store.get_run(self.run_id)
        if run is None:
            raise KeyError(f"unknown run {self.run_id}")
        ledger_path = self.workdir / "ledger.json"
        if ledger_path.exists():
            self.ledger = Ledger.from_dict(
                json.loads(ledger_path.read_text(encoding="utf-8")))
            self.policy.bind_ledger(self.ledger)
        # Cursor + clock: continue after the last checkpointed event.
        rows = self.store._db.execute(
            "SELECT payload FROM checkpoints WHERE run_id=? AND kind='cursor'"
            " ORDER BY id DESC LIMIT 1", (self.run_id,)).fetchone()
        if rows is not None:
            self._last_seq = int(json.loads(rows[0]).get("last_seq", 0))
        self._rebuild_booking_state()
        # Recover the engine from its own journal (durable source);
        # adopted fills route through the ONE handler (bound above).
        self.engine.recover(self._engine_handler)
        self._flush_staged_deltas()
        self._reconcile_commands()
        self._set_state("recovering", f"resume-from-seq:{self._last_seq}")
        self.store.checkpoint(self.run_id, "resume",
                              {"last_seq": self._last_seq})

    def _resume_live(self) -> None:
        """Recover a live paper run: ledger + risk state + engine journal.

        Sim orders never survive restart, so any recovered ledger exposure
        is flattened immediately (fresh mark) before the loop continues.
        """
        run = self.store.get_run(self.run_id)
        if run is None:
            raise KeyError(f"unknown run {self.run_id}")
        # W3-30MIN §4: restart enters reconciliation before new entries.
        self._reconciled = False
        ledger_path = self.workdir / "ledger.json"
        if ledger_path.exists():
            self.ledger = Ledger.from_dict(
                json.loads(ledger_path.read_text(encoding="utf-8")))
            self.policy.bind_ledger(self.ledger)
        self._rebuild_booking_state()
        self.engine.recover(self._engine_handler)
        self._flush_staged_deltas()
        self._reconcile_commands()
        try:
            pending = self.store.open_commands(self.run_id)
        except (ValueError, KeyError):
            pending = []
        self._reconciled = not any(
            c.get("status") == "unknown" for c in pending)
        if not self._reconciled:
            self.store.checkpoint(self.run_id, "resume-blocked", {
                "reason": "unknown-commands"})
        self._day = accounting_date(self.now_utc()).isoformat()
        try:
            self._run_start_utc = datetime.fromisoformat(
                run["started_utc"]) if run.get("started_utc") else None
        except ValueError:
            self._run_start_utc = None
        self._set_state("recovering", "live-resume")
        self.store.checkpoint(self.run_id, "live-resume",
                              {"position_qty": self.ledger.position_qty()})
        if self.ledger.has_position():
            # Flatten the orphaned exposure; retry each cycle until flat
            # (marks may not exist yet at resume time).
            self._flatten_pending = True
            self._retry_pending_flatten("resume-reconcile")

    # -- live paper ------------------------------------------------------------

    def tick_latency_ms(self) -> dict[str, float | int]:
        """p50/p95/p99 of control-step durations (W3-30MIN §4 drill)."""
        samples = sorted(self._tick_ms)
        if not samples:
            return {"n": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0,
                    "max": 0.0}
        pick = lambda p: samples[min(len(samples) - 1,
                                     int(p * len(samples)))]
        return {"n": len(samples), "p50": pick(0.50), "p95": pick(0.95),
                "p99": pick(0.99), "max": samples[-1]}

    def _poll_async_prime(self) -> None:
        """Install a finished stall-resync fetch on the control thread."""
        call = self._prime_call
        if call is None:
            return
        done, result = call.poll()
        if not done:
            return
        self._prime_call = None
        if isinstance(result, BaseException):
            prime = {"source": "rest:fapi/v1/depth", "applied": 0,
                     "synced": [], "primed": [],
                     "failed": {"_": {"stage": "async",
                                      "error": type(result).__name__}}}
        else:
            prime = self._install_depth_snapshots(result)
        self.store.checkpoint(self.run_id, "stall-resync", prime)

    def _control_step(self, event: Any | None, producer: Any | None,
                      adapters: dict[str, Any], modules: dict[str, Any],
                      ctx: dict[str, Any], deadline_mono: float,
                      expect_class: str) -> str | None:
        """One control wake: event + position + supervision (W3-30MIN §4).

        Runs on every tick (event or 250ms timeout), independent of feed
        progress: a blocked producer only yields empty wakes, never a
        stalled supervisor. Returns an end reason, or None to continue.
        ``producer`` may be None in deterministic tests (no feed calls).
        """
        if producer is not None:
            producer.raise_if_failed()
            self._dropped_feed = producer.dropped
            if event is TIMEOUT:
                # Tick wake (no queued item). Feed-ended only when the
                # pump is done AND the queue is drained; an item that
                # lands after the timeout is picked up next wake.
                if producer.finished and producer.qsize == 0:
                    return "feed-ended"
                event = None
        if event is not None:
            if event.get("input_class", expect_class) != expect_class:
                return None
            self._ingest(event, adapters, modules)
            self._events_seen += 1
            ctx["last_market_mono"] = time.monotonic()
        # Position management on every wake: time exits and flat
        # inference cannot wait for the next market event.
        self._advance_engine_clock()
        self._drain_engine(bounded=True)
        if self._position is not None:
            self._update_position(EngineEvent("tick", None, self.now_utc()))
        now_mono = time.monotonic()
        self._poll_async_prime()
        if now_mono - ctx["last_market_mono"] > 60.0:
            ctx["last_market_mono"] = now_mono
            self._append_run_file("risk.jsonl", {
                "ts_utc": self.now_utc().isoformat(),
                "wall_ts_utc": datetime.now(timezone.utc).isoformat(),
                "kind": "stream-stall",
                "from_state": "streaming", "to_state": "resync",
                "reason": "no market events for 60s; re-priming books"})
            if self._prime_call is None:  # reconnect off the control thread.
                self._prime_call = AsyncCall(self._fetch_depth_snapshots,
                                             name="prime")
        # Supervision on EVERY tick (stop recognition cannot wait for
        # traffic); heartbeat/persist stay on the slow beat.
        stop_reason = self._supervise(ctx, now_mono)
        if stop_reason is not None:
            return stop_reason
        if now_mono >= deadline_mono:
            return "duration-elapsed"
        return None

    def _supervise(self, ctx: dict[str, Any],
                   now_mono: float) -> str | None:
        """Position + risk supervision shared by the loop and control_tick."""
        tick = self.policy.monitor_tick(account=None)
        if not tick.ok:
            self._halt_entries(";".join(tick.reasons))
            self._set_state("halted", ";".join(tick.reasons))
        self._run_stop_actions()
        self._drain_unknown_outcomes()
        self._refresh_filters_if_stale()
        if now_mono - ctx["last_beat"] >= 30.0:
            ctx["last_beat"] = now_mono
            self.store.heartbeat(self.run_id, self._pid)
            self._persist_local_state()
        stop = self._stop_flag or self.store.stop_requested(self.run_id)
        if stop is not None:
            if stop == "flatten":
                self._flatten("operator-stop-flatten")
                self._drain_engine()
            return f"operator-stop:{stop}"
        return None

    def control_tick(self) -> str | None:
        """Feed-independent supervision tick (W3-30MIN §4).

        Runs the same supervision as the live loop (risk monitor, stop
        actions, unknown-outcome drain, operator-stop recognition)
        without touching the feed. Control-thread only. Returns an
        operator-stop reason, or None.
        """
        if self._tick_ctx is None:
            self._tick_ctx = {"last_beat": 0.0,
                              "last_market_mono": time.monotonic()}
        return self._supervise(self._tick_ctx, time.monotonic())

    def run_live(self, event_iter: Any, *, duration_s: int,
                 expect_class: str = "observed-public",
                 resume: bool = False) -> dict[str, Any]:
        """Live-feed paper loop over a bridge event iterator (E-007).

        Same _ingest path as replay (strategies/selector/exit/risk), wall
        clock, wall duration budget. No Binance order submission exists on
        this path: fills come from the injected paper engine only.
        Resume continues wall-now with recovered state (no live cursor);
        any recovered exposure is flattened before continuing.
        """
        if self.config.mode not in ("paper", "prod"):
            raise ValueError("run_live needs a paper/prod-mode config")
        # Single-instance lock (contract v1 §4): held until close().
        self.store.acquire_lock()
        if resume:
            self._resume_live()
        else:
            self.store.create_run(self.run_id, self.config.mode,
                                  self.config.fingerprint,
                                  str(self.workdir), self._pid)
            self.policy.reconcile_day(self.config.paper_capital_usdt, 0.0)
            self._day = accounting_date(self.now_utc()).isoformat()
            self._run_start_utc = self.now_utc()
            self.store.checkpoint(self.run_id, "open",
                                  {"equity": self.config.paper_capital_usdt})
        self._init_run_files()
        prime = self._prime_live_books()
        self.store.checkpoint(self.run_id, "depth-prime", prime)
        adapters, modules = self._strategy_adapters()
        self._set_state("warming", "paper-start")
        deadline = time.monotonic() + duration_s
        tick_s = self.config.control_tick_s
        producer = BoundedProducer(event_iter,
                                   maxsize=self.config.feed_queue_max)
        # Watchdog: stream-stall detector. Heartbeats prove the loop is
        # awake; only real market events prove the venue feed is alive.
        # 60s of market silence = resync books (P3-style reaction), never
        # a silent stall. Crypto majors tick every second in practice.
        ctx: dict[str, Any] = {"last_beat": 0.0,
                               "last_market_mono": time.monotonic()}
        end_reason = "duration-elapsed"
        try:
            while True:
                event = producer.poll(tick_s)
                # R1: owner-thread drain of the attached private user
                # stream (if any): pump-thread input applies here on
                # the owner, never on the pump thread itself.
                if self._user_stream_attachment is not None:
                    self._user_stream_attachment.drain_owner()
                # Control-step latency is decision work, not the poll
                # wait: the timer starts after the tick wake fires.
                step_start = time.perf_counter()
                reason = self._control_step(event, producer, adapters,
                                            modules, ctx, deadline,
                                            expect_class)
                self._tick_ms.append((time.perf_counter() - step_start)
                                     * 1000.0)
                if reason is not None:
                    end_reason = reason
                    break
        finally:
            producer.close()
            self._dropped_feed = producer.dropped
        if self._prime_call is not None:
            # Shutdown drain: install the in-flight stall resync (bounded
            # by the run budget; never hangs shutdown).
            wait_s = min(deadline_remaining_s(default=5.0) or 0.0, 5.0)
            self._prime_call.wait(timeout=wait_s)
            self._poll_async_prime()
        if self._position is not None and end_reason == "duration-elapsed":
            self._flatten("duration-end")
            self._drain_engine()
        self._set_state("stopping", end_reason)
        # Final full drain: live wakes are bounded, so sweep the backlog
        # (bounded rounds; a pathological flood cannot hang shutdown).
        for _ in range(25):
            if self._drain_engine() == 0:
                break
        self._persist_local_state()
        self._sample_equity("run-end", force=True)
        self._write_run_identity(
            dataset="live-public-feed",
            window_start_utc=self._run_start_utc or self.now_utc(),
            window_end_utc=self.now_utc(),
            manifest_extra={"note": "live public feed; no frozen manifest"})
        self._set_state("stopped", "run-complete")
        iso, rel = self._ms_stamp()
        self._milestones["capture_end"] = {"ts_utc": iso, "rel_ms": rel}
        report = self._build_report("live-public-feed", expect_class,
                                    mode=self.config.mode)
        (self.workdir / "report.json").write_text(json.dumps(report, indent=2))
        (self.workdir / "report.md").write_text(self._render_report(report))
        self._stop_refresh()
        return report

    # -- report ------------------------------------------------------------------
    def _build_report(self, capture: str, expect_class: str,
                      *, mode: str = "replay") -> dict[str, Any]:
        mark = self._reference_mark()
        closing = self.ledger.marked_equity(mark)
        return {
            "run_id": self.run_id, "mode": mode, "input_class": expect_class,
            "capture": capture, "config_fingerprint": self.config.fingerprint,
            "fee_schedule": {"label": self.config.fee_label,
                             "taker_bps": self.config.taker_bps,
                             "funding_bps_per_8h": self.config.funding_bps_per_8h},
            "execution_model": self.engine.model_label,
            "simulator_assumptions": list(self.engine.assumptions),
            "opening_equity": self.config.paper_capital_usdt,
            "closing_equity": closing,
            "net_return_pct": (closing / self.config.paper_capital_usdt - 1) * 100,
            "paid_costs": self.ledger.paid_costs(),
            "funding_net": self.ledger.funding_net(),
            "realised": self.ledger.net_realised(),
            "open_position": self.ledger.has_position(),
            "position_qty": self.ledger.position_qty(),
            "events_seen": self._events_seen,
            "symbols": sorted(self._feeds),
            "intents_admitted": self._admitted,
            "reject_counts": dict(sorted(self._reject_counts.items())),
            "depth_resyncs": dict(sorted(self._resyncs_seen.items())),
            "store_counts": self.store.counts(self.run_id),
            "latency_ms": {
                "feed_age": _summarize(self._age_ms),
                "strategy_eval": _summarize(self._eval_ms),
                "selector_decide": _summarize(self._decide_ms),
                "submit_to_fill_modeled": _summarize(self._dispatch_ms),
                "control_step": _summarize(list(self._tick_ms))},
            "dropped_feed_events": self._dropped_feed,
            "workdir": str(self.workdir),
            "milestones": self._milestone_report(),
        }

    def _milestone_report(self) -> dict[str, Any]:
        """Native replay timeline for W3 eligibility joins (W3-P2)."""
        out = {k: (dict(v) if isinstance(v, dict) else v)
               for k, v in self._milestones.items()}
        end = self._milestones.get("capture_end") or {}
        if end:
            eligible = {}
            for symbol, gate in self._milestones["gate_ready"].items():
                eligible[symbol] = (
                    end["rel_ms"] - gate["rel_ms"]) / 1000.0
            out["eligible_s"] = eligible
        return out

    def _render_report(self, report: dict[str, Any]) -> str:
        lines = [f"# {report['mode'].title()} report {report['run_id']}", "",
                 f"Capture: {report['capture']} ({report['input_class']})",
                 f"Config: {report['config_fingerprint']} | "
                 f"engine: {report['execution_model']} (replay-only)",
                 f"Fees: {report['fee_schedule']} (labeled simulation rates)",
                 "", "## Equity",
                 f"open {report['opening_equity']:.4f} -> "
                 f"close {report['closing_equity']:.4f} USDT "
                 f"({report['net_return_pct']:+.4f}%)",
                 f"paid costs {report['paid_costs']:.4f}, funding "
                 f"{report['funding_net']:+.4f}, realised {report['realised']:+.4f}",
                 f"open position: {report['open_position']} "
                 f"(qty {report['position_qty']})", "",
                 "## Flow",
                 f"events {report['events_seen']}, symbols "
                 f"{', '.join(report['symbols']) or '(none)'}",
                 f"intents admitted {report['intents_admitted']}",
                 "rejects:"]
        for reason, count in report["reject_counts"].items():
            lines.append(f"- {reason}: {count}")
        lines += ["", "## Latency (ms)",
                  json.dumps(report["latency_ms"], indent=2), "",
                  "## Simulator assumptions", ""]
        lines += [f"- {a}" for a in report["simulator_assumptions"]]
        lines += ["", "Reference-engine replay economics are loop mechanics,",
                  "not profitability evidence.", ""]
        return "\n".join(lines)
