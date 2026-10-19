"""Hash-chained project adjudication (Z5).

SYNTHETIC rows cannot produce a real final state. A repeated decision
does not append and does not unload launchd again.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

FORMAT = "cryptobot-adjudication/1"
NEGATIVE = {"KILLED", "FAIL", "IMPRACTICAL", "NOT_ESTABLISHED"}
CONFIRMED = {"PASS", "FORWARD_PAPER"}
REAL_FINALS = {"ARCHIVE_NEGATIVE", "PAPER_ONLY", "READY_FOR_HUMAN_DECISION"}


def _sha(obj: dict) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def verify_chain(doc: dict | None) -> list[str]:
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        return ["adjudication chain missing or wrong format"]
    prev = "genesis"
    problems = []
    for i, entry in enumerate(doc.get("entries", [])):
        if entry.get("prev") != prev:
            problems.append(f"entry {i}: prev mismatch")
        body = {k: v for k, v in entry.items() if k != "entry_hash"}
        if _sha(body) != entry.get("entry_hash"):
            problems.append(f"entry {i}: hash mismatch")
        prev = entry.get("entry_hash")
    if prev != doc.get("chain_head"):
        problems.append("chain_head mismatch")
    return problems


def project_decision(rows: list[dict], *, now: datetime, t0: datetime | None,
                     gate_is_go: bool) -> tuple[str, list[dict]]:
    if any(str(r.get("provenance", "")).upper() == "SYNTHETIC" for r in rows):
        return "REFUSED_SYNTHETIC", list(rows)
    deadline = None if t0 is None else t0 + timedelta(days=90)
    terminal = NEGATIVE | CONFIRMED
    early = bool(rows) and all(r.get("state") in terminal for r in rows)
    due = deadline is not None and now >= deadline
    if not early and not due and not gate_is_go:
        return "WAITING", list(rows)
    closed = []
    for row in rows:
        if (due or early) and row.get("state") not in terminal:
            closed.append({**row, "state": "NOT_ESTABLISHED", "forced": True})
            continue
        closed.append(dict(row))
    if closed and all(r.get("state") in NEGATIVE for r in closed):
        return "ARCHIVE_NEGATIVE", closed
    if any(r.get("state") in CONFIRMED for r in closed) and not gate_is_go:
        return "PAPER_ONLY", closed
    if gate_is_go:
        return "READY_FOR_HUMAN_DECISION", closed
    return "WAITING", closed


def _load(path: Path) -> dict:
    if not path.exists():
        return {"format": FORMAT, "chain_head": "genesis", "entries": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    tmp.replace(path)


def cryptobot_plists(directory: Path) -> list[Path]:
    return sorted(directory.glob("com.cryptobot.*.plist"))


def unload_launchd(directory: Path, runner) -> list[str]:
    uid = os.getuid()
    issued = []
    for plist in cryptobot_plists(directory):
        cmd = ["launchctl", "bootout", f"gui/{uid}", str(plist)]
        runner(cmd)
        issued.append(" ".join(cmd))
    return issued


def _notify(message: str, runner) -> None:
    runner(["osascript", "-e",
            f'display notification "{message}" with title "cryptobot"'])


def run_adjudication(*, rows: list[dict], now: datetime, t0: datetime | None,
                     gate_is_go: bool, chain_path: Path, plist_dir: Path,
                     verdict_path: Path, runner=None,
                     notify: bool = True) -> dict:
    runner = runner or subprocess.run
    doc = _load(chain_path)
    problems = verify_chain(doc) if doc.get("entries") else []
    if problems:
        return {"decision": "REFUSED_BROKEN_CHAIN", "problems": problems}
    decision, closed = project_decision(
        rows, now=now, t0=t0, gate_is_go=gate_is_go)
    snapshot = _sha({"rows": rows, "decision": decision,
                     "gate_is_go": gate_is_go})
    if doc.get("entries") and doc["entries"][-1].get("snapshot") == snapshot:
        return {"decision": decision, "idempotent": True,
                "chain_head": doc["chain_head"], "closed": closed}
    if decision == "REFUSED_SYNTHETIC" or decision not in REAL_FINALS | {"WAITING"}:
        # A refusal is recorded. WAITING is recorded once per snapshot too,
        # so a later change of inputs still appends.
        pass
    actions: list[str] = []
    if decision in REAL_FINALS and decision != "REFUSED_SYNTHETIC":
        if decision == "ARCHIVE_NEGATIVE":
            actions.extend(unload_launchd(plist_dir, runner))
            verdict_path.write_text(
                "# Final verdict\n\nARCHIVE_NEGATIVE. No hypothesis "
                "established an edge. The recorder is stopped and the "
                "launchd jobs are unloaded.\n")
            actions.append(f"wrote {verdict_path}")
            if notify:
                _notify("ARCHIVE_NEGATIVE: recorder stopped", runner)
                actions.append("notified")
        elif decision == "PAPER_ONLY":
            if notify:
                _notify("PAPER_ONLY: passing hypotheses stay in paper", runner)
                actions.append("notified")
        elif decision == "READY_FOR_HUMAN_DECISION":
            if notify:
                _notify("Gate is GO. Arming stays human-only.", runner)
                actions.append("notified")
    entry = {
        "ts_utc": datetime.now(UTC).isoformat(),
        "decision": decision,
        "snapshot": snapshot,
        "closed": closed,
        "actions": actions,
        "prev": doc.get("chain_head", "genesis"),
    }
    entry["entry_hash"] = _sha(entry)
    doc.setdefault("entries", []).append(entry)
    doc["chain_head"] = entry["entry_hash"]
    doc["format"] = FORMAT
    _save(chain_path, doc)
    return {"decision": decision, "idempotent": False,
            "chain_head": doc["chain_head"], "actions": actions,
            "closed": closed}


__all__ = [
    "CONFIRMED", "NEGATIVE", "cryptobot_plists", "project_decision",
    "run_adjudication", "unload_launchd", "verify_chain",
]
