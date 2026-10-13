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
RUNNER_VERSION = "bench-run-v1"


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

    def _build_session(self, run_id: str) -> Session:
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
            starting_balance_usdt=config.paper_capital_usdt,
            random_seed=int(self.args.engine_seed),
            rest_get=rest_get)
        session = Session(config, store, self.workdir, run_id,
                          pid=os.getpid(), clock=clock, engine=engine)
        engine.bind_sink(session.policy)
        return session

    # -- flat-boundary checkpoints ------------------------------------
    def _is_flat(self, session: Session) -> bool:
        if session._position is not None:
            return False
        try:
            return len(session.engine.open_orders()) == 0
        except Exception:  # noqa: BLE001 - unknown engine state: not flat.
            return False

    def _snapshot(self, session: Session, cursor: dict[str, Any]) -> dict[str, Any]:
        risk_state = (self.workdir / "risk_state.json").read_text(
            encoding="utf-8") if (self.workdir / "risk_state.json").exists() else None
        journal = self.workdir / "engine_journal.jsonl"
        cooldowns = {f"{k[0]}|{k[1]}": v.isoformat()
                     for k, v in session.selector._cooldowns.items()}
        clock_ms = int((session.clock.now() - datetime(
            1970, 1, 1, tzinfo=timezone.utc)).total_seconds() * 1000)
        return {
            "runner_version": RUNNER_VERSION,
            "cursor": cursor,
            "ledger": session.ledger.to_dict(),
            "risk_state_json": risk_state,
            "cooldowns": cooldowns,
            "journal_bytes": journal.stat().st_size if journal.exists() else 0,
            "clock_ms": clock_ms,
            "day": session._day,
            "counts": {"events_seen": session._events_seen,
                       "admitted": session._admitted,
                       "reject_counts": dict(session._reject_counts)},
            "seeds": {"engine_seed": int(self.args.engine_seed),
                      "filters": self._filters_provenance()},
            "estimates": self._estimates,
        }

    def _filters_provenance(self) -> str:
        import hashlib

        src = getattr(self.args, "filters_file", None)
        if not src:
            return "live-rest"
        digest = hashlib.sha256(Path(src).read_bytes()).hexdigest()[:16]
        return f"frozen:{digest}"

    def _commit(self, session: Session, cursor: dict[str, Any],
                force: bool = False) -> None:
        t0 = time.perf_counter()
        session._drain_engine()
        if not force and not self._is_flat(session):
            return  # not a flat boundary: cursor stays, tail grows.
        record = self._snapshot(session, cursor)
        record["forced"] = bool(force and not self._is_flat(session))
        fsync_s = _atomic_write_json(self.ckpt_path, record)
        self._t_fsync += fsync_s
        self._t_commit += time.perf_counter() - t0
        self._n_commits += 1

    def _close_estimates_at_end(self, session: Session) -> None:
        """Attribute estimates for positions flattened at input end."""
        pos = session._position
        res = pos["reservation_id"] if pos else self._open_reservation
        if res is None:
            return
        notional = self._admit_notional(session, res)
        rec: dict[str, Any] = {"reservation_id": res,
                               "instrument": pos["instrument"] if pos else None,
                               "side": pos["side"] if pos else None,
                               "notional_usdt": notional, "estimate": None,
                               "note": "bench-end-flatten"}
        if notional is not None:
            rec["estimate"] = estimate_for_notional(COST_S1, notional).to_dict()
        self._estimates.append(rec)
        self._open_reservation = None

    def _restore(self, session: Session) -> dict[str, Any]:
        """Restore the committed experiment; returns the commit cursor."""
        commit = json.loads(self.ckpt_path.read_text(encoding="utf-8"))
        if commit.get("runner_version") != RUNNER_VERSION:
            raise ValueError("checkpoint runner_version mismatch")
        if int(commit["seeds"]["engine_seed"]) != int(self.args.engine_seed):
            raise ValueError("engine_seed differs from checkpointed run")
        if commit["seeds"].get("filters") != self._filters_provenance():
            raise ValueError("filters source differs from checkpointed run")
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
        journal = self.workdir / "engine_journal.jsonl"
        keep = int(commit["journal_bytes"])
        if journal.exists():
            with open(journal, "r+b") as fh:
                fh.truncate(keep)  # drop the uncommitted tail; replay re-appends.
        session.engine.recover(session.policy)
        session.clock.set_ms(int(commit["clock_ms"]))
        session._day = commit["day"]
        session._events_seen = int(commit["counts"]["events_seen"])
        session._admitted = int(commit["counts"]["admitted"])
        session._reject_counts = dict(commit["counts"]["reject_counts"])
        session._last_seq = int(commit["cursor"]["seq"])
        self._estimates = list(commit["estimates"])
        return commit["cursor"]

    # -- estimates (separate from booked) -------------------------------
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
        session = self._build_session(run_id)
        handle = open_dataset(self.args.dataset)
        commit_cursor: dict[str, Any] | None = None
        prior_stop: dict[str, Any] | None = None
        try:
            if self.args.resume:
                if not self.ckpt_path.exists():
                    raise FileNotFoundError(
                        f"--resume but no checkpoint at {self.ckpt_path}")
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
            adapters, modules = session._strategy_adapters()
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
                        baselined = True
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
                if session._position is not None:
                    session._flatten("bench-end")
                    session._drain_engine()
                    self._track_position(session)
                    self._close_estimates_at_end(session)
                self._commit(session, dict(last_cursor), force=True)
            else:
                _atomic_write_json(self.ckpt_dir / "stop_cursor.json",
                                   dict(last_cursor))
            report = self._report(session, run_id, days, status, stop_reason,
                                  last_cursor, start_mono)
            fsync_s = _atomic_write_json(Path(self.args.report_out), report)
            self._t_fsync += fsync_s
            print(f"[bench] {status} ingested={self._n_ingested} "
                  f"replayed={self._n_replayed} commits={self._n_commits} "
                  f"equity={report['booked']['equity_close']:.2f}",
                  flush=True)
            return (0 if status == "COMPLETE" else EXIT_INCOMPLETE), report
        finally:
            try:
                session.engine.close()
            finally:
                session.store.close()

    def _report(self, session: Session, run_id: str, days: list[str],
                status: str, stop_reason: str | None,
                last_cursor: dict[str, Any],
                start_mono: float) -> dict[str, Any]:
        ledger = session.ledger
        try:
            equity_close = ledger.marked_equity(0.0)
        except Exception:  # noqa: BLE001 - report must not crash.
            equity_close = float("nan")
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
                "equity_close": equity_close,
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
