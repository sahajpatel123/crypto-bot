"""Deterministic recording replayer (Worker 2, E-001).

The replayer yields records in a fixed logical order — (exchange_open_ms,
seq) — so the same file always produces the same event stream. It performs
no sleeping or wall-clock pacing: live-timing simulation is explicitly out
of scope for E-001, and any consumer that needs pacing owns that behaviour.

Every replay exposes the recording's ``input_class`` label so observed and
synthetic data can never be silently mixed; use ``assert_input_class`` to
enforce the expected class at the boundary.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from .recorder import RECORDING_FORMAT


@dataclass(frozen=True)
class ReplayEvent:
    seq: int
    exchange_open_ms: int
    exchange_close_ms: int
    local_recv_ms: int
    closed: bool
    payload: dict[str, Any]


def load_recording(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load a recording file. Returns (header, data records); footer is skipped."""
    lines = [ln for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        raise ValueError("empty recording file")
    header = json.loads(lines[0])
    if header.get("type") != "header":
        raise ValueError("first line must be a recording header")
    if header.get("format") != RECORDING_FORMAT:
        raise ValueError(f"unsupported recording format: {header.get('format')!r}")
    if "input_class" not in header:
        raise ValueError("recording header missing mandatory input_class label")
    records = [json.loads(ln) for ln in lines[1:] if json.loads(ln).get("type") == "kline"]
    return header, records


def assert_input_class(header: dict[str, Any], expected: str) -> None:
    actual = header.get("input_class")
    if actual != expected:
        raise ValueError(f"input_class mismatch: expected {expected!r}, got {actual!r}")


def replay(records: Iterable[dict[str, Any]]) -> Iterator[ReplayEvent]:
    """Yield kline records in deterministic logical order."""
    ordered = sorted(records, key=lambda r: (int(r["exchange_open_ms"]), int(r.get("seq", 0))))
    for r in ordered:
        yield ReplayEvent(
            seq=int(r.get("seq", 0)),
            exchange_open_ms=int(r["exchange_open_ms"]),
            exchange_close_ms=int(r["exchange_close_ms"]),
            local_recv_ms=int(r["local_recv_ms"]),
            closed=bool(r.get("closed", False)),
            payload={k: v for k, v in r.items() if k not in ("type", "seq")},
        )


def replay_hash(records: Iterable[dict[str, Any]]) -> str:
    """Stable SHA-256 over the deterministic replay stream (excludes footer)."""
    digest = hashlib.sha256()
    for event in replay(records):
        digest.update(
            json.dumps(
                [event.seq, event.exchange_open_ms, event.exchange_close_ms,
                 event.local_recv_ms, event.closed, event.payload],
                sort_keys=True,
            ).encode("utf-8")
        )
    return digest.hexdigest()


def load_events(path: str | Path) -> list[dict[str, Any]]:
    """Load a normalized event stream (cryptobot-events/1), enforcing labels."""
    records = [json.loads(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines()
               if ln.strip()]
    for record in records:
        if "input_class" not in record:
            raise ValueError("event record missing mandatory input_class label")
    return records


def replay_events(
    records: Iterable[dict[str, Any]], *, order: str = "arrival"
) -> Iterator[dict[str, Any]]:
    """Yield normalized events in deterministic order.

    ``order="arrival"`` (default) replays in ``seq`` order, reproducing the
    exact arrival sequence the collector saw — feeding the stream back into
    stateful processors (bar builders, books) reproduces capture-time state,
    including live late/dup drops. ``order="exchange_ts"`` replays in
    ``(exchange_ts_ms, seq)`` order for causal analysis; stateful rebuilds
    under this ordering can legitimately differ from capture-time artifacts.
    """
    if order == "exchange_ts":
        key = lambda r: (int(r["exchange_ts_ms"]), int(r["seq"]))  # noqa: E731
    elif order == "arrival":
        key = lambda r: int(r["seq"])  # noqa: E731
    else:
        raise ValueError(f"unknown replay order: {order!r}")
    yield from sorted(records, key=key)


def events_hash(records: Iterable[dict[str, Any]], *, order: str = "arrival") -> str:
    """Stable SHA-256 over the deterministic event replay stream."""
    digest = hashlib.sha256()
    for event in replay_events(records, order=order):
        digest.update(json.dumps(event, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()
