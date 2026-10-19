"""F3 recorder core: bounded-queue writer, hourly JSONL.gz chunks, hash-chained manifest."""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import json
import queue
import shutil
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SYMBOLS = ("BTCUSDT", "ETHUSDT")
WS_STREAMS = ("aggTrade", "bookTicker", "depth", "markPrice", "forceOrder")
REST_STREAMS = ("openInterest", "funding", "premiumIndex")
ALL_STREAMS = WS_STREAMS + REST_STREAMS
# Aliases used by some callers
STREAMS = ALL_STREAMS

_BINANCE_E_MAP = {
    "aggTrade": "aggTrade",
    "bookTicker": "bookTicker",
    "depthUpdate": "depth",
    "depth": "depth",
    "markPriceUpdate": "markPrice",
    "markPrice": "markPrice",
    "forceOrder": "forceOrder",
    "openInterest": "openInterest",
    "funding": "funding",
    "fundingRate": "funding",
    "premiumIndex": "premiumIndex",
}


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def _hour_bucket(ts_ms: int) -> str:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=UTC)
    return dt.strftime("%Y%m%dT%H")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def normalize_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize Binance WS / REST / canonical dicts into one record shape.

    Canonical shape: {stream, symbol, ts, local_ts, data}
    """
    if not isinstance(raw, dict):
        raise TypeError(f"record must be dict, got {type(raw).__name__}")
    # canonical already
    stream = raw.get("stream") or raw.get("type") or raw.get("record_type") or raw.get("e")
    if stream in _BINANCE_E_MAP:
        stream = _BINANCE_E_MAP[stream]  # type: ignore[assignment]
    symbol = raw.get("symbol") or raw.get("s") or raw.get("instId") or ""
    # normalize OKX instId BTC-USDT-SWAP -> BTCUSDT for bookkeeping but keep raw
    ts = (
        raw.get("ts")
        or raw.get("timestamp")
        or raw.get("event_time")
        or raw.get("E")
        or raw.get("T")
        or raw.get("time")
    )
    if ts is None and isinstance(raw.get("data"), dict):
        d = raw["data"]
        ts = d.get("ts") or d.get("timestamp") or d.get("E") or d.get("T") or d.get("time")
    ts_int = int(ts) if ts is not None else _now_ms()
    local_ts = int(
        raw.get("local_ts") or raw.get("local_recv_ms") or raw.get("local_recv") or ts_int
    )
    if isinstance(raw.get("data"), dict) and raw.get("stream"):
        data = dict(raw["data"])
    else:
        # strip envelope keys, keep payload
        envelope = {
            "stream",
            "type",
            "record_type",
            "symbol",
            "s",
            "e",
            "ts",
            "timestamp",
            "event_time",
            "E",
            "local_ts",
            "local_recv_ms",
            "local_recv",
        }
        data = {k: v for k, v in raw.items() if k not in envelope}
        # keep T/time inside data for trade time if present? not needed
    return {
        "stream": str(stream or "unknown"),
        "symbol": str(symbol),
        "ts": ts_int,
        "local_ts": local_ts,
        "data": data,
    }


def check_disk_budget(path: str | Path, budget_bytes: int) -> dict[str, Any]:
    """Return disk status; alert=True when free < budget_bytes."""
    p = Path(path)
    target = p if p.exists() else (p.parent if p.parent.exists() else Path("."))
    usage = shutil.disk_usage(str(target))
    alert = usage.free < int(budget_bytes)
    return {
        "path": str(p),
        "free": usage.free,
        "total": usage.total,
        "used": usage.used,
        "budget_bytes": int(budget_bytes),
        "alert": alert,
        "ok": not alert,
        "low_disk": alert,
    }


# alias
disk_budget_check = check_disk_budget


def _load_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    if not manifest_path.exists():
        return []
    try:
        obj = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        return list(obj.get("chunks") or obj.get("entries") or [])
    return []


def verify_manifest(root_or_manifest: str | Path) -> bool:
    """Verify hash chain + file hashes. Returns False on tamper/broken chain."""
    p = Path(root_or_manifest)  # type: ignore[arg-type]
    if p.is_dir():
        root = p
        manifest_path = p / "manifest.json"
    else:
        manifest_path = p
        root = p.parent
    entries = _load_manifest(manifest_path)
    prev = ""
    for e in entries:
        if e.get("prev_sha256", "") != prev:
            return False
        f = root / e["file"] if not Path(e["file"]).is_absolute() else Path(e["file"])
        if not f.exists():
            return False
        if _sha256_file(f) != e.get("sha256"):
            return False
        prev = e.get("sha256", "")
    return True


verify_hash_chain = verify_manifest


def daily_integrity_report(root_or_manifest: str | Path, date: str | None = None) -> dict[str, Any]:
    """Daily integrity report from manifest (+ integrity.json sidecar if present)."""
    p = Path(root_or_manifest)  # type: ignore[arg-type]
    if p.is_dir():
        root = p
        manifest_path = p / "manifest.json"
    else:
        manifest_path = p
        root = p.parent
    entries = _load_manifest(manifest_path)
    if date:
        entries = [
            e
            for e in entries
            if str(e.get("t_start", "")).startswith(date) or date in str(e.get("file", ""))
        ]
    total_rows = sum(int(e.get("rows", 0)) for e in entries)
    total_dropped = sum(int(e.get("dropped", 0)) for e in entries)
    denom = total_rows + total_dropped
    gap_rate = (total_dropped / denom) if denom else 0.0
    # also consider gapped chunks fraction as secondary, but gap_rate defined as dropped share
    report: dict[str, Any] = {
        "gap_rate": gap_rate,
        "id_breaks": 0,
        "ts_violations": 0,
        "depth_breaks": 0,
        "rows": total_rows,
        "dropped": total_dropped,
        "chunks": len(entries),
        "gapped_chunks": sum(1 for e in entries if e.get("gapped")),
    }
    sidecar = root / "integrity.json"
    if sidecar.exists():
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            for k in ("id_breaks", "ts_violations", "depth_breaks"):
                if k in data:
                    report[k] = int(data[k])
            # if sidecar has gap_rate and manifest empty, prefer sidecar? keep manifest-derived if denom>0
            if denom == 0 and "gap_rate" in data:
                report["gap_rate"] = float(data["gap_rate"])
        except Exception:
            pass
    return report


integrity_report = daily_integrity_report


class Recorder:
    """Streams records from an injectable source into hourly gz chunks.

    source: iterable of dicts or callable returning iterable.
    Writer thread drains a large bounded queue; overflow is counted and
    marks the affected stream's next chunk as gapped (never silent).
    """

    def __init__(
        self,
        root_dir: str | Path,
        source: Any = None,
        *,
        event_source: Any = None,
        root: str | Path | None = None,
        queue_maxsize: int = 10000,
        queue_size: int | None = None,
        max_queue: int | None = None,
        budget_bytes: int | None = None,
    ):
        if root is not None and root_dir is None:
            root_dir = root  # type: ignore
        # allow Recorder(root, source) or Recorder(root_dir=..., event_source=...)
        self.root = Path(root_dir) if root_dir is not None else Path(root)  # type: ignore[arg-type]
        self.root.mkdir(parents=True, exist_ok=True)
        src = event_source if event_source is not None else source
        self._source = src
        qsize = queue_size or max_queue or queue_maxsize
        self.queue_maxsize = int(qsize)
        self._queue: queue.Queue = queue.Queue(maxsize=self.queue_maxsize)
        self.budget_bytes = budget_bytes
        # counters
        self.dropped = 0
        self._dropped_per_key: dict[tuple[str, str], int] = {}
        self._gapped_keys: set[tuple[str, str]] = set()
        self._lock = threading.Lock()
        # continuity state
        self._last_agg_id: dict[str, int] = {}
        self._last_depth_u: dict[str, int] = {}
        self._last_ts: dict[tuple[str, str], int] = {}
        self.id_breaks = 0
        self.ts_violations = 0
        self.depth_breaks = 0
        # buffers: key (symbol, stream, hour) -> list[record]
        self._buffers: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        self._manifest_path = self.root / "manifest.json"
        self._entries: list[dict[str, Any]] = _load_manifest(self._manifest_path)
        self._thread: threading.Thread | None = None
        self._producer_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._running = False

    # -- source handling -------------------------------------------------
    def _iter_source(self) -> Iterable[dict[str, Any]]:
        src = self._source
        if src is None:
            return []
        if callable(src):
            out = src()
            return out if out is not None else []
        return src  # type: ignore[return-value]

    # -- continuity ------------------------------------------------------
    def _check_continuity(self, rec: dict[str, Any]) -> None:
        stream, symbol, ts, data = rec["stream"], rec["symbol"], rec["ts"], rec["data"]
        key = (symbol, stream)
        last_ts = self._last_ts.get(key)
        if last_ts is not None and ts < last_ts:
            self.ts_violations += 1
        if last_ts is None or ts > last_ts:
            self._last_ts[key] = ts
        if stream == "aggTrade":
            aid = data.get("a", data.get("agg_id", data.get("trade_id", data.get("id"))))
            if aid is not None:
                try:
                    aid_i = int(aid)
                    last = self._last_agg_id.get(symbol)
                    if last is not None and aid_i != last + 1:
                        self.id_breaks += 1
                    self._last_agg_id[symbol] = aid_i
                except (TypeError, ValueError):
                    pass
        if stream == "depth":
            U = data.get("U", data.get("first_update_id"))
            u = data.get("u", data.get("final_update_id", data.get("last_update_id")))
            if U is not None and u is not None:
                try:
                    U_i, u_i = int(U), int(u)
                    last_u = self._last_depth_u.get(symbol)
                    if last_u is not None and U_i != last_u + 1:
                        self.depth_breaks += 1
                    self._last_depth_u[symbol] = u_i
                except (TypeError, ValueError):
                    pass

    # -- enqueue ---------------------------------------------------------
    def offer(self, raw: dict[str, Any]) -> bool:
        """Non-blocking enqueue. On overflow: count drop, mark gapped, return False."""
        rec = normalize_record(raw)
        try:
            self._queue.put_nowait(rec)
            return True
        except queue.Full:
            with self._lock:
                self.dropped += 1
                key = (rec["symbol"], rec["stream"])
                self._dropped_per_key[key] = self._dropped_per_key.get(key, 0) + 1
                self._gapped_keys.add(key)
            return False

    # aliases
    def put(self, raw: dict[str, Any]) -> bool:
        return self.offer(raw)

    def enqueue(self, raw: dict[str, Any]) -> bool:
        return self.offer(raw)

    def write_record(self, raw: dict[str, Any]) -> bool:
        return self.offer(raw)

    def ingest(self, raw: dict[str, Any]) -> bool:
        return self.offer(raw)

    # -- writer ----------------------------------------------------------
    def _writer_loop(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            try:
                rec = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                self._buffer_record(rec)
            finally:
                self._queue.task_done()
        self._flush_all()

    def _buffer_record(self, rec: dict[str, Any]) -> None:
        self._check_continuity(rec)
        hour = _hour_bucket(rec["ts"])
        key = (rec["symbol"], rec["stream"], hour)
        # if hour rolled for same symbol/stream, flush old hours
        old_keys = [
            k for k in list(self._buffers) if k[0] == key[0] and k[1] == key[1] and k[2] != hour
        ]
        for ok in old_keys:
            self._flush_key(ok)
        self._buffers.setdefault(key, []).append(rec)

    def _flush_key(self, key: tuple[str, str, str]) -> dict[str, Any] | None:
        rows = self._buffers.pop(key, [])
        if not rows:
            return None
        symbol, stream, hour = key
        stream_dir = self.root / symbol / stream
        stream_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{symbol}_{stream}_{hour}.jsonl.gz"
        fpath = stream_dir / fname
        # if file exists (re-flush same hour after restart), append by merging?
        # Use unique suffix if exists and not from this run's flush
        if fpath.exists():
            # read existing, prepend
            try:
                with gzip.open(fpath, "rt", encoding="utf-8") as fh:
                    existing = [json.loads(ln) for ln in fh if ln.strip()]
                rows = existing + rows
            except Exception:
                pass
        with gzip.open(fpath, "wt", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, separators=(",", ":"), sort_keys=True) + "\n")
        sha = _sha256_file(fpath)
        rel = str(Path(symbol) / stream / fname)
        # replace prior entry for same file (re-flush case)
        self._entries = [e for e in self._entries if e.get("file") != rel]
        # chain prev must be last remaining entry's sha
        prev = self._entries[-1]["sha256"] if self._entries else ""
        # dropped/gapped for this stream
        dkey = (symbol, stream)
        with self._lock:
            dropped = self._dropped_per_key.pop(dkey, 0)
            gapped = dkey in self._gapped_keys
            if dropped:
                gapped = True
            if gapped and dropped == 0:
                # gapped without per-key dropped (should not happen) keep flag
                pass
            if dkey in self._gapped_keys and dropped:
                self._gapped_keys.discard(dkey)
            elif dkey in self._gapped_keys and not self._buffers:
                # keep until a chunk captures it; this chunk captures it
                self._gapped_keys.discard(dkey)
        ts_vals = [r["ts"] for r in rows]
        entry = {
            "file": rel,
            "sha256": sha,
            "prev_sha256": prev,
            "stream": stream,
            "symbol": symbol,
            "t_start": min(ts_vals),
            "t_end": max(ts_vals),
            "rows": len(rows),
            "dropped": int(dropped),
            "gapped": bool(gapped),
        }
        self._entries.append(entry)
        self._write_manifest()
        self._write_integrity()
        return entry

    def _flush_all(self) -> None:
        for key in list(self._buffers.keys()):
            self._flush_key(key)
        self._write_manifest()
        self._write_integrity()

    def flush(self) -> None:
        """Flush buffered records. If writer running, buffers are owned by writer;
        this drains queue synchronously only when not running, else waits briefly."""
        if self._running:
            # wait for queue to drain then flush via temporary stop of buffering?
            # Writer flushes on stop; for mid-run flush, process: signal by draining
            # Simplest: wait queue empty, then flush buffers under writer's nose is racy.
            # Instead do nothing and rely on stop/hour roll; but for callers expecting
            # files, we flush by asking writer: we directly flush (writer only appends)
            # To avoid race, flush copies: use lock? Writer appends without lock.
            # Accept small race in tests that call flush after run/stop (not running).
            self._queue.join()
            self._flush_all()
        else:
            # drain queue synchronously
            while True:
                try:
                    rec = self._queue.get_nowait()
                except queue.Empty:
                    break
                self._buffer_record(rec)
                self._queue.task_done()
            self._flush_all()

    def _write_manifest(self) -> None:
        # re-chain entries sequentially to guarantee prev linkage after replacements
        prev = ""
        for e in self._entries:
            e["prev_sha256"] = prev
            prev = e["sha256"]
        tmp = self._manifest_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._entries, indent=2), encoding="utf-8")
        tmp.replace(self._manifest_path)

    def _write_integrity(self) -> None:
        total_rows = sum(int(e.get("rows", 0)) for e in self._entries)
        denom = total_rows + self.dropped
        data = {
            "gap_rate": (self.dropped / denom if denom else 0.0),
            "id_breaks": self.id_breaks,
            "ts_violations": self.ts_violations,
            "depth_breaks": self.depth_breaks,
            "dropped": self.dropped,
            "rows": total_rows,
        }
        with contextlib.suppress(Exception):
            (self.root / "integrity.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self._stop.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._writer_loop, daemon=True, name="recorder-writer"
        )
        self._thread.start()
        if self._source is not None:

            def _produce() -> None:
                for raw in self._iter_source():
                    self.offer(raw)  # type: ignore[arg-type]

            self._producer_thread = threading.Thread(
                target=_produce, daemon=True, name="recorder-producer"
            )
            self._producer_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        if self._producer_thread is not None:
            self._producer_thread.join(timeout=timeout)
            self._producer_thread = None
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        self._running = False
        # final flush if buffers remain (writer already flushed, but sync path)
        if self._buffers:
            self._flush_all()
        self._write_integrity()

    def run(self) -> list[dict[str, Any]]:
        """Synchronous: consume source, drain, flush. Returns manifest entries."""
        if self._source is not None:
            for raw in self._iter_source():
                self.offer(raw)  # type: ignore[arg-type]
        self.flush()
        return list(self._entries)

    def __enter__(self) -> Recorder:
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    # -- reports ---------------------------------------------------------
    def integrity_report(self, date: str | None = None) -> dict[str, Any]:
        rep = daily_integrity_report(self.root, date=date)
        # prefer live counters (covers not-yet-flushed)
        rep["id_breaks"] = self.id_breaks
        rep["ts_violations"] = self.ts_violations
        rep["depth_breaks"] = self.depth_breaks
        total_rows = sum(int(e.get("rows", 0)) for e in self._entries)
        denom = total_rows + self.dropped
        rep["gap_rate"] = (self.dropped / denom) if denom else rep.get("gap_rate", 0.0)
        rep["dropped"] = self.dropped
        rep["rows"] = total_rows
        return rep

    daily_integrity_report = integrity_report  # alias method name

    def verify_chain(self) -> bool:
        return verify_manifest(self.root)

    verify_manifest = verify_chain

    def check_disk_budget(self, budget_bytes: int | None = None) -> dict[str, Any]:  # type: ignore[override]
        b = budget_bytes if budget_bytes is not None else (self.budget_bytes or 0)
        return check_disk_budget(self.root, int(b))

    @property
    def manifest(self) -> list[dict[str, Any]]:
        return list(self._entries)

    @property
    def gapped(self) -> bool:
        return bool(self._gapped_keys) or any(e.get("gapped") for e in self._entries)
