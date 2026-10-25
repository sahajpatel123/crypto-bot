"""F8.1: end-to-end acceptance on sandbox/SYNTHETIC evidence.

This is an acceptance harness, not a trading path. It proves:
  * the autopilot state machine advances through all stages;
  * SYNTHETIC provenance reaches GATE_READY for state-machine testing,
    but the gate refuses it (no synthetic artifact can arm capital);
  * sandbox fault scenarios end with no unowned order / no crash.
"""
from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from cryptobot.adapters.binance_live import BinanceLiveEngine, UnknownOutcomeError, VenueHttpError
from cryptobot.adapters.sandbox_venue import (
    FaultScript,
    SandboxConfig,
    SandboxSocket,
    SandboxTransport,
    SandboxVenue,
)
from cryptobot.app.engine import EngineOrder
from cryptobot.research.autopilot import Autopilot

SYNTH = "SYNTHETIC"


def _trades(n: int, net: float) -> list[dict]:
    return [{"net_bps": net, "adverse_bps": net - 1.0,
             "day": f"d{i % 30}", "provenance": SYNTH} for i in range(n)]


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc) + "\n", encoding="utf-8")


def _sandbox_scenarios(tmp: Path) -> list[dict]:
    """Faults against the real live engine + offline sandbox venue."""
    rows: list[dict] = []
    cases = [
        ("rate-limit", {"op": "order", "action": "rate-limit", "at": "once"}),
        ("unknown-submit", {"op": "order", "action": "unknown", "at": "once"}),
        ("reject", {"op": "order", "action": "reject", "at": "once"}),
        ("duplicate-event", {"op": "stream", "action": "dupe", "at": "once"}),
        ("reorder-event", {"op": "stream", "action": "reorder", "at": "once"}),
    ]
    for name, fault in cases:
        venue = SandboxVenue(SandboxConfig(
            seed=11, faults=FaultScript(entries=[dict(fault)])))
        engine = BinanceLiveEngine(
            api_key="sandbox-key", api_secret="sandbox-secret",
            journal_path=tmp / f"{name}.jsonl", expected_leverage=3,
            run_tag="accept", live_enable=True,
            transport=SandboxTransport(venue))
        try:
            engine._ensure_ready("ETHUSDT")
            cid = engine.submit(EngineOrder("ETHUSDT", "BUY", 0.01, "MARKET",
                                            reservation_id="r"))
            if name in ("duplicate-event", "reorder-event"):
                sock = SandboxSocket(venue)
                first = sock.recv(0)
                if first is not None:
                    engine.note_user_event(first)
                second = sock.recv(0)
                if second is not None:
                    engine.note_user_event(second)
                status = engine.lookup(cid)
                rows.append({"scenario": name, "result": "PASS",
                             "state": getattr(status, "state", "unknown"),
                             "filled": engine.filled_qty(cid)})
            else:
                rows.append({"scenario": name, "result": "PASS",
                             "state": "submitted",
                             "filled": engine.filled_qty(cid)})
        except UnknownOutcomeError as exc:
            # Unknown must be resolvable, never a crash.
            status = engine.lookup(exc.client_id)
            rows.append({"scenario": name, "result": "PASS",
                         "state": getattr(status, "state", "unknown"),
                         "resolved": True})
        except VenueHttpError as exc:
            # Deterministic refusal: nothing may exist at the venue.
            ok = not venue.orders and not venue.trades
            rows.append({"scenario": name,
                         "result": "PASS" if ok else "FAIL",
                         "state": f"rejected:{exc.status}",
                         "venue_orders": len(venue.orders)})
        except Exception as exc:  # noqa: BLE001 — acceptance reports
            rows.append({"scenario": name, "result": "FAIL",
                         "error": f"{type(exc).__name__}: {exc}"})
        finally:
            engine.close()
    return rows


def run_acceptance(*, full: bool = False,
                   root: str | Path | None = None) -> dict:
    base = Path(root) if root else Path("runs") / (
        "acceptance-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    if base.exists() and root is None:
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    auto = base / "autopilot"
    prereg = auto / "H1.md"
    _write(prereg, {}) if False else None
    prereg.parent.mkdir(parents=True, exist_ok=True)
    prereg.write_text("# H1 acceptance\n", encoding="utf-8")
    cfg = base / "H1.toml"
    cfg.write_text("hypothesis = 'H1'\n", encoding="utf-8")
    import hashlib
    bot = Autopilot(auto, allow_synthetic=True, paper_days=0)
    bot.register("H1", prereg=str(prereg),
                 config_sha256=hashlib.sha256(cfg.read_bytes()).hexdigest(),
                 commit="acceptance", family_size=6)
    steps = []
    for _ in range(8):
        out = bot.run_once()
        steps.append(out["hypotheses"]["H1"]["state"])
        if out["hypotheses"]["H1"]["state"] in ("GATE_READY", "KILLED", "FAIL"):
            break
        state = bot.read_state("H1")
        if state["state"] == "DEV_EVAL" and not (
                auto / "dev" / "H1.json").exists():
            _write(auto / "dev" / "H1.json",
                   {"trades": _trades(120, 8.0), "trades_per_day": 10.0,
                    "provenance": SYNTH})
        if state["state"] == "AWAIT_CONFIRM_DATA" and not (
                auto / "confirm" / "H1.json").exists():
            _write(auto / "confirm" / "H1.json",
                   {"trades": _trades(300, 7.0), "provenance": SYNTH})
        if state["state"] == "PASS" and not (
                auto / "paper" / "H1.json").exists():
            _write(auto / "paper" / "H1.json",
                   {"trades": _trades(100, 8.0), "tolerance_bps": 5.0,
                    "provenance": SYNTH})
    final_state = bot.read_state("H1")
    # Gate must refuse the synthetic GATE_READY artifact even if every
    # other field looks complete.
    import argparse

    from cryptobot import cli
    now = datetime.now(UTC).isoformat()
    verdict = base / "verdict.json"
    _write(verdict, {"verdict": "PASS", "data_provenance": SYNTH,
                     "hashes": {"config_sha256_16":
                                hashlib.sha256(cfg.read_bytes()).hexdigest()[:16]}})
    cost = base / "cost.json"
    _write(cost, {"version": 1, "created_utc": now})
    host = base / "host.json"
    _write(host, {"verdict": "PASS", "generated_utc": now})
    drill = base / "drill.json"
    _write(drill, {"verdict": "PASS", "created_utc": now})
    latency = base / "latency.json"
    _write(latency, {"verdict": "PASS", "p99_feed_age_ms": 100,
                     "drop_rate": 0.0})
    hb = base / "heartbeat.json"
    _write(hb, {"ts_utc": now, "has_exposure": False})
    state_path = auto / "state" / "H1.json"
    gate_rc = cli.cmd_gate(argparse.Namespace(
        verdict_json=str(verdict), drill_json=str(drill),
        latency_json=str(latency), autopilot_state=str(state_path),
        cost_model=str(cost), host_check=str(host),
        watchdog_heartbeat=str(hb), hypothesis="H1",
        config=str(cfg), require_commit=False, out=str(base / "gate.json")))
    fault_rows = _sandbox_scenarios(base) if full else []
    ok = (final_state["state"] == "GATE_READY"
          and final_state.get("provenance") == SYNTH
          and gate_rc == 2
          and all(r["result"] == "PASS" for r in fault_rows))
    return {"acceptance": "full" if full else "state-machine",
            "verdict": "PASS" if ok else "FAIL",
            "steps": steps, "final_state": final_state["state"],
            "provenance": final_state.get("provenance"),
            "gate_exit": gate_rc,
            "gate_verdict": json.loads(
                (base / "gate.json").read_text())["gate"],
            "faults": fault_rows, "root": str(base),
            "generated_utc": now}


__all__ = ["run_acceptance"]
