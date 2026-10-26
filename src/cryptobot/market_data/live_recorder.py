"""Standalone public-market recorder (F3).

This process is deliberately independent of the trading process: it may
keep recording while the bot is stopped, restarted or armed. It captures
Binance USD-M public streams for the configured symbols:

  trade (aggregated per second), bookTicker, depth@100ms
  -- the names this endpoint delivers; aggTrade, markPrice@1s and
  forceOrder handshake and then stay silent (BINANCE_SILENT_STREAMS)
  plus REST polling for openInterest, premiumIndex, settled fundingRate
  (funding_rate_settled records, #49) and daily klines (kline_1d records
  for the point-in-time universe, #49), and periodic depth snapshots.

Optional Bybit/OKX linear-perp trade/top-of-book plugins exist behind
config flags for the H4 cross-venue hypothesis; they are metadata-only
until enabled by the owner.

Durability contract (F3.3):
  * writer thread with a large bounded queue; overflow is counted,
    logged, and flags the interval as GAPPED (never silently dropped);
  * batched fsync, hourly gzip chunk rotation;
  * every sealed chunk is SHA-256 hashed into a hash-chained manifest;
  * per-stream ID/sequence continuity is checked on ingest;
  * reconnect uses jittered backoff and re-syncs depth via REST;
  * disk budget monitor stops cleanly and alerts before the disk fills;
  * integrity report computes gap rate, trade-ID continuity,
    timestamp monotonicity and depth-chain breaks.

No credentials are used anywhere in this module. Network smoke runs must
be invoked separately with ``nice`` and a short duration; tests use
injected fakes.
"""
from __future__ import annotations

import contextlib
import gzip
import hashlib
import json
import os
import queue
import random
import re
import threading
import time
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FAPI_BASE = "https://fapi.binance.com"
BYBIT_WS = "wss://stream.bybit.com/v5/public/linear"
OKX_WS = "wss://ws.okx.com:8443/ws/v5/public"
FORMAT = "cryptobot-recorder/2"
SYNTHETIC = "SYNTHETIC"
OBSERVED = "observed-public"

# Streams the public fstream endpoint actually *delivers* to this host.
#
# Measured 2026-10-25 from the owner's Mac (DoH shim on, raw sockets, both
# /ws/<name> and /stream?streams=): `trade`, `bookTicker` and `depth@100ms`
# deliver frames; `aggTrade`, `markPrice@1s` and `forceOrder` complete the
# handshake and then send zero bytes for the whole window -- no close, no
# error, so a recorder subscribed to them loses the data silently. The
# recorder consequently held no trade print, no mark price and no
# liquidation for the entire 18 Oct -> 25 Oct run.
#
# `aggTrade` and `trade` carry the same economic content (price, qty, maker
# flag); `trade` is the name this endpoint serves, so it is the default.
# Mark price is still captured every 60 s by the REST premiumIndex poll.
BINANCE_STREAMS = ("trade", "bookTicker", "depth@100ms")
# Names that handshake but stay silent on the same path; still subscribable
# via RecorderConfig.streams for venues/hosts where they do deliver.
BINANCE_SILENT_STREAMS = ("aggTrade", "markPrice@1s", "forceOrder")

# Manifest stream token for settled-funding records. The record *type* is
# "funding_rate_settled" (a member of d1_eval.FUNDING_RECORD_TYPES, which the
# recorder must satisfy without touching the evaluator); the *stream* token is
# what lands in the manifest entry and fills the d1_eval "funding" bucket via
# classify_stream ("funding" in name).
FUNDING_STREAM_TOKEN = "funding_settlement"
# Binance USD-M settles funding at 00:00/08:00/16:00 UTC for standard symbols
# (some symbols use shorter intervals; those rows are still recorded, flagged
# off-grid, and never dropped).
SETTLE_GRID_MS = 8 * 3600 * 1000
# Daily klines are pulled after this UTC clock time, mirroring the forward
# booking cutoff: only then is yesterday's 1d bar guaranteed complete.
KLINE_PULL_CUTOFF_HM = (0, 5)
DAY_MS = 24 * 3600 * 1000
# One stream name is satisfied by the other: they carry the same content,
# so a request for either is served if records of the other arrive. This
# mapping is applied to the stream name only, never to the whole symbol --
# a live trade stream must not exempt a dead depth@100ms on the same
# symbol, or the silence alert below would be unreachable in the one case
# it exists to catch.
_STREAM_ALIASES = {"trade": "aggTrade", "aggTrade": "trade"}
# A single-stream connection (/ws/<name>) has no stream field, so its
# records are named by bare event type. Recognise those instead of
# alerting on every chunk -- but only for the one-symbol, one-stream shape
# such a connection exists in, because a bare token is symbol-agnostic and
# would otherwise let one symbol silence the rest (see _silent_streams).
_BARE_EVENT_NAMES = {
    "trade": ("trade",),
    "aggTrade": ("aggTrade",),
    "bookTicker": ("bookTicker",),
    "depth@100ms": ("depth", "depthUpdate"),
    "depth": ("depth", "depthUpdate"),
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _atomic_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


_CHUNK_FILE_RE = re.compile(r"^rec-\d{6}-\d{8}T\d{6}Z\.jsonl\.gz$")


def quarantine_orphans(chunk_dir: Path, manifest: ManifestChain) -> list[str]:
    """Rename unsealed chunk files so no sequence number is ever reused.

    On 2026-10-25 four crash-loop restarts each orphaned one partial chunk
    (seqs 396/401/404/449/458 exist twice on disk; the manifest references
    only the fuller twin) because a fresh process recomputes its next index
    as ``len(manifest entries)``. Any ``rec-*.jsonl.gz`` file the manifest
    does not reference is therefore renamed to ``orphan-<name>`` at startup,
    before the writer thread opens anything. Returns the quarantined names.
    Sealed chunks are never touched: only unreferenced files move.
    """
    referenced = set()
    for entry in manifest.doc.get("entries", []):
        try:
            referenced.add(Path(entry["chunk"]).name)
        except (KeyError, TypeError):
            continue
    moved: list[str] = []
    if not chunk_dir.is_dir():
        return moved
    for path in sorted(chunk_dir.iterdir()):
        name = path.name
        if name.startswith("orphan-") or not _CHUNK_FILE_RE.match(name):
            continue
        if name in referenced:
            continue
        target = chunk_dir / f"orphan-{name}"
        if target.exists():
            continue  # never overwrite an earlier quarantine
        os.replace(path, target)
        moved.append(name)
    return moved


class ManifestChain:
    """SHA-256 hash-chained registry of sealed chunks (F3.5 seed).

    Each entry commits to the previous entry hash. Any byte edit to an
    earlier entry breaks every later link; ``verify`` reports the first
    broken index. This is the recorder-side half of the vault registry;
    ``cryptobot.data.vault`` verifies and imports it.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if self.path.exists():
            self.doc = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.doc = {"format": "cryptobot-chunk-manifest/1",
                        "chain_head": "genesis", "entries": [],
                        "created_utc": _utc_now(), "input_class": OBSERVED}
            _atomic_json(self.path, self.doc)

    def seal(self, chunk_path: Path, *, first_ms: int, last_ms: int,
             records: int, streams: list[str], gaps: int = 0,
             venue: str = "binance-usdm", symbol: str = "*",
             data_class: str = "DEV") -> dict:
        entry = {
            "chunk": str(chunk_path.relative_to(self.path.parent)),
            "sha256": _sha256_file(chunk_path),
            "bytes": chunk_path.stat().st_size,
            "first_ms": int(first_ms), "last_ms": int(last_ms),
            "records": int(records), "streams": sorted(set(streams)),
            "gaps": int(gaps), "venue": venue, "symbol": symbol,
            "class": data_class, "sealed_utc": _utc_now(),
            "prev": self.doc["chain_head"],
        }
        entry["entry_hash"] = hashlib.sha256(
            json.dumps(entry, sort_keys=True).encode()).hexdigest()
        self.doc["entries"].append(entry)
        self.doc["chain_head"] = entry["entry_hash"]
        self.doc["updated_utc"] = _utc_now()
        _atomic_json(self.path, self.doc)
        return entry

    def verify(self) -> list[str]:
        problems: list[str] = []
        prev = "genesis"
        for i, entry in enumerate(self.doc.get("entries", [])):
            if entry.get("prev") != prev:
                problems.append(f"entry {i}: prev mismatch")
            body = {k: v for k, v in entry.items() if k != "entry_hash"}
            digest = hashlib.sha256(
                json.dumps(body, sort_keys=True).encode()).hexdigest()
            if digest != entry.get("entry_hash"):
                problems.append(f"entry {i}: hash mismatch")
            prev = entry.get("entry_hash")
        if prev != self.doc.get("chain_head"):
            problems.append("chain_head does not match last entry")
        return problems


@dataclass
class RecorderConfig:
    out_dir: str = "data/recorder"
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")
    venues: tuple[str, ...] = ("binance",)
    chunk_seconds: int = 3600
    queue_max: int = 200_000
    fsync_every: int = 2000
    disk_budget_mb: int = 50_000
    depth_snapshot_s: int = 60
    rest_poll_s: int = 60
    reconnect_max_s: float = 30.0
    input_class: str = OBSERVED
    stop_file: str | None = None
    # Empty means BINANCE_STREAMS. Set it to request other stream names.
    streams: tuple[str, ...] = ()
    # Aggregate trade prints into per-second order-flow buckets; 0 keeps
    # raw prints (which do not fit the disk budget -- see DECISIONS.md).
    trade_aggregate_s: int = 1
    # Settled-funding sweep cadence (#49 P1). Settlements land every 8 h, so
    # a 15-minute sweep catches all of them with cheap REST traffic.
    funding_poll_s: int = 900
    # Daily-kline universe (#49 P2). Empty means the FULL live listing:
    # every TRADING USDT-margined perpetual from /fapi/v1/exchangeInfo,
    # re-discovered daily. A non-empty tuple pins an explicit symbol list
    # instead -- every kline_1d record then carries universe_source
    # "explicit" plus the list size, so a narrowed universe can never pass
    # silently as the frozen-universe input D1 ranks.
    kline_symbols: tuple[str, ...] = ()
    # Time-based heartbeat cadence (#49 P4). The old every-200-records
    # heartbeat froze whenever chunks held <200 records (the 2026-10-25
    # tail), faking staleness while the writer was alive.
    heartbeat_s: int = 15
    # A websocket frame newer than this keeps the heartbeat's ws_alive true.
    ws_alive_s: int = 120

    def __post_init__(self) -> None:
        if self.input_class not in (OBSERVED, SYNTHETIC):
            raise ValueError("input_class must be observed-public or SYNTHETIC")
        if not self.streams:
            self.streams = BINANCE_STREAMS
        if self.trade_aggregate_s < 0:
            raise ValueError("trade_aggregate_s must be >= 0")
        if self.queue_max < 1:
            raise ValueError("queue_max must be positive")
        if self.chunk_seconds < 1:
            raise ValueError("chunk_seconds must be positive")
        if self.funding_poll_s < 60:
            raise ValueError("funding_poll_s must be >= 60")
        if self.heartbeat_s < 1:
            raise ValueError("heartbeat_s must be positive")
        if self.ws_alive_s < 1:
            raise ValueError("ws_alive_s must be positive")
        self.kline_symbols = tuple(s.strip().upper() for s in self.kline_symbols
                                   if s.strip())


@dataclass
class StreamContinuity:
    last_trade_id: int | None = None
    last_update_id: int | None = None
    last_event_ms: int | None = None
    trade_gaps: int = 0
    depth_breaks: int = 0
    out_of_order: int = 0

    def observe_trade(self, trade_id: int) -> bool:
        ok = True
        if self.last_trade_id is not None and trade_id != self.last_trade_id + 1:
            self.trade_gaps += 1
            ok = False
        self.last_trade_id = trade_id
        return ok

    def observe_depth(self, first: int, final: int, prev_final: int | None) -> bool:
        ok = True
        if prev_final is not None and first > prev_final + 1:
            self.depth_breaks += 1
            ok = False
        self.last_update_id = final
        return ok

    def observe_time(self, ms: int) -> bool:
        ok = True
        if self.last_event_ms is not None and ms < self.last_event_ms:
            self.out_of_order += 1
            ok = False
        self.last_event_ms = ms
        return ok


class RecorderWriter:
    """Bounded queue + writer thread + hourly gzip chunk rotation."""

    def __init__(self, config: RecorderConfig, *,
                 manifest: ManifestChain | None = None,
                 now: Callable[[], float] = time.time) -> None:
        self.config = config
        self.root = Path(config.out_dir)
        self.chunk_dir = self.root / "chunks"
        self.chunk_dir.mkdir(parents=True, exist_ok=True)
        self.manifest = manifest or ManifestChain(
            self.root / "manifest.json")
        self.queue: queue.Queue = queue.Queue(maxsize=config.queue_max)
        self.dropped = 0
        self.gapped = False
        self.records = 0
        self.records_total = 0
        self.sealed: list[dict] = []
        self.alerts: list[dict] = []
        self.fatal_error: BaseException | None = None
        self._now = now
        self._streams: set[str] = set()
        self._chunk_start_ms = int(now() * 1000)
        self._chunk_index = len(self.manifest.doc.get("entries", []))
        self._last_heartbeat = 0.0
        self._last_ws_ms: int | None = None
        # Quarantine BEFORE the writer thread opens anything: any chunk file
        # the manifest does not reference (crash orphan, unsealed tail) is
        # renamed to orphan-* so its sequence number is never reused.
        for name in quarantine_orphans(self.chunk_dir, self.manifest):
            self._alert("orphan-quarantined", {"chunk": name})
        self._fh = None
        self._gz = None
        self._raw_path: Path | None = None
        self._since_fsync = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="recorder-writer",
                                        daemon=True)
        self._thread.start()

    # -- ingestion ---------------------------------------------------------
    def submit(self, record: dict[str, Any]) -> bool:
        try:
            self.queue.put_nowait(record)
            return True
        except queue.Full:
            self.dropped += 1
            self.gapped = True
            self._alert("writer-queue-full", {
                "dropped": self.dropped,
                "queue_max": self.config.queue_max})
            return False

    def _alert(self, kind: str, detail: dict) -> None:
        self.alerts.append({"kind": kind, "ts_utc": _utc_now(), **detail})
        # Alerts are also persisted in the integrity report; keep memory bounded.
        if len(self.alerts) > 1000:
            del self.alerts[:500]

    def note_ws_activity(self, event_ms: int | None = None) -> None:
        """Mark a websocket frame arrival (drives the heartbeat ws_alive)."""
        try:
            self._last_ws_ms = int(event_ms) if event_ms is not None else int(
                self._now() * 1000)
        except (TypeError, ValueError):
            self._last_ws_ms = int(self._now() * 1000)

    def _fatal(self, exc: BaseException, where: str) -> None:
        """Record a fatal writer error LOUDLY and stop the writer thread.

        The 2026-10-25 ENOSPC died inside this thread with only a stderr
        traceback; the process limped on. Now the first OSError anywhere in
        the write path (chunk bytes, seal, heartbeat) is alerted, stops the
        writer, and is re-raised from close() so the process exits nonzero.
        Restart pacing stays where it belongs: launchd ThrottleInterval plus
        the guard's restart margin, both already deployed.
        """
        if self.fatal_error is None:
            self.fatal_error = exc
            self._alert("writer-fatal", {
                "where": where, "error": f"{type(exc).__name__}: {exc}"})
        # Best-effort close: the partial chunk stays unsealed (never added
        # to the manifest) but structurally valid, and the next startup
        # quarantines it instead of reusing its sequence number.
        for handle in (self._gz, self._fh):
            with contextlib.suppress(Exception):
                if handle is not None:
                    handle.close()
        self._gz = None
        self._fh = None
        self._stop.set()

    # -- chunk lifecycle ---------------------------------------------------
    def _open_chunk(self) -> None:
        self._chunk_start_ms = int(self._now() * 1000)
        stamp = datetime.fromtimestamp(
            self._chunk_start_ms / 1000, tz=UTC).strftime(
                "%Y%m%dT%H%M%SZ")
        self._raw_path = self.chunk_dir / (
            f"rec-{self._chunk_index:06d}-{stamp}.jsonl.gz")
        raw = self._raw_path.open("wb")
        self._fh = raw
        self._gz = gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6)
        # event_ms is required: d1_eval.read_records refuses any record
        # without an integer event_ms (it must prove the record is outside
        # the sealed holdout), headers included.
        header = {"type": "header", "format": FORMAT,
                  "input_class": self.config.input_class,
                  "symbols": list(self.config.symbols),
                  "venues": list(self.config.venues),
                  "started_utc": _utc_now(), "chunk": self._chunk_index,
                  "event_ms": self._chunk_start_ms}
        self._write(header)

    def _write(self, record: dict[str, Any]) -> None:
        assert self._gz is not None
        self._gz.write((json.dumps(record, sort_keys=True) + "\n").encode())
        self.records += 1
        self.records_total += 1
        self._since_fsync += 1
        now_s = self._now()
        if now_s - self._last_heartbeat >= self.config.heartbeat_s \
                and self._raw_path is not None:
            self._write_heartbeat(now_s)
        period = now_s - self._chunk_start_ms / 1000.0
        if period >= self.config.chunk_seconds:
            self._rotate()

    def _write_heartbeat(self, now_s: float) -> None:
        assert self._raw_path is not None
        now_ms = int(now_s * 1000)
        idle_ms = (now_ms - self._last_ws_ms
                   if self._last_ws_ms is not None else None)
        self._fsync()
        _atomic_json(self.root / "heartbeat.json", {
            "ts_utc": _utc_now(),
            "state": "running",
            "records": self.records,
            "records_total": self.records_total,
            "chunk": self._raw_path.name,
            "bytes": self._raw_path.stat().st_size,
            "ws_alive": idle_ms is not None
            and idle_ms <= self.config.ws_alive_s * 1000,
            "ws_idle_s": (round(idle_ms / 1000.0, 1)
                          if idle_ms is not None else None),
        })
        self._last_heartbeat = now_s

    def _fsync(self) -> None:
        if self._gz is not None:
            self._gz.flush()
        if self._fh is not None:
            self._fh.flush()
            os.fsync(self._fh.fileno())
        self._since_fsync = 0

    def _silent_streams(self, entry: dict) -> list[str]:
        """Requested binance streams with no record in this chunk."""
        expected: set[str] = set()
        if "binance" in self.config.venues:
            for symbol in self.config.symbols:
                for stream in self.config.streams:
                    expected.add(f"{symbol.lower()}@{stream}")
        seen = set(entry.get("streams", []))
        # A bare name can only arrive from a /ws/<name> connection, which is
        # only ever opened for one symbol and one stream. Accepting bare
        # names on a full run would make a symbol-agnostic token satisfy
        # every symbol's stream of that type, masking a dead one.
        bare_ok = (len(self.config.symbols) == 1
                   and len(self.config.streams) == 1)
        missing = []
        for name in expected:
            if name in seen:
                continue
            symbol, _, stream = name.partition("@")
            alias = _STREAM_ALIASES.get(stream)
            if alias is not None and f"{symbol}@{alias}" in seen:
                continue
            if bare_ok and any(token in seen
                               for token in _BARE_EVENT_NAMES.get(stream, ())):
                continue
            missing.append(name)
        return sorted(missing)

    def _rotate(self) -> None:
        if self._gz is None or self._raw_path is None:
            return
        self._fsync()
        self._gz.close()
        self._fh.close()
        entry = self.manifest.seal(
            self._raw_path, first_ms=self._chunk_start_ms,
            last_ms=int(self._now() * 1000), records=self.records,
            streams=sorted(self._streams), gaps=1 if self.gapped else 0)
        silent = self._silent_streams(entry)
        if silent:
            # A stream we subscribed to produced nothing this chunk. The
            # endpoint closes the handshake and then stays quiet, so this is
            # the only signal that data is being lost.
            self._alert("stream-silent", {"chunk": entry["chunk"],
                                          "streams": silent})
        self.sealed.append(entry)
        self.records = 0
        self._streams = set()
        self.gapped = False
        self._chunk_index += 1
        self._open_chunk()

    def _run(self) -> None:
        try:
            self._open_chunk()
        except OSError as exc:
            self._fatal(exc, "open-chunk")
            return
        while not self._stop.is_set() or not self.queue.empty():
            try:
                record = self.queue.get(timeout=0.2)
            except queue.Empty:
                if self._since_fsync:
                    try:
                        self._fsync()
                    except OSError as exc:
                        self._fatal(exc, "idle-fsync")
                        return
                continue
            if record is None:
                break
            self._streams.add(str(record.get("stream", record.get("type", "?"))))
            try:
                if self.gapped:
                    self._write({"type": "gap", "ts_utc": _utc_now(),
                                 "event_ms": int(self._now() * 1000),
                                 "dropped_before": self.dropped,
                                 "note": "writer queue overflow; interval gapped"})
                self._write(record)
            except OSError as exc:
                # Disk gone (the 2026-10-25 ENOSPC): stop loudly instead of
                # dying quietly in this thread. The half-written chunk stays
                # unsealed; the next startup quarantines it (see above).
                self._fatal(exc, "write")
                return
            if self._since_fsync >= self.config.fsync_every:
                try:
                    self._fsync()
                except OSError as exc:
                    self._fatal(exc, "fsync")
                    return
        if self._gz is not None and self._raw_path is not None \
                and self.fatal_error is None:
            try:
                self._rotate()
            except OSError as exc:
                self._fatal(exc, "final-seal")

    def close(self, timeout_s: float = 30.0) -> list[dict]:
        self._stop.set()
        with contextlib.suppress(queue.Full):
            self.queue.put_nowait(None)
        self._thread.join(timeout=timeout_s)
        if self.fatal_error is not None:
            raise self.fatal_error
        return self.sealed


def _disk_free_mb(path: Path) -> float:
    usage = os.statvfs(path)
    return usage.f_bavail * usage.f_frsize / 1e6


def check_disk_budget(config: RecorderConfig, *,
                      free_mb: float | None = None) -> dict:
    root = Path(config.out_dir)
    root.mkdir(parents=True, exist_ok=True)
    free = _disk_free_mb(root) if free_mb is None else float(free_mb)
    ok = free >= 0 and (config.disk_budget_mb <= 0
                        or free >= config.disk_budget_mb)
    return {"ok": ok, "free_mb": free,
            "budget_mb": config.disk_budget_mb}


def classify_message(venue: str, payload: dict[str, Any]) -> list[dict]:
    """Normalize one venue websocket message into zero or more records.

    Binance combined-stream payloads are ``{"stream": ..., "data": ...}``.
    Bybit/OKX plugins are intentionally conservative: only trade/ticker
    shapes are recognized; unknown messages are recorded as raw metadata.
    """
    if venue == "binance":
        data = payload.get("data", payload)
        stream = payload.get("stream", str(data.get("e", "unknown")))
        out = []
        e = data.get("e")
        if e in ("trade", "aggTrade"):
            # `trade` (raw stream) carries the id in `t`; `aggTrade` in `a`.
            out.append({"type": "trade", "stream": stream, "venue": venue,
                        "symbol": data.get("s"),
                        "trade_id": data.get("a", data.get("t")),
                        "price": data.get("p"), "qty": data.get("q"),
                        "event_ms": data.get("E"), "trade_ms": data.get("T"),
                        "maker": data.get("m")})
        elif e == "bookTicker":
            out.append({"type": "book_ticker", "stream": stream,
                        "venue": venue, "symbol": data.get("s"),
                        "bid": data.get("b"), "bid_qty": data.get("B"),
                        "ask": data.get("a"), "ask_qty": data.get("A"),
                        "update_id": data.get("u"), "event_ms": data.get("E")})
        elif e == "depthUpdate":
            out.append({"type": "depth", "stream": stream, "venue": venue,
                        "symbol": data.get("s"), "first_id": data.get("U"),
                        "final_id": data.get("u"), "prev_final_id": data.get("pu"),
                        "bids": data.get("b"), "asks": data.get("a"),
                        "event_ms": data.get("E")})
        elif e == "markPriceUpdate":
            out.append({"type": "mark", "stream": stream, "venue": venue,
                        "symbol": data.get("s"), "mark": data.get("p"),
                        "index": data.get("i"), "funding": data.get("r"),
                        "next_funding_ms": data.get("T"),
                        "event_ms": data.get("E")})
        elif e == "forceOrder":
            out.append({"type": "liquidation", "stream": stream,
                        "venue": venue,
                        **({"symbol": data.get("o", {}).get("s"),
                            "side": data.get("o", {}).get("S"),
                            "price": data.get("o", {}).get("p"),
                            "qty": data.get("o", {}).get("q"),
                            "event_ms": data.get("E")})})
        else:
            out.append({"type": "raw", "stream": stream, "venue": venue,
                        "event_ms": data.get("E"), "payload": data})
        return out
    # --- optional linear-perp plugins (H4 lead-lag) ---------------------
    if venue == "bybit":
        topic = str(payload.get("topic", ""))
        data = payload.get("data")
        rows = data if isinstance(data, list) else [data]
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if topic.startswith("publicTrade"):
                out.append({"type": "trade", "stream": topic, "venue": venue,
                            "symbol": row.get("s"), "trade_id": row.get("i"),
                            "price": row.get("p"), "qty": row.get("v"),
                            "side": row.get("S"), "event_ms": row.get("T")})
            elif topic.startswith("tickers"):
                out.append({"type": "book_ticker", "stream": topic,
                            "venue": venue, "symbol": row.get("symbol"),
                            "bid": row.get("bid1Price"),
                            "bid_qty": row.get("bid1Size"),
                            "ask": row.get("ask1Price"),
                            "ask_qty": row.get("ask1Size"),
                            "event_ms": row.get("ts")})
        return out
    if venue == "okx":
        arg = payload.get("arg", {})
        data = payload.get("data", [])
        out = []
        for row in data if isinstance(data, list) else []:
            if not isinstance(row, dict):
                continue
            if arg.get("channel") == "trades":
                out.append({"type": "trade", "stream": "trades",
                            "venue": venue, "symbol": row.get("instId"),
                            "trade_id": row.get("tradeId"),
                            "price": row.get("px"), "qty": row.get("sz"),
                            "side": row.get("side"), "event_ms": row.get("ts")})
            elif arg.get("channel") == "tickers":
                out.append({"type": "book_ticker", "stream": "tickers",
                            "venue": venue, "symbol": row.get("instId"),
                            "bid": row.get("bidPx"), "bid_qty": row.get("bidSz"),
                            "ask": row.get("askPx"), "ask_qty": row.get("askSz"),
                            "event_ms": row.get("ts")})
        return out
    return [{"type": "raw", "venue": venue, "payload": payload}]


def venue_stream_url(venue: str, symbols: Iterable[str],
                     streams: Iterable[str] = BINANCE_STREAMS) -> str:
    syms = [s.lower() for s in symbols]
    if venue == "binance":
        jobs = "/".join(f"{s}@{k}" for s in syms for k in streams)
        return f"wss://fstream.binance.com/stream?streams={jobs}"
    if venue == "bybit":
        return BYBIT_WS  # subscription is sent after connect
    if venue == "okx":
        return OKX_WS
    raise ValueError(f"unknown venue {venue!r}")


def subscription_messages(venue: str, symbols: Iterable[str]) -> list[str]:
    if venue == "bybit":
        args = [f"publicTrade.{s}" for s in symbols] + \
               [f"tickers.{s}" for s in symbols]
        return [json.dumps({"op": "subscribe", "args": args})]
    if venue == "okx":
        args = [{"channel": "trades", "instId": f"{s[:-4]}-USDT-SWAP"}
                for s in symbols if s.endswith("USDT")]
        args += [{"channel": "tickers", "instId": f"{s[:-4]}-USDT-SWAP"}
                 for s in symbols if s.endswith("USDT")]
        return [json.dumps({"op": "subscribe", "args": args})]
    return []


def integrity_report(root: str | Path) -> dict:
    """Daily integrity report over the recorder's manifest + chunks."""
    base = Path(root)
    manifest = ManifestChain(base / "manifest.json")
    problems = manifest.verify()
    entries = manifest.doc.get("entries", [])
    total_records = sum(int(e.get("records", 0)) for e in entries)
    total_gaps = sum(int(e.get("gaps", 0)) for e in entries)
    streams: dict[str, dict] = {}
    broken_chunks: list[str] = []
    for entry in entries:
        path = base / entry["chunk"]
        if not path.exists() or _sha256_file(path) != entry["sha256"]:
            broken_chunks.append(entry["chunk"])
            continue
        cont = StreamContinuity()
        last_depth: dict[str, int] = {}
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    broken_chunks.append(entry["chunk"] + ":bad-json")
                    continue
                stream = str(rec.get("stream", rec.get("type", "?")))
                stats = streams.setdefault(stream, {
                    "records": 0, "trade_gaps": 0, "depth_breaks": 0,
                    "out_of_order": 0})
                stats["records"] += 1
                ms = rec.get("event_ms")
                if isinstance(ms, int) and not cont.observe_time(ms):
                    stats["out_of_order"] += 1
                if rec.get("type") == "trade" and rec.get("trade_id") is not None:
                    try:
                        if not cont.observe_trade(int(rec["trade_id"])):
                            stats["trade_gaps"] += 1
                    except (TypeError, ValueError):
                        pass
                if rec.get("type") == "depth":
                    symbol = str(rec.get("symbol"))
                    prev = last_depth.get(symbol)
                    try:
                        if not cont.observe_depth(int(rec["first_id"]),
                                                  int(rec["final_id"]), prev):
                            stats["depth_breaks"] += 1
                        last_depth[symbol] = int(rec["final_id"])
                    except (TypeError, ValueError):
                        stats["depth_breaks"] += 1
    gap_rate = (total_gaps / total_records) if total_records else 0.0
    return {
        "report": "recorder-integrity/1", "generated_utc": _utc_now(),
        "chunks": len(entries), "records": total_records,
        "gaps": total_gaps, "gap_rate": gap_rate,
        "manifest_problems": problems, "broken_chunks": broken_chunks,
        "streams": streams,
        "ok": not problems and not broken_chunks,
    }


class Recorder:
    """Supervised recorder loop (one websocket per venue + REST poller)."""

    def __init__(self, config: RecorderConfig, *,
                 connect: Callable[[str], Any] | None = None,
                 rest_get: Callable[[str, float], tuple[Any, float]] | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.config = config
        self.root = Path(config.out_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self._connect = connect or self._default_connect
        self._rest_get = rest_get or _urllib_json
        self._sleep = sleep
        self.writer = RecorderWriter(config)
        self.continuity: dict[str, StreamContinuity] = {}
        self._buckets: dict[tuple[str, str, int], dict] = {}
        self._stop = threading.Event()
        self._rest_thread: threading.Thread | None = None
        self._boot_ms = int(time.time() * 1000)
        # High-water marks: last settled fundingTime emitted per symbol.
        # Persisted so a restart re-emits downtime settlements exactly once;
        # a cold start seeds the mark at boot (pre-boot history is skipped --
        # emitting it could stamp records inside the sealed holdout window).
        self._funding_hw: dict[str, int] = {}
        self._off_grid_alerted: set[str] = set()
        self._universe_cache: tuple[str, list[str]] | None = None
        self._universe_fallback_alerted: str | None = None
        self._last_funding_sweep = 0.0
        try:
            state = json.loads((self.root / "funding_state.json").read_text(
                encoding="utf-8"))
            if isinstance(state, dict):
                self._funding_hw = {str(k): int(v)
                                    for k, v in state.items()
                                    if isinstance(v, int)}
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            self.writer._alert("funding-state-unreadable", {
                "error": f"{type(exc).__name__}: {exc}"})
        self.status = {"state": "starting", "started_utc": _utc_now(),
                       "symbols": list(config.symbols),
                       "venues": list(config.venues),
                       "input_class": config.input_class}

    @staticmethod
    def _default_connect(url: str) -> Any:
        from .ws import WsClient
        return WsClient.connect(url, timeout_s=10.0)

    def stop(self) -> None:
        self._stop.set()

    def _record_stream(self, venue: str, payload: dict) -> None:
        for rec in classify_message(venue, payload):
            self.writer.note_ws_activity(rec.get("event_ms"))
            key = f"{venue}/{rec.get('stream', '?')}"
            cont = self.continuity.setdefault(key, StreamContinuity())
            if rec.get("type") == "trade" and rec.get("trade_id") is not None:
                try:
                    if not cont.observe_trade(int(rec["trade_id"])):
                        rec["gap"] = "trade-id"
                except (TypeError, ValueError):
                    pass
            if rec.get("type") == "depth":
                try:
                    if not cont.observe_depth(int(rec["first_id"]),
                                              int(rec["final_id"]),
                                              cont.last_update_id):
                        rec["gap"] = "depth-chain"
                    cont.last_update_id = int(rec["final_id"])
                except (TypeError, ValueError):
                    pass
            if isinstance(rec.get("event_ms"), int) \
                    and not cont.observe_time(int(rec["event_ms"])):
                rec["out_of_order"] = True
            if rec.get("type") == "trade" \
                    and self.config.trade_aggregate_s > 0:
                self._aggregate_trade(rec)
                continue
            self.writer.submit(rec)

    def _aggregate_trade(self, rec: dict) -> None:
        """Fold one trade print into its per-second order-flow bucket.

        Raw prints are ~65% of the whole feed and do not fit the 4 GB disk
        budget; one bucket per (symbol, second) keeps buy/sell volume, count
        and VWAP, which is what the order-flow work actually reads. Anything
        malformed falls back to writing the raw record.
        """
        width_ms = max(1, int(self.config.trade_aggregate_s)) * 1000
        try:
            ts = int(rec.get("trade_ms") or rec.get("event_ms"))
            qty = float(rec.get("qty"))
            price = float(rec.get("price"))
        except (TypeError, ValueError):
            self.writer.submit(rec)
            return
        sec = ts - (ts % width_ms)
        key = (str(rec.get("venue")), str(rec.get("symbol")), sec)
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = {"type": "trade_agg", "stream": rec.get("stream"),
                      "venue": rec.get("venue"), "symbol": rec.get("symbol"),
                      "event_ms": sec, "bucket_ms": width_ms,
                      "buy_qty": 0.0, "sell_qty": 0.0, "trades": 0,
                      "notional": 0.0, "gap": rec.get("gap"),
                      "out_of_order": rec.get("out_of_order", False),
                      "first_trade_id": None, "last_trade_id": None}
            self._buckets[key] = bucket
        # A gap or out-of-order print can land on a second whose bucket
        # already exists; without this the flag would be dropped and the
        # aggregate would read as clean.
        bucket["gap"] = bucket["gap"] or rec.get("gap")
        bucket["out_of_order"] = (bucket["out_of_order"]
                                  or rec.get("out_of_order", False))
        trade_id = rec.get("trade_id")
        if isinstance(trade_id, int):
            first = bucket["first_trade_id"]
            last = bucket["last_trade_id"]
            if first is None or trade_id < first:
                bucket["first_trade_id"] = trade_id
            if last is None or trade_id > last:
                bucket["last_trade_id"] = trade_id
        if rec.get("maker"):
            bucket["sell_qty"] += qty
        else:
            bucket["buy_qty"] += qty
        bucket["trades"] += 1
        bucket["notional"] += qty * price
        self._flush_buckets(before_ms=sec)

    def _flush_buckets(self, before_ms: int | None = None) -> None:
        for key in sorted(self._buckets):
            if before_ms is not None and key[2] >= before_ms:
                continue
            bucket = self._buckets.pop(key)
            qty = bucket["buy_qty"] + bucket["sell_qty"]
            bucket["vwap"] = (round(bucket["notional"] / qty, 8)
                              if qty else None)
            for field in ("buy_qty", "sell_qty", "notional"):
                bucket[field] = round(bucket[field], 8)
            self.writer.submit(bucket)

    # -- #49: settled funding + daily klines --------------------------------
    def _universe_for_pull(self, purpose: str) -> tuple[list[str], str]:
        """Symbols a funding/kline sweep must cover, plus provenance.

        Default is the FULL live listing (TRADING USDT-margined perps from
        exchangeInfo, refreshed daily) -- the frozen-universe rule ranks the
        candidate listing, so a silent 2-symbol pull would satisfy the field
        while violating the rule. An explicit ``kline_symbols`` config pins
        the list instead and is tagged "explicit" on every record. If live
        discovery fails, the sweep degrades to the WS symbols and says so
        ("config-fallback"); it never fails over silently.
        """
        if self.config.kline_symbols:
            return list(self.config.kline_symbols), "explicit"
        today = datetime.now(UTC).date().isoformat()
        if self._universe_cache is not None and self._universe_cache[0] == today:
            return list(self._universe_cache[1]), "exchangeInfo"
        try:
            body, _rtt = self._rest_get(FAPI_BASE + "/fapi/v1/exchangeInfo",
                                        10.0)
            rows = body.get("symbols", []) if isinstance(body, dict) else []
            symbols = sorted(str(row["symbol"]) for row in rows
                             if isinstance(row, dict)
                             and row.get("status") == "TRADING"
                             and row.get("contractType") == "PERPETUAL"
                             and row.get("quoteAsset") == "USDT")
        except Exception as exc:  # noqa: BLE001 -- degraded, loudly
            symbols = []
            error = f"{type(exc).__name__}: {exc}"
        else:
            error = ""
        if not symbols:
            if self._universe_fallback_alerted != today + purpose:
                self._universe_fallback_alerted = today + purpose
                self.writer._alert("universe-discovery-failed", {
                    "purpose": purpose, "error": error or "empty listing",
                    "fallback": list(self.config.symbols)})
            return list(self.config.symbols), "config-fallback"
        self._universe_cache = (today, symbols)
        return list(symbols), "exchangeInfo"

    def _funding_sweep(self, venue: str, now_ms: int) -> dict[str, int]:
        """Emit newly settled funding rates; returns per-sweep counts.

        Exactly-once per settlement under restarts: the per-symbol
        high-water mark persists in funding_state.json. A cold start seeds
        each mark at boot (prior history is skipped, never backfilled --
        stamping pre-boot settlements could poison a chunk with records from
        inside the sealed holdout window).
        """
        symbols, source = self._universe_for_pull("funding")
        emitted = skipped_grid = errors = 0
        advanced = False
        for symbol in symbols:
            if self._stop.is_set():
                break
            high_water = self._funding_hw.get(symbol, self._boot_ms)
            try:
                body, _rtt = self._rest_get(
                    FAPI_BASE + "/fapi/v1/fundingRate"
                    f"?symbol={symbol}&startTime={high_water + 1}&limit=100",
                    10.0)
            except Exception as exc:  # noqa: BLE001 -- recorder reports
                errors += 1
                self.writer._alert("rest-poll-failed", {
                    "symbol": symbol, "path": "/fapi/v1/fundingRate",
                    "error": f"{type(exc).__name__}: {exc}"})
                continue
            rows = body if isinstance(body, list) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    settle_ms = int(row["fundingTime"])
                    float(row["fundingRate"])  # validate; raw value recorded
                except (KeyError, TypeError, ValueError):
                    continue
                if settle_ms <= high_water or settle_ms > now_ms:
                    continue
                grid_ok = settle_ms % SETTLE_GRID_MS == 0
                if not grid_ok and symbol not in self._off_grid_alerted:
                    self._off_grid_alerted.add(symbol)
                    self.writer._alert("funding-off-grid", {
                        "symbol": symbol, "settle_ms": settle_ms,
                        "note": "non-8h funding interval; row kept, flagged"})
                self.writer.submit({
                    "type": "funding_rate_settled",
                    "stream": FUNDING_STREAM_TOKEN,
                    "venue": venue, "symbol": symbol,
                    "event_ms": settle_ms, "fundingRate": row["fundingRate"],
                    "payload": {"fundingRate": row["fundingRate"],
                                "fundingTime": settle_ms},
                    "grid_8h": grid_ok, "universe_source": source})
                high_water = settle_ms
                self._funding_hw[symbol] = settle_ms
                emitted += 1
                advanced = True
                if not grid_ok:
                    skipped_grid += 1
        if advanced:
            try:
                _atomic_json(self.root / "funding_state.json",
                             dict(sorted(self._funding_hw.items())))
            except OSError as exc:
                # State loss only risks duplicates after a crash, and D1
                # dedupes funding by (symbol, settlement) key -- alert, keep
                # the in-memory marks, and stay up.
                self.writer._alert("state-persist-failed", {
                    "file": "funding_state.json",
                    "error": f"{type(exc).__name__}: {exc}"})
        return {"emitted": emitted, "off_grid": skipped_grid,
                "errors": errors, "symbols": len(symbols)}

    def _kline_sweep(self, venue: str, now_utc: datetime) -> dict[str, Any]:
        """Pull completed 1d bars once per UTC day; returns what happened.

        Runs only after the 00:05 UTC cutoff and only completed bars
        (closeTime in the past) are emitted, so quote_volume is final.
        Idempotent-by-key downstream: a restart mid-pull may re-emit a day,
        and D1 overwrites daily_quote_volume[day]. A downtime longer than
        the pull window leaves permanently missing days -- those need the
        sidecar backfill (proposal only), never a sealed-chunk edit.
        """
        cutoff_h, cutoff_m = KLINE_PULL_CUTOFF_HM
        today = now_utc.date().isoformat()
        state_path = self.root / "kline_state.json"
        last_pulled: str | None = None
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(state, dict):
                last_pulled = state.get("last_pulled_day")
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            self.writer._alert("kline-state-unreadable", {
                "error": f"{type(exc).__name__}: {exc}"})
        if (now_utc.hour, now_utc.minute) < (cutoff_h, cutoff_m):
            return {"pulled": False, "reason": "before-cutoff"}
        if last_pulled == today:
            return {"pulled": False, "reason": "already-pulled"}
        symbols, source = self._universe_for_pull("klines")
        now_ms = int(now_utc.timestamp() * 1000)
        emitted = errors = 0
        for symbol in symbols:
            if self._stop.is_set():
                break
            try:
                body, _rtt = self._rest_get(
                    FAPI_BASE + "/fapi/v1/klines"
                    f"?symbol={symbol}&interval=1d&limit=5", 10.0)
            except Exception as exc:  # noqa: BLE001 -- recorder reports
                errors += 1
                self.writer._alert("rest-poll-failed", {
                    "symbol": symbol, "path": "/fapi/v1/klines?interval=1d",
                    "error": f"{type(exc).__name__}: {exc}"})
                continue
            rows = body if isinstance(body, list) else []
            for row in rows:
                if not isinstance(row, (list, tuple)) or len(row) < 11:
                    continue
                try:
                    open_ms = int(row[0])
                    close_ms = int(row[6])
                    quote_volume = float(row[7])
                except (TypeError, ValueError):
                    continue
                if close_ms >= now_ms or quote_volume < 0:
                    continue  # forming bar or corrupt row: never emit
                try:
                    record = {
                        "type": "kline_1d", "venue": venue, "symbol": symbol,
                        "event_ms": now_ms, "exchange_open_ms": open_ms,
                        "open": float(row[1]), "high": float(row[2]),
                        "low": float(row[3]), "close": float(row[4]),
                        "volume": float(row[5]), "close_ms": close_ms,
                        "quote_volume": quote_volume,
                        "trades": int(row[8]),
                        "taker_base": float(row[9]),
                        "taker_quote": float(row[10]),
                        "universe_source": source,
                        "universe_size": len(symbols)}
                except (TypeError, ValueError):
                    continue
                self.writer.submit(record)
                emitted += 1
        if errors and not emitted:
            return {"pulled": False, "reason": "all-symbols-failed",
                    "errors": errors, "symbols": len(symbols)}
        try:
            _atomic_json(state_path, {"last_pulled_day": today,
                                      "universe_source": source,
                                      "universe_size": len(symbols)})
        except OSError as exc:
            self.writer._alert("state-persist-failed", {
                "file": "kline_state.json",
                "error": f"{type(exc).__name__}: {exc}"})
        return {"pulled": True, "emitted": emitted, "errors": errors,
                "symbols": len(symbols), "universe_source": source}

    def _rest_poll(self, venue: str) -> None:
        while not self._stop.is_set():
            for symbol in self.config.symbols:
                if self._stop.is_set():
                    break
                for path, kind, fields in (
                    (f"/fapi/v1/openInterest?symbol={symbol}", "open_interest",
                     ("openInterest", "time")),
                    (f"/fapi/v1/premiumIndex?symbol={symbol}", "premium_index",
                     ("markPrice", "indexPrice", "lastFundingRate",
                      "nextFundingTime", "time")),
                ):
                    try:
                        body, _rtt = self._rest_get(FAPI_BASE + path, 10.0)
                        rec = {"type": kind, "venue": venue,
                               "symbol": symbol, "event_ms": int(
                                   body.get("time") or time.time() * 1000),
                               "payload": {k: body.get(k) for k in fields}}
                        self.writer.submit(rec)
                    except Exception as exc:  # noqa: BLE001 — recorder reports
                        self.writer._alert("rest-poll-failed", {
                            "symbol": symbol, "path": path,
                            "error": f"{type(exc).__name__}: {exc}"})
                try:
                    body, _rtt = self._rest_get(
                        FAPI_BASE + f"/fapi/v1/depth?symbol={symbol}&limit=1000",
                        10.0)
                    self.writer.submit({
                        "type": "depth_snapshot", "venue": venue,
                        "symbol": symbol, "event_ms": int(body.get("T") or 0),
                        "last_update_id": body.get("lastUpdateId"),
                        "bids": body.get("bids"), "asks": body.get("asks")})
                except Exception as exc:  # noqa: BLE001
                    self.writer._alert("depth-snapshot-failed", {
                        "symbol": symbol,
                        "error": f"{type(exc).__name__}: {exc}"})
            now_s = time.time()
            if now_s - self._last_funding_sweep >= self.config.funding_poll_s:
                self._last_funding_sweep = now_s
                self._funding_sweep(venue, int(now_s * 1000))
            self._kline_sweep(venue, datetime.now(UTC))
            self._stop.wait(self.config.rest_poll_s)

    def run(self, *, duration_s: float | None = None) -> dict:
        deadline = time.monotonic() + duration_s if duration_s else None
        self.status["state"] = "recording"
        self._rest_thread = threading.Thread(
            target=self._rest_poll, args=("binance",), daemon=True,
            name="recorder-rest")
        self._rest_thread.start()
        try:
            for venue in self.config.venues:
                self._run_venue(venue, deadline)
        finally:
            self._stop.set()
            if self._rest_thread is not None:
                self._rest_thread.join(timeout=5.0)
            # Flush the open per-second trade buckets before sealing.
            self._flush_buckets()
            fatal: BaseException | None = None
            try:
                self.writer.close()
            except BaseException as exc:  # noqa: BLE001 -- loud exit below
                fatal = exc
            self.status.update({"state": "stopped", "stopped_utc": _utc_now(),
                                "records": self.writer.records,
                                "dropped": self.writer.dropped,
                                "chunks": len(self.writer.sealed),
                                "alerts": self.writer.alerts[-20:],
                                "manifest": str(self.root / "manifest.json"),
                                "fatal": (f"{type(fatal).__name__}: {fatal}"
                                          if fatal is not None else None)})
            with contextlib.suppress(OSError):
                _atomic_json(self.root / "status.json", self.status)
            if fatal is not None:
                raise fatal
        return self.status

    def _run_venue(self, venue: str, deadline: float | None) -> None:
        backoff = 1.0
        url = venue_stream_url(venue, self.config.symbols,
                               self.config.streams)
        while not self._stop.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                return
            if self.config.stop_file and Path(self.config.stop_file).exists():
                return
            if not check_disk_budget(self.config)["ok"]:
                self.writer._alert("disk-budget-exceeded",
                                   check_disk_budget(self.config))
                self._stop.set()
                return
            try:
                conn = self._connect(url)
                for message in subscription_messages(venue,
                                                    self.config.symbols):
                    conn.send_text(message)
                backoff = 1.0
                while not self._stop.is_set():
                    if deadline is not None \
                            and time.monotonic() >= deadline:
                        return
                    try:
                        msg = conn.recv_message(timeout_s=1.0)
                    except Exception as exc:  # noqa: BLE001
                        # Timeouts are normal; distinguish by name/string.
                        if "timeout" in str(exc).lower():
                            continue
                        raise
                    kind, raw = msg
                    if kind != "text":
                        continue
                    try:
                        payload = json.loads(raw.decode("utf-8"))
                    except ValueError:
                        self.writer.submit({"type": "malformed",
                                            "venue": venue,
                                            "payload": raw[:200].decode(
                                                "utf-8", "replace")})
                        continue
                    self._record_stream(venue, payload)
            except Exception as exc:  # noqa: BLE001 — reconnect with jitter
                self.writer._alert("reconnect", {
                    "venue": venue, "error": f"{type(exc).__name__}: {exc}",
                    "backoff_s": backoff})
                self._sleep(backoff * (0.5 + random.random()))
                backoff = min(backoff * 2.0, self.config.reconnect_max_s)


def _urllib_json(url: str, timeout: float) -> tuple[Any, float]:
    started = time.time()
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
        body = json.loads(resp.read().decode("utf-8"))
    return body, (time.time() - started) * 1000.0


def run_recorder(config: RecorderConfig, *, duration_s: float | None = None,
                 connect: Callable[[str], Any] | None = None,
                 rest_get: Callable[[str, float], tuple[Any, float]] | None = None
                 ) -> dict:
    return Recorder(config, connect=connect, rest_get=rest_get).run(
        duration_s=duration_s)


__all__ = [
    "ManifestChain", "RecorderConfig", "RecorderWriter", "Recorder",
    "StreamContinuity", "classify_message", "integrity_report",
    "venue_stream_url", "subscription_messages", "check_disk_budget",
    "run_recorder", "BINANCE_STREAMS", "FUNDING_STREAM_TOKEN",
    "quarantine_orphans",
]
