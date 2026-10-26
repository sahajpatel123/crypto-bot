"""Hermetic selftest. Localhost and temp files only. No keys, no orders."""
from __future__ import annotations

import argparse
import io
import json
import os
import select
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


def command_rows(parser: argparse.ArgumentParser | None = None) -> list[dict]:
    from cryptobot.cli import build_parser
    parser = parser or build_parser()
    rows: list[dict] = []

    def walk(node: argparse.ArgumentParser, prefix: str) -> None:
        choice_actions = [
            a for a in node._actions
            if not a.option_strings and getattr(a, "choices", None)
            and not isinstance(a, argparse._SubParsersAction)]
        subs = [a for a in node._actions
                if isinstance(a, argparse._SubParsersAction)]
        if choice_actions and not subs:
            for action in choice_actions:
                for choice in action.choices:
                    rows.append({"command": f"{prefix} {choice}",
                                 "help": (node.description or "").split("\n")[0]})
            return
        if subs:
            for action in subs:
                for name, sub in action.choices.items():
                    walk(sub, f"{prefix} {name}")
            return
        rows.append({"command": prefix,
                     "help": (node.description or "").split("\n")[0]})

    walk(parser, "cryptobot")
    return rows


def invoke(argv: list[str]) -> tuple[int, str]:
    from cryptobot.cli import main
    out, err = io.StringIO(), io.StringIO()
    code = 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:
        err.write(f"cryptobot: ERROR {type(exc).__name__}: {exc}\n")
        code = 1
    text = out.getvalue() + err.getvalue()
    return int(code), text


def _check(name: str, ok: bool, detail: str, results: list[dict]) -> None:
    results.append({"name": name, "status": "PASS" if ok else "FAIL",
                    "detail": detail})


def _pytest_subset(files: list[str], label: str,
                   results: list[dict]) -> None:
    """Run a focused, hermetic pytest subset (A3 acceptance evidence)."""
    root = Path(__file__).resolve().parents[2]
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             *files],
            cwd=root, capture_output=True, text=True, timeout=600)
        body = (proc.stdout or "") + (proc.stderr or "")
        # Report the failing test, not the last line of output. The last line
        # of a pytest run here is conftest's disk diagnostic, which hid the
        # real failure behind "pytest scratch left in ...: 0.0 MB".
        failed_lines = [ln.strip() for ln in body.splitlines()
                        if ln.startswith("FAILED ")]
        summary = [ln.strip() for ln in body.splitlines()
                   if " passed" in ln or " failed" in ln]
        fallback = (body.strip().splitlines() or [""])[-1]
        detail = (failed_lines[0] if failed_lines
                  else summary[-1] if summary else fallback)
        _check(f"acceptance-{label}", proc.returncode == 0,
               detail[:160], results)
    except subprocess.TimeoutExpired:
        _check(f"acceptance-{label}", False, "timeout", results)


def run_selftest(*, include_emulator: bool = True,
                 include_suites: bool = False) -> dict:
    results: list[dict] = []
    rows = command_rows()
    for row in rows:
        parts = row["command"].split()[1:]
        code, text = invoke(parts + ["--help"])
        ok = code == 0 and "usage" in text.lower() and "Traceback" not in text
        _check(f"help {row['command']}", ok, f"exit {code}", results)
        code, text = invoke(parts + ["--not-a-real-flag"])
        ok = code != 0 and "Traceback" not in text
        _check(f"bad-flag {row['command']}", ok, f"exit {code}", results)

    code, text = invoke(["no-such-command"])
    _check("unknown-command", code != 0 and "Traceback" not in text
           and "usage" in text.lower(), f"exit {code}", results)

    with tempfile.TemporaryDirectory() as tmp:
        missing = str(Path(tmp) / "missing.toml")
        code, text = invoke(["doctor", "--config", missing])
        _check("doctor-missing-config", code == 1 and "Traceback" not in text
               and "config" in text.lower(), text.strip()[:120], results)
        code, text = invoke(["run", "--mode", "prod", "--config", missing])
        _check("prod-missing-config", code == 2 and "Traceback" not in text,
               f"exit {code}", results)
        code, text = invoke(["arm", "--capital-usdt", "120",
                             "--max-daily-loss", "1",
                             "--out", str(Path(tmp) / "armed.json")])
        armed = Path(tmp) / "armed.json"
        _check("arm-without-tty", code == 2 and "REFUSED" in text
               and not armed.exists() and "Traceback" not in text,
               text.strip()[:160], results)
        # missing credentials: demo readiness without keys is BLOCKED (3)
        code, text = invoke(["readiness", "--config", "configs/demo.toml"])
        _check("readiness-missing-creds", code == 3
               and "Traceback" not in text,
               text.strip().splitlines()[0][:120] if text.strip() else "",
               results)
        # bare parents and invalid choices print usage, never a traceback
        for argv, label in ((["ops"], "ops-bare"),
                           (["data"], "data-bare"),
                           (["run", "--mode", "bogus", "--config",
                             "configs/paper.toml"], "run-bad-mode")):
            code, text = invoke(argv)
            _check(label, code == 2 and "usage" in text.lower()
                   and "Traceback" not in text, f"exit {code}", results)
        # ops prod refusal is exact exit 2 for every action
        for action in ("status", "order", "cancel", "flatten", "kill"):
            argv = ["ops", action, "--mode", "prod",
                   "--journal", str(Path(tmp) / "j.jsonl"),
                   "--book", str(Path(tmp) / "b.json"),
                   "--risk-state", str(Path(tmp) / "r.json"),
                   "--armed", str(Path(tmp) / "a.json"),
                   "--gate", str(Path(tmp) / "g.json")]
            if action == "order":
                argv += ["--symbol", "BTCUSDT", "--side", "BUY",
                        "--qty", "0.01"]
            if action == "cancel":
                argv += ["--client-id", "x"]
            code, text = invoke(argv)
            _check(f"ops-prod-refuses-{action}", code == 2
                   and "REFUSED" in text and "Traceback" not in text,
                   f"exit {code}", results)
        # idempotent read-only commands
        a, _ = invoke(["final-status"])
        b, _ = invoke(["final-status"])
        _check("final-status-idempotent", a == b == 0, f"{a},{b}", results)
        m1, t1 = invoke(["monitor"])
        m2, t2 = invoke(["monitor"])
        _check("monitor-idempotent", m1 == m2 == 0 and t1 == t2,
               f"{m1},{m2}", results)

    # SIGINT on the emulator server, which never dials a public host.
    # Wait for the ready line, not a blind sleep: the server installs its
    # SIGINT handler before printing it, so signalling only after the line
    # proves the handler ran instead of racing interpreter startup.
    proc = subprocess.Popen(
        [sys.executable, "-m", "cryptobot.cli", "emulator", "serve",
         "--port", "0"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    ready = False
    deadline = time.time() + 15
    assert proc.stdout is not None
    while time.time() < deadline and proc.poll() is None:
        ready_r, _, _ = select.select([proc.stdout], [], [], 0.2)
        if ready_r:
            line = proc.stdout.readline()
            if line and '"url"' in line:
                ready = True
                break
    if proc.poll() is None:
        proc.send_signal(signal.SIGINT)
    try:
        out, err = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    blob = (out or "") + (err or "")
    _check("emulator-sigint", ready and proc.returncode == 0
           and "Traceback" not in blob,
           f"ready={ready} rc={proc.returncode}", results)

    if include_emulator:
        from cryptobot.emulator.drill import run_drill, run_recorder_smoke, run_soak
        with tempfile.TemporaryDirectory() as tmp:
            drill = run_drill(Path(tmp))
            _check("emulator-drill", drill["verdict"] == "PASS"
                   and drill["provenance"] == "EMULATED",
                   json.dumps(drill["cells"])[:400], results)
            soak = run_soak(24)
            _check("emulator-soak", soak["verdict"] == "PASS"
                   and soak["provenance"] == "EMULATED"
                   and soak["peak_bytes"] < 200_000_000,
                   f"peak={soak['peak_bytes']}", results)
            smoke = run_recorder_smoke(Path(tmp) / "rec")
            _check("recorder-emulator-smoke", smoke["verdict"] == "PASS"
                   and smoke["input_class"] == "SYNTHETIC",
                   f"chunks={smoke.get('chunks')} "
                   f"records={smoke.get('records')}", results)
        code, text = invoke(["host-check", "--no-network"])
        _check("host-check", code in (0, 2) and "verdict" in text
               and "Traceback" not in text, f"exit {code}", results)
        code, text = invoke(["background", "status"])
        _check("background-status", code == 0
               and "adjudication_final_utc" in text
               and "Traceback" not in text, f"exit {code}", results)

    if include_suites:
        _pytest_subset(["tests/acceptance/test_risk_gates.py"],
                       "risk", results)
        _pytest_subset(["tests/audit/test_sandbox_drill.py"],
                       "chaos", results)
        _pytest_subset(["tests/acceptance/test_determinism.py"],
                       "determinism", results)
        _pytest_subset(["tests/unit/test_autopilot_gate.py",
                        "tests/unit/test_invalidation.py"],
                       "vault-verdict-gate-arm", results)
        _pytest_subset(["tests/unit/test_adjudicate.py"],
                       "adjudicator", results)

    failed = [r for r in results if r["status"] != "PASS"]
    return {"verdict": "FAIL" if failed else "PASS",
            "passed": len(results) - len(failed),
            "failed": len(failed),
            "commands": len(rows),
            "results": results}


def render_matrix(report: dict | None = None) -> str:
    rows = command_rows()
    status = {}
    if report:
        for item in report["results"]:
            if item["name"].startswith("help "):
                status[item["name"][5:]] = item["status"]
    lines = ["# Command matrix", "",
             "Generated from the CLI parser. A row is PASS only when "
             "`cryptobot selftest` exercised it. Modes: replay, paper, "
             "emulator-demo (paper or the live adapter pointed at "
             "127.0.0.1), prod.",
             "",
             "| Command | Mode | Expected | Test |",
             "|---|---|---|---|"]
    for row in rows:
        name = row["command"]
        mode = "n/a"
        if name == "cryptobot run":
            mode = "replay, paper, emulator-demo, prod"
        expected = "works, or a clear non-zero refusal with no traceback"
        if "prod" in name or name.endswith(" arm"):
            expected = "prod and arm refuse without a human TTY arm"
        lines.append(
            f"| `{name}` | {mode} | {expected} | "
            f"{status.get(name, 'UNTESTED')} |")
    return "\n".join(lines) + "\n"


def main_selftest(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cryptobot selftest")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--matrix-out", default=None)
    args = parser.parse_args(argv)
    os.environ.setdefault("CRYPTOBOT_SELFTEST", "1")
    report = run_selftest(include_emulator=True,
                          include_suites=bool(args.all))
    if args.matrix_out:
        Path(args.matrix_out).write_text(render_matrix(report), encoding="utf-8")
    print(f"selftest: {report['verdict']}")
    print(json.dumps({k: report[k] for k in ("verdict", "passed", "failed",
                                             "commands")},
                     sort_keys=True))
    if report["verdict"] != "PASS":
        for item in report["results"]:
            if item["status"] != "PASS":
                print(f"FAIL {item['name']}: {item['detail']}", file=sys.stderr)
        return 1
    return 0
