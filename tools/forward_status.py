#!/usr/bin/env python3
"""Unified forward status across B4b / F-CARRY / V-REG (read-only).

Calls each study's existing ``status_doc`` ONLY and prints one table:
forward days, per-cell round trips, blocking gate, days to power and to
first possible PASS, data hash, prereg sha and code sha256. ``--report``
emits the 6-line owner report (seq-763 template shape).

HARD LIMITS (pinned by tests, see test_forward_status.py):
- Never calls run / verify / evaluate / evaluate_frames / forward_command.
- Never prints Sharpe, P&L, equity, returns, or any verdict before the
  stopping rule is met: every status doc passes through ``_scrub``,
  which rebuilds the row from an allowlist of counter/clock/hash fields.
  Anything else (including poisoned performance keys) cannot leak.
- Never invents returns: the Returns line stays '$0 proven' until a
  stored non-UNDERPOWERED verdict file exists; only its STATUS word is
  ever read, never its numbers.
- No network, no Nov+ Vision reads here (status_doc reads local roots).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

STUDIES = (
    {"key": "B4b", "module": "forward_b4b", "file": "tools/forward_b4b.py",
     "leaf": "forward_b4b", "verdict": "B4b-forward.json",
     "prereg": "research/prereg/B4b-forward-basis.md"},
    {"key": "F-CARRY", "module": "forward_fcarry",
     "file": "tools/forward_fcarry.py", "leaf": "forward_fcarry",
     "verdict": "F-carry-forward.json",
     "prereg": "research/prereg/F-carry-forward.md"},
    {"key": "V-REG", "module": "forward_vreg", "file": "tools/forward_vreg.py",
     "leaf": "forward_vreg", "verdict": "V-reg-forward.json",
     "prereg": "research/prereg/V-reg-forward.md"},
)

# The ONLY status_doc fields this tool may read. Everything else --
# Sharpe, P&L, equity, returns, stats, gates, verdicts, selections --
# is dropped by _scrub and can never reach any output.
_SAFE_TOP_FIELDS = frozenset({
    "forward_days", "forward_days_required", "forward_days_remaining",
    "round_trips", "round_trips_required", "round_trips_remaining",
    "powered", "blocking_gate", "years_assessable_from_forward_day",
    "years_assessable_from", "forward_days_to_first_possible_pass",
    "forward_clock_start", "coverage", "regime_absent_cells", "per_cell",
})
_SAFE_CELL_FIELDS = frozenset({"round_trips", "round_trips_required",
                               "round_trips_remaining"})


_MODULES: dict[str, object] = {}


def _load_module(name: str, relpath: str):
    if name in _MODULES:
        return _MODULES[name]
    spec = importlib.util.spec_from_file_location(name, str(ROOT / relpath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    _MODULES[name] = mod
    return mod


def _sha_short(blob: bytes, n: int = 12) -> str:
    return hashlib.sha256(blob).hexdigest()[:n]


def _manifest_hash(doc: dict) -> str:
    """One short hash over what the study binds: its data manifest, or --
    for studies that predate manifest binding (B4b) -- its coverage map."""
    payload = doc.get("data_manifest")
    if payload is None:
        payload = {"coverage": doc.get("coverage", {})}
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return _sha_short(blob)


def _cells(doc: dict) -> dict[str, dict]:
    """Normalized {cell: {round_trips, ...}} across both status shapes."""
    per_cell = doc.get("per_cell")
    if isinstance(per_cell, dict) and per_cell:
        out = {}
        for name in sorted(per_cell, key=repr):
            cell = per_cell[name] or {}
            out[name] = {k: cell.get(k) for k in sorted(_SAFE_CELL_FIELDS)}
        return out
    return {"book": {
        "round_trips": doc.get("round_trips", 0),
        "round_trips_required": doc.get("round_trips_required", 20),
        "round_trips_remaining": doc.get("round_trips_remaining", 20),
    }}


def _blocking(doc: dict, cells: dict[str, dict]) -> str:
    """The study's blocking gate, or the same rule derived from counters."""
    if isinstance(doc.get("blocking_gate"), str):
        return doc["blocking_gate"]
    if doc.get("forward_days", 0) < doc.get("forward_days_required", 90):
        return "forward_days"
    short = [k for k, c in cells.items()
             if (c.get("round_trips") or 0) < (c.get("round_trips_required")
                                               or 20)]
    if short:
        return "round_trips:" + ",".join(sorted(short))
    return "years_assessability"


def _prereg_sha(doc: dict, study: dict) -> str:
    """Bound prereg sha, else the same sha computed from the frozen file."""
    bound = doc.get("prereg_sha256")
    if isinstance(bound, str) and len(bound) >= 12:
        return bound[:12]
    try:
        blob = (ROOT / study["prereg"]).read_bytes()
    except OSError:
        return "missing"
    return _sha_short(blob)


def _code_sha(doc: dict, study: dict) -> str:
    """Bound evaluator-module sha, else the same sha computed locally."""
    bound = doc.get("code_sha256")
    if isinstance(bound, dict):
        for name, digest in sorted(bound.items()):
            if name.startswith("forward_") and isinstance(digest, str):
                return digest[:12]
    try:
        blob = (ROOT / study["file"]).read_bytes()
    except OSError:
        return "missing"
    return _sha_short(blob)


def _scrub(doc: dict) -> dict:
    """Rebuild a status doc from the allowlist; NOTHING else passes.

    Guard-deletion proof: bypassing this (rendering the raw doc) leaks
    performance fields and fails test_leak_guard_blocks_performance_fields.
    """
    if not isinstance(doc, dict):
        return {}
    out = {k: doc[k] for k in sorted(_SAFE_TOP_FIELDS) if k in doc}
    per_cell = out.get("per_cell")
    if isinstance(per_cell, dict):  # nested allowlist for cell subfields
        out["per_cell"] = {
            name: {f: (cell or {}).get(f) for f in sorted(_SAFE_CELL_FIELDS)}
            for name, cell in per_cell.items()}
    return out


def collect(study: dict, data_root: Path) -> dict:
    """One scrubbed status row. Calls status_doc ONLY (never run/verify)."""
    mod = _load_module(study["module"], study["file"])
    try:
        raw = mod.status_doc(Path(data_root))
    except Exception as exc:  # noqa: BLE001 -- day-0 roots may be absent
        return {"study": study["key"], "error": f"{type(exc).__name__}",
                "forward_days": 0, "cells": {}, "powered": False,
                "blocking_gate": "forward_days", "to_power_days": 90,
                "to_pass_days": 121, "years_from": "2027-03-01",
                "manifest_hash": _sha_short(b"{}"),
                "prereg": study["prereg"], "prereg_sha12": "missing",
                "code_sha12": "missing", "clock_start": "2026-11-01"}
    doc = _scrub(raw)
    cells = _cells(doc)
    to_power = max(0, doc.get("forward_days_required", 90)
                   - doc.get("forward_days", 0))
    return {
        "study": study["key"],
        "forward_days": doc.get("forward_days", 0),
        "days_required": doc.get("forward_days_required", 90),
        "cells": cells,
        "powered": bool(doc.get("powered", False)),
        "blocking_gate": _blocking(doc, cells),
        "to_power_days": to_power,
        "to_pass_days": doc.get("forward_days_to_first_possible_pass", 121),
        "years_from": doc.get("years_assessable_from", "2027-03-01"),
        "manifest_hash": _manifest_hash(doc),
        "prereg": study["prereg"],
        "prereg_sha12": _prereg_sha(doc, study),
        "code_sha12": _code_sha(doc, study),
        "clock_start": doc.get("forward_clock_start", "2026-11-01"),
    }


def _verdict_statuses(reports_dir: Path) -> dict[str, str | None]:
    """Stored verdict STATUS words only. Numbers inside are never read."""
    out: dict[str, str | None] = {}
    for study in STUDIES:
        path = Path(reports_dir) / study["verdict"]
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError):
            out[study["key"]] = None
            continue
        status = doc.get("status") if isinstance(doc, dict) else None
        out[study["key"]] = status if isinstance(status, str) else None
    return out


def render_table(rows: list[dict]) -> str:
    lines = ["STUDY    DAYS   BLOCKING              TO-POWER  TO-PASS  "
             "MANIFEST      PREREG        CODE"]
    for r in rows:
        if "error" in r:
            lines.append(f"{r['study']:<8} error: {r['error']}")
            continue
        lines.append(
            f"{r['study']:<8} {r['forward_days']:>3}/{r['days_required']:<3}  "
            f"{r['blocking_gate']:<21.21} {r['to_power_days']:>8} "
            f"{r['to_pass_days']:>7}  {r['manifest_hash']:<12} "
            f"{r['prereg_sha12']:<12} {r['code_sha12']:<12}")
        for name, c in r["cells"].items():
            lines.append(f"  {name}: {c.get('round_trips', 0)}/"
                         f"{c.get('round_trips_required', 20)} RTs")
    lines.append("TO-POWER = days leg only (RT leg unpredictable); "
                 "TO-PASS = years gate.")
    return "\n".join(lines)


def _min_rt(rows: list[dict]) -> tuple[str, int]:
    worst, arg = 20, "-"
    for r in rows:
        for name, c in r.get("cells", {}).items():
            rt = c.get("round_trips") or 0
            if rt < worst:
                worst, arg = rt, f"{r['study']}/{name}"
    return arg, worst


def render_report(rows: list[dict], verdicts: dict[str, str | None],
                  tip: str) -> str:
    """The 6-line owner report (seq-763 template shape). No invented numbers:
    every value comes from status_doc counters/clocks/hashes or verdict
    STATUS words. Returns stays '$0 proven' until a PASS verdict exists."""
    days = max([r.get("forward_days", 0) for r in rows] + [0])
    clock = rows[0].get("clock_start", "2026-11-01") if rows else "2026-11-01"
    passes = sorted(k for k, v in verdicts.items() if v == "PASS")
    kills = sorted(k for k, v in verdicts.items() if v == "KILLED")
    gate = "NO-GO" if not passes else f"NO-GO (PASS {','.join(passes)} awaits paper+arm)"
    money = "$0" if not passes else f"PASS {','.join(passes)} (see verdict)"
    fwd = ", ".join(f"{r['study']} {r.get('forward_days', 0)}/"
                    f"{r.get('days_required', 90)}d"
                    for r in rows) if rows else "-"
    edge = "none" if not passes else ",".join(passes)
    hist_killed = "B1-B7,C1-C4,H/X/S,D1-fail-closed"
    killed = hist_killed + ("" if not kills else "+" + ",".join(kills))
    try:
        import datetime as _dt
        kill_date = (_dt.date.fromisoformat(str(clock)[:10])
                     + _dt.timedelta(days=89)).isoformat()
    except ValueError:
        kill_date = "?"
    pass_dates = sorted({str(r.get("years_from", "?")) for r in rows})
    pass_date = pass_dates[-1] if pass_dates else "?"
    # Blocker/Next from the most-blocked row (deterministic priority).
    prio = {"forward_days": 0, "round_trips": 1}
    def _rank(r: dict) -> tuple[int, str]:
        b = str(r.get("blocking_gate", "forward_days"))
        key = "forward_days" if b == "forward_days" else (
            "round_trips" if b.startswith("round_trips") else "zzz")
        return (prio.get(key, 2), r.get("study", ""))
    worst = min(rows, key=_rank) if rows else {}
    wb = str(worst.get("blocking_gate", "forward_days"))
    if wb == "forward_days":
        blocker = (f"data-clock — {worst.get('study')} at "
                   f"{worst.get('forward_days', 0)}/90d")
        nxt = "wait for forward data (day 1 was 2026-11-01)"
    elif wb.startswith("round_trips"):
        arg, rt = _min_rt(rows)
        blocker = f"regime — thinnest cell {arg} at {rt}/20 RTs"
        nxt = "wait for regime (20 RTs in every cell)"
    else:
        blocker = "years gate — waits 2027-03-01 for first PASS"
        nxt = "wait for 2027-03-01 (90d looks are kill-or-underpowered)"
    return "\n".join([
        f"1. Gate: {gate} | Money proven: {money}",
        f"2. Strategies: Killed: {killed} | Forward-waiting: "
        f"{len(rows)} ({fwd}) | Edge: {edge}",
        f"3. Code: tip {tip} | suite: CI | PR queue: gh",
        f"4. Clock: day1 {clock} | days so far: {days} | next verdict: "
        f"{kill_date} kill-only, {pass_date} PASS-capable",
        f"5. Blocker: {blocker}",
        f"6. Next: {nxt}",
    ])


def _git_tip() -> str:
    import subprocess
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=ROOT, capture_output=True, text=True,
                             timeout=10)
    except (OSError, ValueError):
        return "unknown"
    tip = (out.stdout or "").strip()
    return tip if tip else "unknown"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="forward_status",
                                 description="Unified forward status "
                                 "(read-only, never a verdict).")
    ap.add_argument("--data", default=str(ROOT / "data"),
                    help="parent dir of per-study data roots")
    ap.add_argument("--reports", default=str(ROOT / "reports/hypotheses"),
                    help="dir of stored verdict JSON files (status only)")
    ap.add_argument("--report", action="store_true",
                    help="emit the 6-line owner report instead of the table")
    args = ap.parse_args(argv)
    rows = [collect(s, Path(args.data) / s["leaf"]) for s in STUDIES]
    if args.report:
        verdicts = _verdict_statuses(Path(args.reports))
        print(render_report(rows, verdicts, _git_tip()))
    else:
        print(render_table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
