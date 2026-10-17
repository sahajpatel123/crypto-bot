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
            symbols=list(config.symbols) or None,
            max_symbols=config.max_symbols,
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
