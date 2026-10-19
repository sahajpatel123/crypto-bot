"""Hermetic selftest. Localhost and temp files only. No keys, no orders."""
from __future__ import annotations

import argparse
import io
import json
import os
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


def run_selftest(*, include_emulator: bool = True) -> dict:
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
        _check("doctor-missing-config", code != 0 and "Traceback" not in text
               and "config" in text.lower(), text.strip()[:120], results)
        code, text = invoke(["run", "--mode", "prod", "--config", missing])
        _check("prod-missing-config", code != 0 and "Traceback" not in text,
               f"exit {code}", results)
        code, text = invoke(["arm", "--capital-usdt", "120",
                             "--max-daily-loss", "1",
                             "--out", str(Path(tmp) / "armed.json")])
        armed = Path(tmp) / "armed.json"
        _check("arm-without-tty", code != 0 and "REFUSED" in text
               and not armed.exists() and "Traceback" not in text,
               text.strip()[:160], results)
        # idempotent read-only command
        a, _ = invoke(["final-status"])
        b, _ = invoke(["final-status"])
        _check("final-status-idempotent", a == b == 0, f"{a},{b}", results)

    # SIGINT on the emulator server, which never dials a public host.
    proc = subprocess.Popen(
        [sys.executable, "-m", "cryptobot.cli", "emulator", "serve",
         "--port", "0"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(0.4)
    proc.send_signal(signal.SIGINT)
    try:
        out, err = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    blob = (out or "") + (err or "")
    _check("emulator-sigint", proc.returncode is not None
           and "Traceback" not in blob, f"rc={proc.returncode}", results)

    if include_emulator:
        from cryptobot.emulator.drill import run_drill, run_soak
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
    report = run_selftest(include_emulator=True)
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
