"""Autonomous session: lifecycle, replay loop, exits, recovery (manager-owned).

Replay and paper share the strategy/selector/exit/risk path; they differ
only in the event source (capture file vs live bridge) and the clock (event
time vs wall time). The engine is injected (reference for replay/tests,
Nautilus for paper via E-007).
"""
from __future__ import annotations

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
from cryptobot.market_data.replayer import (assert_input_class, load_events,
                                            replay_events)
from cryptobot.risk.policy import RiskPolicy
from cryptobot.risk.types import AccountSnapshot, Approved, RiskConfig

from .config import AppConfig
from .engine import EngineEvent, EngineOrder
from .reference import ReferenceEngine
from .store import RunStore

__all__ = ["Session", "ReplayClock", "WallClock", "STRATEGY_ARMS"]

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

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
            "ts_utc": self.now_utc().isoformat(), "kind": "run-state",
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
        return AccountSnapshot(
            reconciled_equity=self.ledger.marked_equity(mark),
            marked_equity=self.ledger.marked_equity(mark),
            net_liquidation=self.ledger.net_liquidation(mark, close_bps),
            net_realised_global=self.ledger.net_realised(),
            open_position=self.ledger.has_position() or self._position is not None,
            flows_cumulative=self.ledger.total_flows())

    def _sample_equity(self, source: str, *, force: bool = False) -> None:
        """Append an equity curve point (periodic + on fills + on day roll)."""
        now = self.now_utc()
        if not force and not self._equity_dirty:
            if self._last_equity_sample is not None and (
                    now - self._last_equity_sample).total_seconds() < \
                    self.config.equity_sample_s:
                return
        mark = self._reference_mark()
        qty = self.ledger.position_qty()
        basis = self.ledger.entry_basis()
        open_pnl = qty * (mark - basis) if basis is not None and mark > 0 else 0.0
        cash = self.ledger.marked_equity(mark) - qty * mark if mark > 0 else \
            self.ledger.marked_equity(0.0)
        self._append_run_file("equity.jsonl", {
            "ts_utc": now.isoformat(),
            "marked_equity": self.ledger.marked_equity(mark),
            "cash": cash, "position_qty": qty,
            "position_symbol": self._position_symbol() or "",
            "open_pnl": open_pnl, "source": source})
        self._last_equity_sample = now
        self._equity_dirty = False

    def _reference_mark(self) -> float:
        if self._position is not None:
            feed = self._feeds.get(self._position["instrument"])
            if feed is not None and feed.mark:
                return feed.mark
        for feed in self._feeds.values():
            if feed.mark:
                return feed.mark
        return 0.0

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
        view = MarketView(
            instrument=symbol, bars=tuple(bars), now_utc=self.now_utc(),
            depth=None, flow=None, quality=DataQuality.CLEAN,
            quality_reason="depth:unsynced-no-snapshot;flow:window-incomplete")
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
        verdict = self.policy.evaluate(intent, self._snapshot_account())
        if not isinstance(verdict, Approved):
            self._note_reject(f"risk:{verdict.reason}", intent.strategy,
                              intent.instrument, intent.side.value)
            self._append_run_file("risk.jsonl", {
                "ts_utc": self.now_utc().isoformat(), "kind": "risk-decision",
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
        pre_id = self.engine.submit(EngineOrder(
            instrument=intent.instrument, side=side, qty=verdict.qty,
            kind="MARKET", reservation_id=verdict.reservation_id))
        self._submit_ts[pre_id] = self.now_utc()
        self._position = {"reservation_id": verdict.reservation_id,
                          "instrument": intent.instrument,
                          "side": intent.side.value,
                          "entry_pre_id": pre_id, "entry_id": None,
                          "legs": [], "stop": stop, "target": target,
                          "time_exit": time_exit, "legacy_exit": legacy,
                          "protected": False, "protect_attempts": 0}
        self._admitted += 1
        self._set_state("holding", f"admitted:{intent.evidence_ref}")
        self.store.checkpoint(self.run_id, "admit", {
            "reservation_id": verdict.reservation_id, "qty": verdict.qty,
            "notional": verdict.notional_usdt, "legacy_exit": legacy})

    def _note_reject(self, reason: str, strategy: str = "",
                     instrument: str = "", side: str = "") -> None:
        self._reject_counts[reason] = self._reject_counts.get(reason, 0) + 1
        stage = reason.split(":")[0] if ":" in reason else "unknown"
        self._append_run_file("rejections.jsonl", {
            "ts_utc": self.now_utc().isoformat(), "stage": stage,
            "reason": reason, "strategy": strategy, "instrument": instrument,
            "side": side})

    def _drain_engine(self) -> None:
        for event in self.engine.poll():
            self._on_engine_event(event)

    def _append_run_file(self, name: str, record: dict[str, Any]) -> None:
        """Append one JSON record to a per-run result file (B9 reporting).

        Schemas (stable, consumed by reporting/build):
        - fills.jsonl: {execution_id, client_order_id, instrument, side, qty,
          price, fee, liquidity, ts_utc}
        - rejections.jsonl: {ts_utc, stage, reason, strategy, instrument, side}
        - risk.jsonl: {ts_utc, kind, from_state, to_state, reason}
        - equity.jsonl: {ts_utc, marked_equity, cash, position_qty,
          position_symbol, open_pnl, source}
        """
        with (self.workdir / name).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

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
                self._position = None
                self._set_state("ready", "position-flat")
        # Entry died with zero fills: reservation released by callbacks; clear.
        if entry is not None and entry.filled_qty <= 1e-12 and entry.state in (
                "rejected", "cancelled", "expired"):
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
        stop = statuses.get(pos["legs"][0])
        if stop is None or stop.state not in ("open", "partial"):
            self.store.checkpoint(self.run_id, "protection-unverified",
                                  {"leg": pos["legs"][0],
                                   "state": stop.state if stop else "missing"})
            pos["legs"] = []
            return
        if stop.qty - stop.filled_qty + 1e-9 < net:
            self.store.checkpoint(self.run_id, "protection-unverified",
                                  {"leg": pos["legs"][0], "reason": "qty-short",
                                   "open_qty": stop.qty - stop.filled_qty,
                                   "net": net})
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
    def run_replay(self, capture_dir: str | Path, *,
                   expect_class: str = "observed-public",
                   resume: bool = False,
                   crash_after: int | None = None) -> dict[str, Any]:
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
        records = load_events(events_path)
        for record in records:
            assert_input_class({"input_class": record["input_class"]}, expect_class)
        adapters, modules = self._strategy_adapters()
        if not resume:
            # Day baseline at first event time (causal).
            first_ts = min(int(r["exchange_ts_ms"]) for r in records)
            self.clock.set_ms(first_ts)
            self.policy.reconcile_day(self.config.paper_capital_usdt, 0.0)
            self._day = accounting_date(self.now_utc()).isoformat()
        self._set_state("warming", "replay-start")
        for event in replay_events(records):
            if int(event.get("seq", 0)) <= self._last_seq:
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
        report = self._build_report(str(capture_dir), expect_class)
        (self.workdir / "report.json").write_text(json.dumps(report, indent=2))
        (self.workdir / "report.md").write_text(self._render_report(report))
        self._set_state("stopped", "report-written")
        return report

    def _ingest(self, event: dict[str, Any], adapters: dict[str, Any],
                modules: dict[str, Any]) -> None:
        channel = event.get("channel")
        symbol = event.get("symbol")
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
            closed = feed.agg.on_trade(event)
        else:
            payload = event["payload"]
            bid, ask = float(payload["bid"]), float(payload["ask"])
            if bid > 0 and ask >= bid:
                feed.mark = (bid + ask) / 2
            feed.agg.on_bbo(bid, ask, int(event["exchange_ts_ms"]))
        if feed.mark:
            self.engine.note_mark(symbol, feed.mark)
        if hasattr(self.engine, "note_event"):
            # True-cross upgrade: full normalized event to the sim (additive;
            # reference engine lacks it and keeps mark-quote behavior).
            self.engine.note_event(event)
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
        health = self.policy.check_health(self._snapshot_account())
        if not health.ok:
            self.engine.set_exit_only(True, ";".join(health.reasons))
            self._set_state("halted", ";".join(health.reasons))

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
            self.store.checkpoint(self.run_id, "open",
                                  {"equity": self.config.paper_capital_usdt})
        adapters, modules = self._strategy_adapters()
        self._set_state("warming", "paper-start")
        deadline = time.monotonic() + duration_s
        last_beat = 0.0
        end_reason = "duration-elapsed"
        for event in event_iter:
            if event.get("input_class", expect_class) != expect_class:
                continue
            self._ingest(event, adapters, modules)
            self._events_seen += 1
            now_mono = time.monotonic()
            if now_mono - last_beat >= 30.0:
                last_beat = now_mono
                self.store.heartbeat(self.run_id, self._pid)
                self._persist_local_state()
                # Traffic-independent oversight tick (+ dead-monitor stamp).
                tick = self.policy.monitor_tick(account=None)
                if not tick.ok:
                    self.engine.set_exit_only(True, ";".join(tick.reasons))
                    self._set_state("halted", ";".join(tick.reasons))
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
        self._drain_engine()
        self._persist_local_state()
        report = self._build_report("live-public-feed", expect_class,
                                    mode="paper")
        (self.workdir / "report.json").write_text(json.dumps(report, indent=2))
        (self.workdir / "report.md").write_text(self._render_report(report))
        self._set_state("stopped", "report-written")
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
