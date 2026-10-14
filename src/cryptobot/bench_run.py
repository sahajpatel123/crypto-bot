"""Bounded resumable benchmark runner over streaming datasets (W2, 30MIN §6).

Streams ``open_dataset`` events (vision-archive or captured-runs days)
through a Session with a wall budget, crash-safe checkpoints, and
resume. Checkpoints preserve the economic experiment (equity via
ledger, loss-budget/floor via risk state, selector cooldowns, engine
journal offset, cursor, seeds) with FLAT-BOUNDARY commits: the commit
cursor advances only when flat (no position, no open orders); the
uncommitted tail is replayed from the commit on resume, never dropped.

Exit codes: 0 with status COMPLETE only when the input is exhausted;
124 with status INCOMPLETE_BUDGET (deadline/signal) or
TRUNCATED_MAX_EVENTS (max-events bound) otherwise — partial work is
never reported complete. Honors CRYPTOBOT_DEADLINE_MONO (inherited
deadline wins over --wall-budget-s).

Example:
  python -m cryptobot.bench_run --config configs/paper.toml \\
      --dataset datasets/benchmark_30d.toml --symbol BTCUSDT \\
      --days 2026-09-12,2026-09-13 --wall-budget-s 1500 \\
      --checkpoint-dir bench/ckpts/day12 --report-out bench/rep12.json
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptobot.accounting.day import accounting_date
from cryptobot.accounting.ledger import Ledger
from cryptobot.app.config import load_config
from cryptobot.app.session import ReplayClock, Session
from cryptobot.app.store import RunStore
from cryptobot.costs import COST_S1, estimate_for_notional
from cryptobot.market_data.datasets import open_dataset

EXIT_INCOMPLETE = 124
ENV_DEADLINE = "CRYPTOBOT_DEADLINE_MONO"
RUNNER_VERSION = "bench-run-v2"
# Per-run result files truncated to the commit on resume (tail re-appends).
RUN_FILES = ("fills.jsonl", "equity.jsonl", "rejections.jsonl", "risk.jsonl")


def _atomic_write_json(path: Path, record: dict) -> float:
    """Atomic JSON write + fsync; returns fsync seconds (file + dir)."""
    t0 = time.perf_counter()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(record, indent=1) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    return time.perf_counter() - t0


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"bench-{stamp}-{os.getpid()}"


class BenchRunner:
    """Wall-budgeted dataset replay with flat-boundary checkpoints."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.ckpt_dir = Path(args.checkpoint_dir)
        self.workdir = self.ckpt_dir / "work"
        self.ckpt_path = self.ckpt_dir / "bench_checkpoint.json"
        self._stop_reason: str | None = None
        self._t_read = 0.0
        self._t_ingest = 0.0
        self._t_commit = 0.0
        self._t_fsync = 0.0
        self._t_store = 0.0
        self._n_commits = 0
        self._n_replayed = 0
        self._n_ingested = 0
        self._n_heartbeats = 0
        self._estimates: list[dict[str, Any]] = []
        self._open_reservation: str | None = None

    # -- lifecycle ----------------------------------------------------
    def _install_signal_handlers(self) -> None:
        def _handle(signum: int, _frame: object) -> None:
            if self._stop_reason is None:
                self._stop_reason = ("sigterm" if signum == signal.SIGTERM
                                     else "sigint")

        signal.signal(signal.SIGTERM, _handle)
        signal.signal(signal.SIGINT, _handle)

    def _deadline(self, start_mono: float) -> float:
        deadline = start_mono + float(self.args.wall_budget_s)
        inherited = os.environ.get(ENV_DEADLINE)
        if inherited:
            try:
                outer = float(inherited)
            except ValueError:
                outer = None
            if outer is not None and outer < deadline:
                deadline = outer
        return deadline

    def _build_session(self, run_id: str,
                       starting_balance: float | None = None) -> Session:
        from cryptobot.adapters import NautilusPaperEngine

        config = load_config(self.args.config)
        store = RunStore(str(self.ckpt_dir / "store.db"))
        clock = ReplayClock()
        rest_get = None
        filters_src = getattr(self.args, "filters_file", None)
        if filters_src:
            frozen = json.loads(Path(filters_src).read_text(encoding="utf-8"))

            def _frozen_get(url: str, timeout_s: float = 15.0,
                            _payload: Any = frozen,
                            _src: str = str(filters_src)) -> tuple[Any, dict]:
                return _payload, {"frozen_filters": _src}

            rest_get = _frozen_get
        engine = NautilusPaperEngine(
            outcome_sink=None, taker_bps=config.taker_bps,
            now_utc=clock.now, submit_delay_ms=config.submit_delay_ms,
            fill_delay_ms=max(1, config.fill_delay_ms),
            journal_path=self.workdir / "engine_journal.jsonl",
            starting_balance_usdt=(config.paper_capital_usdt
                                   if starting_balance is None
                                   else starting_balance),
            random_seed=int(self.args.engine_seed),
            rest_get=rest_get)
        session = Session(config, store, self.workdir, run_id,
                          pid=os.getpid(), clock=clock, engine=engine)
        # Contract v1: push fills through the Session event entry (the
        # same method the poll drain uses). W1 swaps this for the
        # durable _apply_engine_event handler at Checkpoint A.
        engine.bind_sink(session._on_engine_event)
        return session

    # -- flat-boundary checkpoints ------------------------------------
    def _is_flat(self, session: Any) -> bool:
        """True only when NO open exposure exists anywhere.

        Checks Session position + pending flatten, ledger quantity
        (orphan fills without a Session position still count), engine
        nonterminal orders (terminal fills/rejects/cancels/expiries are
        history, NOT exposure), engine pending commands/events, open IOC
        arrivals, engine portfolio positions, and risk reservations +
        unresolved outcomes. Components absent from a partial view (e.g.
        an engine-only probe namespace) pass their sub-check; every
        PRESENT component must pass.
        """
        if getattr(session, "_position", None) is not None:
            return False
        if getattr(session, "_flatten_pending", False):
            return False
        ledger = getattr(session, "ledger", None)
        if ledger is not None:
            try:
                qty = abs(float(ledger.position_qty()))
            except Exception:  # noqa: BLE001 - unreadable ledger: not flat.
                return False
            if qty > 1e-12:
                return False
        engine = getattr(session, "engine", None)
        if engine is not None:
            try:
                orders = engine.open_orders()
            except Exception:  # noqa: BLE001 - unreadable orders: not flat.
                return False
            for order in orders:
                if getattr(order, "state", "open") in ("open", "partial"):
                    return False
            if getattr(engine, "_submit_queue", []):
                return False  # pending commands not yet submitted.
            if getattr(engine, "_pending", []):
                return False  # unconsumed execution events.
            if getattr(engine, "_ioc_open", {}):
                return False  # IOC arrivals not yet retired.
            cache = getattr(engine, "_cache", None)
            if cache is not None:
                try:
                    open_positions = cache.positions_open()
                except Exception:  # noqa: BLE001 - unreadable: not flat.
                    return False
                if open_positions:
                    return False
        policy = getattr(session, "policy", None)
        state = getattr(policy, "_state", None)
        if state is not None:
            if getattr(state, "reservations", {}):
                return False
            if getattr(state, "unresolved", {}):
                return False
        return True

    @staticmethod
    def _clock_ms(session: Session) -> int:
        return int((session.clock.now() - datetime(
            1970, 1, 1, tzinfo=timezone.utc)).total_seconds() * 1000)

    def _snapshot_feeds(self, session: Session) -> dict[str, Any]:
        feeds = {}
        for symbol, feed in getattr(session, "_feeds", {}).items():
            bars = []
            for bar in feed.bars:
                if bar is None:
                    bars.append(None)
                    continue
                bars.append({"ts_utc": bar.ts_utc.isoformat(),
                             "open": bar.open, "high": bar.high,
                             "low": bar.low, "close": bar.close,
                             "volume": bar.volume, "trades": bar.trades,
                             "buy_frac": bar.buy_frac,
                             "spread_bps": bar.spread_bps,
                             "source": bar.source})
            mark_ts = getattr(feed, "mark_ts", None)
            feeds[symbol] = {
                "bars": bars, "agg": feed.agg.to_dict(),
                "mark": getattr(feed, "mark", None),
                "mark_ts": mark_ts.isoformat() if mark_ts else None,
                "missing": int(getattr(feed, "missing", 0)),
                "warmup": int(feed.bars.maxlen or 0) - 5}
        return feeds

    def _snapshot_engine(self, session: Session) -> dict[str, Any]:
        engine = session.engine
        journal = self.workdir / "engine_journal.jsonl"
        marks_ts = {s: v.isoformat()
                    for s, v in getattr(engine, "_mark_ts", {}).items()}
        try:
            margin = engine.account_margin()
            cash = [float(margin[0]), float(margin[1])]
        except Exception:  # noqa: BLE001 - snapshot must not crash.
            cash = None
        return {
            "marks": dict(getattr(engine, "_marks", {})),
            "mark_ts": marks_ts,
            "funding_terms": {s: dict(v) for s, v in
                              getattr(engine, "_funding_terms", {}).items()},
            "settled_funding": dict(getattr(engine, "_settled_funding", {})),
            "bbo": {s: [float(x) for x in p]
                    for s, p in getattr(engine, "_bbo", {}).items()},
            "last_print": {s: [float(v[0]), float(v[1])]
                           for s, v in
                           getattr(engine, "_last_print", {}).items()},
            "op_seq": int(getattr(engine, "_op_seq",
                                  getattr(engine, "_data_seq", 0))),
            "journal_bytes": journal.stat().st_size if journal.exists() else 0,
            "cash": cash,
        }

    def _snapshot_run_files(self) -> dict[str, int]:
        sizes = {}
        for name in RUN_FILES:
            path = self.workdir / name
            sizes[name] = path.stat().st_size if path.exists() else 0
        return sizes

    def _snapshot_store(self, session: Session) -> dict[str, int]:
        cursors = {}
        for table in ("intents", "execution_events", "risk_transitions",
                      "checkpoints"):
            row = session.store._db.execute(
                f"SELECT COALESCE(MAX(id), 0) FROM {table}").fetchone()
            cursors[table] = int(row[0])
        return cursors

    def _snapshot_identity(self, session: Session) -> dict[str, Any]:
        import hashlib

        from cryptobot.costs import CONTRACT_VERSION as COST_VERSION
        from cryptobot.strategies.contract import STRATEGY_VERSION

        config_src = Path(str(self.args.config)).read_bytes()
        return {
            "config_fingerprint": session.config.fingerprint,
            "config_file_sha16": hashlib.sha256(config_src).hexdigest()[:16],
            "cooldown_s": getattr(session.config, "cooldown_s", None),
            "mode": getattr(session.config, "mode", None),
            "strategy_version": STRATEGY_VERSION,
            "adapters": sorted(getattr(self, "_adapter_names", [])),
            "cost_contract": COST_VERSION,
            "dataset": dict(getattr(self, "_dataset_id", {})),
            "engine_seed": int(self.args.engine_seed),
            "filters": self._filters_provenance(),
        }

    def _snapshot_protection(self, session: Session) -> dict[str, Any] | None:
        runtime = getattr(session, "protection", None)
        if runtime is None:
            return None
        anomaly = getattr(runtime, "anomaly_state", None)
        evidence = self.workdir / "protection_evidence.jsonl"
        return {
            "anomaly": (None if anomaly is None else {
                "tripped": list(anomaly.tripped),
                "ok_streak": int(anomaly.ok_streak),
                "cooldown_until_utc": (
                    anomaly.cooldown_until_utc.isoformat()
                    if anomaly.cooldown_until_utc else None)}),
            "evidence_bytes": (evidence.stat().st_size
                               if evidence.exists() else 0),
            "first_event_ms": getattr(self, "_first_event_ms", None),
        }

    def _snapshot(self, session: Session, cursor: dict[str, Any]) -> dict[str, Any]:
        risk_state = (self.workdir / "risk_state.json").read_text(
            encoding="utf-8") if (self.workdir / "risk_state.json").exists() else None
        cooldowns = {f"{k[0]}|{k[1]}": v.isoformat()
                     for k, v in session.selector._cooldowns.items()}
        return {
            "runner_version": RUNNER_VERSION,
            "cursor": cursor,
            "ledger": session.ledger.to_dict(),
            "risk_state_json": risk_state,
            "cooldowns": cooldowns,
            "clock_ms": self._clock_ms(session),
            "day": session._day,
            "warmed": bool(getattr(session, "_warmed", False)),
            "saw_marks": bool(getattr(session, "_saw_exchange_marks", False)),
            "feeds": self._snapshot_feeds(session),
            "depth_store": session._depth_store.to_dict(),
            "engine": self._snapshot_engine(session),
            "protection": self._snapshot_protection(session),
            "store_cursors": self._snapshot_store(session),
            "run_state": (session.store.get_run(session.run_id) or {}
                          ).get("state", ""),
            "counts": {"events_seen": session._events_seen,
                       "admitted": session._admitted,
                       "reject_counts": dict(session._reject_counts),
                       "dispatch_ms": len(getattr(session, "_dispatch_ms", []))},
            "run_files": self._snapshot_run_files(),
            "identity": self._snapshot_identity(session),
            "last_mark": dict(getattr(self, "_last_mark", {})),
            "estimates": self._estimates,
        }

    def _filters_provenance(self) -> str:
        import hashlib

        src = getattr(self.args, "filters_file", None)
        if not src:
            return "live-rest"
        digest = hashlib.sha256(Path(src).read_bytes()).hexdigest()[:16]
        return f"frozen:{digest}"

    def _commit(self, session: Session, cursor: dict[str, Any]) -> bool:
        """Commit only at a true flat boundary; returns whether committed.

        Never forced: input exhaustion or a wall budget with open exposure
        leaves the last flat commit in place (the tail replays on resume,
        and the run reports unresolved rather than complete).
        """
        t0 = time.perf_counter()
        session._drain_engine()
        if not self._is_flat(session):
            return False  # not a flat boundary: cursor stays, tail grows.
        record = self._snapshot(session, cursor)
        fsync_s = _atomic_write_json(self.ckpt_path, record)
        self._t_fsync += fsync_s
        self._t_commit += time.perf_counter() - t0
        self._n_commits += 1
        return True

    def _check_identity(self, session: Session,
                        commit: dict[str, Any]) -> None:
        """Refuse resume when source/config/strategy/cost/dataset differ."""
        if commit.get("runner_version") != RUNNER_VERSION:
            raise ValueError(
                f"checkpoint runner_version {commit.get('runner_version')!r} "
                f"!= {RUNNER_VERSION!r}")
        want = commit.get("identity", {})
        got = self._snapshot_identity(session)
        for key in ("config_fingerprint", "config_file_sha16", "cooldown_s",
                    "mode", "strategy_version", "adapters", "cost_contract",
                    "dataset", "engine_seed", "filters"):
            if want.get(key) != got.get(key):
                raise ValueError(
                    f"resume identity mismatch on {key}: checkpoint "
                    f"{want.get(key)!r} != current {got.get(key)!r}")

    def _restore_feeds(self, session: Session, commit: dict[str, Any]) -> None:
        from cryptobot.app.session import _SymbolFeed
        from cryptobot.market_data.bars import BarAggregator
        from cryptobot.strategies.s1 import Bar

        feeds = {}
        for symbol, saved in commit.get("feeds", {}).items():
            feed = _SymbolFeed(symbol, int(saved["warmup"]))
            bars = []
            for raw in saved["bars"]:
                bars.append(None if raw is None else Bar(
                    ts_utc=datetime.fromisoformat(raw["ts_utc"]),
                    open=float(raw["open"]), high=float(raw["high"]),
                    low=float(raw["low"]), close=float(raw["close"]),
                    volume=float(raw["volume"]), trades=int(raw["trades"]),
                    buy_frac=float(raw["buy_frac"]),
                    spread_bps=float(raw["spread_bps"]),
                    source=str(raw["source"])))
            feed.bars.extend(bars)
            feed.agg = BarAggregator.from_dict(saved["agg"])
            feed.mark = saved["mark"]
            feed.mark_ts = (datetime.fromisoformat(saved["mark_ts"])
                            if saved["mark_ts"] else None)
            feed.missing = int(saved["missing"])
            feeds[symbol] = feed
        session._feeds = feeds

    def _restore_engine_state(self, session: Session,
                              commit: dict[str, Any]) -> None:
        engine = session.engine
        saved = commit.get("engine", {})
        engine._marks = dict(saved.get("marks", {}))
        engine._mark_ts = {s: datetime.fromisoformat(v)
                           for s, v in saved.get("mark_ts", {}).items()}
        engine._funding_terms = {s: dict(v) for s, v in
                                 saved.get("funding_terms", {}).items()}
        engine._settled_funding = dict(saved.get("settled_funding", {}))
        engine._bbo = {s: tuple(float(x) for x in p)
                       for s, p in saved.get("bbo", {}).items()}
        engine._last_print = {s: (float(v[0]), float(v[1]))
                              for s, v in
                              saved.get("last_print", {}).items()}
        engine._op_seq = int(saved.get("op_seq", saved.get("data_seq", 0)))
        journal = self.workdir / "engine_journal.jsonl"
        keep = int(saved.get("journal_bytes", 0))
        if journal.exists():
            with open(journal, "r+b") as fh:
                fh.truncate(keep)  # drop the uncommitted tail; replay re-appends.
        # Contract v1: recover through the Session event entry (a
        # policy is not an EngineEvent callable).
        engine.recover(session._on_engine_event)
        if saved.get("cash") is not None:
            free, _locked = engine.account_margin()
            if abs(float(free) - float(saved["cash"][0])) > 1e-6:
                raise ValueError(
                    f"engine cash mismatch after restore: {free} != "
                    f"committed {saved['cash'][0]}")

    def _restore_store(self, session: Session, commit: dict[str, Any]) -> None:
        """Roll back store tables to the commit (no dupes on tail replay)."""
        db = session.store._db
        try:
            for table, max_id in commit.get("store_cursors", {}).items():
                if table not in ("intents", "execution_events",
                                 "risk_transitions", "checkpoints"):
                    raise ValueError(f"unexpected store table {table!r}")
                db.execute(f"DELETE FROM {table} WHERE id > ?",
                           (int(max_id),))
                # Reuse ids on replay: without this the AUTOINCREMENT
                # sequence keeps climbing and resumed stores diverge.
                db.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = ?",
                           (int(max_id), table))
            # _set_state reads `old` from the run row: rewind it so replayed
            # transitions record the same from-state (direct UPDATE: the
            # set_state() helper would insert a spurious transition row).
            if commit.get("run_state") is not None:
                db.execute("UPDATE runs SET state=? WHERE run_id=?",
                           (commit["run_state"], session.run_id))
            db.commit()
        except Exception:
            db.rollback()
            raise

    def _restore_run_files(self, commit: dict[str, Any]) -> None:
        """Truncate run files to the commit (no dupes on tail replay)."""
        for name, keep in commit.get("run_files", {}).items():
            if name not in RUN_FILES:
                raise ValueError(f"unexpected run file {name!r}")
            path = self.workdir / name
            if not path.exists():
                if int(keep) == 0:
                    continue
                raise ValueError(
                    f"run file {name} missing, cannot restore {keep} bytes")
            with open(path, "r+b") as fh:
                fh.truncate(int(keep))

    def _restore_protection(self, session: Session,
                            commit: dict[str, Any]) -> None:
        saved = commit.get("protection")
        runtime = getattr(session, "protection", None)
        if saved is None or runtime is None:
            if (saved is None) != (runtime is None):
                raise ValueError("protection enabled-status differs "
                                 "from checkpointed run")
            return
        from cryptobot.events.anomaly import AnomalyState

        anomaly = saved.get("anomaly")
        runtime.anomaly_state = None if anomaly is None else AnomalyState(
            tripped=tuple(anomaly["tripped"]),
            ok_streak=int(anomaly["ok_streak"]),
            cooldown_until_utc=(
                datetime.fromisoformat(anomaly["cooldown_until_utc"])
                if anomaly["cooldown_until_utc"] else None))
        evidence = self.workdir / "protection_evidence.jsonl"
        if evidence.exists():
            with open(evidence, "r+b") as fh:
                fh.truncate(int(saved.get("evidence_bytes", 0)))

    def _restore(self, session: Session) -> dict[str, Any]:
        """Restore the committed experiment; returns the commit cursor."""
        from cryptobot.market_data.views import DepthStore

        commit = json.loads(self.ckpt_path.read_text(encoding="utf-8"))
        self._check_identity(session, commit)
        session.ledger = Ledger.from_dict(commit["ledger"])
        session.policy.bind_ledger(session.ledger)
        if commit["risk_state_json"] is not None:
            (self.workdir / "risk_state.json").write_text(
                commit["risk_state_json"], encoding="utf-8")
            from cryptobot.risk.state import load_state
            session.policy._state = load_state(self.workdir / "risk_state.json")
        session.selector._cooldowns = {
            tuple(k.split("|", 1)): datetime.fromisoformat(v)
            for k, v in commit["cooldowns"].items()}
        self._restore_feeds(session, commit)
        session._depth_store = DepthStore.from_dict(commit["depth_store"])
        self._restore_engine_state(session, commit)
        self._restore_store(session, commit)
        self._restore_run_files(commit)
        self._restore_protection(session, commit)
        session.clock.set_ms(int(commit["clock_ms"]))
        session._day = commit["day"]
        session._warmed = bool(commit.get("warmed", False))
        session._saw_exchange_marks = bool(commit.get("saw_marks", False))
        session._events_seen = int(commit["counts"]["events_seen"])
        session._admitted = int(commit["counts"]["admitted"])
        session._reject_counts = dict(commit["counts"]["reject_counts"])
        keep_ms = int(commit["counts"].get("dispatch_ms", 0))
        if hasattr(session, "_dispatch_ms"):
            del session._dispatch_ms[keep_ms:]
        session._last_seq = int(commit["cursor"]["seq"])
        self._estimates = list(commit["estimates"])
        self._last_mark = dict(commit.get("last_mark", {}))
        return commit["cursor"]

    # -- estimates (separate from booked) -------------------------------
    def _track_mark(self, event: dict[str, Any]) -> None:
        """Remember the latest sourced valuation price (never zero)."""
        channel = event.get("channel")
        payload = event.get("payload") or {}
        ts = int(event.get("exchange_ts_ms") or 0)
        price = None
        if channel == "markPrice":
            price = payload.get("mark") or payload.get("price")
        elif channel == "aggTrade":
            price = payload.get("price")
        elif channel == "bookTicker":
            bid = payload.get("bid") or payload.get("best_bid")
            ask = payload.get("ask") or payload.get("best_ask")
            if bid and ask:
                price = (float(bid) + float(ask)) / 2.0
        if price is not None and ts > 0:
            try:
                price_f = float(price)
            except (TypeError, ValueError):
                return
            if price_f > 0 and ts >= int(self._last_mark.get("ts_ms", -1)):
                self._last_mark = {"price": price_f, "ts_ms": ts,
                                   "source": channel}

    def _track_position(self, session: Session) -> None:
        pos = session._position
        res = pos["reservation_id"] if pos else None
        if res is not None:
            self._open_reservation = res
            return
        if self._open_reservation is None:
            return
        notional = self._admit_notional(session, self._open_reservation)
        rec: dict[str, Any] = {"reservation_id": self._open_reservation,
                               "instrument": None, "side": None,
                               "notional_usdt": notional, "estimate": None}
        if notional is not None:
            est = estimate_for_notional(COST_S1, notional)
            rec["estimate"] = est.to_dict()
        self._estimates.append(rec)
        self._open_reservation = None

    def _admit_notional(self, session: Session,
                        reservation_id: str) -> float | None:
        try:
            rows = session.store._db.execute(
                "SELECT payload FROM checkpoints WHERE run_id=? AND kind='admit'"
                " ORDER BY id DESC LIMIT 20", (session.run_id,)).fetchall()
        except Exception:  # noqa: BLE001 - store hiccup: estimate skipped.
            return None
        for (payload,) in rows:
            try:
                doc = json.loads(payload)
            except ValueError:
                continue
            if doc.get("reservation_id") == reservation_id:
                try:
                    return float(doc["notional"])
                except (KeyError, TypeError, ValueError):
                    return None
        return None

    # -- main loop ------------------------------------------------------
    def run(self) -> tuple[int, dict[str, Any]]:
        self._install_signal_handlers()
        start_mono = time.monotonic()
        deadline = self._deadline(start_mono)
        days = [d.strip() for d in str(self.args.days).split(",") if d.strip()]
        if not days:
            raise ValueError("--days needs at least one YYYY-MM-DD")
        run_id = self.args.run_id or _new_run_id()
        starting_balance: float | None = None
        if self.args.resume:
            if not self.ckpt_path.exists():
                raise FileNotFoundError(
                    f"--resume but no checkpoint at {self.ckpt_path}")
            peek = json.loads(self.ckpt_path.read_text(encoding="utf-8"))
            if peek.get("runner_version") != RUNNER_VERSION:
                raise ValueError(
                    f"checkpoint runner_version {peek.get('runner_version')!r} "
                    f"!= {RUNNER_VERSION!r}")
            cash = (peek.get("engine") or {}).get("cash")
            if cash is None:
                raise ValueError("commit lacks engine cash; cannot rebase")
            starting_balance = float(cash[0])
        session = self._build_session(run_id, starting_balance)
        handle = open_dataset(self.args.dataset)
        self._dataset_id = {"manifest_sha": handle.manifest_sha(),
                            "kind": handle.manifest.get("kind"),
                            "symbol": self.args.symbol, "days": days}
        self._last_mark = {}
        self._first_event_ms = None
        commit_cursor: dict[str, Any] | None = None
        prior_stop: dict[str, Any] | None = None
        adapters, modules = session._strategy_adapters()
        self._adapter_names = sorted(adapters)
        try:
            if self.args.resume:
                resumed = self._restore(session)
                commit_cursor = {"day": resumed["day"], "seq": resumed["seq"]}
                stop_file = self.ckpt_dir / "stop_cursor.json"
                if stop_file.exists():
                    prior_stop = json.loads(stop_file.read_text(
                        encoding="utf-8"))
                session.store.checkpoint(run_id, "bench-resume",
                                         {"cursor": resumed})
                print(f"resumed {run_id} at {resumed}", flush=True)
            else:
                if self.ckpt_path.exists():
                    raise FileExistsError(
                        f"checkpoint exists at {self.ckpt_path}; pass --resume")
                session.store.create_run(run_id, "bench", session.config.fingerprint,
                                         str(self.workdir), os.getpid())
                session.store.checkpoint(run_id, "bench-open",
                                         {"dataset": str(self.args.dataset),
                                          "symbol": self.args.symbol,
                                          "days": days})
            day_pos = {day: idx for idx, day in enumerate(days)}
            need_initial_commit = not self.args.resume
            status = "COMPLETE"
            stop_reason: str | None = None
            baselined = self.args.resume
            last_cursor: dict[str, Any] = {"day": days[0], "seq": 0}
            for day in days:
                if commit_cursor is not None \
                        and day_pos[day] < day_pos[commit_cursor["day"]]:
                    continue  # whole day committed: skip.
                stream = iter(handle.events(self.args.symbol, day))
                while True:
                    t0 = time.perf_counter()
                    try:
                        event = next(stream)
                    except StopIteration:
                        break
                    finally:
                        self._t_read += time.perf_counter() - t0
                    if event is None:
                        self._n_heartbeats += 1
                        now_ms = int((session.clock.now() - datetime(
                            1970, 1, 1, tzinfo=timezone.utc)
                        ).total_seconds() * 1000)
                        session.clock.set_ms(now_ms + 1000)
                        continue
                    seq = int(event.get("seq", 0))
                    if commit_cursor is not None and day == commit_cursor["day"] \
                            and seq <= int(commit_cursor["seq"]):
                        continue  # already committed: skip without replay.
                    if not baselined:
                        session.clock.set_ms(int(event["exchange_ts_ms"]))
                        session.policy.reconcile_day(
                            session.config.paper_capital_usdt, 0.0)
                        session._day = accounting_date(
                            session.now_utc()).isoformat()
                        self._first_event_ms = int(event["exchange_ts_ms"])
                        baselined = True
                    self._track_mark(event)
                    exch_ms = event.get("exchange_ts_ms")
                    if isinstance(exch_ms, (int, float)) and exch_ms > 0:
                        # Replay clock tracks event time (30MIN scoring fix):
                        # without this the 1s quote-age gate compares a
                        # heartbeat-lagged clock against event-time marks and
                        # every candidate dies stale on the bench path.
                        # set_ms is forward-only: safe for resume/replay.
                        session.clock.set_ms(int(exch_ms))
                    t1 = time.perf_counter()
                    session._ingest(event, adapters, modules)
                    session._roll_day_if_needed()
                    self._t_ingest += time.perf_counter() - t1
                    self._track_position(session)
                    self._n_ingested += 1
                    session._events_seen += 1
                    session._last_seq = seq
                    last_cursor = {"day": day, "seq": seq}
                    if prior_stop is not None and (
                            day_pos[day] < day_pos[prior_stop["day"]]
                            or (day == prior_stop["day"]
                                and seq <= int(prior_stop["seq"]))):
                        self._n_replayed += 1  # uncommitted tail, replayed.
                    if self.args.max_events is not None \
                            and self._n_ingested >= int(self.args.max_events):
                        stop_reason = "max_events"
                        status = "TRUNCATED_MAX_EVENTS"
                        break
                    if self._stop_reason is not None \
                            or time.monotonic() >= deadline:
                        stop_reason = self._stop_reason or "wall_budget"
                        status = "INCOMPLETE_BUDGET"
                        break
                    if need_initial_commit and self._is_flat(session):
                        # Run start is a flat boundary: guarantees resume can
                        # always replay from a commit, even for tiny chunks.
                        self._commit(session, dict(last_cursor))
                        need_initial_commit = False
                    if self._n_ingested % int(self.args.commit_every) == 0:
                        self._commit(session, dict(last_cursor))
                    if self._n_ingested % 5000 == 0:
                        t2 = time.perf_counter()
                        session.store.heartbeat(run_id, os.getpid())
                        self._t_store += time.perf_counter() - t2
                        remain = max(0.0, deadline - time.monotonic())
                        print(f"[bench] ingested={self._n_ingested} "
                              f"day={day} seq={seq} commits={self._n_commits} "
                              f"remaining={remain:.0f}s", file=sys.stderr,
                              flush=True)
                if stop_reason is not None:
                    break
                # Day boundary: commit when flat (cheap resume point).
                self._commit(session, dict(last_cursor))
            else:
                stop_reason = None
            if status == "COMPLETE":
                # Input exhausted: COMPLETE only when actually flat. Open
                # exposure is an unresolved end state, never a completed
                # economic result; no forced flatten, no forced commit.
                committed = self._commit(session, dict(last_cursor))
                if not committed or not self._is_flat(session):
                    status = "INCOMPLETE_EXPOSURE"
                    stop_reason = "exposed_at_input_end"
            if status != "COMPLETE":
                _atomic_write_json(self.ckpt_dir / "stop_cursor.json",
                                   dict(last_cursor))
            report = self._report(session, run_id, days, status, stop_reason,
                                  last_cursor, start_mono)
            fsync_s = _atomic_write_json(Path(self.args.report_out), report)
            self._t_fsync += fsync_s
            equity = report["booked"]["equity_close"]
            print(f"[bench] {status} ingested={self._n_ingested} "
                  f"replayed={self._n_replayed} commits={self._n_commits} "
                  f"equity={equity if equity is None else f'{equity:.2f}'}",
                  flush=True)
            return (0 if status == "COMPLETE" else EXIT_INCOMPLETE), report
        finally:
            try:
                session.engine.close()
            finally:
                session.store.close()

    def _value_close(self, session: Session) -> dict[str, Any]:
        """Closing valuation: sourced price or explicit unavailable.

        Flat books value at cash (exact, no mark needed). Open exposure
        marks at the latest sourced price (trade/mark/quote, newest
        first); with no sourced price the valuation is explicitly
        unavailable — never zero.
        """
        ledger = session.ledger
        try:
            exposed = abs(float(ledger.position_qty())) > 1e-12
        except Exception:  # noqa: BLE001 - report must not crash.
            return {"equity_close": None, "valuation": "unavailable",
                    "reason": "ledger unreadable"}
        if not exposed:
            try:
                return {"equity_close": float(ledger.marked_equity(0.0)),
                        "valuation": "cash-exact",
                        "reason": "flat: no mark required"}
            except Exception:  # noqa: BLE001 - report must not crash.
                return {"equity_close": None, "valuation": "unavailable",
                        "reason": "ledger unreadable"}
        mark = dict(getattr(self, "_last_mark", {}))
        if not mark:
            return {"equity_close": None, "valuation": "unavailable",
                    "reason": "exposed with no sourced price"}
        try:
            equity = float(ledger.marked_equity(float(mark["price"])))
        except Exception:  # noqa: BLE001 - report must not crash.
            return {"equity_close": None, "valuation": "unavailable",
                    "reason": "marking failed"}
        return {"equity_close": equity, "valuation": "sourced-mark",
                "reason": mark}

    def _report(self, session: Session, run_id: str, days: list[str],
                status: str, stop_reason: str | None,
                last_cursor: dict[str, Any],
                start_mono: float) -> dict[str, Any]:
        ledger = session.ledger
        close = self._value_close(session)
        elapsed = time.monotonic() - start_mono
        return {
            "runner_version": RUNNER_VERSION,
            "status": status,
            "stop_reason": stop_reason,
            "run_id": run_id,
            "dataset": str(self.args.dataset),
            "symbol": self.args.symbol,
            "days": days,
            "elapsed_s": round(elapsed, 3),
            "events": {"ingested": self._n_ingested,
                       "replayed_tail": self._n_replayed,
                       "heartbeats": self._n_heartbeats,
                       "commits": self._n_commits},
            "cursor": last_cursor,
            "booked": {
                "equity_open": float(session.config.paper_capital_usdt),
                "equity_close": close["equity_close"],
                "valuation": close["valuation"],
                "valuation_reason": close["reason"],
                "realised": float(ledger.net_realised()),
                "commissions": float(ledger.paid_costs()),
                "funding": float(ledger.funding_net()),
            },
            "estimated_costs": self._estimates,
            "profile": {
                "read_s": round(self._t_read, 3),
                "ingest_s": round(self._t_ingest, 3),
                "commit_s": round(self._t_commit, 3),
                "fsync_s": round(self._t_fsync, 3),
                "store_s": round(self._t_store, 3),
                "events_per_s": round(self._n_ingested / max(elapsed, 1e-9), 1),
            },
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bounded resumable benchmark run")
    parser.add_argument("--config", required=True)
    parser.add_argument("--dataset", required=True, help="dataset manifest .toml")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--days", required=True,
                        help="comma-separated YYYY-MM-DD UTC days")
    parser.add_argument("--wall-budget-s", type=float, required=True)
    parser.add_argument("--checkpoint-dir", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--run-id", default=None,
                        help="required for --resume (same id)")
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument("--report-out", required=True)
    parser.add_argument("--commit-every", type=int, default=2000)
    parser.add_argument("--engine-seed", type=int, default=42)
    parser.add_argument("--filters-file", default=None,
                        help="frozen exchangeInfo JSON (deterministic; "
                             "no live REST when set)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.wall_budget_s <= 0:
        print("--wall-budget-s must be positive", file=sys.stderr)
        return 2
    if args.resume and not args.run_id:
        print("--resume needs --run-id", file=sys.stderr)
        return 2
    runner = BenchRunner(args)
    try:
        rc, _ = runner.run()
    except (ValueError, FileNotFoundError, FileExistsError, OSError) as exc:
        print(f"bench failed: {exc}", file=sys.stderr)
        return 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
