"""Protection evidence log + replayer (Worker 4, W4-24H).

Every runtime decision (entry check, anomaly observation, source refresh)
is appended as one JSONL record carrying its full inputs. replay_evidence
re-folds a log through fresh gate + anomaly state and reports any
divergence, proving the log actually explains the run.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

EVIDENCE_FORMAT = "cryptobot-protection-evidence/1"


class EvidenceLog:
    def __init__(self, path: str | Path, header: dict[str, Any]) -> None:
        import threading
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._seq = 0
        record = {"format": EVIDENCE_FORMAT, "kind": "header", **header}
        with self.path.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    @property
    def seq(self) -> int:
        return self._seq

    def append(self, kind: str, ts_utc: datetime,
               payload: dict[str, Any]) -> int:
        if ts_utc.tzinfo is None:
            raise ValueError("ts_utc must be timezone-aware")
        # The freshness refresher thread and the session loop append
        # concurrently; serialize seq + file write (watchdog review).
        with self._lock:
            self._seq += 1
            record = {"format": EVIDENCE_FORMAT, "seq": self._seq,
                      "ts_utc": ts_utc.isoformat(), "kind": kind, **payload}
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
            return self._seq


def read_evidence(path: str | Path) -> tuple[dict[str, Any],
                                             list[dict[str, Any]]]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"evidence {path} is empty")
    records = [json.loads(line) for line in lines if line.strip()]
    for record in records:
        if record.get("format") != EVIDENCE_FORMAT:
            raise ValueError(
                f"bad evidence format: {record.get('format')!r}")
    header = records[0]
    if header.get("kind") != "header":
        raise ValueError("evidence log missing header")
    return header, records[1:]


def replay_evidence(path: str | Path,
                    rebuild: Callable[[dict[str, Any]], Any],
                    ) -> dict[str, Any]:
    """Re-fold a log through fresh components and compare decisions.

    rebuild(header) returns an object with check_entry(now, reading,
    baseline) and observe(now, reading, baseline) (a ProtectionRuntime
    over a rebuilt store). Refresh records are counted, not re-folded
    (HTTP is not replayed). Returns counts + mismatch list.

    rebuild MUST NOT reuse the log being replayed as its evidence path
    (pass evidence_path=None or a scratch path); replaying into the same
    file would append while reading.
    """
    from .anomaly import AnomalyBaseline, AnomalyReading
    from .timezones import parse_iso_utc

    header, records = read_evidence(path)
    runtime = rebuild(header)
    compared = 0
    mismatches: list[dict[str, Any]] = []
    skipped = 0
    for record in records:
        kind = record.get("kind")
        if kind not in ("entry-check", "observation"):
            skipped += 1
            continue
        now = parse_iso_utc(record["ts_utc"])
        inputs = record.get("inputs", {})
        reading = AnomalyReading(
            spread_bps=inputs.get("spread_bps"),
            book_depth_ratio=inputs.get("book_depth_ratio"),
            abs_return_bps=inputs.get("abs_return_bps"),
            latency_ms=inputs.get("latency_ms"),
            exchange_error_count=int(inputs.get("exchange_error_count", 0)))
        baseline = AnomalyBaseline(
            spread_bps=inputs.get("baseline_spread_bps"),
            book_depth_notional=inputs.get("baseline_book_notional"))
        if kind == "entry-check":
            fresh = runtime.check_entry(now, reading, baseline)
            expect = {"blocked": record["final"]["blocked"],
                      "reason": record["final"]["reason"]}
            got = {"blocked": fresh.blocked, "reason": fresh.reason}
        else:
            fresh = runtime.observe(now, reading, baseline)
            expect = {"action": record["anomaly"]["action"],
                      "reason": record["anomaly"]["reason"]}
            got = {"action": fresh.action, "reason": fresh.reason}
        compared += 1
        if got != expect:
            mismatches.append({"seq": record.get("seq"), "kind": kind,
                               "expected": expect, "got": got})
    return {"records": len(records), "compared": compared,
            "skipped_non_replayable": skipped,
            "mismatches": mismatches, "ok": not mismatches}
