"""Prod preflight gate (W3-30MIN §9) — CONFIGURATION-ONLY.

Validates a run config before any live/prod run: structural load
(secret keys, demo hosts, prod engine kind are rejected by load_config),
§4 runtime knobs (tick, queue bound, 1s age gates), and the submission
contract — allow_live_submission=true requires explicit
--confirm-live-submission AND credentials present ONLY via environment.

This tool checks FILES, not the venue account. It never signs a request
and never reads balances, positions, fees, or permissions. A passing
result is CONFIG-READY (configuration only), NOT account readiness and
NOT a production GO. Use `cryptobot readiness` for signed venue checks.

Exit 0: CONFIG-READY. Exit 2: CONFIG-NOT-READY with reasons (also
printed as JSON with --json). Never prints credential values.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cryptobot.app.config import ConfigError, load_config  # noqa: E402

KEY_ENV = "CRYPTOBOT_API_KEY"
SECRET_ENV = "CRYPTOBOT_API_SECRET"

_SECRET_RE = re.compile(
    r"(?i)^\s*(api_key|api_secret|secret|password|token)\s*=")


def _scan_raw_secrets(path: Path) -> list[str]:
    """Reject secret-looking keys in the raw file (api_key_ref allowed)."""
    findings = []
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        code = line.split("#", 1)[0]
        if _SECRET_RE.search(code):
            findings.append(f"{path}:{lineno}: secret-looking key in "
                            f"config file (use api_key_ref + env)")
    return findings


def check_config(path: Path, *, confirm_live: bool = False) -> dict:
    """Run all preflight checks. ok=True means GO."""
    report: dict = {"config": str(path), "ok": True, "checks": [],
                    "mode": None, "submission": "unknown"}
    try:
        cfg = load_config(path)
    except ConfigError as exc:
        report["ok"] = False
        report["checks"].append({"name": "config-loads", "ok": False,
                                 "detail": str(exc)})
        return report
    report["mode"] = cfg.mode
    report["checks"].append({"name": "config-loads", "ok": True,
                             "detail": f"mode={cfg.mode}"})

    def check(name, ok, detail=""):
        report["checks"].append({"name": name, "ok": bool(ok),
                                 "detail": str(detail)})
        if not ok:
            report["ok"] = False

    raw = _scan_raw_secrets(path)
    check("no-inline-secrets", not raw, "; ".join(raw) or "clean")
    if cfg.mode in ("paper", "prod"):
        limit = cfg.risk.max_mark_age_ms
        check("1s-max-mark-age", limit is not None and limit <= 1000,
              f"max_mark_age_ms={limit!r}")
        check("quote-age-gate", cfg.quote_max_age_s <= 1.0,
              f"quote_max_age_s={cfg.quote_max_age_s}")
    else:
        check("1s-max-mark-age", True, "replay: not required")
        check("quote-age-gate", True, "replay: not required")
    check("control-tick", 0.05 <= cfg.control_tick_s <= 1.0,
          f"control_tick_s={cfg.control_tick_s}")
    check("feed-queue-bound", cfg.feed_queue_max >= 100,
          f"feed_queue_max={cfg.feed_queue_max}")
    if cfg.mode == "prod":
        check("prod-engine", cfg.engine_kind == "live" and not cfg.engine_demo,
              f"kind={cfg.engine_kind} demo={cfg.engine_demo}")
        host = cfg.engine_base_url or ""
        check("prod-host", "demo" not in host and "testnet" not in host,
              f"base_url={host or 'default?'}")
    if cfg.allow_live_submission:
        report["submission"] = "enabled"
        check("submission-confirmed", confirm_live,
              "allow_live_submission=true needs --confirm-live-submission")
        key = os.environ.get(KEY_ENV, "")
        secret = os.environ.get(SECRET_ENV, "")
        check("key-from-env", bool(key),
              f"{KEY_ENV}={'set' if key else 'MISSING'} (value never shown)")
        check("secret-from-env", bool(secret),
              f"{SECRET_ENV}={'set' if secret else 'MISSING'} (value never shown)")
    else:
        report["submission"] = "disabled"
        check("submission-default-off", True, "observe-only")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Prod preflight gate (§9).")
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--confirm-live-submission", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    report = check_config(args.config,
                          confirm_live=args.confirm_live_submission)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"preflight {report['config']}: "
              f"{'CONFIG-READY' if report['ok'] else 'CONFIG-NOT-READY'} "
              f"(mode={report['mode']} submission={report['submission']}; "
              f"configuration only, not account readiness)")
        for item in report["checks"]:
            print(f"  [{'PASS' if item['ok'] else 'FAIL'}] {item['name']}: "
                  f"{item['detail']}")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
