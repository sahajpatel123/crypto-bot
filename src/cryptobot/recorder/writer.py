"""Durable single-writer event recorder (F3 data engine).

One writer thread drains a large bounded queue into hourly JSONL chunk files.
Chunks are gzipped on rotation, fsync'd in batches, and sealed with a
per-chunk SHA-256 inside a hash-chained manifest (tamper-evident).

Overflow policy: the queue NEVER drops silently. A full queue increments the
``dropped`` counter, emits a warning log, and flags the current hour interval
as GAPPED in the manifest entry for that chunk.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "DurableWriter",
    "verify_manifest_chain",
    "GENESIS_HASH",
    "CHUNK_TIME_FORMAT",
    "CHUNKS_DIR_NAME",
    "MANIFEST_NAME",
]

GENESIS_HASH = "0" * 64
CHUNK_TIME_FORMAT = "%Y%m%dT%H"
CHUNKS_DIR_NAME = "chunks"
MANIFEST_NAME = "manifest.jsonl"

logger = logging.getLogger(__name__)


def _hour_str(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime(CHUNK_TIME_FORMAT)


def _canonical(entry: dict[str, Any]) -> str:
    body = {k: v for k, v in entry.items() if k != "entry_hash"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def verify_manifest_chain(manifest_path: str | Path, *, chunks_dir: str | Path | None = None) -> dict[str, Any]:
    """Verify a recorder manifest: chain linkage, entry hashes, and chunk SHAs.

    Returns ``{"ok": bool, "entries": int, "errors": [str]}``. ``ok`` is False
    when any chunk is missing/tampered, any entry hash mismatches, or the
    prev_hash chain breaks. Pure read-only check (no network).
    """
    manifest_path = Path(manifest_path)
    base = Path(chunks_dir) if chunks_dir is not None else manifest_path.parent / CHUNKS_DIR_NAME
    errors: list[str] = []
    entries = 0
    expected_prev = GENESIS_HASH
    if not manifest_path.exists():
        return {"ok": False, "entries": 0, "errors": [f"manifest not found: {manifest_path}"]}
    with manifest_path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            entries += 1
            try:
                entry = json.loads(line)
            except ValueError:
                errors.append(f"line {lineno}: not valid JSON")
                continue
            if entry.get("prev_hash") != expected_prev:
                errors.append(f"line {lineno}: prev_hash break (chunk={entry.get('chunk')})")
            recomputed = hashlib.sha256(_canonical(entry).encode("utf-8")).hexdigest()
            if entry.get("entry_hash") != recomputed:
                errors.append(f"line {lineno}: entry_hash mismatch (chunk={entry.get('chunk')})")
            else:
                expected_prev = entry["entry_hash"]
            chunk = base / str(entry.get("chunk", ""))
            want_sha = entry.get("sha256", "")
            if not chunk.exists():
                errors.append(f"line {lineno}: chunk missing: {entry.get('chunk')}")
                continue
            digest = hashlib.sha256()
            with chunk.open("rb") as cfh:
                for block in iter(lambda: cfh.read(1 << 20), b""):
                    digest.update(block)
            if digest.hexdigest() != want_sha:
                errors.append(f"line {lineno}: chunk SHA mismatch (tampered?): {entry.get('chunk')}")
    return {"ok": not errors, "entries": entries, "errors": errors}


class DurableWriter:
    """Single-threaded durable writer with a bounded input queue.

    Chunk naming: ``<SYMBOL>.<stream>.<YYYYMMDDTHH>.jsonl`` (``.gz`` after
    rotation). Rotation is driven by :meth:`rotate_if_needed`; call it
    periodically (e.g. every service loop iteration) with the current UTC time.
    """

    def __init__(
        self,
        run_dir: str | Path,
        *,
        queue_size: int = 100_000,
        fsync_every_n: int = 1000,
        fsync_every_s: float = 5.0,
    ) -> None:
        if queue_size <= 0:
            raise ValueError("queue_size must be positive")
        self._run_dir = Path(run_dir)
        self._chunks_dir = self._run_dir / CHUNKS_DIR_NAME
        self._manifest_path = self._run_dir / MANIFEST_NAME
        self._queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(maxsize=queue_size)
        self._fsync_every_n = max(1, int(fsync_every_n))
        self._fsync_every_s = float(fsync_every_s)
        self._lock = threading.Lock()
        now_hour = _hour_str(datetime.now(timezone.utc))
        self._current_hour = now_hour
        self._pending_hour = now_hour
        self._gapped: set[str] = set()
        self._dropped = 0
        self._counts: dict[str, int] = {}
        self._open: dict[tuple[str, str], dict[str, Any]] = {}
        self._prev_hash = GENESIS_HASH
        self._since_fsync = 0
        self._last_fsync = time.monotonic()
        self._thread: threading.Thread | None = None
        self._running = False
        self._closed = False
        self._thread_error: BaseException | None = None

    # -- properties ------------------------------------------------------
    @property
    def manifest_path(self) -> Path:
        return self._manifest_path

    @property
    def dropped(self) -> int:
        with self._lock:
            return self._dropped

    @property
    def counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    @property
    def gapped_intervals(self) -> list[str]:
        with self._lock:
            return sorted(self._gapped)

    @property
    def thread_error(self) -> BaseException | None:
        return self._thread_error

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        """Create the run layout and start the writer thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        if self._closed:
            raise RuntimeError("writer is closed")
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._chunks_dir.mkdir(parents=True, exist_ok=True)
        self._prev_hash = self._load_chain_tip()
        self._running = True
        self._thread = threading.Thread(target=self._run, name="recorder-writer", daemon=True)
        self._thread.start()

    def append(self, stream: str, event_dict: dict[str, Any]) -> bool:
        """Enqueue one event. Returns False (and counts a loud drop) when full."""
        if self._closed:
            with self._lock:
                self._dropped += 1
                self._gapped.add(self._current_hour)
            logger.warning("recorder append after close: dropped stream=%s", stream)
            return False
        try:
            self._queue.put_nowait((str(stream), dict(event_dict)))
            return True
        except queue.Full:
            with self._lock:
                self._dropped += 1
                hour = self._current_hour
                self._gapped.add(hour)
                dropped = self._dropped
            logger.warning(
                "recorder queue overflow: dropped stream=%s event "
                "(dropped=%d, hour=%s flagged GAPPED)",
                stream, dropped, hour,
            )
            return False

    def rotate_if_needed(self, now: datetime) -> None:
        """Request rotation to the hour bucket containing ``now`` (UTC)."""
        hour = _hour_str(now)
        with self._lock:
            self._pending_hour = hour

    def wait_idle(self, timeout_s: float = 5.0) -> bool:
        """Block until the queue is drained and any pending rotation applied."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._queue.unfinished_tasks == 0:
                with self._lock:
                    settled = self._pending_hour == self._current_hour
                if settled:
                    return True
            time.sleep(0.01)
        return False

    def close(self) -> None:
        """Drain, seal all chunks, fsync the manifest, and stop the thread."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if self._thread is None:
            # Never started: drain inline on the caller thread.
            self._run_dir.mkdir(parents=True, exist_ok=True)
            self._chunks_dir.mkdir(parents=True, exist_ok=True)
            self._prev_hash = self._load_chain_tip()
            self._drain_all()
            self._fsync_open()
            self._finalize_all()
            self._fsync_manifest()
            return
        self._running = False
        self._thread.join(timeout=60.0)

    # -- writer thread ---------------------------------------------------
    def _run(self) -> None:
        try:
            while self._running or not self._queue.empty():
                try:
                    item = self._queue.get(timeout=0.05)
                except queue.Empty:
                    self._maybe_rotate()
                    self._maybe_fsync_time()
                    continue
                try:
                    self._maybe_rotate()
                    stream, event = item
                    self._write_event(stream, event)
                finally:
                    self._queue.task_done()
            self._maybe_rotate()
            self._fsync_open()
            self._finalize_all()
            self._fsync_manifest()
        except BaseException as exc:  # loud: never die silently.
            self._thread_error = exc
            logger.exception("recorder writer thread failed: %r", exc)

    def _drain_all(self) -> None:
        while True:
            try:
                stream, event = self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                self._maybe_rotate()
                self._write_event(stream, event)
            finally:
                self._queue.task_done()

    def _maybe_rotate(self) -> None:
        with self._lock:
            pending, current = self._pending_hour, self._current_hour
        if pending != current:
            self._fsync_open()
            self._finalize_all()
            with self._lock:
                self._current_hour = self._pending_hour

    def _write_event(self, stream: str, event: dict[str, Any]) -> None:
        symbol = str(event.get("symbol", "all")).upper() or "ALL"
        key = (symbol, stream)
        slot = self._open.get(key)
        if slot is None:
            with self._lock:
                hour = self._current_hour
            path = self._chunks_dir / f"{symbol}.{stream}.{hour}.jsonl"
            fh = path.open("a", encoding="utf-8")
            slot = {"fh": fh, "path": path, "hour": hour, "events": 0}
            self._open[key] = slot
        slot["fh"].write(json.dumps(event) + "\n")
        slot["events"] += 1
        with self._lock:
            name = f"{symbol}.{stream}"
            self._counts[name] = self._counts.get(name, 0) + 1
        self._since_fsync += 1
        if self._since_fsync >= self._fsync_every_n:
            self._fsync_open()
            self._since_fsync = 0
            self._last_fsync = time.monotonic()
        else:
            self._maybe_fsync_time()

    def _maybe_fsync_time(self) -> None:
        if self._since_fsync > 0 and (time.monotonic() - self._last_fsync) >= self._fsync_every_s:
            self._fsync_open()
            self._since_fsync = 0
            self._last_fsync = time.monotonic()

    def _fsync_open(self) -> None:
        for slot in self._open.values():
            fh = slot["fh"]
            fh.flush()
            os.fsync(fh.fileno())

    def _finalize_all(self) -> None:
        if not self._open:
            return
        with self._manifest_path.open("a", encoding="utf-8") as manifest_fh:
            for (symbol, stream), slot in sorted(self._open.items()):
                fh, path = slot["fh"], slot["path"]
                fh.flush()
                fh.close()
                gz_path = path.with_suffix(path.suffix + ".gz")  # .jsonl -> .jsonl.gz
                with path.open("rb") as src, gzip.open(gz_path, "wb") as dst:
                    for block in iter(lambda: src.read(1 << 20), b""):
                        dst.write(block)
                digest = hashlib.sha256()
                with gz_path.open("rb") as cfh:
                    for block in iter(lambda: cfh.read(1 << 20), b""):
                        digest.update(block)
                path.unlink()
                with self._lock:
                    gapped = slot["hour"] in self._gapped
                entry = {
                    "chunk": gz_path.name,
                    "symbol": symbol,
                    "stream": stream,
                    "hour": slot["hour"],
                    "events": slot["events"],
                    "bytes": gz_path.stat().st_size,
                    "sha256": digest.hexdigest(),
                    "gapped": gapped,
                    "prev_hash": self._prev_hash,
                }
                entry["entry_hash"] = hashlib.sha256(_canonical(entry).encode("utf-8")).hexdigest()
                self._prev_hash = entry["entry_hash"]
                manifest_fh.write(json.dumps(entry) + "\n")
            manifest_fh.flush()
        self._open = {}

    def _fsync_manifest(self) -> None:
        if not self._manifest_path.exists():
            return
        with self._manifest_path.open("a", encoding="utf-8") as fh:
            fh.flush()
            os.fsync(fh.fileno())

    def _load_chain_tip(self) -> str:
        """Resume the hash chain from an existing manifest (fresh run_dir -> genesis)."""
        if not self._manifest_path.exists() or self._manifest_path.stat().st_size == 0:
            return GENESIS_HASH
        last = ""
        with self._manifest_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = line
        if not last:
            return GENESIS_HASH
        try:
            tip = json.loads(last).get("entry_hash", "")
        except ValueError as exc:
            raise ValueError(f"corrupt manifest tail in {self._manifest_path}") from exc
        if len(tip) != 64:
            raise ValueError(f"corrupt manifest tail in {self._manifest_path}")
        return tip
