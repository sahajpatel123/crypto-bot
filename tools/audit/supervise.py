#!/usr/bin/env python3
"""Sustained-run supervision audit: health, heartbeat, recovery, resources.

Read-only over run/capture dirs. Collects: paper liveness trail
(checkpoints, risk transitions, equity samples, flatness), capture
heartbeat/run-stats, resume/recovery markers, disk usage, event rates,
and any live run processes. Prints verdict lines + writes JSON.

Usage:
    supervise.py --paper runs/<paper-id> --capture data/captures/<cap-id>
      [--recovery runs/<id> ...] --out <report.json>
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return None


def _load_jsonl(path):
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    return [json.loads(line) for line in lines if line.strip()]


def _du(path):
    try:
        out = subprocess.run(["du", "-sb", str(path)], capture_output=True,
                             text=True, timeout=120)
        return int(out.stdout.split()[0])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


def _parse_ts(value):
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000
                                          if value > 1e12 else value,
                                          tz=timezone.utc)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def audit_paper(paper_dir):
    paper_dir = Path(paper_dir)
    report = _load_json(paper_dir / "report.json") or {}
    equity = _load_jsonl(paper_dir / "equity.jsonl") or []
    risk = _load_jsonl(paper_dir / "risk.jsonl") or []
    out = {"run": str(paper_dir), "exists": (paper_dir / "report.json").exists(),
           "run_id": report.get("run_id"), "mode": report.get("mode"),
           "execution_model": report.get("execution_model"),
           "events_seen": report.get("events_seen"),
           "intents_admitted": report.get("intents_admitted"),
           "store_counts": report.get("store_counts"),
           "risk_transitions": len(risk),
           "equity_samples": len(equity),
           "open_position": report.get("open_position"),
           "position_qty": report.get("position_qty"),
           "heartbeat_json": (paper_dir / "heartbeat.json").exists()}
    stamps = [t for t in (_parse_ts(e.get("ts_utc")) for e in equity)
              if t is not None]
    if len(stamps) >= 2:
        out["window_utc"] = [min(stamps).isoformat(), max(stamps).isoformat()]
        out["elapsed_s"] = (max(stamps) - min(stamps)).total_seconds()
        if out["elapsed_s"] > 0 and report.get("events_seen"):
            out["events_per_s"] = (report["events_seen"] / out["elapsed_s"])
    out["disk_bytes"] = _du(paper_dir)
    out["checks"] = {
        "liveness_trail": bool((report.get("store_counts") or {})
                               .get("checkpoints")) or len(equity) > 1,
        "flat_at_end": report.get("open_position") is False
        and float(report.get("position_qty") or 0.0) == 0.0,
    }
    return out


def audit_capture(cap_dir):
    cap_dir = Path(cap_dir)
    stats = _load_json(cap_dir / "run_stats.json") or {}
    beat = _load_json(cap_dir / "heartbeat.json") or {}
    manifest = _load_json(cap_dir / "manifest.json") or {}
    files = manifest.get("files", {})
    verified, total = 0, 0
    import hashlib
    for name, info in files.items():
        total += 1
        raw = Path(info.get("path", ""))
        candidates = [raw] if raw.is_absolute() else [
            Path.cwd() / raw, cap_dir / raw, cap_dir / raw.name]
        for path in candidates:
            try:
                digest = hashlib.sha256()
                with open(path, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        digest.update(chunk)
            except OSError:
                continue
            if digest.hexdigest() == info.get("sha256"):
                verified += 1
            break
    return {"run": str(cap_dir),
            "events_total": stats.get("events_total"),
            "stop_reason": stats.get("stop_reason"),
            "bytes_written": stats.get("bytes_written"),
            "disconnects": stats.get("disconnects"),
            "depth_resyncs": stats.get("depth_resyncs"),
            "heartbeat_at_utc": beat.get("at_utc"),
            "heartbeat_events": beat.get("events_total"),
            "manifest_files_verified": f"{verified}/{total}",
            "disk_bytes": _du(cap_dir)}


def audit_recovery(run_dir):
    run_dir = Path(run_dir)
    report = _load_json(run_dir / "report.json") or {}
    risk_state = _load_json(run_dir / "risk_state.json")
    blob = json.dumps(report) + json.dumps(risk_state or {})
    lowered = blob.lower()
    markers = [m for m in ("resume", "recover", "crash", "kill",
                           "restart", "cursor")
               if m in lowered]
    return {"run": str(run_dir),
            "resume_markers": sorted(set(markers)),
            "open_position": report.get("open_position"),
            "closing_equity": report.get("closing_equity"),
            "recovered_flat": report.get("open_position") is False}


def live_processes():
    try:
        out = subprocess.run(["ps", "-ax", "-o", "pid,etime,command"],
                             capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return []
    hits = []
    for line in out.stdout.splitlines()[1:]:
        low = line.lower()
        if "cryptobot" in low or "capture_stream" in low or "replay_stream" in low:
            if "ps -ax" in line:
                continue
            hits.append(" ".join(line.split()))
    return hits[:20]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper", action="append", default=[])
    parser.add_argument("--capture", action="append", default=[])
    parser.add_argument("--recovery", action="append", default=[])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = {"papers": [audit_paper(p) for p in args.paper],
              "captures": [audit_capture(c) for c in args.capture],
              "recoveries": [audit_recovery(r) for r in args.recovery],
              "live_processes": live_processes()}
    Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    for paper in result["papers"]:
        trail = "TRAIL" if paper["checks"]["liveness_trail"] else "NO-TRAIL"
        flat = "FLAT" if paper["checks"]["flat_at_end"] else "NOT-FLAT"
        print(f"paper {paper['run_id']}: {paper['events_seen']} events, "
              f"{paper['risk_transitions']} risk transitions, "
              f"{paper['equity_samples']} equity samples, "
              f"heartbeat.json={paper['heartbeat_json']} -> {trail} {flat}")
    for cap in result["captures"]:
        print(f"capture {cap['run']}: {cap['events_total']} events, "
              f"stop={cap['stop_reason']}, files {cap['manifest_files_verified']}, "
              f"heartbeat={cap['heartbeat_at_utc']}")
    for rec in result["recoveries"]:
        print(f"recovery {rec['run']}: markers={rec['resume_markers']}, "
              f"flat={rec['recovered_flat']}")
    print(f"live run processes: {len(result['live_processes'])}")
    for proc in result["live_processes"]:
        print(f"  {proc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
