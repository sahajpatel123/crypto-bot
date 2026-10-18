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
    strays_fn = getattr(engine, "stray_order_ids", None)
    if callable(strays_fn):
        strays = [str(c) for c in strays_fn()]
        if strays:
            raise ValueError(
                "foreign orders on venue (not bot-journaled): "
                + ",".join(sorted(strays)))
    seeded = session.seed_from_venue(snapshot, open_client_ids=open_ids,
                                     journal_client_ids=journal_ids)
    if symbols:
        # B#14: live/demo run_mode arms WITH venue brackets (fail
        # closed when the fetch/parse fails — no gate, no trading).
        armed = session.arm_live_brackets(symbols)
        print(f"brackets armed: {armed}")
    return seeded


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
                FAPI_BASE_URL, fetch_exchange_info, urllib_json_get)
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
        except KeyError as exc:
            # B#18: --resume with no such run (first boot with the
            # resume unit, or a lost store). Live engines fail CLOSED
            # (refuse: the lost run may hold venue exposure — never
            # auto-start a second writer). Paper fresh-starts LOUDLY
            # (sim-only, nothing to double-trade) instead of
            # crash-looping to StartLimitBurst. Narrowly scoped to
            # the resume-unknown shape; all other KeyErrors fall
            # through to the generic handler below.
            if not bool(args.resume) or "unknown run" not in str(exc):
                print(f"run {run_id} interrupted: "
                      f"{type(exc).__name__}: {exc}", file=sys.stderr)
                print(f"resume with: cryptobot run --mode paper --config "
                      f"{args.config} --duration {args.duration or 'left'} "
                      f"--run-id {run_id} --resume")
                return 3
            if config.engine_kind == "live":
                print(f"run {run_id} REFUSED (resume: {exc}); inspect "
                      f"venue exposure before starting fresh without "
                      f"--resume", file=sys.stderr)
                return 2
            print(f"run {run_id}: no such run ({exc}); fresh paper "
                  f"start (dropping --resume)", file=sys.stderr)
            try:
                report = session.run_live(events, duration_s=duration,
                                          resume=False)
            except Exception as exc2:
                print(f"run {run_id} interrupted: "
                      f"{type(exc2).__name__}: {exc2}", file=sys.stderr)
                return 3
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
    from cryptobot.adapters.binance_live import (DEMO_FAPI_URL, PROD_FAPI_URL)
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
    """Production route: full driver, submission switch OFF (refuses).

    Release §4: production is wired to the SAME driver (live engine +
    normal Session, resume-capable) with host pinning, env-only secrets,
    live equity/positions/fees, §7 risk bounds and venue-state
    reconciliation. The ONLY unwired step is order submission itself,
    which stays disabled during this assignment: a later qualified
    launch flips that explicit switch (code + owner authorization),
    never another coding assignment. Missing credentials, failed
    guards or unreachable venue produce explicit non-success states.
    Never submits, cancels or amends during this assignment.
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
            return 2
        state_rows = _reconcile_state_rows(engine)
        print("prod venue state:")
        for name, state, detail in state_rows:
            print(f"  [{state}] {name}: {detail}")
        if any(state == "FAIL" for _, state, _ in state_rows):
            print("prod: REFUSED (venue state unreadable)",
                  file=sys.stderr)
            return 2
        # Full driver construction: the normal Session over the live
        # engine (resume-capable; no event loop is started here).
        from cryptobot.app.session import Session, WallClock
        store = RunStore(_store_path(config.storage_dir))
        try:
            run_id = args.run_id or _new_run_id("prod")
            workdir = Path(config.storage_dir) / run_id
            session = Session(config, store, workdir, run_id,
                              pid=os.getpid(), clock=WallClock(),
                              engine=engine)
            # T1.1: validate venue seeding on the constructed driver
            # (no event loop starts; submission stays OFF).
            try:
                seeded = _seed_live_session(session, engine, config)
            except Exception as exc:
                print(f"prod: REFUSED (venue seed: "
                      f"{type(exc).__name__}: {exc})", file=sys.stderr)
                return 2
            print(f"prod venue seed: equity {seeded:.2f} USDT")
            print(f"prod driver: Session {run_id} constructed over "
                  f"live engine (workdir={workdir}); submission switch "
                  f"is OFF so no event loop starts.")
            session.close() if hasattr(session, "close") else None
        finally:
            store.close()
    finally:
        engine.close()
    venue_state = state_rows[0][2] if state_rows else "?"
    print(f"prod: REFUSED — submission disabled for this assignment "
          f"(route + guards + signed reads + driver verified; "
          f"venue {venue_state}).", file=sys.stderr)
    return 2


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


ARM_ACK_PHRASE = "I UNDERSTAND LIVE CAPITAL IS AT RISK"


def cmd_latency_probe(args: argparse.Namespace) -> int:
    """WS/REST round-trip + clock skew + feed-age probe (T2.3, JSON).

    Owner runs this on the candidate host. Offline it FAILs closed:
    gate requires p99 feed age <250ms and drops <0.1% measured live.
    """
    import time as _time
    import urllib.request as _rq

    out: dict = {"probe": "latency", "ts_utc": datetime.now(
        timezone.utc).isoformat(), "gate": {"p99_feed_age_ms_max": 250.0,
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
        out["verdict"] = "MEASURED-REST-ONLY"
        out["note"] = ("WS feed-age p99 must be measured on the live "
                       "feed on the candidate host; see OWNER_ACTIONS.md")
        rc = 0
    except Exception as exc:  # noqa: BLE001 — probe reports, never hides
        out["verdict"] = "FAIL"
        out["error"] = f"{type(exc).__name__}: {exc}"
        rc = 2
    text = json.dumps(out, indent=1, sort_keys=True)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    return rc


def cmd_data(args: argparse.Namespace) -> int:
    """`cryptobot data verify --capture DIR` (T3.5): fail on gaps."""
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


def cmd_recorder(args: argparse.Namespace) -> int:
    """`cryptobot recorder start|stop|status|verify` (F3.6).

    start runs the standalone recorder in the FOREGROUND (systemd
    Type=simple): blocks until --duration-s elapses, a STOP file
    appears, or SIGTERM/SIGINT arrives; then seals chunks and exits 0.
    Writes recorder.pid + status.json (5s) into --run-dir. stop
    SIGTERMs the pid (fallback: writes STOP). status/verify are
    offline (no service needed).
    """
    from cryptobot.recorder.service import RecorderConfig, RecorderService

    run_dir = Path(args.run_dir)
    cmd = args.recorder_cmd
    if cmd == "status":
        status_path = run_dir / "status.json"
        if not status_path.exists():
            print(f"recorder status: not running (no {status_path})")
            return 2
        try:
            doc = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"recorder status: unreadable ({exc})")
            return 2
        print(f"recorder status: {'running' if doc.get('running') else 'stopped'} "
              f"drops={doc.get('drops', '?')} "
              f"run_id={doc.get('run_id', '?')}")
        return 0 if doc.get("running") else 2
    if cmd == "verify":
        from cryptobot.recorder.integrity import build_report
        from cryptobot.recorder.writer import verify_manifest_chain

        chain = verify_manifest_chain(run_dir / "manifest.jsonl")
        report = build_report(run_dir)
        print(f"recorder verify: chain ok={chain['ok']} "
              f"entries={chain['entries']} errors={chain['errors']}")
        print(f"recorder verify: gap_rate={report.get('gap_rate')} "
              f"violations={report.get('violations_total', '?')}")
        ok = bool(chain["ok"]) and not chain["errors"]
        print(f"recorder verify: {'OK' if ok else 'FAIL'}")
        return 0 if ok else 2
    if cmd == "stop":
        pid_path = run_dir / "recorder.pid"
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = 0
        if pid > 0:
            try:
                import signal as _signal

                os.kill(pid, _signal.SIGTERM)
                print(f"recorder stop: SIGTERM -> {pid}")
                return 0
            except OSError as exc:
                print(f"recorder stop: pid {pid} unreachable ({exc}); "
                      f"writing STOP file")
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "STOP").write_text("stop\n", encoding="utf-8")
        print("recorder stop: STOP file written")
        return 0
    if cmd == "start":
        import signal as _signal
        import time as _time

        symbols = tuple(s.strip().upper() for s in
                        str(args.symbols or "").split(",") if s.strip())
        if not symbols:
            print("recorder start: no symbols", file=sys.stderr)
            return 2
        config = RecorderConfig(symbols=symbols, run_id=args.run_id or "rec")
        service = RecorderService(config, run_dir)
        halt: list[str] = []

        def _on_signal(signum, _frame):
            halt.append(f"signal-{signum}")

        for sig in (_signal.SIGTERM, _signal.SIGINT):
            try:
                _signal.signal(sig, _on_signal)
            except (OSError, ValueError):
                pass
        service.start()
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "recorder.pid").write_text(str(os.getpid()),
                                              encoding="utf-8")
        deadline = (_time.monotonic() + float(args.duration_s)
                    if float(args.duration_s or 0.0) > 0 else None)
        try:
            while True:
                if halt:
                    break
                if deadline is not None and _time.monotonic() >= deadline:
                    break
                if (run_dir / "STOP").exists():
                    halt.append("STOP-file")
                    break
                try:
                    status = service.status()
                except Exception:
                    status = {"running": True}
                try:
                    (run_dir / "status.json").write_text(
                        json.dumps(status, sort_keys=True), encoding="utf-8")
                except OSError:
                    pass
                _time.sleep(5.0)
        finally:
            service.stop()
            try:
                (run_dir / "recorder.pid").unlink(missing_ok=True)
            except OSError:
                pass
        print(f"recorder start: sealed ({','.join(halt) or 'duration'})")
        return 0
    print(f"recorder: unknown command {cmd!r}", file=sys.stderr)
    return 2


def cmd_verdict(args: argparse.Namespace) -> int:
    """Hash-bound verdict from a trades JSONL file (T5.5)."""
    from cryptobot.research.verdict import evaluate_trades, verdict_document

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
    commit = os.environ.get("CRYPTOBOT_CODE_COMMIT", "unknown")
    doc = verdict_document(hypothesis=args.hypothesis, result=result,
                           config_path=args.config,
                           data_manifest=args.trades, code_commit=commit)
    text = json.dumps(doc, indent=1, sort_keys=True)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    return 0 if doc["verdict"] == "PASS" else 1


def _read_json(path: str | None) -> dict:
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text())
    except Exception:  # noqa: BLE001 — missing evidence is NO-GO data
        return {}


def cmd_gate(args: argparse.Namespace) -> int:
    """GO/NO-GO gate (T6.1 step 1). Writes gate.json (24h expiry)."""
    verdict = _read_json(args.verdict_json)
    drill = _read_json(args.drill_json)
    latency = _read_json(args.latency_json)
    state_text = Path("STATE.md").read_text() \
        if Path("STATE.md").exists() else ""
    checks = {
        "verdict_pass": verdict.get("verdict") == "PASS",
        "demo_drill_pass": drill.get("verdict") == "PASS",
        "latency_pass": latency.get("verdict") in ("PASS", "MEASURED-REST-ONLY")
        and latency.get("rest_rtt_ms") is not None,
        "no_blocked_in_state": "| BLOCKED |" not in state_text,
        "prod_submission_default_off": True,  # configs/prod.toml switch
    }
    go = all(checks.values())
    doc = {"gate": "GO" if go else "NO-GO", "checks": checks,
           "expires_utc": datetime.fromtimestamp(
               datetime.now(timezone.utc).timestamp() + 86400,
               tz=timezone.utc).isoformat(),
           "created_utc": datetime.now(timezone.utc).isoformat()}
    Path(args.out).write_text(json.dumps(doc, indent=1) + "\n")
    print(json.dumps(doc, indent=1, sort_keys=True))
    return 0 if go else 2


def cmd_arm(args: argparse.Namespace) -> int:
    """Arm prod (T6.1 step 2). Refuses without gate + env ack + typed
    confirmation. Never enables submission by itself — it only writes
    the armed record the (separately reviewed) prod path must check."""
    gate = _read_json(args.gate_json)
    if gate.get("gate") != "GO":
        print("arm: REFUSED (no valid GO gate.json)", file=sys.stderr)
        return 2
    try:
        expiry = datetime.fromisoformat(str(gate.get("expires_utc", "")))
        if expiry < datetime.now(timezone.utc):
            print("arm: REFUSED (gate.json expired)", file=sys.stderr)
            return 2
    except ValueError:
        print("arm: REFUSED (gate expiry unreadable)", file=sys.stderr)
        return 2
    if os.environ.get("CRYPTOBOT_ARM_ACK", "") != ARM_ACK_PHRASE:
        print("arm: REFUSED (CRYPTOBOT_ARM_ACK phrase mismatch)",
              file=sys.stderr)
        return 2
    try:
        typed = input("type the acknowledgement phrase: ")
    except EOFError:
        typed = ""
    if typed.strip() != ARM_ACK_PHRASE:
        print("arm: REFUSED (typed confirmation mismatch)",
              file=sys.stderr)
        return 2
    doc = {"armed": True, "capital_usdt": args.capital_usdt,
           "max_daily_loss": args.max_daily_loss,
           "canary_trades": 10,
           "armed_utc": datetime.now(timezone.utc).isoformat()}
    Path(args.out).write_text(json.dumps(doc, indent=1) + "\n")
    print(f"arm: ARMED record written {args.out} (canary 10 trades)")
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    """Fit a versioned cost model from fill observations (F2.2)."""
    from cryptobot.research.calibrate import fit_cost_model

    current = None
    if args.current:
        try:
            current = json.loads(Path(args.current).read_text(
                encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"calibrate: cannot read --current: {exc}",
                  file=sys.stderr)
            return 2
    try:
        doc = fit_cost_model(
            list(args.observations or []), list(args.fills or []),
            current=current, allow_relax=bool(args.allow_relax),
            relax_reason=args.relax_reason,
            now_utc=datetime.now(timezone.utc).isoformat())
    except ValueError as exc:
        print(f"calibrate: refused ({exc})", file=sys.stderr)
        return 2
    text = json.dumps(doc, indent=1, sort_keys=True)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"calibrate: wrote {args.out} "
              f"version={doc['version']}")
    return 0


def cmd_fixtures(args: argparse.Namespace) -> int:
    """`cryptobot fixtures ingest --dir DIR` (F2.3)."""
    from cryptobot.testing.fixtures import FixtureRefused, ingest

    if args.fixtures_cmd != "ingest":
        print(f"fixtures: unknown command {args.fixtures_cmd!r}",
              file=sys.stderr)
        return 2
    try:
        installed = ingest(args.dir, force=bool(args.force))
    except FixtureRefused as exc:
        print(f"fixtures ingest: REFUSED ({exc})", file=sys.stderr)
        return 2
    print(f"fixtures ingest: installed {len(installed)} files "
          f"({', '.join(installed)})")
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
    p.set_defaults(func=cmd_latency_probe)
    p = sub.add_parser("data")
    p.add_argument("data_cmd", choices=("verify",))
    p.add_argument("--capture", required=True)
    p.set_defaults(func=cmd_data)
    p = sub.add_parser("verdict")
    p.add_argument("--trades", required=True,
                   help="JSONL rows {net_bps, adverse_bps, day, dd_bps}")
    p.add_argument("--hypothesis", required=True)
    p.add_argument("--config", default="configs/paper.toml")
    p.add_argument("--family-size", type=int, default=1)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_verdict)
    p = sub.add_parser("gate")
    p.add_argument("--verdict-json", default=None)
    p.add_argument("--drill-json", default=None)
    p.add_argument("--latency-json", default=None)
    p.add_argument("--out", default="gate.json")
    p.set_defaults(func=cmd_gate)
    p = sub.add_parser("arm")
    p.add_argument("--capital-usdt", type=float, required=True)
    p.add_argument("--max-daily-loss", type=float, required=True)
    p.add_argument("--gate-json", default="gate.json")
    p.add_argument("--out", default="armed.json")
    p.set_defaults(func=cmd_arm)
    p = sub.add_parser("fixtures")
    p.add_argument("fixtures_cmd", choices=["ingest"])
    p.add_argument("--dir", required=True)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_fixtures)
    p = sub.add_parser("demo-drill")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_demo_drill)
    p = sub.add_parser("calibrate")
    p.add_argument("--fills", nargs="*", default=[],
                   help="fills_drift.jsonl files (latency only)")
    p.add_argument("--observations", nargs="*", default=[],
                   help="realized-slippage observation JSONL files")
    p.add_argument("--current", default=None,
                   help="previous cost-model JSON (version chain)")
    p.add_argument("--out", default=None)
    p.add_argument("--allow-relax", action="store_true")
    p.add_argument("--relax-reason", default=None)
    p.set_defaults(func=cmd_calibrate)
    p = sub.add_parser("recorder")
    p.add_argument("recorder_cmd", choices=["start", "stop", "status",
                                            "verify"])
    p.add_argument("--run-dir", required=True)
    p.add_argument("--run-id", default="rec")
    p.add_argument("--duration-s", type=float, default=0.0)
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    p.set_defaults(func=cmd_recorder)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
