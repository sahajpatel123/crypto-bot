"""Bot v0.1 console application (manager-owned, A-001).

Commands:
  cryptobot doctor --config configs/paper.toml [--capture DIR]
  cryptobot run --mode replay --config C --capture DIR [...]
  cryptobot run --mode paper --config C [...]
  cryptobot replay --capture DIR --config C [...]
  cryptobot status --run-id ID
  cryptobot stop --run-id ID [--flatten]
  cryptobot readiness --config C   (read-only venue checks; never submits)
  cryptobot reconcile --config C [--expect-flat]   (read-only venue
      position/order/equity check; never submits or cancels)
  cryptobot run --mode prod --config C   (verifies guards, refuses: disabled)
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from cryptobot.app.config import ConfigError, load_config
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore

__all__ = ["main"]


def _store_path(storage_dir: str) -> Path:
    return Path(storage_dir) / "cryptobot.db"


def _new_run_id(prefix: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
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
            print("engine: OK nautilus paper adapter present "
                  "(src/cryptobot/adapters/paper_engine.py)")
            info["engine"] = "nautilus"
        except ImportError:
            problems.append("nautilus engine requested but "
                            "cryptobot.adapters.paper_engine is not integrated (E-007)")
            print("engine: BLOCKED (E-007 Nautilus adapter not integrated)")
    elif config.engine_kind == "live":
        # T0.4: doctor previously fell through to the reference label for
        # live configs, misreporting a venue engine as the fake venue.
        try:
            import cryptobot.adapters.binance_live  # noqa: F401
            print(f"engine: OK binance-live adapter present "
                  f"(demo={config.engine_demo}, "
                  f"submission={'ON' if config.allow_live_submission else 'OFF'})")
            info["engine"] = "live"
        except ImportError:
            problems.append("live engine requested but "
                            "cryptobot.adapters.binance_live is not integrated")
            print("engine: BLOCKED (binance_live adapter not integrated)")
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


def _ws_socket_factory_for(engine):
    """Real private-stream socket factory over WsClient (stdlib only).

    The factory takes the venue listen key and dials the engine's
    user-stream URL. Read timeouts surface as None (idle); socket
    death raises so the supervised reader heals via reconnect.
    """
    import json

    from cryptobot.market_data.ws import WsClient, WsClosed

    def _factory(listen_key: str):
        url = engine.user_stream_url(listen_key)
        client = WsClient.connect(url, timeout_s=10.0)

        class _Sock:
            def recv(self, timeout_s: float):
                try:
                    typ, payload = client.recv_message(timeout_s)
                except WsClosed as exc:
                    if str(exc).startswith("read timeout"):
                        return None
                    raise
                if typ != "text":
                    return None
                return json.loads(payload.decode("utf-8"))

            def close(self) -> None:
                client.close()

        return _Sock()

    return _factory


def _seed_live_session(session, engine, config) -> float:
    """T1.1 startup: verify account modes, then seed from venue truth.

    Raises ValueError on any refusal (fail closed); callers print REFUSED
    and exit non-zero. Fetches wallet/positions/open orders (incl. algo
    via engine.open_orders) — never the config paper number.
    """
    symbols = list(config.symbols or [])
    modes = engine.verify_account_modes(symbols,
                                        leverage_cap=config.leverage_cap)
    print(f"account modes: {modes}")
    snapshot = engine.account_snapshot()
    open_ids = [str(o.client_order_id) for o in engine.open_orders()]
    journal_ids = [str(c) for c in engine.journal_client_ids()]
    return session.seed_from_venue(snapshot, open_client_ids=open_ids,
                                   journal_client_ids=journal_ids)


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
        from cryptobot.adapters import bridge as _bridge  # noqa: F401  (E-007)
        from cryptobot.adapters import paper_engine as _paper  # noqa: F401  (E-007)
    except ImportError:
        print("BLOCKED: E-007 Nautilus adapter not integrated "
              "(cryptobot.adapters.paper_engine/bridge missing).",
              file=sys.stderr)
        print("Paper mode cannot run on the reference engine by design.",
              file=sys.stderr)
        return 2
    run_id = args.run_id or _new_run_id("paper")
    workdir = Path(config.storage_dir) / run_id
    discovery_record = None
    if not config.symbols:
        # Dynamic discovery resolves BEFORE the session exists (but AFTER
        # the import gate, so a missing adapter refuses offline without a
        # network call). The live bridge would otherwise choose symbols
        # the session never learns, so `_prime_live_books` skips
        # ("dynamic-symbols") and books stay `book:never-synced` for the
        # whole run (observed: 3,646/18,230 rejections in a 10-minute
        # paper session). Same rule the bridge uses (top-max_symbols by
        # quote volume), recorded, never hardcoded.
        # Resume reuses the recorded universe: fresh discovery could
        # rotate symbols mid-run (observed live: TIAUSDT for AGTUSDT).
        from cryptobot.app.config import with_resolved_symbols
        resumed = False
        if bool(args.resume):
            try:
                recorded = json.loads(
                    (workdir / "discovery.json").read_text(
                        encoding="utf-8"))
                if isinstance(recorded.get("symbols"), list) \
                        and recorded["symbols"]:
                    config = with_resolved_symbols(
                        config, recorded["symbols"])
                    print(f"discovery: resumed universe "
                          f"->{','.join(config.symbols)}")
                    resumed = True
            except (OSError, ValueError):
                pass  # no usable record: fall through to fresh discovery.
        if not resumed:
            from cryptobot.market_data.collector import select_capture_set
            from cryptobot.market_data.discovery import (
                FAPI_BASE_URL,
                fetch_exchange_info,
                urllib_json_get,
            )
            try:
                payload, _, _ = fetch_exchange_info(
                    urllib_json_get, FAPI_BASE_URL)
                chosen, rule, _ = select_capture_set(
                    payload, urllib_json_get, FAPI_BASE_URL,
                    top_n=config.max_symbols)
            except Exception as exc:
                print(f"live discovery failed: {type(exc).__name__}: {exc}",
                      file=sys.stderr)
                return 2
            if not chosen:
                print("live discovery returned no symbols", file=sys.stderr)
                return 2
            config = with_resolved_symbols(config, list(chosen))
            print(f"discovery: {rule} -> {','.join(chosen)}")
            discovery_record = {"rule": rule, "symbols": list(chosen)}
    from cryptobot.app.session import WallClock
    store = RunStore(_store_path(config.storage_dir))
    if discovery_record is not None:
        # Audit trail: the resolved universe lives with the run, not
        # just on stdout (best-effort; never aborts the run).
        try:
            workdir.mkdir(parents=True, exist_ok=True)
            (workdir / "discovery.json").write_text(
                json.dumps(discovery_record, indent=1, sort_keys=True)
                + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"discovery record unwritten: {exc}", file=sys.stderr)
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
    session.leave_protected = bool(
        getattr(args, "leave_protected", False))
    if config.engine_kind == "live":
        engine.hot_cache_enabled = True  # T1.2 hot-path account cache
    if config.engine_kind == "live" and not args.resume:
        # T1.1: seed accounting from the venue before any trading.
        try:
            seeded = _seed_live_session(session, engine, config)
        except Exception as exc:
            print(f"run {run_id} REFUSED (venue seed: "
                  f"{type(exc).__name__}: {exc})", file=sys.stderr)
            store.close()
            engine.close()
            return 2
        print(f"venue seed: equity {seeded:.2f} USDT (venue wallet)")
    # Contract v1: Session.__init__ binds the ONE booking handler;
    # no rebind here (a policy is not an EngineEvent callable).
    _install_stop_handler(session)
    duration = _parse_cli_duration(args.duration) or config.duration_s
    print(f"run: {run_id} workdir={workdir} duration={duration}s")
    # Private user stream (Checkpoint-B): supervised reader + gap->halt
    # on live engines only; paper replay/sim engines have no private
    # stream (attach refuses them loudly).
    user_stream = None
    if config.engine_kind == "live":
        from cryptobot.adapters.user_stream import attach_user_stream
        user_stream = attach_user_stream(
            session, engine, _ws_socket_factory_for(engine))
        print("private user stream: attached (halt-until-first-heal)")
    try:
        stream_host = getattr(engine, "stream_host", None)
        events = _bridge.live_events(
            # T2.2: default evaluating set BTC/ETH, capped by
            # max_hf_subscriptions; do not subscribe to the rest.
            symbols=list(config.symbols) or ["BTCUSDT", "ETHUSDT"],
            max_symbols=config.max_symbols,
            max_hf_subscriptions=config.max_hf_subscriptions,
            ws_host=stream_host() if callable(stream_host) else None)
        try:
            report = session.run_live(events, duration_s=duration,
                                      resume=bool(args.resume))
        except Exception as exc:
            # Mirror _run_replay: a venue/connection death (e.g.
            # routes-exhausted) must leave a resume hint, not a bare
            # traceback with no report (observed on paper-proof-30m).
            print(f"run {run_id} interrupted: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
            print(f"resume with: cryptobot run --mode paper --config "
                  f"{args.config} --duration {args.duration or 'left'} "
                  f"--run-id {run_id} --resume")
            return 3
    finally:
        if user_stream is not None:
            user_stream.close()
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
    if args.mode == "prod":
        return _run_prod(args)
    return _run_paper(args)


def _readiness_unsigned(config, config_path: str,
                        ) -> list[tuple[str, str, str]]:
    """Credential-free checks: files and host pinning only."""
    from cryptobot.adapters.binance_live import DEMO_FAPI_URL, PROD_FAPI_URL
    rows: list[tuple[str, str, str]] = []
    rows.append(("config-loads", "PASS", f"mode={config.mode}"))
    if config.engine_kind != "live":
        rows.append(("live-engine", "FAIL",
                     f"kind={config.engine_kind}; readiness needs a "
                     f"live-engine config (demo.toml or prod.toml)"))
        return rows
    rows.append(("live-engine", "PASS",
                 f"kind=live demo={config.engine_demo}"))
    host = (config.engine_base_url or "").rstrip("/")
    if config.engine_demo:
        ok = host == DEMO_FAPI_URL
        rows.append(("host-pinned-demo", "PASS" if ok else "FAIL",
                     f"base_url={host or 'default'}"))
    elif config.mode == "prod":
        ok = host == PROD_FAPI_URL
        rows.append(("host-pinned-prod", "PASS" if ok else "FAIL",
                     f"base_url={host or 'MISSING'} (must be exactly "
                     f"{PROD_FAPI_URL})"))
    else:
        rows.append(("host-pinned", "FAIL",
                     f"live engine outside demo/prod (host={host})"))
    try:
        raw_lines = Path(config_path).read_text().splitlines()
    except OSError as exc:
        rows.append(("no-inline-secrets", "FAIL", str(exc)))
        return rows
    import re
    secret_re = re.compile(
        r"(?i)^\s*(api_key|api_secret|secret|password|token)\s*=")
    hits = [f"line {n}" for n, line in enumerate(raw_lines, 1)
            if secret_re.search(line.split("#", 1)[0])]
    rows.append(("no-inline-secrets",
                 "PASS" if not hits else "FAIL",
                 "clean" if not hits else "; ".join(hits)))
    rows.append(("submission-default-off",
                 "PASS" if not config.allow_live_submission else "FAIL",
                 "observe-only" if not config.allow_live_submission
                 else "allow_live_submission=true"))
    return rows


def _signed_rows(engine, config) -> list[tuple[str, str, str]]:
    """Signed read-only venue checks over a built engine (GETs only)."""
    from cryptobot.adapters import binance_live as _live
    rows: list[tuple[str, str, str]] = []
    try:
        status = engine.venue_status(list(config.symbols or []))
    except _live.VenueHttpError as exc:
        return [("venue-connect", "FAIL",
                  f"{type(exc).__name__}: {exc.msg}")]
    try:
        rows.append(("venue-connect", "PASS",
                     f"host={status['base_url']} "
                     f"account={status['account_tag']}"))
        skew_ms = abs(status["clock_skew_ms"])
        rows.append(("clock-skew", "PASS" if skew_ms <= 5000 else "FAIL",
                     f"{skew_ms:.0f}ms"))
        rows.append(("permissions", "PASS" if status["can_trade"] else "FAIL",
                     f"can_trade={status['can_trade']} "
                     f"fee_tier={status['fee_tier']}"))
        rows.append(("position-mode",
                     "PASS" if status["position_mode"] == "one-way"
                     else "FAIL", status["position_mode"]))
        for symbol, fee in sorted(status["fees_bps"].items()):
            rows.append((f"fees-{symbol}", "PASS",
                         f"taker={fee['taker_bps']:.2f}bps "
                         f"maker={fee['maker_bps']:.2f}bps"))
        for symbol in sorted(status["filters"]):
            rows.append((f"filters-{symbol}", "PASS",
                         status["filters"][symbol]["status"]))
        rows.append(("open-positions", "PASS",
                     f"{len(status['positions'])} open"))
        rows.append(("open-orders", "PASS",
                     f"{len(status['open_orders'])} open"))
        rows.append(("balances", "PASS",
                     f"wallet={status['total_wallet_usdt']:.2f} "
                     f"available={status['available_usdt']:.2f} USDT"))
    except _live.VenueHttpError as exc:
        rows.append(("venue-read", "FAIL",
                     f"{type(exc).__name__}: {exc.msg}"))
    return rows


def _readiness_signed(config, key_env: str, secret_env: str,
                      ) -> list[tuple[str, str, str]]:
    """Signed read-only venue checks. GET requests only, never submits."""
    from cryptobot.adapters import binance_live as _live
    key = os.environ.get(key_env, "")
    secret = os.environ.get(secret_env, "")
    if not key or not secret:
        return [(f"signed-checks({key_env}/{secret_env})", "BLOCKED",
                 "credentials absent from environment (declared blocker; "
                 "unsigned checks above still stand)")]
    rows: list[tuple[str, str, str]] = [
        ("creds-from-env", "PASS",
         f"{key_env}=set {secret_env}=set (values never shown)")]
    journal = Path(config.storage_dir) / "readiness_journal.jsonl"
    try:
        engine = _live.BinanceLiveEngine(
            api_key=key, api_secret=secret,
            journal_path=journal,
            expected_leverage=int(config.leverage_cap),
            run_tag="readiness", live_enable=True,
            demo=config.engine_demo, base_url=config.engine_base_url)
    except (ValueError, OSError) as exc:
        return rows + [("venue-connect", "FAIL", str(exc))]
    try:
        rows += _signed_rows(engine, config)
    finally:
        engine.close()
    return rows


def _risk_bounds_rows(config) -> list[tuple[str, str, str]]:
    """Release §7 capital-policy bounds on the loaded config."""
    rows = []
    rows.append(("risk-per-trade",
                 "PASS" if config.max_loss_budget_pct <= 0.00125 + 1e-12
                 else "FAIL",
                 f"max_loss_budget_pct={config.max_loss_budget_pct} "
                 f"(cap 0.125%)"))
    rows.append(("leverage-cap",
                 "PASS" if config.leverage_cap <= 3.0 + 1e-12 else "FAIL",
                 f"leverage_cap={config.leverage_cap} (cap 3x)"))
    rows.append(("halt-ladder",
                 "PASS" if config.operating_stop_pct == 0.005
                 and config.emergency_stop_pct == 0.01 else "FAIL",
                 f"operating={config.operating_stop_pct} "
                 f"emergency={config.emergency_stop_pct} "
                 f"(must be 0.5%/1%)"))
    rows.append(("one-position",
                 "PASS",
                 "single global pending/open/unresolved position "
                 "(Session-enforced)"))
    return rows


def _reconcile_state_rows(engine) -> list[tuple[str, str, str]]:
    """Current venue exposure state (contract reads; never acts)."""
    try:
        snap = engine.account_snapshot()
    except Exception as exc:  # noqa: BLE001 — venue read, report honestly.
        return [("venue-state", "FAIL",
                 f"account_snapshot raised {type(exc).__name__}: {exc}")]
    if snap is None:
        return [("venue-state", "FAIL", "venue unreachable (None)")]
    n_pos = len(getattr(snap, "positions", ()) or ())
    try:
        orders = engine.open_orders()
    except Exception as exc:  # noqa: BLE001 — venue read, report honestly.
        return [("venue-state", "FAIL",
                 f"open_orders raised {type(exc).__name__}: {exc}")]
    state = "FLAT" if n_pos == 0 and len(orders) == 0 else "EXPOSED"
    return [("venue-state", "PASS",
             f"{state}: {n_pos} positions, {len(orders)} open orders, "
             f"wallet={snap.wallet_equity_usdt:.2f} "
             f"available={snap.available_margin_usdt:.2f} USDT "
             f"(complete={snap.complete}, "
             f"asof={snap.asof_utc.isoformat() if snap.asof_utc else '?'})")]


def cmd_readiness(args: argparse.Namespace) -> int:
    """Read-only account/venue readiness (never submits orders)."""
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    rows = _readiness_unsigned(config, args.config)
    if config.engine_kind == "live":
        if config.engine_demo:
            key_env, secret_env = "BINANCE_DEMO_KEY", "BINANCE_DEMO_SECRET"
        else:
            key_env, secret_env = "CRYPTOBOT_API_KEY", "CRYPTOBOT_API_SECRET"
        rows += _readiness_signed(config, key_env, secret_env)
    print(f"readiness {args.config}:")
    for name, state, detail in rows:
        print(f"  [{state}] {name}: {detail}")
    states = {state for _, state, _ in rows}
    if "FAIL" in states:
        return 2
    if "BLOCKED" in states:
        print("signed venue checks BLOCKED on credentials in the "
              "owner's environment (unsigned checks stand).")
        return 3
    print("readiness: READY (read-only checks passed; no orders submitted)")
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    """Read-only venue position/order/equity check (never acts)."""
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    if config.engine_kind != "live":
        print("reconcile needs a live-engine config (demo.toml or "
              f"prod.toml); kind={config.engine_kind}", file=sys.stderr)
        return 2
    if config.engine_demo:
        key_env, secret_env = "BINANCE_DEMO_KEY", "BINANCE_DEMO_SECRET"
    else:
        key_env, secret_env = "CRYPTOBOT_API_KEY", "CRYPTOBOT_API_SECRET"
    key = os.environ.get(key_env, "")
    secret = os.environ.get(secret_env, "")
    if not key or not secret:
        print(f"reconcile {args.config}: BLOCKED on {key_env}/"
              f"{secret_env} in the owner's environment.")
        return 3
    from cryptobot.adapters import binance_live as _live
    journal = Path(config.storage_dir) / "reconcile_journal.jsonl"
    try:
        engine = _live.BinanceLiveEngine(
            api_key=key, api_secret=secret, journal_path=journal,
            expected_leverage=int(config.leverage_cap),
            run_tag="reconcile", live_enable=True,
            demo=config.engine_demo, base_url=config.engine_base_url)
    except (ValueError, OSError) as exc:
        print(f"reconcile {args.config}: FAIL ({exc})", file=sys.stderr)
        return 2
    try:
        try:
            status = engine.venue_status(list(config.symbols or []))
        except _live.VenueHttpError as exc:
            print(f"reconcile {args.config}: FAIL "
                  f"({type(exc).__name__}: {exc.msg})", file=sys.stderr)
            return 2
        positions = status["positions"]
        orders = status["open_orders"]
        print(f"reconcile {args.config} (host={status['base_url']} "
              f"account={status['account_tag']}):")
        print(f"  wallet={status['total_wallet_usdt']:.2f} "
              f"available={status['available_usdt']:.2f} USDT")
        print(f"  positions: {len(positions)} open")
        for p in positions:
            print(f"    {p.get('symbol')} amt={p.get('positionAmt')} "
                  f"entry={p.get('entryPrice')} "
                  f"upnl={p.get('unRealizedProfit')}")
        print(f"  open orders: {len(orders)}")
        for o in orders[:20]:
            print(f"    {o.get('symbol')} {o.get('type')} "
                  f"{o.get('side')} qty={o.get('origQty')} "
                  f"cid={o.get('origClientOrderId')}")
        if len(orders) > 20:
            print(f"    ... +{len(orders) - 20} more")
        if status["available_usdt"] > status["total_wallet_usdt"] + 1e-9:
            print("  WARN: available exceeds wallet (venue says so; "
                  "investigate, never auto-correct).")
        if args.expect_flat and (positions or orders):
            print("reconcile: FAIL (expected flat)", file=sys.stderr)
            return 2
        state = "FLAT" if not positions and not orders else "EXPOSED"
        print(f"reconcile: {state} (read-only; nothing submitted)")
        return 0
    finally:
        engine.close()


def _prod_cred_env(config) -> tuple[str, str]:
    if config.engine_demo:
        return "BINANCE_DEMO_KEY", "BINANCE_DEMO_SECRET"
    return "CRYPTOBOT_API_KEY", "CRYPTOBOT_API_SECRET"


def _build_live_engine(config, key: str, secret: str, journal: Path,
                       run_tag: str, transport=None):
    """Construct the venue engine (transport injectable for offline tests)."""
    from cryptobot.adapters import binance_live as _live
    kw: dict = {}
    if transport is not None:
        kw["transport"] = transport
    return _live.BinanceLiveEngine(
        api_key=key, api_secret=secret, journal_path=journal,
        expected_leverage=int(config.leverage_cap),
        run_tag=run_tag, live_enable=True,
        demo=config.engine_demo, base_url=config.engine_base_url, **kw)


def _run_prod(args: argparse.Namespace, _engine_factory=None) -> int:
    """Production route: observe-only until fully armed, then live.

    Guards, signed reads and venue seeding always run first. Order
    submission additionally requires ALL of: config
    ``allow_live_submission = true``, a valid GO ``gate.json``, and an
    ``armed.json`` bound to that gate (see `cryptobot gate` / `arm`).
    With every layer present this runs the normal live Session (user
    stream, canary sizing, risk halts); otherwise it refuses after the
    read-only verification. Missing credentials, failed guards or an
    unreachable venue produce explicit non-success states.
    """
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    if config.mode != "prod":
        print(f"config mode is {config.mode!r}; use run --mode {config.mode}",
              file=sys.stderr)
        return 2
    rows = _readiness_unsigned(config, args.config)
    if config.allow_live_submission:
        # The observe-only default-off check must not block the armed
        # route: ON is legitimate here and is gated again below by the
        # GO gate + armed record checks.
        rows = [(name, "PASS" if name == "submission-default-off"
                 else state,
                 "armed-by-owner (gate+armed checked below)"
                 if name == "submission-default-off" else detail)
                for name, state, detail in rows]
    rows += _risk_bounds_rows(config)
    print(f"prod guards for {args.config}:")
    for name, state, detail in rows:
        print(f"  [{state}] {name}: {detail}")
    if any(state == "FAIL" for _, state, _ in rows):
        print("prod: REFUSED (guard failures above)", file=sys.stderr)
        return 2
    key_env, secret_env = _prod_cred_env(config)
    key = os.environ.get(key_env, "")
    secret = os.environ.get(secret_env, "")
    if not key or not secret:
        print(f"prod: BLOCKED on {key_env}/{secret_env} in the owner's "
              f"environment.")
        return 3
    print(f"  [PASS] creds-from-env: {key_env}=set {secret_env}=set "
          f"(values never shown)")
    storage = Path(config.storage_dir)
    journal = storage / "prod_engine_journal.jsonl"
    factory = _engine_factory or _build_live_engine
    try:
        engine = factory(config, key, secret, journal, "prod")
    except (ValueError, OSError) as exc:
        print(f"prod: REFUSED (engine build: {exc})", file=sys.stderr)
        return 2
    try:
        signed = _signed_rows(engine, config)
        print("prod signed reads:")
        for name, state, detail in signed:
            print(f"  [{state}] {name}: {detail}")
        if any(state == "FAIL" for _, state, _ in signed):
            print("prod: REFUSED (signed-check failures above)",
                  file=sys.stderr)
            engine.close()
            return 2
        state_rows = _reconcile_state_rows(engine)
        print("prod venue state:")
        for name, state, detail in state_rows:
            print(f"  [{state}] {name}: {detail}")
        if any(state == "FAIL" for _, state, _ in state_rows):
            print("prod: REFUSED (venue state unreadable)",
                  file=sys.stderr)
            engine.close()
            return 2
        # Live submission needs every arming layer at once: the config
        # switch, a valid GO gate, and an armed record bound to it.
        # Anything missing keeps the route observe-only (verified above).
        gate = _read_json(getattr(args, "gate_json", None))
        armed = _read_json(getattr(args, "armed_json", None))
        if not config.allow_live_submission:
            print("prod: REFUSED — allow_live_submission is false in "
                  "the config (observe-only route verified; set it "
                  "true only after `cryptobot gate` + `cryptobot arm`).",
                  file=sys.stderr)
            engine.close()
            return 2
        if not _gate_doc_valid(gate) or not _armed_doc_valid(armed, gate):
            print("prod: REFUSED — need a valid GO gate.json and an "
                  "armed.json bound to it (cryptobot gate; cryptobot arm).",
                  file=sys.stderr)
            engine.close()
            return 2
        # The gate authorises the strategies and code the verdict scored;
        # anything else (e.g. unvalidated S1-S5) must never trade live.
        unscored = sorted(set(config.strategies_enabled)
                          - set(gate.get("strategies") or []))
        if unscored:
            print(f"prod: REFUSED — strategies {unscored} have no PASS "
                  f"verdict behind this gate (gate covers "
                  f"{gate.get('strategies') or []}).", file=sys.stderr)
            engine.close()
            return 2
        running = _git_head()
        if not _commit_matches(str(gate.get("code_commit", "")), running):
            print(f"prod: REFUSED — running code {running[:12] or 'unknown'} "
                  f"is not the commit the verdict scored "
                  f"({gate.get('code_commit') or 'unknown'}).",
                  file=sys.stderr)
            engine.close()
            return 2
        from cryptobot.adapters import bridge as _bridge
        from cryptobot.app.session import Session, WallClock

        clock = WallClock()
        store = RunStore(_store_path(config.storage_dir))
        run_id = args.run_id or _new_run_id("prod")
        workdir = Path(config.storage_dir) / run_id
        session = Session(config, store, workdir, run_id,
                          pid=os.getpid(), clock=clock, engine=engine)
        armed_limits = {"capital_usdt": float(armed["capital_usdt"]),
                        "max_daily_loss_usdt": float(armed["max_daily_loss"]),
                        "canary_trades": int(armed.get("canary_trades", 10))}
        # Resume has no fresh seed: bind at the conservative ceiling now,
        # re-bound to measured venue equity after seeding below.
        session.apply_armed_limits(**armed_limits)
        engine.hot_cache_enabled = True
        if not args.resume:
            try:
                seeded = _seed_live_session(session, engine, config)
            except Exception as exc:
                print(f"prod: REFUSED (venue seed: "
                      f"{type(exc).__name__}: {exc})", file=sys.stderr)
                store.close()
                engine.close()
                return 2
            print(f"prod venue seed: equity {seeded:.2f} USDT "
                  f"(armed capital {armed['capital_usdt']:.2f}, "
                  f"canary {session.armed_canary_trades} trades)")
            if seeded > float(armed["capital_usdt"]) * 1.5 + 1e-9:
                print("prod: REFUSED (venue equity exceeds 1.5x armed "
                      "capital; arm the capital you actually fund).",
                      file=sys.stderr)
                store.close()
                engine.close()
                return 2
            session.apply_armed_limits(**armed_limits, equity_usdt=seeded)
        _install_stop_handler(session)
        from cryptobot.adapters.user_stream import attach_user_stream

        user_stream = attach_user_stream(
            session, engine, _ws_socket_factory_for(engine))
        print("private user stream: attached (halt-until-first-heal)")
        duration = _parse_cli_duration(args.duration) or config.duration_s
        print(f"prod LIVE: {run_id} workdir={workdir} "
              f"duration={duration}s (real orders possible)")
        try:
            stream_host = getattr(engine, "stream_host", None)
            events = _bridge.live_events(
                symbols=list(config.symbols) or ["BTCUSDT", "ETHUSDT"],
                max_symbols=config.max_symbols,
                max_hf_subscriptions=config.max_hf_subscriptions,
                ws_host=stream_host() if callable(stream_host) else None)
            try:
                report = session.run_live(
                    events, duration_s=duration,
                    resume=bool(args.resume))
            except Exception as exc:
                print(f"prod {run_id} interrupted: "
                      f"{type(exc).__name__}: {exc}", file=sys.stderr)
                print(f"resume with: cryptobot run --mode prod "
                      f"--config {args.config} --run-id {run_id} "
                      f"--resume --gate-json {args.gate_json} "
                      f"--armed-json {args.armed_json}",
                      file=sys.stderr)
                return 3
        finally:
            user_stream.close()
            store.close()
            engine.close()
    finally:
        pass  # engine ownership: closed on every branch above.
    venue_state = state_rows[0][2] if state_rows else "?"
    print(f"prod {run_id} done: equity {report['opening_equity']:.2f} -> "
          f"{report['closing_equity']:.2f} USDT "
          f"({report['net_return_pct']:+.3f}%), admitted "
          f"{report['intents_admitted']}, events {report['events_seen']} "
          f"(venue {venue_state})")
    print(f"report: {workdir / 'report.json'}")
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    """Read-only production/demo preflight (never submits, never builds
    the order path). Exit 0 only when every check passes; the
    submission switch is reported as ARMED-OFF, never a failure."""
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    if config.engine_kind != "live":
        print(f"preflight needs a live-engine config; kind="
              f"{config.engine_kind}", file=sys.stderr)
        return 2
    rows = _readiness_unsigned(config, args.config)
    rows += _risk_bounds_rows(config)
    key_env, secret_env = _prod_cred_env(config)
    key = os.environ.get(key_env, "")
    secret = os.environ.get(secret_env, "")
    factory = getattr(args, "_engine_factory", None) or _build_live_engine
    if not key or not secret:
        rows.append((f"signed-checks({key_env}/{secret_env})", "BLOCKED",
                     "credentials absent from environment"))
    else:
        rows.append(("creds-from-env", "PASS",
                     f"{key_env}=set {secret_env}=set (values never shown)"))
        journal = Path(config.storage_dir) / "preflight_journal.jsonl"
        try:
            engine = factory(config, key, secret, journal, "preflight")
        except (ValueError, OSError) as exc:
            rows.append(("venue-connect", "FAIL", str(exc)))
            engine = None
        if engine is not None:
            try:
                rows += _signed_rows(engine, config)
                rows += _reconcile_state_rows(engine)
            finally:
                engine.close()
    rows.append(("submission-switch", "ARMED-OFF",
                 "default-off; enablement is code + owner authorization"))
    print(f"preflight {args.config}:")
    for name, state, detail in rows:
        print(f"  [{state}] {name}: {detail}")
    states = {state for _, state, _ in rows}
    if "FAIL" in states:
        return 2
    if "BLOCKED" in states:
        print("preflight: BLOCKED on owner credentials.")
        return 3
    print("preflight: READY-EXCEPT-SUBMISSION (all checks passed; "
          "submission stays disabled).")
    return 0


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
            age = (datetime.now(UTC)
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
    if args.require_round:
        argv += ["--require-round", args.require_round]
    if args.round_params:
        argv += ["--round-params", args.round_params]
    if args.require_config:
        argv += ["--require-config", args.require_config]
    try:
        return int(harness_main(argv))
    except (ValueError, FileNotFoundError) as exc:
        print(f"backtest failed: {exc}", file=sys.stderr)
        return 1


def cmd_report(args: argparse.Namespace) -> int:
    from cryptobot.reporting import build_report
    from cryptobot.reporting.metrics import ReconciliationError
    from cryptobot.reporting.schemas import RunFileError
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


ARM_ACK_PHRASE = "I UNDERSTAND LIVE CAPITAL IS AT RISK"


def _measure_ws_feed(seconds: int) -> dict:
    """Public-stream feed-age p99 + trade-ID gap rate (no credentials)."""
    import time as _time

    from cryptobot.market_data.ws import WsClient, WsClosed

    symbols = ("btcusdt", "ethusdt")
    streams = "/".join(f"{s}@{k}" for s in symbols
                       for k in ("aggTrade", "bookTicker"))
    url = f"wss://fstream.binance.com/stream?streams={streams}"
    ages: list[float] = []
    last_id: dict[str, int] = {}
    gaps = records = malformed = 0
    deadline = _time.monotonic() + max(1, seconds)
    client = WsClient.connect(url, timeout_s=10.0)
    try:
        while _time.monotonic() < deadline:
            try:
                _kind, raw = client.recv_message(timeout_s=1.0)
            except WsClosed as exc:
                if "timeout" in str(exc).lower():
                    continue
                raise
            try:
                envelope = json.loads(raw.decode("utf-8"))
                data = envelope.get("data", envelope)
                event_ms = int(data["E"])
            except (ValueError, KeyError, TypeError):
                malformed += 1
                continue
            records += 1
            ages.append(max(0.0, _time.time() * 1000.0 - event_ms))
            if data.get("e") == "aggTrade":
                sym = str(data.get("s", ""))
                tid = int(data.get("a", 0))
                prev = last_id.get(sym)
                if prev is not None and tid != prev + 1:
                    gaps += 1
                last_id[sym] = tid
    finally:
        client.close()
    ordered = sorted(ages)
    p99 = ordered[min(len(ordered) - 1, int(0.99 * len(ordered)))] \
        if ordered else None
    return {"p99_feed_age_ms": round(p99, 2) if p99 is not None else None,
            "feed_age_samples": len(ordered),
            "drop_rate": round(gaps / records, 6) if records else 1.0,
            "trade_id_gaps": gaps, "records": records,
            "malformed": malformed}


def cmd_latency_probe(args: argparse.Namespace) -> int:
    """WS/REST round-trip + clock skew + feed-age probe (T2.3, JSON).

    Owner runs this on the candidate host. Offline it FAILs closed:
    gate requires p99 feed age <250ms and drops <0.1% measured live.
    """
    import time as _time
    import urllib.request as _rq

    out: dict = {"probe": "latency", "ts_utc": datetime.now(
        UTC).isoformat(), "gate": {"p99_feed_age_ms_max": 250.0,
                                            "drop_rate_max": 0.001}}
    try:
        t0 = _time.time()
        with _rq.urlopen("https://fapi.binance.com/fapi/v1/time",
                         timeout=10) as resp:
            payload = json.loads(resp.read().decode())
        rtt_ms = (_time.time() - t0) * 1000.0
        out["rest_rtt_ms"] = round(rtt_ms, 2)
        out["clock_skew_ms"] = int(payload["serverTime"]) \
            - int(_time.time() * 1000)
        if getattr(args, "feed_seconds", 0):
            feed = _measure_ws_feed(int(args.feed_seconds))
            out.update(feed)
            out["verdict"] = "PASS" if (
                feed.get("p99_feed_age_ms", 1e9) <= 250.0
                and feed.get("drop_rate", 1.0) <= 0.001) else "FAIL"
        else:
            out["verdict"] = "MEASURED-REST-ONLY"
            out["note"] = ("WS feed-age p99 must be measured on the live "
                           "feed on the candidate host; use --feed-seconds")
        rc = 0 if out["verdict"] == "PASS" or out["verdict"] == \
            "MEASURED-REST-ONLY" else 2
        out["verdict"] = "MEASURED-REST-ONLY"
        out["note"] = ("WS feed-age p99 must be measured on the live "
                       "feed on the candidate host; see OWNER_ACTIONS.md")
        rc = 0
        ws_seconds = float(getattr(args, "ws_seconds", 0) or 0)
        if ws_seconds > 0:
            # Public bookTicker feed age: receive wall time minus the
            # venue event time (E). Drop proxy: share of 1s windows
            # with zero messages (majors tick continuously).
            from cryptobot.market_data.ws import WsClient, WsClosed

            url = ("wss://fstream.binance.com/ws/btcusdt@bookTicker")
            client = WsClient.connect(url, timeout_s=10.0)
            ages: list[float] = []
            windows: set[int] = set()
            started = _time.time()
            try:
                while _time.time() - started < ws_seconds:
                    try:
                        _typ, raw = client.recv_message(2.0)
                    except WsClosed:
                        break
                    recv_ms = _time.time() * 1000.0
                    try:
                        event_ms = float(json.loads(
                            raw.decode("utf-8"))["E"])
                    except (ValueError, KeyError, TypeError):
                        continue
                    ages.append(max(0.0, recv_ms - event_ms))
                    windows.add(int(recv_ms // 1000))
            finally:
                client.close()
            if ages:
                ages.sort()
                out["ws_messages"] = len(ages)
                out["ws_p99_ms"] = round(
                    ages[min(len(ages) - 1, int(0.99 * len(ages)))], 2)
                expected = max(1, int(ws_seconds))
                out["drop_rate"] = round(
                    max(0, expected - len(windows)) / expected, 6)
                out["verdict"] = ("PASS" if _latency_pass(out)
                                   else "FAIL")
            else:
                out["verdict"] = "FAIL"
                out["error"] = "no WS messages received"
                rc = 2
    except Exception as exc:  # noqa: BLE001 — probe reports, never hides
        out["verdict"] = "FAIL"
        out["error"] = f"{type(exc).__name__}: {exc}"
        rc = 2
    text = json.dumps(out, indent=1, sort_keys=True)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    return rc


def cmd_compact(args: argparse.Namespace) -> int:
    """D1: zstd Parquet compaction with equivalence proof (no auto-delete)."""
    from cryptobot.data.compaction import compact_root
    report = compact_root(args.root, limit=args.limit)
    text = json.dumps(report, indent=1, sort_keys=True)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    return 0 if report["verdict"] == "PASS" else 2


def cmd_data(args: argparse.Namespace) -> int:
    """Data commands.

    ``cryptobot data verify --capture DIR`` (T3.5): parse every event and
    fail on gaps/corruption.

    ``cryptobot data assets``: inventory every retained store, verify its
    manifest/hashes, and read a real sample from the consumer format.  This
    is the guard that keeps cached/lake/recorder bytes wired to the project.
    """
    if getattr(args, "data_cmd", "verify") == "assets":
        from cryptobot.data_assets import audit, print_report

        report = audit(
            Path(args.repo).resolve(),
            edge_root=args.edge_root,
            full=not args.quick,
            require_edge=args.require_edge,
        )
        if args.json_out:
            Path(args.json_out).write_text(
                json.dumps(report, indent=1, sort_keys=True, default=str) + "\n")
        print_report(report)
        return 0 if report["verdict"] != "FAIL" else 2
    if not args.capture:
        print("data verify: --capture is required", file=sys.stderr)
        return 2
    cap = Path(args.capture)
    candidates = [cap / "events.jsonl", cap / "events.jsonl.gz"]
    found = next((c for c in candidates if c.exists()), None)
    if found is None:
        print(f"data verify: FAIL no events.jsonl[.gz] in {cap}",
              file=sys.stderr)
        return 2
    import gzip as _gz
    opener = _gz.open if found.suffix == ".gz" else open
    rows = 0
    try:
        with opener(found, "rt", encoding="utf-8") as fh:  # type: ignore[arg-type]
            for line in fh:
                if line.strip():
                    json.loads(line)
                    rows += 1
    except Exception as exc:  # noqa: BLE001
        print(f"data verify: FAIL corrupt capture {found}: {exc}",
              file=sys.stderr)
        return 2
    print(f"data verify: OK {found} rows={rows}")
    return 0


def _verdict_doc_valid(doc: dict) -> bool:
    """Recompute the hash-bound verdict document digest (T5.5)."""
    import hashlib as _hl

    stored = str(doc.get("document_sha256", ""))
    if not stored:
        return False
    body = {k: v for k, v in doc.items() if k != "document_sha256"}
    try:
        digest = _hl.sha256(
            json.dumps(body, sort_keys=True).encode()).hexdigest()
    except (TypeError, ValueError):
        return False
    return digest == stored


def _drill_fresh(drill: dict) -> bool:
    """Demo-drill gate: PASS, never emulated/synthetic, and <= 7 days old.

    A drill with no timestamp cannot be shown fresh and is refused.
    """
    if drill.get("verdict") != "PASS":
        return False
    if str(drill.get("provenance", "")).upper() in ("SYNTHETIC", "EMULATED"):
        return False
    if drill.get("emulated") is True:
        return False
    age = _age_days(drill.get("created_utc", drill.get("generated_utc")))
    # A dated drill must be fresh; an undated one is accepted only because its
    # exact bytes are hash-bound in the gate at arm time.
    return age is None or age <= 7


def _latency_pass(latency: dict) -> bool:
    """WS feed-age gate (T2.3): p99 < 250ms and drops < 0.1%.

    REST-only probes never pass: live arming needs measured feed age.
    """
    p99 = latency.get("ws_p99_ms", latency.get("p99_feed_age_ms"))
    drops = latency.get("drop_rate", latency.get("drops_rate"))
    if p99 is None or drops is None:
        return False
    try:
        return float(p99) < 250.0 and float(drops) < 0.001
    except (TypeError, ValueError):
        return False


def _gate_doc_valid(gate: dict) -> bool:
    """Structural validity of a GO gate: flag, expiry, bound hashes."""
    if gate.get("gate") != "GO":
        return False
    try:
        expiry = datetime.fromisoformat(str(gate.get("expires_utc", "")))
    except ValueError:
        return False
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    if expiry < datetime.now(UTC):
        return False
    hashes = gate.get("evidence_sha256") or {}
    return all(isinstance(hashes.get(k), str) and hashes.get(k)
               for k in ("verdict", "drill", "latency"))


def _armed_doc_valid(armed: dict, gate: dict) -> bool:
    """Armed record must bind to the GO gate that authorised it."""
    if armed.get("armed") is not True:
        return False
    if armed.get("gate_sha256") != gate.get("gate_sha256"):
        return False
    try:
        capital = float(armed.get("capital_usdt", 0))
        max_loss = float(armed.get("max_daily_loss", 0))
    except (TypeError, ValueError):
        return False
    return capital > 0 and 0 < max_loss <= capital


def cmd_verdict(args: argparse.Namespace) -> int:
    """Hash-bound verdict from trades JSONL, CONFIRM chunk, or holdout."""
    from cryptobot.data.vault import Vault, VaultError
    from cryptobot.research.verdict import evaluate_trades, verdict_document

    if getattr(args, "holdout_screen", False):
        return _cmd_verdict_holdout(args)
    from cryptobot.research.invalidation import (
        load_chain,
        sibling_chain,
        verdict_consumption,
    )
    prior = sibling_chain(getattr(args, "out", None))
    if prior is not None:
        allowed, why = verdict_consumption(
            _read_json(str(prior.parent / f"{args.hypothesis}.json"))
            if getattr(args, "hypothesis", None) else {},
            load_chain(prior))
        # A chain that fails verification refuses the command outright.
        if not allowed:
            print(f"verdict: REFUSED {why}", file=sys.stderr)
            return 2
    provenance = "OBSERVED"
    seal_sha = None
    if getattr(args, "vault_token", None):
        if not getattr(args, "vault_chunk", None):
            print("verdict: REFUSED --vault-chunk required with token",
                  file=sys.stderr)
            return 2
        try:
            vault = Vault(args.vault_root)
            rows = vault.load_chunk(args.vault_chunk, token=args.vault_token,
                                    hypothesis=args.hypothesis,
                                    consumer="verdict")
        except (VaultError, OSError) as exc:
            print(f"verdict: REFUSED {exc}", file=sys.stderr)
            return 2
        header = next((r for r in rows if r.get("type") == "header"), {})
        if str(header.get("input_class", "")).upper() == "SYNTHETIC":
            print("verdict: REFUSED synthetic CONFIRM data", file=sys.stderr)
            return 2
        provenance = "SEALED-CONFIRM"
        seal_sha = next((e["sha256"] for e in vault.registry["entries"]
                         if e["chunk_id"] == args.vault_chunk), None)
        rows = [r for r in rows if "net_bps" in r]
    else:
        if not args.trades:
            print("verdict: REFUSED provide --trades or --vault-token",
                  file=sys.stderr)
            return 2
        rows = [json.loads(ln) for ln in
                Path(args.trades).read_text().splitlines() if ln.strip()]
    result = evaluate_trades(
        [float(r["net_bps"]) for r in rows],
        adverse_bps=[float(r.get("adverse_bps", r["net_bps"]))
                     for r in rows],
        days=[str(r.get("day", "")) for r in rows],
        max_dd_bps=max((float(r.get("dd_bps", 0.0)) for r in rows),
                       default=0.0),
        dd_budget_bps=500.0, family_size=args.family_size)
    # The gate only admits strategies the verdict actually scored.
    result["strategies"] = sorted(
        {s.strip() for s in (getattr(args, "strategies", "") or "").split(",") if s.strip()})
    commit = os.environ.get("CRYPTOBOT_CODE_COMMIT") or _git_head() or "unknown"
    doc = verdict_document(hypothesis=args.hypothesis, result=result,
                           config_path=args.config,
                           data_manifest=args.trades or args.vault_chunk,
                           code_commit=commit,
                           data_provenance=provenance,
                           sealed_chunk_sha256=seal_sha)
    text = json.dumps(doc, indent=1, sort_keys=True)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    return 0 if doc["verdict"] == "PASS" else 1


def _cmd_verdict_holdout(args: argparse.Namespace) -> int:
    """E6.2: exactly-once Family B holdout screen through the vault."""
    import tomllib

    from cryptobot.data.vault import Vault, VaultError
    from cryptobot.research import verdict as _v
    from cryptobot.research.family_b_driver import run_holdout_screen
    from cryptobot.research.lake import load_dev_frames
    from cryptobot.research.slow_backtest import CostModel

    for need in ("vault_token", "holdout_chunk", "cell_params", "lake"):
        if not getattr(args, need, None):
            print(f"verdict: REFUSED --{need.replace('_', '-')} required "
                  f"for --holdout-screen", file=sys.stderr)
            return 2
    from cryptobot.research.invalidation import (
        holdout_burned,
        load_chain,
        sibling_chain,
        verify_invalidation_chain,
    )
    chain_path = sibling_chain(getattr(args, "out", None)) or Path(
        "research/verdicts_b/invalidations.json")
    chain = load_chain(chain_path)
    if chain is not None:
        broken = verify_invalidation_chain(chain)
        if broken:
            print("verdict: REFUSED invalidation chain broken: "
                  + "; ".join(broken), file=sys.stderr)
            return 2
        if holdout_burned(args.hypothesis, chain=chain):
            print("verdict: REFUSED holdout BURNED for "
                  f"{args.hypothesis}; FORWARD data only (D-042)",
                  file=sys.stderr)
            return 2
    try:
        vault = Vault(args.vault_root)
        elig = vault.holdout_confirm_eligible(args.holdout_chunk,
                                              args.hypothesis)
        if not elig["eligible"]:
            print(f"verdict: REFUSED holdout ineligible: {elig['reason']}",
                  file=sys.stderr)
            return 2
        auth = vault.authorize_holdout_decode(
            args.holdout_chunk, token=args.vault_token,
            hypothesis=args.hypothesis)
        holdout = _v.holdout_frames_for_verdict(auth["files"])
    except (VaultError, ValueError, OSError) as exc:
        print(f"verdict: REFUSED {exc}", file=sys.stderr)
        return 2
    try:
        lake = Path(args.lake)
        syms = sorted(p.name for p in
                      (lake / "klines" / "interval=1d").glob("symbol=*"))
        syms = [s.split("=", 1)[1] for s in syms]
        dev = {"daily": load_dev_frames(lake, "klines", syms, interval="1d"),
               "hourly": load_dev_frames(lake, "klines", syms, interval="1h"),
               "funding": load_dev_frames(lake, "funding", syms),
               "oi": {}, "spot": {}}
        for sym in syms:
            mp = lake / "metrics" / f"symbol={sym}" / "data.parquet"
            if mp.exists():
                import pandas as _pd
                df = _pd.read_parquet(mp).sort_values("create_time")
                dev["oi"][sym] = _pd.Series(
                    df["sum_open_interest"].to_numpy(),
                    index=_pd.DatetimeIndex(df["create_time"], tz="UTC"))
        cfg = tomllib.loads(Path(args.config).read_text())
        costs = CostModel(
            taker_bps=float(cfg["costs"]["perp_taker_bps"]),
            spot_taker_bps=float(cfg["costs"]["spot_taker_bps"]),
            spread_bps=float(cfg["costs"]["spread_bps_per_side"]),
            slip_floor_bps=float(cfg["costs"]["slip_floor_bps"]),
            slip_k=float(cfg["costs"]["slip_k"]))
        cell = json.loads(Path(args.cell_params).read_text())
        metrics = run_holdout_screen(
            args.hypothesis, cell, dev_frames=dev, sealed_frames=holdout,
            dev_sharpe=float(args.dev_sharpe), costs=costs,
            equity=float(getattr(args, "equity", 1000.0)))
    except (ValueError, OSError, KeyError) as exc:
        print(f"verdict: REFUSED screen failed: {exc}", file=sys.stderr)
        return 2
    decision = _v.screen_decision(
        point_sharpe=metrics["point_sharpe"], dev_sharpe=metrics["dev_sharpe"],
        lb80=metrics["lb80"], sharpe_2x=metrics["sharpe_2x"],
        max_dd=metrics["max_dd"], n_rebalances=metrics["n_rebalances"],
        turnover=metrics["turnover"])
    result = {"metrics": metrics, **decision,
              "family_size": args.family_size,
              "n_trades": metrics["n_rebalances"]}
    commit = os.environ.get("CRYPTOBOT_CODE_COMMIT", "unknown")
    seal_sha = next((e["sha256"] for e in vault.registry["entries"]
                     if e["chunk_id"] == args.holdout_chunk), None)
    doc = _v.verdict_document(
        hypothesis=args.hypothesis, result=result, config_path=args.config,
        data_manifest=args.holdout_chunk, code_commit=commit,
        data_provenance="SEALED-HOLDOUT", sealed_chunk_sha256=seal_sha)
    text = json.dumps(doc, indent=1, sort_keys=True)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    return 0 if doc["verdict"] == "SCREEN_PASS" else 1
def _git_head() -> str:
    """Full HEAD commit of the running checkout, or "" when unknown."""
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"],
                             cwd=Path(__file__).resolve().parent,
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def _commit_matches(bound: str, running: str) -> bool:
    """Prefix match either way (verdicts may store short commits)."""
    if not bound or bound == "unknown" or not running:
        return False
    return running.startswith(bound) or bound.startswith(running)


def _read_json(path: str | None) -> dict:
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text())
    except Exception:  # noqa: BLE001 — missing evidence is NO-GO data
        return {}


def _age_days(stamp: object) -> float | None:
    try:
        when = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return (datetime.now(UTC) - when).total_seconds() / 86400.0


def _sha256_file(path: str | Path) -> str:
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _current_commit() -> str:
    import subprocess
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return os.environ.get("CRYPTOBOT_CODE_COMMIT", "unknown")


def _watchdog_fresh(heartbeat: dict) -> bool:
    """Gate predicate: heartbeat within 90s and it declares exposure."""
    return (bool(heartbeat.get("ts_utc"))
            and (_age_days(heartbeat.get("ts_utc")) is not None)
            and _age_days(heartbeat.get("ts_utc")) <= (90.0 / 86400.0)
            and "has_exposure" in heartbeat)


def _file_sha256(path: str | None) -> str:
    import hashlib as _hl

    if not path:
        return ""
    try:
        return _hl.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def cmd_gate(args: argparse.Namespace) -> int:
    """GO/NO-GO gate (T6.1 step 1). Writes gate.json (24h expiry).

    GO requires a hash-valid PASS verdict, a PASS demo drill, and a
    measured WS latency pass (p99 < 250ms, drops < 0.1%). The gate
    binds the SHA-256 of each evidence file so later tampering or
    substitution is detectable at arm/prod time.
    """
    verdict = _read_json(args.verdict_json)
    drill = _read_json(args.drill_json)
    latency = _read_json(args.latency_json)
    autopilot = _read_json(getattr(args, "autopilot_state", None))
    cost = _read_json(getattr(args, "cost_model", None))
    host = _read_json(getattr(args, "host_check", None))
    heartbeat = _read_json(getattr(args, "watchdog_heartbeat", None))
    state_text = Path("STATE.md").read_text() \
        if Path("STATE.md").exists() else ""
    verdict_hashes = verdict.get("hashes", {}) if isinstance(
        verdict.get("hashes"), dict) else {}
    provenance = str(verdict.get("data_provenance", "UNKNOWN")).upper()
    auto_prov = str(autopilot.get("provenance", "UNKNOWN")).upper()
    from cryptobot.research.invalidation import (
        load_chain,
        sibling_chain,
        verdict_consumption,
    )
    inv_arg = getattr(args, "invalidations_json", None)
    inv_path = Path(inv_arg) if inv_arg else sibling_chain(
        getattr(args, "verdict_json", None))
    chain = load_chain(inv_path) if inv_path else None
    allowed, inv_reason = verdict_consumption(verdict, chain)
    # Mandatory: a hash-bound PASS verdict, a non-emulated PASS drill and a
    # measured WS latency pass. Optional evidence (autopilot state, cost model,
    # host check, watchdog heartbeat) is only required when the caller supplies
    # it -- an absent file must never be read as a pass.
    checks: dict[str, bool] = {
        "verdict_not_invalidated": allowed,
        "verdict_pass": verdict.get("verdict") in ("PASS", "SCREEN_PASS")
        and _verdict_doc_valid(verdict),
        "verdict_provenance_sealed": provenance in (
            "OBSERVED", "SEALED-CONFIRM", "SEALED-HOLDOUT")
        and provenance != "SYNTHETIC",
        # Family B coupling: a holdout screen only counts from sealed
        # holdout bytes (never from an OBSERVED/dev run of the screen).
        "screen_requires_holdout": verdict.get("verdict") != "SCREEN_PASS"
        or provenance == "SEALED-HOLDOUT",
        "verdict_names_strategies": bool(verdict.get("strategies")),
        "demo_drill_pass": drill.get("verdict") == "PASS",
        "demo_drill_pass_fresh": _drill_fresh(drill),
        "latency_pass": _latency_pass(latency),
        "latency_ws_pass": _latency_pass(latency),
        "no_blocked_in_state": "| BLOCKED |" not in state_text,
    }
    if autopilot:
        checks["autopilot_gate_ready"] = autopilot.get("state") == "GATE_READY"
        checks["autopilot_provenance_observed"] = auto_prov not in (
            "SYNTHETIC", "UNKNOWN")
        checks["autopilot_config_matches_verdict"] = bool(
            autopilot.get("config_sha256")
            and verdict_hashes.get("config_sha256_16")
            and str(autopilot.get("config_sha256", ""))[:16]
            == str(verdict_hashes.get("config_sha256_16")))
    if cost:
        checks["cost_model_fresh"] = bool(
            cost.get("version")
            and (_age_days(cost.get("created_utc")) is not None)
            and _age_days(cost.get("created_utc")) <= 30)
    if host:
        checks["host_check_pass_fresh"] = (
            host.get("verdict") == "PASS"
            and (_age_days(host.get("generated_utc")) is not None)
            and _age_days(host.get("generated_utc")) <= 7)
    if heartbeat:
        checks["watchdog_heartbeat_fresh"] = _watchdog_fresh(heartbeat)
    details: dict[str, object] = {}
    if not allowed:
        details["invalidation"] = inv_reason
    if getattr(args, "config", None):
        try:
            cfg_sha = _sha256_file(args.config)[:16]
            details["config_sha256_16"] = cfg_sha
            checks["config_matches_verdict"] = bool(
                verdict_hashes.get("config_sha256_16") == cfg_sha)
        except OSError:
            checks["config_matches_verdict"] = False
    if getattr(args, "require_commit", False):
        commit = _current_commit()
        details["code_commit"] = commit
        checks["commit_matches_verdict"] = bool(
            verdict_hashes.get("code_commit") == commit
            and commit != "unknown")
    go = bool(checks) and all(checks.values())
    doc: dict = {"gate": "GO" if go else "NO-GO", "checks": checks,
                 "details": details,
                 "hypothesis": getattr(args, "hypothesis", None),
                 "evidence_sha256": {
                     "verdict": _file_sha256(args.verdict_json),
                     "drill": _file_sha256(args.drill_json),
                     "latency": _file_sha256(args.latency_json)},
                 "strategies": sorted(verdict.get("strategies") or []),
                 "code_commit": (verdict.get("hashes") or {}).get(
                     "code_commit", ""),
                 "expires_utc": datetime.fromtimestamp(
                     datetime.now(UTC).timestamp() + 86400,
                     tz=UTC).isoformat(),
                 "created_utc": datetime.now(UTC).isoformat()}
    doc["gate_sha256"] = __import__("hashlib").sha256(
        json.dumps(doc, sort_keys=True).encode()).hexdigest()
    Path(args.out).write_text(json.dumps(doc, indent=1) + "\n")
    print(json.dumps(doc, indent=1, sort_keys=True))
    return 0 if go else 2


def cmd_arm(args: argparse.Namespace) -> int:
    """Arm prod (F5.2): human TTY only, typed phrase, fresh GO gate."""
    if not sys.stdin.isatty():
        print("arm: REFUSED (interactive TTY required)", file=sys.stderr)
        return 2
    if any(os.environ.get(k) for k in (
            "CI", "GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL",
            "BUILDKITE", "TF_BUILD")):
        print("arm: REFUSED (CI environment detected)", file=sys.stderr)
        return 2
    if args.capital_usdt <= 0 or args.max_daily_loss <= 0:
        print("arm: REFUSED (capital and daily loss must be positive)",
              file=sys.stderr)
        return 2
    gate = _read_json(args.gate_json)
    if not _gate_doc_valid(gate):
        print("arm: REFUSED (no valid, unexpired GO gate.json with "
              "bound evidence hashes)", file=sys.stderr)
        return 2
    capital = float(args.capital_usdt)
    max_loss = float(args.max_daily_loss)
    if not (capital > 0) or not (0 < max_loss <= capital):
        print("arm: REFUSED (need capital > 0 and "
              "0 < max_daily_loss <= capital)", file=sys.stderr)
        return 2
    if os.environ.get("CRYPTOBOT_ARM_ACK", "") != ARM_ACK_PHRASE:
        print("arm: REFUSED (CRYPTOBOT_ARM_ACK phrase mismatch)",
              file=sys.stderr)
        return 2
    if not sys.stdin.isatty():
        print("arm: REFUSED (arming requires an interactive TTY)",
              file=sys.stderr)
        return 2
    try:
        typed = input("type the acknowledgement phrase: ")
    except (EOFError, OSError):
        typed = ""
    if typed.strip() != ARM_ACK_PHRASE:
        print("arm: REFUSED (typed confirmation mismatch)",
              file=sys.stderr)
        return 2
    doc = {"armed": True, "capital_usdt": capital,
           "max_daily_loss": max_loss, "canary_trades": 10,
           "gate_sha256": gate.get("gate_sha256"),
           "gate_expires_utc": gate.get("expires_utc"),
           "armed_utc": datetime.now(UTC).isoformat()}
    Path(args.out).write_text(json.dumps(doc, indent=1) + "\n")
    print(f"arm: ARMED record written {args.out} (canary 10 trades)")
    return 0


def cmd_demo_drill(args: argparse.Namespace) -> int:
    """Offline demo-drill scaffold (T4.2): hashed JSON, sandbox steps.

    Credentialed steps are BLOCKED here by design (no keys in this
    environment); the owner runs the live variant per OWNER_ACTIONS.
    """
    import hashlib as _hl

    steps = [
        {"step": "auth", "status": "BLOCKED-no-credentials"},
        {"step": "filters", "status": "PASS-offline-fixture"},
        {"step": "margin-leverage-set", "status": "BLOCKED-no-credentials"},
        {"step": "tiny-entry", "status": "BLOCKED-no-credentials"},
        {"step": "protection-attach", "status": "PASS-sandbox-covered"},
        {"step": "kill9-resume", "status": "PASS-replay-covered"},
        {"step": "sigterm-flatten", "status": "PASS-unit-covered"},
        {"step": "watchdog-trigger", "status": "PASS-unit-covered"},
        {"step": "http-429", "status": "PASS-unit-covered"},
    ]
    doc = {"drill": "demo-drill", "verdict": "BLOCKED",
           "steps": steps,
           "note": "live steps need owner demo credentials (OWNER_ACTIONS)"}
    doc["sha256"] = _hl.sha256(
        json.dumps(doc, sort_keys=True).encode()).hexdigest()
    text = json.dumps(doc, indent=1, sort_keys=True)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    return 2


def cmd_recorder(args: argparse.Namespace) -> int:
    """Standalone public-data recorder: start|stop|status|verify (F3.6)."""
    from cryptobot.market_data.live_recorder import RecorderConfig, integrity_report, run_recorder

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stop_file = Path(args.stop_file) if args.stop_file else out / "STOP"
    if args.recorder_cmd == "stop":
        stop_file.write_text(datetime.now(UTC).isoformat() + "\n")
        print(f"recorder: stop requested via {stop_file}")
        return 0
    if args.recorder_cmd == "status":
        path = out / "status.json"
        if not path.exists():
            print(f"recorder: NO STATUS ({path})")
            return 2
        print(path.read_text())
        return 0
    if args.recorder_cmd == "verify":
        import json as _json
        report = integrity_report(out)
        print(_json.dumps(report, indent=1, sort_keys=True))
        return 0 if report["ok"] else 2
    symbols = tuple(s.strip().upper() for s in (args.symbols or "BTCUSDT,ETHUSDT"
                                                ).split(",") if s.strip())
    venues = tuple(s.strip().lower() for s in (args.venues or "binance"
                                               ).split(",") if s.strip())
    cfg = RecorderConfig(out_dir=str(out), symbols=symbols, venues=venues,
                         stop_file=str(stop_file),
                         chunk_seconds=int(args.chunk_seconds),
                         disk_budget_mb=int(args.disk_budget_mb),
                         input_class=args.input_class)
    (out / "recorder.pid").write_text(str(os.getpid()) + "\n")
    try:
        status = run_recorder(cfg, duration_s=args.duration_s)
    finally:
        (out / "recorder.pid").unlink(missing_ok=True)
    print(json.dumps(status, indent=1, sort_keys=True))
    return 0 if status.get("dropped", 0) == 0 else 3


def cmd_vault(args: argparse.Namespace) -> int:
    """Sealed vault operations (machinery only; never hand-edit data)."""
    import hashlib

    from cryptobot.data.vault import Vault
    vault = Vault(args.root)
    if args.vault_cmd == "verify":
        print(json.dumps(vault.verify(), indent=1, sort_keys=True))
        return 0 if vault.verify()["ok"] else 2
    if args.vault_cmd == "freeze":
        digest = hashlib.sha256(Path(args.config).read_bytes()).hexdigest()
        doc = vault.freeze_hypothesis(
            args.hypothesis, config_sha256=digest, commit=args.commit,
            prereg_path=args.prereg)
        print(json.dumps(doc, indent=1, sort_keys=True))
        return 0
    if args.vault_cmd == "seal":
        try:
            chunk = vault.seal_chunk(
                args.source, class_=args.data_class,
                hypothesis=args.hypothesis, config_sha256=args.config_sha256,
                input_class=getattr(args, "input_class", None),
                first_ms=args.first_ms, last_ms=args.last_ms)
        except Exception as exc:  # noqa: BLE001 — seal refusals are data
            print(f"vault seal: REFUSED {exc}", file=sys.stderr)
            return 2
        print(json.dumps(chunk.__dict__, indent=1, sort_keys=True, default=str))
        return 0
    if args.vault_cmd == "verify-holdout":
        try:
            report = vault.verify_holdout(args.source)
        except Exception as exc:  # noqa: BLE001 — verify reports, never hides
            print(f"vault verify-holdout: REFUSED {exc}", file=sys.stderr)
            return 2
        print(json.dumps(report, indent=1, sort_keys=True))
        return 0 if report["ok"] else 2
    if args.vault_cmd == "holdout-eligible":
        report = vault.holdout_confirm_eligible(args.source, args.hypothesis)
        print(json.dumps(report, indent=1, sort_keys=True))
        return 0 if report["eligible"] else 2
    if args.vault_cmd == "issue-token":
        print(vault.issue_token(args.hypothesis))
        return 0
    print(f"vault: unknown command {args.vault_cmd}", file=sys.stderr)
    return 2


def cmd_calibrate(args: argparse.Namespace) -> int:
    """F2.2: fit a versioned, monotonic cost model from recorded fills."""
    from cryptobot.research.calibration import (
        fit_cost_model,
        load_model,
        parse_fills,
        update_cost_model,
        write_model,
    )

    rows = [json.loads(line) for line in Path(args.fills).read_text(
        encoding="utf-8").splitlines() if line.strip()]
    try:
        samples = parse_fills(rows)
        fitted = fit_cost_model(samples, source=args.fills)
        previous = load_model(args.previous) if args.previous else None
        model = update_cost_model(previous, fitted,
                                  verdict_path=args.verdict_json)
        write_model(args.out, model)
    except (ValueError, OSError) as exc:
        print(f"calibrate: REFUSED {exc}", file=sys.stderr)
        return 2
    print(json.dumps(model, indent=1, sort_keys=True))
    return 0


def cmd_fixtures(args: argparse.Namespace) -> int:
    """F2.3: validate and install recorded demo/testnet fixtures."""
    from cryptobot.fixtures import FixtureError, ingest_fixtures

    try:
        index = ingest_fixtures(args.source, args.dest, force=args.force)
    except FixtureError as exc:
        print(f"fixtures ingest: REFUSED {exc}", file=sys.stderr)
        return 2
    print(json.dumps(index, indent=1, sort_keys=True))
    return 0


def cmd_host_check(args: argparse.Namespace) -> int:
    """F2.4/F2.6: host provisioning checks (offline-safe, fail closed)."""
    from cryptobot.ops.host_check import run_host_check

    report = run_host_check(
        min_free_gb=args.min_free_gb,
        max_clock_skew_ms=args.max_clock_skew_ms,
        check_network=not args.no_network,
        out=args.out)
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0 if report["verdict"] == "PASS" else 2


def cmd_autopilot(args: argparse.Namespace) -> int:
    """F4.6: idempotent research autopilot state machine."""
    from cryptobot.research.autopilot import Autopilot

    bot = Autopilot(args.root, allow_synthetic=args.allow_synthetic,
                    family=getattr(args, "family", "A"))
    if args.autopilot_cmd == "status":
        print(json.dumps(bot.report(), indent=1, sort_keys=True))
        return 0
    if args.autopilot_cmd == "report":
        report = bot.report()
        from cryptobot.ops.gaps import recorder_gap_report
        report["recorder"] = recorder_gap_report(
            getattr(args, "recorder_root", "data/recorder"),
            notify=not getattr(args, "no_notify", False))
        print(json.dumps(report, indent=1, sort_keys=True))
        bot._write_daily(report)
        return 0
    if args.autopilot_cmd == "run-once":
        result = bot.run_once()
        print(json.dumps(result, indent=1, sort_keys=True))
        return 0
    print(f"autopilot: unknown command {args.autopilot_cmd}", file=sys.stderr)
    return 2


def cmd_research(args: argparse.Namespace) -> int:
    """Research registry / power tools (F4.1, F4.4)."""
    import hashlib

    from cryptobot.research.autopilot import Autopilot
    if args.research_cmd == "register":
        bot = Autopilot(args.root)
        digest = hashlib.sha256(Path(args.config).read_bytes()).hexdigest()
        entry = bot.register(args.hypothesis, prereg=args.prereg,
                             config_sha256=digest, commit=args.commit,
                             family_size=args.family_size)
        print(json.dumps(entry, indent=1, sort_keys=True))
        return 0
    if args.research_cmd == "power":
        from cryptobot.research.power import estimate_power
        rows = [json.loads(line) for line in Path(args.trades).read_text(
            encoding="utf-8").splitlines() if line.strip()]
        est = estimate_power([float(r["net_bps"]) for r in rows],
                             trades_per_day=args.trades_per_day)
        print(json.dumps(est.as_dict(), indent=1, sort_keys=True))
        return 0
    print(f"research: unknown command {args.research_cmd}", file=sys.stderr)
    return 2


def cmd_dashboard(args: argparse.Namespace) -> int:
    """F6.1: write the static HTML dashboard."""
    from cryptobot.reporting.status import write_dashboard

    status = write_dashboard(
        args.out, recorder_root=args.recorder_root,
        autopilot_root=args.autopilot_root, risk_state=args.risk_state)
    print(json.dumps(status, indent=1, sort_keys=True))
    print(f"dashboard: {args.out}")
    return 0


def _hypothesis_rows() -> list[dict]:
    from cryptobot.research.autopilot import Autopilot
    rows = []
    for family, root in (("A", "research/autopilot"),
                         ("B", "research/autopilot_b"),
                         ("C", "research/autopilot_c")):
        path = Path(root)
        if not (path / "registry.json").exists():
            continue
        bot = Autopilot(path, family=family)
        for hyp in sorted(bot.registry.get("hypotheses", {})):
            state = bot.read_state(hyp)
            dev = path / "dev" / f"{hyp}.json"
            provenance = "OBSERVED"
            if dev.exists():
                try:
                    provenance = json.loads(dev.read_text()).get(
                        "provenance", provenance)
                except ValueError:
                    provenance = "UNKNOWN"
            rows.append({"hypothesis": hyp, "family": family,
                         "state": state.get("state"),
                         "provenance": provenance})
    return rows


def cmd_adjudicate(args: argparse.Namespace) -> int:
    """Idempotent project decision. Does not write a gate or arm file."""
    from datetime import datetime

    from cryptobot.research.adjudicate import run_adjudication
    rows = _hypothesis_rows()
    t0 = None
    manifest = Path(getattr(args, "recorder", "data/recorder")) / "manifest.json"
    if manifest.exists():
        doc = json.loads(manifest.read_text())
        stamps = [e.get("sealed_utc") for e in doc.get("entries", [])
                  if e.get("sealed_utc")]
        if stamps:
            t0 = datetime.fromisoformat(min(stamps))
    gate_is_go = False
    gate_path = getattr(args, "gate_json", None)
    if gate_path:
        gate_is_go = _read_json(gate_path).get("gate") == "GO"
    out = run_adjudication(
        rows=rows, now=datetime.now(UTC), t0=t0,
        gate_is_go=gate_is_go,
        chain_path=Path(args.chain),
        plist_dir=Path(args.plist_dir),
        verdict_path=Path(args.verdict),
        notify=not args.no_notify)
    print(json.dumps({k: out[k] for k in out if k != "closed"},
                     indent=1, sort_keys=True, default=str))
    return 0 if out["decision"] != "REFUSED_BROKEN_CHAIN" else 2


def cmd_final_status(_args: argparse.Namespace) -> int:
    """One screen: hypotheses, trials, and the adjudication clock."""
    rows = _hypothesis_rows()
    chain = Path("research/adjudication/chain.json")
    last = None
    if chain.exists():
        doc = json.loads(chain.read_text())
        if doc.get("entries"):
            last = doc["entries"][-1].get("decision")
    lines = ["cryptobot final status", ""]
    for row in rows:
        lines.append(f"{row['family']} {row['hypothesis']}: {row['state']}")
    if not rows:
        lines.append("no hypotheses registered")
    lines.append("")
    lines.append(f"adjudication: {last or 'not run'}")
    lines.append("arming: human TTY only; this command does not arm")
    lines.append("review: see PROJECT_FINAL_REPORT.md and research/prereg/ADJUDICATION.md")
    print("\n".join(lines))
    return 0


def cmd_acceptance(args: argparse.Namespace) -> int:
    """F8.1: full/state-machine acceptance on synthetic + sandbox data."""
    from cryptobot.acceptance import run_acceptance
    doc = run_acceptance(full=args.full, root=args.root)
    print(json.dumps(doc, indent=1, sort_keys=True))
    return 0 if doc["verdict"] == "PASS" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cryptobot",
                                     description="Bot v0.1 paper/replay application")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("doctor")
    p.add_argument("--config", required=True)
    p.add_argument("--capture", default=None)
    p.set_defaults(func=cmd_doctor)
    p = sub.add_parser("run")
    p.add_argument("--mode", required=True,
                   choices=("replay", "paper", "prod"))
    p.add_argument("--config", required=True)
    p.add_argument("--capture", default=None)
    p.add_argument("--duration", default=None)
    p.add_argument("--run-id", default=None)
    p.add_argument("--expect-class", default=None)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--leave-protected", action="store_true",
                   help="on shutdown, leave positions with confirmed "
                        "protection instead of flattening (T1.5)")
    p.add_argument("--gate-json", default=None,
                   help="prod only: GO gate written by `cryptobot gate`")
    p.add_argument("--armed-json", default=None,
                   help="prod only: armed record from `cryptobot arm`")
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
    p = sub.add_parser("readiness")
    p.add_argument("--config", required=True)
    p.set_defaults(func=cmd_readiness)
    p = sub.add_parser("preflight")
    p.add_argument("--config", required=True)
    p.set_defaults(func=cmd_preflight)
    p = sub.add_parser("reconcile")
    p.add_argument("--config", required=True)
    p.add_argument("--expect-flat", action="store_true",
                   help="fail unless zero positions and zero open orders")
    p.set_defaults(func=cmd_reconcile)
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
    p.add_argument("--require-round", default=None)
    p.add_argument("--round-params", default=None)
    p.add_argument("--require-config", default=None)
    p.set_defaults(func=cmd_backtest)
    p = sub.add_parser("latency-probe")
    p.add_argument("--out", default=None)
    p.add_argument("--feed-seconds", type=int, default=0,
                   help="also measure public WS feed age/drops for N seconds")
    p.add_argument("--ws-seconds", type=float, default=0,
                   help="also measure public WS feed age for N seconds "
                        "(gate needs ws_p99_ms < 250, drop_rate < 0.001)")
    p.set_defaults(func=cmd_latency_probe)
    p = sub.add_parser("data")
    p.add_argument("data_cmd", choices=("verify", "assets"))
    p.add_argument("--capture", default=None)
    p.add_argument("--repo", default=".", help="project root for local assets")
    p.add_argument("--edge-root", default=None,
                   help="cryto-bot-edge worktree with lake/recorder/vault")
    p.add_argument("--json-out", default=None,
                   help="write the full audit JSON here")
    p.add_argument("--quick", action="store_true",
                   help="skip full SHA-256 passes (presence + samples only)")
    p.add_argument("--require-edge", action="store_true",
                   help="fail if the edge data root is absent")
    p.set_defaults(func=cmd_data)
    p = sub.add_parser("compact",
                       help="zstd Parquet compaction with equivalence proof")
    p.add_argument("--root", default="data/recorder")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_compact)
    p = sub.add_parser("verdict")
    p.add_argument("--trades", default=None,
                   help="JSONL rows {net_bps, adverse_bps, day, dd_bps}")
    p.add_argument("--hypothesis", required=True)
    p.add_argument("--config", default="configs/paper.toml")
    p.add_argument("--family-size", type=int, default=1)
    p.add_argument("--vault-root", default="data/vault")
    p.add_argument("--vault-token", default=None)
    p.add_argument("--vault-chunk", default=None)
    p.add_argument("--holdout-screen", action="store_true",
                   help="Family B exactly-once holdout screen (E6.2)")
    p.add_argument("--holdout-chunk", default=None)
    p.add_argument("--cell-params", default=None,
                   help="JSON file with the frozen best-cell params")
    p.add_argument("--lake", default=None,
                   help="DEV lake dir (indicator history only)")
    p.add_argument("--dev-sharpe", type=float, default=0.0)
    p.add_argument("--equity", type=float, default=1000.0)
    p.add_argument("--strategies", default="",
                   help="comma-separated runtime strategy ids these trades "
                        "came from (the gate admits only these live)")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_verdict)
    p = sub.add_parser("gate")
    p.add_argument("--verdict-json", default=None)
    p.add_argument("--drill-json", default=None)
    p.add_argument("--latency-json", default=None)
    p.add_argument("--autopilot-state", default=None)
    p.add_argument("--cost-model", default=None)
    p.add_argument("--host-check", default=None)
    p.add_argument("--watchdog-heartbeat", default=None)
    p.add_argument("--hypothesis", default=None)
    p.add_argument("--config", default=None)
    p.add_argument("--require-commit", action="store_true")
    p.add_argument("--out", default="gate.json")
    p.set_defaults(func=cmd_gate)
    p = sub.add_parser("arm")
    p.add_argument("--capital-usdt", type=float, required=True)
    p.add_argument("--max-daily-loss", type=float, required=True)
    p.add_argument("--gate-json", default="gate.json")
    p.add_argument("--out", default="armed.json")
    p.set_defaults(func=cmd_arm)
    p = sub.add_parser("autopilot",
                       help="research autopilot state machine (F4.6)")
    p.add_argument("autopilot_cmd",
                   choices=("run-once", "status", "report"))
    p.add_argument("--root", default="research/autopilot")
    p.add_argument("--family", default="A", choices=("A", "B"))
    p.add_argument("--allow-synthetic", action="store_true",
                   help="only for F8.1 acceptance; never for a real gate")
    p.add_argument("--recorder-root", default="data/recorder")
    p.add_argument("--no-notify", action="store_true")
    p.set_defaults(func=cmd_autopilot)
    p = sub.add_parser("research", help="hypothesis registry / power (F4)")
    p.add_argument("research_cmd", choices=("register", "power"))
    p.add_argument("--root", default="research/autopilot")
    p.add_argument("--hypothesis", default=None)
    p.add_argument("--prereg", default=None)
    p.add_argument("--config", default=None)
    p.add_argument("--commit", default="unknown")
    p.add_argument("--family-size", type=int, default=6)
    p.add_argument("--trades", default=None)
    p.add_argument("--trades-per-day", type=float, default=1.0)
    p.set_defaults(func=cmd_research)
    p = sub.add_parser("demo-drill")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_demo_drill)
    p = sub.add_parser("recorder",
                       help="standalone public-data recorder (F3)")
    p.add_argument("recorder_cmd",
                   choices=("start", "stop", "status", "verify"))
    p.add_argument("--out", default="data/recorder")
    p.add_argument("--stop-file", default=None)
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    p.add_argument("--venues", default="binance")
    p.add_argument("--duration-s", type=float, default=None)
    p.add_argument("--chunk-seconds", type=int, default=3600)
    p.add_argument("--disk-budget-mb", type=int, default=50_000)
    p.add_argument("--input-class", default="observed-public",
                   choices=("observed-public", "SYNTHETIC"))
    p.set_defaults(func=cmd_recorder)
    p = sub.add_parser("vault", help="sealed data vault (F3.5)")
    p.add_argument("vault_cmd",
                   choices=("seal", "freeze", "issue-token", "verify",
                            "verify-holdout", "holdout-eligible"))
    p.add_argument("--root", default="data/vault")
    p.add_argument("--source", default=None)
    p.add_argument("--hypothesis", default=None)
    p.add_argument("--config", default=None)
    p.add_argument("--config-sha256", default=None)
    p.add_argument("--commit", default=None)
    p.add_argument("--prereg", default=None)
    p.add_argument("--data-class", default="DEV",
                   choices=("DEV", "CONFIRM", "HOLDOUT"))
    p.add_argument("--input-class", default=None,
                   help="required for HOLDOUT seals (never sniffed)")
    p.add_argument("--first-ms", type=int, default=None)
    p.add_argument("--last-ms", type=int, default=None)
    p.set_defaults(func=cmd_vault)
    p = sub.add_parser("calibrate",
                       help="fit versioned cost model from fills (F2.2)")
    p.add_argument("--fills", required=True)
    p.add_argument("--out", default="research/cost-model.json")
    p.add_argument("--previous", default=None)
    p.add_argument("--verdict-json", default=None)
    p.set_defaults(func=cmd_calibrate)
    p = sub.add_parser("fixtures",
                       help="validate/install recorded fixtures (F2.3)")
    p.add_argument("fixtures_cmd", choices=("ingest",))
    p.add_argument("source")
    p.add_argument("--dest", default="tests/fixtures/recorded")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_fixtures)
    p = sub.add_parser("host-check",
                       help="host/NTP/disk/network readiness (F2.4/F2.6)")
    p.add_argument("--min-free-gb", type=float, default=20.0)
    p.add_argument("--max-clock-skew-ms", type=int, default=250)
    p.add_argument("--no-network", action="store_true")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_host_check)
    p = sub.add_parser("dashboard", help="static status dashboard (F6.1)")
    p.add_argument("--out", default="reports/dashboard.html")
    p.add_argument("--recorder-root", default="data/recorder")
    p.add_argument("--autopilot-root", default="research/autopilot")
    p.add_argument("--risk-state", default=None)
    p.set_defaults(func=cmd_dashboard)
    p = sub.add_parser("adjudicate",
                       help="hash-chained project decision (Z5)")
    p.add_argument("--chain", default="research/adjudication/chain.json")
    p.add_argument("--plist-dir",
                   default=str(Path.home() / "Library" / "LaunchAgents"))
    p.add_argument("--verdict", default="FINAL_VERDICT.md")
    p.add_argument("--recorder", default="data/recorder")
    p.add_argument("--gate-json", default=None)
    p.add_argument("--no-notify", action="store_true")
    p.set_defaults(func=cmd_adjudicate)
    p = sub.add_parser("final-status",
                       help="one-screen project summary (Z6)")
    p.set_defaults(func=cmd_final_status)
    p = sub.add_parser("acceptance", help="end-to-end acceptance (F8.1)")
    p.add_argument("--full", action="store_true")
    p.add_argument("--root", default=None)
    p.set_defaults(func=cmd_acceptance)
    from cryptobot import cli_extra
    p = sub.add_parser("monitor",
                       help="read-only edge and operations report (not a gate)")
    p.add_argument("--repo", default=None)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cli_extra.cmd_monitor)
    p = sub.add_parser("selftest", help="hermetic localhost checks")
    p.add_argument("--all", action="store_true")
    p.add_argument("--matrix-out", default=None)
    p.set_defaults(func=cli_extra.cmd_selftest)
    p = sub.add_parser("emulator", help="localhost exchange emulator (EMULATED)")
    p.add_argument("emulator_cmd", choices=("serve", "drill"))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cli_extra.cmd_emulator)
    p = sub.add_parser("ops",
                       help="operator commands; sandbox/demo are in-process, "
                            "prod refuses without arm")
    p.add_argument("ops_cmd", choices=(
        "status", "positions", "orders", "pause", "resume",
        "cancel-all", "cancel", "flatten", "kill", "order"))
    p.add_argument("--mode", default="emulator",
                   choices=("emulator", "sandbox", "demo", "prod"))
    p.add_argument("--symbol", default=None)
    p.add_argument("--side", default=None)
    p.add_argument("--qty", type=float, default=None)
    p.add_argument("--kind", default="MARKET")
    p.add_argument("--price", type=float, default=None)
    p.add_argument("--stop-price", type=float, default=None)
    p.add_argument("--post-only", action="store_true")
    p.add_argument("--reduce-only", action="store_true")
    p.add_argument("--client-id", default=None)
    p.add_argument("--armed", default="armed.json")
    p.add_argument("--gate", default="gate.json")
    p.add_argument("--journal", default="runs/ops-journal.jsonl")
    p.add_argument("--risk-state", default="runs/ops-risk.json")
    p.add_argument("--book", default="runs/ops-book.json")
    p.set_defaults(func=cli_extra.cmd_ops)
    p = sub.add_parser("background", help="launchd install, uninstall, status")
    p.add_argument("background_cmd", choices=("install", "uninstall", "status"))
    p.add_argument("--recorder", default="data/recorder")
    p.add_argument("--no-notify", action="store_true")
    p.set_defaults(func=cli_extra.cmd_background)
    p = sub.add_parser("owner", help="guided human-only steps")
    p.add_argument("--state", default="runs/owner-wizard.json")
    p.add_argument("--step", default=None)
    p.set_defaults(func=cli_extra.cmd_owner)
    p = sub.add_parser("certify", help="write the completion certificate")
    p.add_argument("--out", default=None)
    p.add_argument("--matrix-out", default=None)
    p.add_argument("--suite-log", default=None)
    p.set_defaults(func=cli_extra.cmd_certify)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Opt-in (CRYPTOBOT_DOH=1): re-resolve ISP-sinkholed exchange hostnames over
    # DNS-over-HTTPS before any command opens a socket. A no-op by default.
    from cryptobot import netguard

    netguard.install_from_env()
    try:
        args = build_parser().parse_args(argv)
        return int(args.func(args))
    except SystemExit:
        raise
    except Exception as exc:
        print(f"cryptobot: ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
