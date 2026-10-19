"""Read-only project monitor. Does not write a gate or an arm file."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from cryptobot.research.hurdle import hurdle_verdict


def _read(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def hypothesis_rows(repo: Path) -> list[dict]:
    rows = []
    for family, root in (("A", "research/autopilot"),
                         ("B", "research/autopilot_b"),
                         ("C", "research/autopilot_c")):
        state_dir = repo / root / "state"
        if not state_dir.is_dir():
            continue
        for path in sorted(state_dir.glob("*.json")):
            doc = _read(path) or {}
            rows.append({"family": family, "hypothesis": path.stem,
                         "state": doc.get("state", "UNKNOWN")})
    return rows


def best_family_b(repo: Path) -> dict | None:
    best = None
    dev = repo / "research" / "autopilot_b" / "dev"
    if not dev.is_dir():
        return None
    for path in sorted(dev.glob("B*.json")):
        doc = _read(path) or {}
        gates = doc.get("gates") or {}
        sharpe = gates.get("best_oos_sharpe")
        if not isinstance(sharpe, (int, float)):
            continue
        row = {"hypothesis": path.stem, "sharpe": float(sharpe),
               "drawdown": float(gates.get("drawdown") or 1.0),
               "pass": bool(gates.get("pass")),
               "turnover": gates.get("turnover")}
        if best is None or row["sharpe"] > best["sharpe"]:
            best = row
    return best


def recorder_status(repo: Path) -> dict:
    heart = _read(repo / "data" / "recorder" / "heartbeat.json")
    manifest = _read(repo / "data" / "recorder" / "manifest.json") or {}
    age = None
    if heart and heart.get("ts_utc"):
        try:
            when = datetime.fromisoformat(str(heart["ts_utc"]))
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            age = (datetime.now(UTC) - when).total_seconds()
        except ValueError:
            age = None
    return {"heartbeat_age_s": age,
            "sealed_chunks": len(manifest.get("entries") or []),
            "running": heart.get("state") == "running" if heart else False}


def build_report(repo: Path) -> dict:
    rows = hypothesis_rows(repo)
    best = best_family_b(repo)
    hurdle = None
    if best is not None:
        hurdle = hurdle_verdict(best_sharpe=best["sharpe"],
                                max_drawdown=best["drawdown"])
        hurdle["source"] = best
    killed = sum(1 for r in rows if r["state"] == "KILLED")
    return {
        "provenance": "ANALYSIS",
        "gate": "NO-GO",
        "demonstrated_edge": False,
        "hypotheses": rows,
        "killed": killed,
        "best_family_b": best,
        "owner_hurdle_2_to_3_pct_daily": hurdle,
        "recorder": recorder_status(repo),
        "sentence": "no demonstrated edge",
    }
