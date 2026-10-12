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


def iter_events(path: str | Path) -> Iterator[dict[str, Any]]:
    """Stream a normalized event file line by line (O(1) memory).

    Same per-record contract as load_events (input_class presence
    enforced); yields dicts in file order without materializing.
    """
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            if "input_class" not in record:
                raise ValueError(
                    "event record missing mandatory input_class label")
            yield record


def stream_events(path: str | Path, *,
                  order: str = "arrival") -> Iterator[dict[str, Any]]:
    """Yield capture events in deterministic order without sorting.

    Captures are seq-ordered by construction, so ``order="arrival"``
    enforces non-decreasing seq (ValueError naming the regressing
    record) instead of buffering a full-list sort. ``order="exchange_ts"``
    additionally enforces non-decreasing (exchange_ts_ms, seq). Output
    on a compliant file is identical to replay_events(load_events(path));
    non-compliant files raise rather than reorder — use replay_events on
    a loaded list when reordering foreign files is required.
    """
    if order == "arrival":
        def key(record: dict[str, Any]):
            return int(record["seq"])
    elif order == "exchange_ts":
        def key(record: dict[str, Any]):
            return (int(record["exchange_ts_ms"]), int(record["seq"]))
    else:
        raise ValueError(f"unknown replay order: {order!r}")
    prev = None
    for record in iter_events(path):
        cur = key(record)
        if prev is not None and cur < prev:
            raise ValueError(
                f"capture not {order}-ordered: seq {record.get('seq')} "
                f"regresses after {prev!r}")
        prev = cur
        yield record


class RollingEventHash:
    """Incremental events_hash over a streamed replay (O(1) memory).

    update() applies the exact events_hash step per event, so the final
    hexdigest equals events_hash() over the same ordered stream.
    """

    def __init__(self) -> None:
        self._digest = hashlib.sha256()
        self.count = 0

    def update(self, event: dict[str, Any]) -> None:
        self._digest.update(json.dumps(event, sort_keys=True).encode("utf-8"))
        self.count += 1

    def hexdigest(self) -> str:
        return self._digest.hexdigest()
