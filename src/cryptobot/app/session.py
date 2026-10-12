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
from cryptobot.risk.rounding import ceil_to_tick, floor_to_tick
from cryptobot.risk.types import AccountSnapshot, Approved, RiskConfig

from .config import AppConfig
from .engine import EngineEvent, EngineOrder
from .reference import ReferenceEngine
from .store import RunStore

__all__ = ["Session", "ReplayClock", "WallClock", "STRATEGY_ARMS"]

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

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
                outcome_sink=self.policy, taker_bps=config.taker_bps,
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
        self._warmed = False
        self._last_seq = 0
        self._last_equity_sample: datetime | None = None
        self._equity_dirty = True
        self._run_start_utc: datetime | None = None
        self._crash_after: int | None = None
        self._stop_flag: str | None = None
        self._pid = pid

    # -- lifecycle ---------------------------------------------------------
    def _set_state(self, state: str, reason: str = "") -> None:
        try:
            old = (self.store.get_run(self.run_id) or {}).get("state", "")
        except Exception:
            old = ""
        self.store.set_state(self.run_id, state, reason)
        self._append_run_file("risk.jsonl", {
            "ts_utc": self.now_utc().isoformat(),
            "wall_ts_utc": datetime.now(timezone.utc).isoformat(),
            "kind": "run-state",
            "from_state": old, "to_state": state, "reason": reason})

    # -- run-mode filter arming (paper only) -----------------------------------
    def arm_run_mode(self, symbols: list[str], *, http_get: Any = None) -> None:
        """Fetch live venue filters and arm strict run mode. Fail-closed."""
        from dataclasses import replace

        from .filters import build_run_filters
        filters, asof = build_run_filters(
            symbols,
            max_notional_cap_usdt=self.config.max_notional_cap_usdt,
            http_get=http_get)
        merged = dict(self.policy.config.instrument_filters)
        merged.update(filters)
        self.policy.config = replace(
            self.policy.config, instrument_filters=merged,
            filters_asof_utc=asof, run_mode=True)
        self.store.checkpoint(self.run_id, "filters-armed",
                              {"symbols": sorted(filters),
                               "asof_utc": asof.isoformat()})

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
            self.engine.set_exit_only(True, f"filters:{exc}")
            self._set_state("halted", f"filters:unavailable:{symbol}")
            self.store.checkpoint(self.run_id, "filters-blocked",
                                  {"symbol": symbol, "reason": str(exc)})
            return False
        return True

    def _snapshot_account(self) -> AccountSnapshot:
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
        _m, _s, _ts = self._reference_mark_full()
        mark_age: float | None = None
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
        for name in self.config.strategies_enabled:
            try:
                adapters[name] = get_adapter(name)
            except KeyError:
                continue
            if name == "S5":
                continue  # S5 has no evaluate_bar variant path.
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
        view = MarketView(
            instrument=symbol, bars=tuple(bars), now_utc=self.now_utc(),
            depth=depth, flow=flow_view, quality=quality,
            quality_reason=";".join(reasons))
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
            if outcome.intent is not None:
                out.append(Candidate(outcome.intent.strategy, outcome.intent))
            else:
                out.append(Candidate(adapter.strategy_id, None,
                                     f"strategy:{outcome.reject_reason}"))
        if self.config.strategies_arms == "all":
            for name, module in modules.items():
                base, all_arms = STRATEGY_ARMS[name]
                for arm in all_arms:
                    if arm == base:
                        continue  # base covered by the adapter above.
                    start = time.perf_counter()
                    try:
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

    def _maybe_admit(self, candidates: list[Candidate]) -> None:
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
                    self._note_reject(reason, strat)
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
            self._note_reject(reason, strat, inst, side)
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
        verdict = self.policy.evaluate(intent, self._snapshot_account())
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
                self.engine.set_exit_only(True, verdict.reason)
                self._set_state("halted", verdict.reason)
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
            instrument=intent.instrument, side=side, qty=verdict.qty,
            kind="MARKET", reservation_id=verdict.reservation_id,
            expire_at_utc=intent.entry_expiry_utc)
        submit_protected = getattr(self.engine, "submit_protected", None)
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
        self._position = {"reservation_id": verdict.reservation_id,
                          "instrument": intent.instrument,
                          "side": intent.side.value,
                          "entry_pre_id": pre_id, "entry_id": None,
                          "legs": [], "stop": stop, "target": target,
                          "time_exit": time_exit, "legacy_exit": legacy,
                          "protected": False, "protect_attempts": 0,
                          "entry_cap": cap}
        self._admitted += 1
        self._set_state("holding", f"admitted:{intent.evidence_ref}")
        self.store.checkpoint(self.run_id, "admit", {
            "reservation_id": verdict.reservation_id, "qty": verdict.qty,
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
            self._on_engine_event(event)
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

    def _on_engine_event(self, event: EngineEvent) -> None:
        payload = event.payload
        if event.kind == "fill":
            submitted = self._submit_ts.pop(payload.client_order_id, None)
            if submitted is None:
                # Fill arrived before the submit-time id resolved; match
                # via the engine's own mapping (protocol-only).
                for key in list(self._submit_ts):
                    if self.engine.resolve(key) == payload.client_order_id:
                        submitted = self._submit_ts.pop(key)
                        break
            if submitted is not None:
                self._dispatch_ms.append(
                    (payload.ts_utc - submitted).total_seconds() * 1000)
            self._append_run_file("fills.jsonl", {
                "execution_id": payload.execution_id,
                "client_order_id": payload.client_order_id,
                "instrument": payload.instrument, "side": payload.side,
                "qty": payload.qty, "price": payload.price, "fee": payload.fee,
                "liquidity": payload.liquidity,
                "ts_utc": payload.ts_utc.isoformat()})
            self._equity_dirty = True
            self.store.record_event(
                self.run_id, payload.execution_id, "fill",
                {"client_order_id": payload.client_order_id,
                 "instrument": payload.instrument, "side": payload.side,
                 "qty": payload.qty, "price": payload.price, "fee": payload.fee,
                 "liquidity": payload.liquidity},
                payload.ts_utc.isoformat())
        elif event.kind in ("cancel", "reject", "expire"):
            self.store.record_event(
                self.run_id, payload.client_order_id, event.kind,
                {"instrument": payload.instrument, "reason": payload.reason},
                payload.ts_utc.isoformat())
        elif event.kind == "funding":
            # Engine-settled funding reaches the ledger (idempotent by
            # event_id); without this backtests silently book funding 0.
            self.policy.note_funding(payload.event_id, payload.amount,
                                     payload.ts_utc.isoformat())
            self._equity_dirty = True
            self.store.record_event(
                self.run_id, payload.event_id, "funding",
                {"instrument": payload.instrument,
                 "amount": payload.amount},
                payload.ts_utc.isoformat())
            self._reconcile_funding()
        self._update_position(event)

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
        statuses = {s.client_order_id: s for s in self.engine.open_orders()}
        entry = statuses.get(pos["entry_id"] or "")
        if entry is not None and entry.filled_qty > 1e-12 and not pos["protected"]:
            self._ensure_protection(pos)
        # Time exit: cancel legs, flatten the remainder at market.
        if (self.ledger.has_position()
                and self.now_utc() >= pos["time_exit"]):
            self._flatten("time-exit")
        # Flat inference: filled entry + ledger flat + no live reservation orders.
        if entry is not None and entry.filled_qty > 1e-12:
            live = [s for s in statuses.values()
                    if s.reservation_id == pos["reservation_id"]
                    and s.state not in ("filled", "rejected", "cancelled", "expired")]
            if not self.ledger.has_position() and not live:
                # Release the risk hold: booked exposure nets zero, so this
                # frees the reservation (or lifts a zero-net unresolved
                # leftover). Without it the next approval blocks on
                # exposure:unresolved forever (Q-007 finding).
                self.policy.note_flat()
                self.policy.release(pos["reservation_id"])
                self._position = None
                self._set_state("ready", "position-flat")
        # Entry died with zero fills: free the risk hold, then clear.
        if entry is not None and entry.filled_qty <= 1e-12 and entry.state in (
                "rejected", "cancelled", "expired"):
            self.policy.release(pos["reservation_id"])
            self._position = None
            self._set_state("ready", f"entry-dead:{entry.state}")

    def _ensure_protection(self, pos: dict[str, Any]) -> None:
        """Attach + VERIFY required stop cover (B8 protection invariant).

        protected flips True only when the stop leg is acknowledged and
        verified live with covering quantity. On failure: entries stay
        blocked (position retained), retries are bounded (3), then a
        reduce-only emergency close is attempted. Never falsely protected.
        """
        entry_id = pos["entry_id"] or ""
        if not pos["legs"]:
            if pos["protect_attempts"] >= 3:
                self.store.checkpoint(self.run_id, "protection-emergency",
                                      {"attempts": pos["protect_attempts"]})
                self._flatten("protection-emergency-close")
                self._drain_engine()
                return
            pos["protect_attempts"] += 1
            try:
                pos["legs"] = self.engine.attach_protection(
                    entry_id, pos["stop"], pos["target"])
            except (ValueError, KeyError) as exc:
                self.store.checkpoint(self.run_id, "protection-failed",
                                      {"attempt": pos["protect_attempts"],
                                       "reason": str(exc)})
                return
        # Acknowledgement gate: queued legs resolve on a later drain.
        resolved = [self.engine.resolve(lid) for lid in pos["legs"]]
        if any(rid is None for rid in resolved):
            return
        pos["legs"] = resolved
        # Verify against a FRESH snapshot: stop leg live + covering.
        statuses = {s.client_order_id: s for s in self.engine.open_orders()}
        net = abs(self.ledger.position_qty())
        # B8 ack loop (V-007): the stop must also cover the risk-approved
        # quantity (partial fills leave the remainder approved-but-unfilled).
        # Unknown (None) falls back to the ledger net, never to verified.
        required = self.policy.required_stop_qty(pos["reservation_id"])
        need = net if required is None else max(net, required)
        stop = statuses.get(pos["legs"][0])
        if stop is None or stop.state not in ("open", "partial"):
            self.store.checkpoint(self.run_id, "protection-unverified",
                                  {"leg": pos["legs"][0],
                                   "state": stop.state if stop else "missing"})
            pos["legs"] = []
            return
        if stop.qty - stop.filled_qty + 1e-9 < need:
            self.store.checkpoint(self.run_id, "protection-unverified",
                                  {"leg": pos["legs"][0], "reason": "qty-short",
                                   "open_qty": stop.qty - stop.filled_qty,
                                   "net": net, "required_stop_qty": required})
            pos["legs"] = []
            return
        if not pos["protected"]:
            pos["protected"] = True
            self.store.checkpoint(self.run_id, "protection-verified",
                                  {"legs": pos["legs"]})

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
        pos = self._position
        legs = pos["legs"] if pos is not None else []
        for leg in legs:
            try:
                self.engine.cancel(leg, reason)
            except Exception:
                pass
        net = self.ledger.position_qty()
        if abs(net) > 1e-12:
            symbol = pos["instrument"] if pos is not None else self._position_symbol()
            if symbol is None:
                raise ValueError("cannot flatten: exposure without instrument")
            side = "SELL" if net > 0 else "BUY"
            self.engine.submit_immediate(EngineOrder(
                instrument=symbol, side=side, qty=abs(net),
                kind="MARKET", reduce_only=True,
                reservation_id=pos["reservation_id"] if pos is not None else None,
                role="target"))
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

    def _prime_live_books(self) -> dict[str, Any]:
        """REST depth snapshot per configured symbol at live start.

        Dynamic discovery (empty symbols) cannot prime upfront: recorded
        as skipped. A failed fetch never aborts the run; the symbol is
        recorded unprimed and its book stays unsynced.
        """
        import urllib.request
        summary: dict[str, Any] = {"source": "rest:fapi/v1/depth",
                                   "applied": 0, "synced": [],
                                   "primed": [], "failed": {}}
        if not self.config.symbols:
            summary["skipped"] = "dynamic-symbols"
            return summary
        for symbol in self.config.symbols:
            url = ("https://fapi.binance.com/fapi/v1/depth"
                   f"?symbol={symbol}&limit=1000")
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "cryptobot-paper/0.1"})
                with urllib.request.urlopen(req, timeout=15.0) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                recv_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                # P2: report the ACTUAL install outcome, never the fetch.
                outcome = self._depth_store.apply_snapshot_record({
                    "symbol": symbol, "bids": payload["bids"],
                    "asks": payload["asks"],
                    "last_update_id": int(payload["lastUpdateId"]),
                    "rest_recv_ms": recv_ms,
                    "exchange_ts_ms": payload.get("T")})
            except Exception as exc:  # noqa: BLE001 - priming never aborts.
                summary["failed"][symbol] = {
                    "stage": "fetch-or-install",
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

    def run_replay(self, capture_dir: str | Path, *,
                   expect_class: str = "observed-public",
                   resume: bool = False,
                   crash_after: int | None = None) -> dict[str, Any]:
        # Streaming replay (W1-24H): single O(1)-memory pass over the
        # capture — no load_events list, no full-list sort. Local import
        # keeps this shared-file-queue patch inside this method.
        from cryptobot.market_data.replayer import RollingEventHash, stream_events

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
            # views on the Session path).
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
        if hasattr(self.clock, "set_ms"):
            self.clock.set_ms(int(event["exchange_ts_ms"]))  # replay: event time.
        age = int(event.get("local_recv_ms", event["exchange_ts_ms"])) - int(
            event["exchange_ts_ms"])
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
        if channel == "aggTrade":
            payload = event["payload"]
            feed.mark = float(payload["price"])
            feed.mark_ts = self.now_utc()
            closed = feed.agg.on_trade(event)
        else:
            payload = event["payload"]
            bid, ask = float(payload["bid"]), float(payload["ask"])
            if bid > 0 and ask >= bid:
                feed.mark = (bid + ask) / 2
                feed.mark_ts = self.now_utc()
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
            else:
                feed.bars.append(to_s1_bar(bar))
            if feed.ready(self.config.warmup_bars):
                if not self._warmed:
                    self._warmed = True
                    self._set_state("ready", "warmup-complete")
                self._maybe_admit(self._evaluate_symbol(symbol, adapters, modules))
        if closed:
            self._sample_equity("bar")
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
            self.engine.set_exit_only(True, ";".join(health.reasons))
            self._set_state("halted", ";".join(health.reasons))
        self._run_stop_actions()

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
                    self.engine.set_exit_only(False, "emergency-recovered")
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
        from cryptobot.events.sources import CpiSource, FomcSource
        from cryptobot.events.store import EventStore
        now = self.now_utc()
        try:
            profile = load_profile(self.config.source_path)
        except (ValueError, OSError):
            profile = None
        protected = (
            profile is not None and profile.posture == "protected"
            and self.config.mode == "paper")
        tracker = FreshnessTracker(
            self.workdir / "event_source_state.json",
            [FomcSource(), CpiSource()])
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
            runtime.log_refresh(now, {
                k: {"ok": v.ok, "error": v.error} for k, v in results.items()})
        self.protection = runtime
        self.event_gate = runtime.gate  # pre-window sweep compat.
        self._freshness = tracker
        if protected:
            interval = float(profile.refresh_interval_s)
            tracker.start(store, default_http_get, interval_s=interval,
                          now_utc=self.now_utc,
                          on_result=lambda res: runtime.log_refresh(
                              self.now_utc(), {
                                  k: {"ok": v.ok, "error": v.error}
                                  for k, v in res.items()}))

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
        if len(bars) >= 2 and getattr(bars[-2], "close", 0) > 0:
            abs_ret = abs(bars[-1].close / bars[-2].close - 1.0) * 1e4
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
        statuses = {s.client_order_id: s
                    for s in self.engine.open_orders()}
        entry = statuses.get(entry_id)
        if entry is not None and entry.filled_qty > 1e-12:
            return  # filled: protection stays on.
        try:
            self.engine.cancel(entry_id, "event-prepare-flat")
        except (ValueError, KeyError):
            pass  # already gone; still clear + release below.
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
        self.engine.set_exit_only(True, "funding-mismatch")
        self._set_state("halted", "funding-mismatch")

    def _roll_day_if_needed(self) -> None:
        today = accounting_date(self.now_utc()).isoformat()
        if self._day is not None and today != self._day:
            marked = self.ledger.marked_equity(self._reference_mark())
            self.policy.reconcile_day(marked, self.ledger.total_flows())
            self.engine.set_exit_only(False, "day-reconciled")
            self._set_state("ready", "day-reconciled")
            self._sample_equity("day-roll", force=True)
            self.store.checkpoint(self.run_id, "day-roll",
                                  {"day": today, "marked": marked})
        self._day = today

    def _refresh_filters_if_stale(self) -> None:
        """Re-arm paper filters when the record outlives its max age."""
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
        from .filters import FilterError
        try:
            self.arm_run_mode(symbols)
        except (FilterError, ValueError, OSError) as exc:
            self.engine.set_exit_only(True, f"filters-refresh:{exc}")
            self._set_state("halted", "filters:refresh-failed")

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
        # Recover the engine from its own journal (durable source).
        self.engine.recover(self.policy)
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
        ledger_path = self.workdir / "ledger.json"
        if ledger_path.exists():
            self.ledger = Ledger.from_dict(
                json.loads(ledger_path.read_text(encoding="utf-8")))
            self.policy.bind_ledger(self.ledger)
        self.engine.recover(self.policy)
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
        if self.config.mode != "paper":
            raise ValueError("run_live needs a paper-mode config")
        if resume:
            self._resume_live()
        else:
            self.store.create_run(self.run_id, "paper", self.config.fingerprint,
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
        last_beat = 0.0
        # Watchdog: stream-stall detector. Heartbeats prove the loop is
        # awake; only real market events prove the venue feed is alive.
        # 60s of market silence = resync books (P3-style reaction), never
        # a silent stall. Crypto majors tick every second in practice.
        last_market_mono = time.monotonic()
        stall_notified = False
        end_reason = "duration-elapsed"
        for event in event_iter:
            # None = idle heartbeat (B3): iterators never block longer
            # than 1s, so timers/stop/duration below run on every wake,
            # with or without market traffic.
            if event is None:
                pass
            elif event.get("input_class", expect_class) != expect_class:
                continue
            else:
                self._ingest(event, adapters, modules)
                self._events_seen += 1
                last_market_mono = time.monotonic()
                stall_notified = False
            # Position management on every wake (B3): time exits and flat
            # inference cannot wait for the next market event.
            self._advance_engine_clock()
            self._drain_engine(bounded=True)
            if self._position is not None:
                self._update_position(EngineEvent("tick", None, self.now_utc()))
            now_mono = time.monotonic()
            if (not stall_notified
                    and now_mono - last_market_mono > 60.0):
                stall_notified = True
                self._append_run_file("risk.jsonl", {
                    "ts_utc": self.now_utc().isoformat(),
                    "wall_ts_utc": datetime.now(timezone.utc).isoformat(),
                    "kind": "stream-stall",
                    "from_state": "streaming", "to_state": "resync",
                    "reason": "no market events for 60s; re-priming books"})
                prime = self._prime_live_books()
                self.store.checkpoint(self.run_id, "stall-resync", prime)
                last_market_mono = time.monotonic()
                stall_notified = False  # re-arm: fire again per 60s window.
            if now_mono - last_beat >= 30.0:
                last_beat = now_mono
                self.store.heartbeat(self.run_id, self._pid)
                self._persist_local_state()
                # Traffic-independent oversight tick (+ dead-monitor stamp).
                tick = self.policy.monitor_tick(account=None)
                if not tick.ok:
                    self.engine.set_exit_only(True, ";".join(tick.reasons))
                    self._set_state("halted", ";".join(tick.reasons))
                self._run_stop_actions()
                self._drain_unknown_outcomes()
                self._refresh_filters_if_stale()
            stop = self._stop_flag or self.store.stop_requested(self.run_id)
            if stop is not None:
                end_reason = f"operator-stop:{stop}"
                if stop == "flatten":
                    self._flatten("operator-stop-flatten")
                    self._drain_engine()
                break
            if now_mono >= deadline:
                break
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
        report = self._build_report("live-public-feed", expect_class,
                                    mode="paper")
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
                "submit_to_fill_modeled": _summarize(self._dispatch_ms)},
            "workdir": str(self.workdir),
        }

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
