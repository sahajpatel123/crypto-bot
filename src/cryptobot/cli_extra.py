"""Operator, emulator, selftest, background, owner, and certify commands."""
from __future__ import annotations

import argparse
import json
import os
import signal
import time
from datetime import datetime
from pathlib import Path

from cryptobot.ops.manual import Book, apply_order, cancel_all, cancel_one, flatten, journal, prod_arm_refusal
from cryptobot.research.adjudicate import c1_final_utc


def cmd_monitor(args: argparse.Namespace) -> int:
    """Read-only analysis. Never writes a gate or an arm file."""
    from cryptobot.research.monitor import build_report
    repo = Path(args.repo) if args.repo else Path(__file__).resolve().parents[2]
    report = build_report(repo)
    print(f"monitor: {report['gate']}")
    print(report["sentence"])
    hurdle = report.get("owner_hurdle_2_to_3_pct_daily") or {}
    if hurdle:
        print(f"hurdle: {hurdle.get('verdict')} "
              f"best={hurdle.get('best_sharpe_ann')} "
              f"vol_required_for_2pct={hurdle.get('daily_vol_required_for_2pct')}")
    for row in report["hypotheses"]:
        print(f"{row['family']} {row['hypothesis']}: {row['state']}")
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, indent=1, sort_keys=True) + "\n")
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    from cryptobot.selftest import main_selftest
    argv = ["--all"] if args.all else []
    if args.matrix_out:
        argv += ["--matrix-out", args.matrix_out]
    return main_selftest(argv)


def cmd_emulator(args: argparse.Namespace) -> int:
    from cryptobot.adapters.mockex_server import EMULATED, MockEx
    if args.emulator_cmd == "drill":
        from cryptobot.emulator.drill import run_drill, run_soak
        out = Path(args.out or "emulator-drill.json")
        drill = run_drill(out.parent / "emulator-journal")
        soak = run_soak(4)
        doc = {"provenance": EMULATED, "emulated": True,
               "drill": drill, "soak": soak,
               "verdict": "PASS" if drill["verdict"] == "PASS"
               and soak["verdict"] == "PASS" else "FAIL"}
        text = json.dumps(doc, indent=1, sort_keys=True)
        print(text)
        if args.out:
            Path(args.out).write_text(text + "\n")
        return 0 if doc["verdict"] == "PASS" else 1
    mock = MockEx()
    port = mock.serve(args.host, args.port)
    print(json.dumps({"provenance": EMULATED, "emulated": True,
                      "url": f"http://{args.host}:{port}"}))
    sys_stdout_flush = __import__("sys").stdout.flush
    sys_stdout_flush()

    def _stop(signum, _frame):
        mock.close()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    try:
        while True:
            time.sleep(0.2)
    except SystemExit:
        return 0


def cmd_ops(args: argparse.Namespace) -> int:
    mode = args.mode
    refusal = prod_arm_refusal(mode, Path(args.armed), Path(args.gate))
    if refusal:
        print(refusal)
        return 2
    if mode == "prod":
        print("ops: REFUSED prod orders are not sent by this command")
        return 2
    if mode not in ("emulator", "sandbox", "demo"):
        print(f"ops: REFUSED unknown mode {mode}")
        return 2
    book_path = Path(args.book)
    book = Book()
    if book_path.exists():
        saved = json.loads(book_path.read_text(encoding="utf-8"))
        book.paused = bool(saved.get("paused"))
        if saved.get("venue"):
            book.venue.restore(saved["venue"])
    log = Path(args.journal)
    action = args.ops_cmd
    if action == "status":
        doc = book.snapshot()
    elif action == "positions":
        doc = {"positions": book.snapshot()["positions"], "provenance": "EMULATED"}
    elif action == "orders":
        snap = book.snapshot()
        doc = {"orders": snap["orders"], "algo_orders": snap.get("algo_orders", []),
               "provenance": "EMULATED"}
    elif action == "pause":
        book.paused = True
        doc = {"paused": True, "provenance": "EMULATED"}
    elif action == "resume":
        book.paused = False
        doc = {"paused": False, "provenance": "EMULATED"}
    elif action == "cancel-all":
        doc = cancel_all(book)
    elif action == "cancel":
        if not getattr(args, "client_id", None):
            print("ops: REFUSED cancel needs --client-id")
            return 2
        doc = cancel_one(book, args.client_id)
        if not doc.get("ok"):
            journal(log, {"action": action, "mode": mode, "result": doc})
            print(doc["message"])
            return 2
    elif action in ("flatten", "kill"):
        if action == "kill":
            cancel_all(book)
        doc = flatten(book, args.symbol)
        if action == "kill":
            book.paused = True
            doc["halted"] = True
    elif action == "order":
        doc = apply_order(
            book, symbol=args.symbol or "BTCUSDT", side=args.side or "BUY",
            qty=float(args.qty or 0), kind=(args.kind or "MARKET").upper(),
            price=args.price, reduce_only=bool(args.reduce_only),
            state_path=Path(args.risk_state),
            stop_price=getattr(args, "stop_price", None),
            post_only=bool(getattr(args, "post_only", False)),
            client_id=getattr(args, "client_id", None))
        if not doc.get("ok"):
            journal(log, {"action": action, "mode": mode, "result": doc})
            print(doc["message"])
            return 2
    else:
        print(f"ops: REFUSED unknown action {action}")
        return 2
    journal(log, {"action": action, "mode": mode, "result": "ok"})
    book_path.parent.mkdir(parents=True, exist_ok=True)
    book_path.write_text(json.dumps(
        {"paused": book.paused, "venue": book.venue.snapshot()},
        default=list, sort_keys=True))
    print(json.dumps(doc, default=str, sort_keys=True))
    return 0


def cmd_background(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parents[2]
    script_dir = root / "deploy" / "macos"
    if args.background_cmd == "install":
        return os_system(script_dir / "install.sh")
    if args.background_cmd == "uninstall":
        return os_system(script_dir / "uninstall.sh")
    import shutil
    t0 = _first_seal(Path(args.recorder))
    final = None if t0 is None else c1_final_utc(t0, None)
    free_mb = shutil.disk_usage(Path(args.recorder if Path(args.recorder).exists()
                                    else ".")).free / (1024 * 1024)
    print(json.dumps({
        "install": str(script_dir / "install.sh"),
        "uninstall": str(script_dir / "uninstall.sh"),
        "recorder": args.recorder,
        "free_mb": round(free_mb, 1),
        "adjudication_final_utc": None if final is None else final.isoformat(),
        "external_data_root": os.environ.get("EXTERNAL_DATA_ROOT") or "",
    }, sort_keys=True))
    return 0


def os_system(script: Path) -> int:
    import subprocess
    if not script.exists():
        print(f"background: REFUSED missing {script}")
        return 2
    return subprocess.call(["/bin/sh", str(script)])


def _first_seal(recorder: Path) -> datetime | None:
    manifest = recorder / "manifest.json"
    if not manifest.exists():
        return None
    try:
        doc = json.loads(manifest.read_text(encoding="utf-8"))
    except ValueError:
        return None
    stamps = [e.get("sealed_utc") for e in doc.get("entries", []) if e.get("sealed_utc")]
    if not stamps:
        return None
    return datetime.fromisoformat(min(stamps))


def cmd_owner(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except ValueError:
            state = {}
    steps = [
        ("host-check", "run cryptobot host-check --no-network"),
        ("demo-keys", "export demo keys in the environment; this wizard never stores them"),
        ("readiness", "run cryptobot readiness --config configs/demo.toml when that file exists"),
        ("demo-drill", "BLOCKED-OWNER: real demo-account drill is a human step"),
        ("latency-probe", "run cryptobot latency-probe when a capture exists"),
        ("fixtures", "run cryptobot fixtures ingest <source>"),
        ("calibrate", "run cryptobot calibrate --fills <file>"),
        ("legal", "BLOCKED-OWNER: venue access from your jurisdiction"),
        ("tax", "BLOCKED-OWNER: tax treatment of gains and losses"),
    ]
    done = set(state.get("done", []))
    if args.step:
        done.add(args.step)
    state["done"] = sorted(done)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    print("owner wizard")
    for name, text in steps:
        mark = "done" if name in done else "open"
        print(f"  [{mark}] {name}: {text}")
    print("gate: NO-GO until a real demo drill passes and you arm")
    print("no demonstrated edge")
    return 0


def cmd_certify(args: argparse.Namespace) -> int:
    from cryptobot.selftest import render_matrix, run_selftest
    report = run_selftest(include_emulator=True)
    matrix = render_matrix(report)
    if args.matrix_out:
        Path(args.matrix_out).write_text(matrix, encoding="utf-8")
    covered = report["commands"] > 0 and report["failed"] == 0
    verdict = "PASS" if report["verdict"] == "PASS" and covered else "FAIL"
    commit = os.popen("git rev-parse HEAD").read().strip() or "unknown"
    text = "\n".join([
        "# Completion certificate",
        "",
        f"commit: `{commit}`",
        f"selftest: {report['verdict']} ({report['passed']} passed, {report['failed']} failed)",
        f"command-matrix coverage: {report['commands']} commands, "
        f"{'100% PASS' if covered else 'INCOMPLETE'}",
        "emulator drill: see selftest emulator-drill and emulator-soak "
        "(provenance EMULATED, not a demo drill)",
        "suite: see STATE.md",
        "BLOCKED-OWNER: real demo-account drill; legal access to the venue; "
        "tax treatment of gains and losses",
        "gate: NO-GO",
        "",
        "no demonstrated edge",
        "",
    ])
    print(text)
    if args.out and verdict == "PASS":
        Path(args.out).write_text(text, encoding="utf-8")
    if verdict != "PASS":
        print("certify: FAIL", flush=True)
        return 1
    return 0
