"""Bot v0.1 console application (manager-owned, A-001).

Commands:
  cryptobot doctor --config configs/paper.toml [--capture DIR]
  cryptobot run --mode replay --config C --capture DIR [...]
  cryptobot run --mode paper --config C [...]
  cryptobot replay --capture DIR --config C [...]
  cryptobot status --run-id ID
  cryptobot stop --run-id ID [--flatten]
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptobot.app.config import ConfigError, load_config
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore

__all__ = ["main"]


def _store_path(storage_dir: str) -> Path:
    return Path(storage_dir) / "cryptobot.db"


def _new_run_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}-{os.getpid()}"


def _parse_cli_duration(raw: str | None) -> int | None:
    if not raw:
        return None
    unit = raw[-1]
    scale = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(unit)
    try:
        magnitude = float(raw[:-1])
    except ValueError:
        magnitude = -1
    if scale is None or magnitude <= 0:
        print(f"bad --duration {raw!r}; want like '24h'", file=sys.stderr)
        raise SystemExit(2)
    return int(magnitude * scale)


def cmd_doctor(args: argparse.Namespace) -> int:
    problems: list[str] = []
    info: dict[str, object] = {
        "python": sys.version.split()[0],
        "package": "crypto-scalping-bot 0.1.0",
    }
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config: FAIL {exc}")
        return 1
    info["config_fingerprint"] = config.fingerprint
    info["mode"] = config.mode
    print(f"config: OK {args.config} fingerprint={config.fingerprint}")
    print(f"python: {info['python']} package: {info['package']}")
    if config.engine_kind == "nautilus":
        try:
            import cryptobot.adapters.paper_engine  # noqa: F401  (E-007)
            print("engine: OK nautilus adapter present")
            info["engine"] = "nautilus"
        except ImportError:
            problems.append("nautilus engine requested but "
                            "cryptobot.adapters.paper_engine is not integrated (E-007)")
            print("engine: BLOCKED (E-007 Nautilus adapter not integrated)")
    else:
        print("engine: reference-fake-venue (replay/tests only; paper refuses it)")
        info["engine"] = "reference"
    if args.capture:
        events = Path(args.capture) / "events.jsonl"
        if events.exists():
            with events.open(encoding="utf-8") as fh:
                first = fh.readline()
            try:
                klass = json.loads(first).get("input_class")
            except ValueError:
                klass = None
            print(f"capture: OK {args.capture} first-record class={klass}")
            info["capture"] = str(args.capture)
        else:
            problems.append(f"capture {args.capture} has no events.jsonl")
            print(f"capture: FAIL no events.jsonl in {args.capture}")
    storage = Path(config.storage_dir)
    try:
        storage.mkdir(parents=True, exist_ok=True)
        probe = storage / ".doctor_write_probe"
        probe.write_text("ok")
        probe.unlink()
        usage = os.statvfs(storage) if hasattr(os, "statvfs") else None
        free_mb = usage.f_bavail * usage.f_frsize / 1e6 if usage else -1
        print(f"storage: OK {storage} free={free_mb:.0f}MB budget={config.storage_budget_mb}MB")
        info["storage"] = str(storage)
    except OSError as exc:
        problems.append(f"storage {storage} not writable: {exc}")
        print(f"storage: FAIL {exc}")
    print(f"fees: {config.fee_label} taker={config.taker_bps}bps "
          f"(labeled simulation rates)")
    print(f"strategies: {','.join(config.strategies_enabled)} arms={config.strategies_arms} "
          f"legacy_exits={config.allow_legacy_exit_rules}")
    if problems:
        print(f"doctor: {len(problems)} problem(s)")
        return 1
    print("doctor: READY")
    return 0


def _install_stop_handler(session: Session) -> None:
    def _handle(signum: int, _frame: object) -> None:
        session._stop_flag = "graceful"
    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


def _run_replay(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    if config.mode != "replay":
        print(f"config mode is {config.mode!r}; use run --mode {config.mode}",
              file=sys.stderr)
        return 2
    if not args.capture:
        print("replay needs --capture <retained-capture-directory>", file=sys.stderr)
        return 2
    store = RunStore(_store_path(config.storage_dir))
    run_id = args.run_id or _new_run_id("replay")
    workdir = Path(config.storage_dir) / run_id
    session = Session(config, store, workdir, run_id, pid=os.getpid())
    _install_stop_handler(session)
    print(f"run: {run_id} workdir={workdir}")
    try:
        report = session.run_replay(
            args.capture, expect_class=args.expect_class or "observed-public",
            resume=bool(args.resume), crash_after=args.crash_after)
    except RuntimeError as exc:
        print(f"run {run_id} interrupted: {exc}", file=sys.stderr)
        print(f"resume with: cryptobot run --mode replay --config {args.config}"
              f" --capture {args.capture} --run-id {run_id} --resume")
        return 3
    finally:
        store.close()
    print(f"run {run_id} done: equity {report['opening_equity']:.2f} -> "
          f"{report['closing_equity']:.2f} USDT "
          f"({report['net_return_pct']:+.3f}%), admitted "
          f"{report['intents_admitted']}, events {report['events_seen']}")
    print(f"report: {workdir / 'report.json'}")
    return 0


def _run_paper(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    if config.mode != "paper":
        print(f"config mode is {config.mode!r}; use run --mode {config.mode}",
              file=sys.stderr)
        return 2
    try:
        from cryptobot.adapters import paper_engine as _paper  # noqa: F401  (E-007)
        from cryptobot.adapters import bridge as _bridge  # noqa: F401  (E-007)
    except ImportError:
        print("BLOCKED: E-007 Nautilus adapter not integrated "
              "(cryptobot.adapters.paper_engine/bridge missing).",
              file=sys.stderr)
        print("Paper mode cannot run on the reference engine by design.",
              file=sys.stderr)
        return 2
    from cryptobot.app.session import WallClock
    store = RunStore(_store_path(config.storage_dir))
    run_id = args.run_id or _new_run_id("paper")
    workdir = Path(config.storage_dir) / run_id
    clock = WallClock()
    if config.engine_kind == "live":
        # W3-24H P5 demo mode: config already enforces demo = true.
        # Credentials come ONLY from the environment (never chat/files).
        from cryptobot.adapters import binance_live as _live
        api_key = os.environ.get("BINANCE_DEMO_KEY", "")
        api_secret = os.environ.get("BINANCE_DEMO_SECRET", "")
        if not api_key or not api_secret:
            print("demo engine needs BINANCE_DEMO_KEY and "
                  "BINANCE_DEMO_SECRET in the environment.",
                  file=sys.stderr)
            return 2
        engine = _live.BinanceLiveEngine(
            api_key=api_key, api_secret=api_secret,
            journal_path=workdir / "live_engine_journal.jsonl",
            expected_leverage=int(config.leverage_cap),
            run_tag=run_id[:8], live_enable=True, demo=True,
            base_url=config.engine_base_url, now_utc=clock.now)
    else:
        engine = _paper.NautilusPaperEngine(
            outcome_sink=None, taker_bps=config.taker_bps,  # sink bound below
            now_utc=clock.now, submit_delay_ms=config.submit_delay_ms,
            fill_delay_ms=config.fill_delay_ms,
            journal_path=workdir / "paper_engine_journal.jsonl",
            starting_balance_usdt=config.paper_capital_usdt)
    session = Session(config, store, workdir, run_id, pid=os.getpid(),
                      clock=clock, engine=engine)
    engine.bind_sink(session.policy)
    _install_stop_handler(session)
    duration = _parse_cli_duration(args.duration) or config.duration_s
    print(f"run: {run_id} workdir={workdir} duration={duration}s")
    try:
        stream_host = getattr(engine, "stream_host", None)
        events = _bridge.live_events(
            symbols=list(config.symbols) or None,
            max_symbols=config.max_symbols,
            ws_host=stream_host() if callable(stream_host) else None)
        report = session.run_live(events, duration_s=duration,
                                  resume=bool(args.resume))
    finally:
        store.close()
        engine.close()
    print(f"run {run_id} done: equity {report['opening_equity']:.2f} -> "
          f"{report['closing_equity']:.2f} USDT "
          f"({report['net_return_pct']:+.3f}%), admitted "
          f"{report['intents_admitted']}, events {report['events_seen']}")
    print(f"report: {workdir / 'report.json'}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if args.mode == "replay":
        return _run_replay(args)
    return _run_paper(args)


def cmd_status(args: argparse.Namespace) -> int:
    store = RunStore(_store_path(args.storage))
    try:
        run = store.get_run(args.run_id)
        if run is None:
            print(f"unknown run {args.run_id}", file=sys.stderr)
            return 1
        counts = store.counts(args.run_id)
        beat = run.get("heartbeat_utc") or "?"
        try:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(beat)).total_seconds()
            age_s = f"{age:.0f}s ago"
        except ValueError:
            age_s = beat
        print(f"run: {run['run_id']} mode={run['mode']} state={run['state']}")
        print(f"pid: {run.get('pid')} heartbeat: {age_s}")
        print(f"workdir: {run['workdir']}")
        print(f"counts: {counts}")
        stop = store.stop_requested(args.run_id)
        if stop:
            print(f"stop requested: {stop}")
        report = Path(run["workdir"]) / "report.json"
        if report.exists():
            print(f"report: {report}")
        return 0
    finally:
        store.close()


def cmd_stop(args: argparse.Namespace) -> int:
    store = RunStore(_store_path(args.storage))
    try:
        run = store.get_run(args.run_id)
        if run is None:
            print(f"unknown run {args.run_id}", file=sys.stderr)
            return 1
        mode = "flatten" if args.flatten else "graceful"
        store.request_stop(args.run_id, mode)
        print(f"stop requested for {args.run_id} mode={mode}")
        return 0
    finally:
        store.close()


def cmd_backtest(args: argparse.Namespace) -> int:
    from cryptobot.research.backtest import main as harness_main
    argv = ["--dataset", args.dataset, "--out", args.out,
           "--config", args.config]
    if args.splits:
        argv += ["--splits", args.splits]
    if args.armsets:
        argv += ["--armsets", args.armsets]
    if args.symbols:
        argv += ["--symbols", args.symbols]
    if args.max_events is not None:
        argv += ["--max-events", str(args.max_events)]
    if args.sensitivity:
        argv += ["--sensitivity"]
    try:
        return int(harness_main(argv))
    except (ValueError, FileNotFoundError) as exc:
        print(f"backtest failed: {exc}", file=sys.stderr)
        return 1


def cmd_report(args: argparse.Namespace) -> int:
    from cryptobot.reporting import build_report
    from cryptobot.reporting.schemas import RunFileError
    from cryptobot.reporting.metrics import ReconciliationError
    run_dir = Path(args.run_dir)
    out_dir = Path(args.out) if args.out else run_dir / "analysis"
    try:
        artifacts = build_report(run_dir, out_dir)
    except (RunFileError, ReconciliationError) as exc:
        print(f"report failed: {exc}", file=sys.stderr)
        return 1
    for name, path in artifacts.items():
        print(f"{name}: {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cryptobot",
                                     description="Bot v0.1 paper/replay application")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("doctor")
    p.add_argument("--config", required=True)
    p.add_argument("--capture", default=None)
    p.set_defaults(func=cmd_doctor)
    p = sub.add_parser("run")
    p.add_argument("--mode", required=True, choices=("replay", "paper"))
    p.add_argument("--config", required=True)
    p.add_argument("--capture", default=None)
    p.add_argument("--duration", default=None)
    p.add_argument("--run-id", default=None)
    p.add_argument("--expect-class", default=None)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--crash-after", type=int, default=None)
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("replay")
    p.add_argument("--capture", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--run-id", default=None)
    p.add_argument("--expect-class", default=None)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--crash-after", type=int, default=None)
    p.set_defaults(func=lambda a: _run_replay(a))
    p = sub.add_parser("status")
    p.add_argument("--run-id", required=True)
    p.add_argument("--storage", default="runs")
    p.set_defaults(func=cmd_status)
    p = sub.add_parser("stop")
    p.add_argument("--run-id", required=True)
    p.add_argument("--flatten", action="store_true")
    p.add_argument("--storage", default="runs")
    p.set_defaults(func=cmd_stop)
    p = sub.add_parser("report")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_report)
    p = sub.add_parser("backtest")
    p.add_argument("--dataset", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--config", default="configs/paper.toml")
    p.add_argument("--splits", default=None)
    p.add_argument("--armsets", default=None)
    p.add_argument("--symbols", default=None)
    p.add_argument("--max-events", type=int, default=None)
    p.add_argument("--sensitivity", action="store_true")
    p.set_defaults(func=cmd_backtest)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
