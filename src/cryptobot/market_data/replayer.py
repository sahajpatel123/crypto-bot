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
    return list(iter_events(path))


def iter_events(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield normalized events in file order without materializing the stream.

    Blank lines are skipped. Malformed JSON and missing ``input_class``
    labels raise ``ValueError`` naming the offending line. This is the bulk
    path: multi-million-event captures must stream, never ``load_events``.
    """
    with Path(path).open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}: line {lineno}: invalid JSON ({exc})") from exc
            if "input_class" not in record:
                raise ValueError(f"{path}: line {lineno}: missing mandatory input_class label")
            yield record


def streaming_events_hash(path: str | Path, *, expect_class: str) -> tuple[str, int]:
    """SHA-256 over the arrival-ordered event file in O(1) memory.

    Byte-identical to ``events_hash(load_events(path))`` whenever the file
    is arrival-ordered (what the collector writes): same per-event digest
    updates, same order. Enforces strictly increasing ``seq`` (proving the
    file order IS arrival order, so no sort is needed) and ``input_class``
    on every record. Returns (hexdigest, event count).
    """
    digest = hashlib.sha256()
    count = 0
    last_seq: int | None = None
    for record in iter_events(path):
        seq = int(record["seq"])
        if last_seq is not None and seq <= last_seq:
            raise ValueError(
                f"{path}: seq {seq} after {last_seq}: file is not arrival-ordered; "
                "streaming arrival replay requires seq order"
            )
        last_seq = seq
        if record["input_class"] != expect_class:
            raise ValueError(
                f"input_class mismatch: expected {expect_class!r}, "
                f"got {record['input_class']!r} at seq {seq}"
            )
        digest.update(json.dumps(record, sort_keys=True).encode("utf-8"))
        count += 1
    return digest.hexdigest(), count


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


_LEGACY_SNAPSHOT_SKEW_MS = 1000


def replay_with_snapshots(
    records: Iterable[dict[str, Any]],
    snaps: Iterable[dict[str, Any]],
    *,
    order: str = "arrival",
    assume_ordered: bool = False,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ("event"|"snapshot", payload) in causal replay order.

    Snapshots install when the replay clock (monotonic max of event
    ``exchange_ts_ms``) reaches them — never all-upfront, so a future
    snapshot cannot leak into earlier queries. Each snapshot is yielded
    BEFORE the first event at/after its time. The event subsequence is
    identical to :func:`replay_events` (parity); only snapshot items are
    added, at causal positions.

    Snapshots key on the exchange clock (``snapshot_ms``); records with a
    venue transaction time merge exactly. Legacy records (receipt clock
    only) get a 1000 ms install tolerance for host skew — installing
    slightly early is safe because views still refuse queries older than
    the applied state (``book:future-data``). Snapshots newer than every
    event are NEVER yielded: no clock reached them, so no install.

    Consumer contract: install yielded snapshots unconditionally (no
    ``as_of_ms``) — the iterator already enforced clock >= snapshot time
    at yield. Queries between install and clock catch-up are still safe:
    views refuse anything older than the applied state (``book:future-data``).

    ``assume_ordered`` skips the :func:`replay_events` sort for callers
    holding an already-ordered stream (Session streaming replay): the
    merge stays O(snapshots) memory. Ordering enforcement is then the
    caller's stream contract (manager integration adaptation).
    """
    from .bridge import snapshot_ms

    ordered_snaps = sorted(snaps, key=snapshot_ms)
    clock: int | None = None
    idx = 0
    stream = records if assume_ordered else replay_events(records, order=order)
    for event in stream:
        ts = int(event["exchange_ts_ms"])
        clock = ts if clock is None else max(clock, ts)
        while idx < len(ordered_snaps):
            snap = ordered_snaps[idx]
            tol = 0 if snap.get("exchange_ts_ms") else _LEGACY_SNAPSHOT_SKEW_MS
            if snapshot_ms(snap) - tol > clock:
                break
            idx += 1
            yield "snapshot", snap
        yield "event", event
