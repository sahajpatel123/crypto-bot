"""Supervised public-stream collector (Worker 2, E-006).

Runs one websocket per routed surface (market: aggTrade + markPrice;
public: bookTicker + depth), maintains diff-depth books with resync,
normalizes every message with full timestamp provenance, aggregates causal
1s bars, and writes raw + normalized + bar files with a run manifest.

Supervision: run ID, PID file, JSON heartbeat, per-channel counters,
bounded storage (clean stop at the cap), bounded reservoirs for timing
percentiles, clean stop on duration/stop-file/interrupt, and distinct
labelling of natural vs injected discontinuities. Bulk output stays in the
run directory (outside git); only fixtures/manifests/reports ship.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import select
import signal
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .bars import BarAggregator, BarMissing
from .bridge import snapshot_record
from .depth import DepthBook
from .discovery import FAPI_BASE_URL, discover_usdt_perps, fetch_exchange_info, urllib_json_get
from .events import EVENT_FORMAT, parse_message, raw_envelope
from .recorder import INPUT_OBSERVED
from .ws import WsClient, WsClosed, WsHandshakeError

__all__ = [
    "CollectorConfig", "Collector", "RunStats", "select_capture_set",
    "measure_clock_offset_ms", "MARKET_ROUTE", "PUBLIC_ROUTE",
]

MARKET_ROUTE = "wss://fstream.binance.com/market/stream?streams="
PUBLIC_ROUTE = "wss://fstream.binance.com/public/stream?streams="
REST_BASE = FAPI_BASE_URL
_STALE_PARTIAL_S = 5.0  # incomplete buffered bytes this old mean a sick connection.


@dataclass(frozen=True)
class CollectorConfig:
    symbols: tuple[str, ...]
    run_dir: str
    run_id: str
    capture_set_rule: str
    max_bytes: int = 2_000_000_000
    heartbeat_every_s: float = 5.0
    depth_snapshot_limit: int = 1000
    lateness_ms: int = 500
    chaos_disconnect_after_s: float | None = None
    market_streams: tuple[str, ...] = ("aggTrade", "markPrice@1s")
    public_streams: tuple[str, ...] = ("bookTicker", "depth@100ms")


class _Reservoir:
    """Bounded uniform sample for percentiles (Vitter Algorithm R)."""

    def __init__(self, capacity: int = 20000) -> None:
        self.capacity = capacity
        self.samples: list[float] = []
        self.count = 0

    def add(self, value: float) -> None:
        self.count += 1
        if len(self.samples) < self.capacity:
            self.samples.append(value)
        else:
            j = random.randint(0, self.count - 1)
            if j < self.capacity:
                self.samples[j] = value


@dataclass
class RunStats:
    run_id: str
    events_total: int = 0
    malformed: int = 0
    per_channel: dict = field(default_factory=dict)  # "route/channel/symbol" -> count
    duplicates: int = 0
    out_of_order: int = 0
    gaps_natural: int = 0
    gaps_injected: int = 0
    disconnects_natural: int = 0
    disconnects_injected: int = 0
    depth_resyncs: int = 0
    depth_applied: int = 0
    reconnects: int = 0
    bytes_written: int = 0
    stop_reason: str = ""


def measure_clock_offset_ms(rest_get: Callable = urllib_json_get,
                            base_url: str = REST_BASE) -> dict[str, float]:
    """Estimate (server - local) clock offset via REST time (single sample, RTT halved)."""
    before = time.time() * 1000
    payload, _ = rest_get(base_url + "/fapi/v1/time", 10.0)
    after = time.time() * 1000
    server = float(payload["serverTime"])
    return {"offset_ms": server - (before + after) / 2, "rtt_ms": after - before}


def select_capture_set(discovery_payload: dict[str, Any], rest_get: Callable,
                       base_url: str, top_n: int = 2) -> tuple[tuple[str, ...], str, dict[str, Any]]:
    """Select N symbols by 24h quote volume among TRADING USDT perps.

    Returns (symbols, rule_text, evidence). The rule is recomputed every run;
    the chosen symbols are recorded, never hardcoded.
    """
    result = discover_usdt_perps(discovery_payload)
    tickers, _ = rest_get(base_url + "/fapi/v1/ticker/24hr", 15.0)
    volumes = {t["symbol"]: float(t.get("quoteVolume") or 0.0) for t in tickers}
    ranked = sorted(result.symbols, key=lambda m: (-volumes.get(m.symbol, 0.0), m.symbol))
    chosen = tuple(m.symbol for m in ranked[:top_n])
    rule = (f"top-{top_n} by 24h quoteVolume among {len(result.symbols)} TRADING "
            f"USDT-perp symbols from live discovery (recomputed per run)")
    evidence = {s: volumes.get(s, 0.0) for s in chosen}
    return chosen, rule, evidence


class Collector:
    def __init__(self, config: CollectorConfig, *,
                 connect: Callable[[str], WsClient] = WsClient.connect,
                 rest_get: Callable = urllib_json_get,
                 wall_ms: Callable[[], int] | None = None,
                 mono_ns: Callable[[], int] | None = None) -> None:
        self.config = config
        self._connect = connect
        self._rest_get = rest_get
        self._wall_ms = wall_ms or (lambda: int(time.time() * 1000))
        self._mono_ns = mono_ns or time.perf_counter_ns
        self.run_dir = Path(config.run_dir)
        self.stats = RunStats(config.run_id)
        self._books = {s: DepthBook(s) for s in config.symbols}
        self._bars = {s: BarAggregator(s, lateness_ms=config.lateness_ms) for s in config.symbols}
        self._last_venue_seq: dict[str, int] = {}
        self._pending_gap: dict[str, str | None] = {"market": None, "public": None}
        self._age_samples = _Reservoir()
        self._proc_samples = _Reservoir()
        self._seq = 0
        self._stop_requested = False
        self._chaos_done = False
        self._snapshot_due: dict[str, float] = {}  # symbol -> mono deadline for buffer-fill window.
        self._conns: dict[str, WsClient] = {}
        self._turn: list[str] = ["market", "public"]  # rotated each pump: fair service.
        self._route_last_msg: dict[str, int] = {}
        self._started_mono = 0
        self._deadline_mono: int | None = None
        self._clock_start: dict[str, float] = {}
        self._selection_evidence: dict[str, Any] = {}
        self._metadata_hash = ""

    # -- setup -------------------------------------------------------------
    def _stream_url(self, route: str) -> str:
        base = MARKET_ROUTE if route == "market" else PUBLIC_ROUTE
        kinds = self.config.market_streams if route == "market" else self.config.public_streams
        streams = "/".join(f"{s.lower()}@{k}" for s in self.config.symbols for k in kinds)
        return base + streams

    def _open(self, route: str) -> None:
        self._conns[route] = self._connect(self._stream_url(route))
        self._conns[route].native_socket.settimeout(0.2)
        self._route_last_msg[route] = self._mono_ns()

    def _snapshot_symbol(self, symbol: str, raw_fh, events_fh, bars_fh, snaps_fh) -> None:
        """Fetch a depth snapshot, drain in-flight diffs into the buffer, then install.

        The post-REST drain is load-bearing: diffs generated while the snapshot
        request was in flight sit in the kernel queue, and the event spanning
        lastUpdateId + 1 is typically among them. Installing without draining
        strands the book (every subsequent diff looks like a chain break).

        Every fetched snapshot is persisted (E-007) so book-feature replay can
        rebuild from snapshot + chained diffs; the outcome field marks the
        sync boundary (synced | resync).
        """
        payload, _ = self._rest_get(
            f"{REST_BASE}/fapi/v1/depth?symbol={symbol}&limit={self.config.depth_snapshot_limit}", 15.0)
        rest_wall, rest_mono = self._wall_ms(), self._mono_ns()
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            if self._pump_once(raw_fh, events_fh, bars_fh) == 0:
                break
        book = self._books[symbol]
        outcome = book.on_snapshot(payload["bids"], payload["asks"], payload["lastUpdateId"])
        self._write_json(snaps_fh, snapshot_record(
            run_id=self.config.run_id, symbol=symbol,
            last_update_id=payload["lastUpdateId"],
            bids=payload["bids"], asks=payload["asks"],
            rest_recv_ms=rest_wall, rest_mono_ns=rest_mono,
            limit=self.config.depth_snapshot_limit, outcome=outcome))
        if outcome == "resync":
            self.stats.depth_resyncs += 1
            self._snapshot_due[symbol] = time.monotonic() + 2.5  # genuine gap; re-buffer, retry.

    def _snapshot_due_check(self, raw_fh, events_fh, bars_fh, snaps_fh) -> None:
        now = time.monotonic()
        for symbol in list(self._snapshot_due):
            if now >= self._snapshot_due[symbol]:
                del self._snapshot_due[symbol]
                try:
                    self._snapshot_symbol(symbol, raw_fh, events_fh, bars_fh, snaps_fh)
                except (OSError, ValueError, KeyError):
                    # REST failed or answered garbage (rate limit, error page):
                    # re-buffer and retry shortly; never kill a capture over it.
                    self._snapshot_due[symbol] = now + 5.0

    def _write_manifest(self, ended_utc: str, files: dict[str, Path]) -> Path:
        manifest = {
            "run_id": self.config.run_id,
            "input_class": INPUT_OBSERVED,
            "format": EVENT_FORMAT,
            "started_utc": getattr(self, "_started_utc", ""),
            "ended_utc": ended_utc,
            "symbols": list(self.config.symbols),
            "capture_set_rule": self.config.capture_set_rule,
            "selection_evidence": self._selection_evidence,
            "metadata_hash": self._metadata_hash,
            "clock_offset_start": self._clock_start,
            "config": {
                "market_streams": list(self.config.market_streams),
                "public_streams": list(self.config.public_streams),
                "depth_snapshot_limit": self.config.depth_snapshot_limit,
                "lateness_ms": self.config.lateness_ms,
                "max_bytes": self.config.max_bytes,
                "chaos_disconnect_after_s": self.config.chaos_disconnect_after_s,
            },
            "files": {},
        }
        for name, path in files.items():
            digest = hashlib.sha256()
            with path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    digest.update(chunk)
            manifest["files"][name] = {"path": str(path), "sha256": digest.hexdigest(),
                                       "bytes": path.stat().st_size}
        out = self.run_dir / "manifest.json"
        out.write_text(json.dumps(manifest, indent=2))
        return out

    # -- main loop -----------------------------------------------------------
    def run(self, duration_s: float | None = None) -> RunStats:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "pid").write_text(str(os.getpid()))
        self._started_utc = datetime.now(timezone.utc).isoformat()
        self._started_mono = self._mono_ns()
        try:
            self._clock_start = measure_clock_offset_ms(self._rest_get)
        except (OSError, ValueError, KeyError):
            self._clock_start = {}  # clock probe is advisory; the capture stands alone.
        raw_fh = (self.run_dir / "raw.jsonl").open("w", encoding="utf-8")
        events_fh = (self.run_dir / "events.jsonl").open("w", encoding="utf-8")
        bars_fh = (self.run_dir / "bars.jsonl").open("w", encoding="utf-8")
        snaps_fh = (self.run_dir / "depth_snapshots.jsonl").open("w", encoding="utf-8")
        files = {"raw": self.run_dir / "raw.jsonl", "events": self.run_dir / "events.jsonl",
                 "bars": self.run_dir / "bars.jsonl",
                 "depth_snapshots": self.run_dir / "depth_snapshots.jsonl"}
        last_heartbeat = 0.0
        last_flush = time.monotonic()
        if duration_s is not None:
            self._deadline_mono = self._started_mono + int(duration_s * 1e9)
        try:
            for route in ("market", "public"):
                if not self._open_with_retry(route):
                    self.stats.stop_reason = "connect-failed"
                    return self.stats
            for symbol in self.config.symbols:
                self._snapshot_due[symbol] = time.monotonic()  # sync ASAP in-loop.
            while not self._stop_requested:
                elapsed = (self._mono_ns() - self._started_mono) / 1e9
                if duration_s is not None and elapsed >= duration_s:
                    self.stats.stop_reason = "duration-reached"
                    break
                if (self.run_dir / "STOP").exists():
                    self.stats.stop_reason = "stop-file"
                    break
                if self.stats.bytes_written >= self.config.max_bytes:
                    self.stats.stop_reason = "storage-bound"
                    break
                if (self.config.chaos_disconnect_after_s is not None and not self._chaos_done
                        and elapsed >= self.config.chaos_disconnect_after_s):
                    self._drop_connection("public", injected=True)
                    self._chaos_done = True
                self._pump_once(raw_fh, events_fh, bars_fh)
                self._snapshot_due_check(raw_fh, events_fh, bars_fh, snaps_fh)
                now = time.monotonic()
                if now - last_heartbeat >= self.config.heartbeat_every_s:
                    self._heartbeat()
                    last_heartbeat = now
                if now - last_flush >= 1.0:
                    raw_fh.flush()
                    events_fh.flush()
                    bars_fh.flush()
                    snaps_fh.flush()
                    last_flush = now
        except KeyboardInterrupt:
            self.stats.stop_reason = "interrupted"
        finally:
            for bar in self._drain_bars():
                self._write_json(bars_fh, bar)
            for fh in (raw_fh, events_fh, bars_fh, snaps_fh):
                fh.flush()
                os.fsync(fh.fileno())
                fh.close()
            for route in ("market", "public"):
                try:
                    self._conns[route].close()
                except (KeyError, OSError, WsClosed):
                    pass
            try:
                (self.run_dir / "pid").unlink()
            except OSError:
                pass
            if not self.stats.stop_reason:
                self.stats.stop_reason = "stopped"
            self._write_stats()
            self._write_manifest(datetime.now(timezone.utc).isoformat(), files)
            self._heartbeat()
        return self.stats

    def request_stop(self) -> None:
        self._stop_requested = True

    # -- per-iteration -------------------------------------------------------
    def _pump_once(self, raw_fh, events_fh, bars_fh) -> int:
        """Process at most one message per route (round-robin). Returns messages read.

        Routes are polled via ``recv_message_nowait`` so complete
        application-buffered messages and TLS pending data drain without
        awaiting new kernel readability (E-009); ``select`` is only an idle
        sleep. A route holding incomplete bytes past the stale threshold is
        dropped as sick and reconnected with a natural gap.
        """
        if not self._conns:
            time.sleep(0.2)
            return 0
        processed = 0
        for route in list(self._turn):
            conn = self._conns.get(route)
            if conn is None:
                continue
            drain = getattr(conn, "recv_message_nowait", None)
            if drain is None:
                # Legacy/foreign conn: honor has_pending() without select.
                if not getattr(conn, "has_pending", lambda: False)():
                    continue
                try:
                    message = conn.recv_message(timeout_s=0)
                except WsClosed:
                    self._drop_connection(route, injected=False)
                    continue
            else:
                try:
                    message = drain()
                except WsClosed:
                    self._drop_connection(route, injected=False)
                    continue
            if message is None:
                continue
            if self._handle_message(route, *message, raw_fh, events_fh, bars_fh):
                processed += 1
        self._turn = self._turn[1:] + self._turn[:1]
        if processed:
            return processed
        now_mono = self._mono_ns()
        for route, conn in list(self._conns.items()):
            buffered = getattr(conn, "buffered_bytes", 0)
            last = self._route_last_msg.get(route, now_mono)
            if buffered and (now_mono - last) / 1e9 > _STALE_PARTIAL_S:
                self._drop_connection(route, injected=False)  # sick: never assembles.
                break
        else:
            try:
                select.select([c.native_socket for c in self._conns.values()],
                              [], [], 0.2)
            except (OSError, ValueError):
                time.sleep(0.2)  # dead socket set: never busy-spin.
        return 0

    def _handle_message(self, route: str, kind: str, payload: bytes,
                        raw_fh, events_fh, bars_fh) -> bool:
        """Normalize + persist one message; True when it became an event."""
        if kind != "text":
            return False
        recv_wall = self._wall_ms()
        recv_mono = self._mono_ns()
        try:
            message = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self.stats.malformed += 1
            return False
        self._seq += 1
        self._write_json(raw_fh, raw_envelope(message, route=route, local_recv_ms=recv_wall,
                                              local_mono_ns=recv_mono, seq=self._seq,
                                              run_id=self.config.run_id))
        try:
            event = parse_message(message, route=route, local_recv_ms=recv_wall,
                                  local_mono_ns=recv_mono, seq=self._seq,
                                  run_id=self.config.run_id)
            self._ingest(event, bars_fh)
        except (ValueError, KeyError, TypeError):
            # One bad message must never kill a capture: raw is preserved,
            # the failure is counted, and the loop continues.
            self.stats.malformed += 1
            return False
        self._write_json(events_fh, event)
        self._route_last_msg[route] = recv_mono
        self._proc_samples.add((self._mono_ns() - event["local_mono_ns"]) / 1e6)
        return True

    def _ingest(self, event: dict[str, Any], bars_fh) -> None:
        self.stats.events_total += 1
        key = f"{event['route']}/{event['channel']}/{event['symbol']}"
        self.stats.per_channel[key] = self.stats.per_channel.get(key, 0) + 1
        pending = self._pending_gap.get(event["route"])
        if pending is not None:
            event["gap_kind"] = pending
            if pending == "natural":
                self.stats.gaps_natural += 1
            else:
                self.stats.gaps_injected += 1
            self._pending_gap[event["route"]] = None
        venue_seq = event.get("venue_seq")
        if venue_seq is not None:
            last = self._last_venue_seq.get(key)
            if last is not None:
                if venue_seq == last:
                    self.stats.duplicates += 1
                elif venue_seq < last:
                    self.stats.out_of_order += 1
            self._last_venue_seq[key] = max(venue_seq, last or 0)
        channel, symbol = event["channel"], event["symbol"]
        if channel == "depth":
            book = self._books[symbol]
            outcome = book.on_diff(event["payload"])
            if outcome == "resync":
                book.request_resync("chain-break")
                self.stats.depth_resyncs += 1
                self._snapshot_due[symbol] = time.monotonic() + 2.5  # re-buffer, then retry.
            elif outcome == "applied":
                self.stats.depth_applied += 1
        elif channel == "aggTrade":
            bars = self._bars[symbol].on_trade(event)
            for bar in bars:
                self._write_json(bars_fh, self._bar_record(bar, symbol))
        elif channel == "bookTicker":
            payload = event["payload"]
            self._bars[symbol].on_bbo(payload["bid"], payload["ask"], event["exchange_ts_ms"])
        self._age_samples.add(event["local_recv_ms"] - event["exchange_ts_ms"])
        # Proc latency is sampled by the pump AFTER the normalized-event write,
        # so it covers parse + state update + all write buffering.

    def _bar_record(self, bar, symbol: str) -> dict[str, Any]:
        if isinstance(bar, BarMissing):
            return {"type": "missing", "input_class": INPUT_OBSERVED, "symbol": symbol,
                    "window_start_ms": bar.window_start_ms, "gap_before": bar.gap_before}
        return {"type": "bar", "input_class": INPUT_OBSERVED, "symbol": symbol,
                "window_start_ms": bar.window_start_ms, "o": bar.open, "h": bar.high,
                "l": bar.low, "c": bar.close, "volume": bar.volume, "trades": bar.trades,
                "buy_volume": bar.buy_volume, "first_id": bar.first_id, "last_id": bar.last_id,
                "spread_bps": bar.spread_bps, "gap_before": bar.gap_before}

    def _drain_bars(self) -> list:
        out = []
        for symbol in self.config.symbols:
            out.extend(self._bar_record(b, symbol) for b in self._bars[symbol].flush())
        return out

    def _past_deadline(self) -> bool:
        return self._deadline_mono is not None and self._mono_ns() >= self._deadline_mono

    def _open_with_retry(self, route: str) -> bool:
        """Open a route, retrying with backoff until stopped, deadline, or success."""
        backoff = 1.0
        while not self._stop_requested and not self._past_deadline():
            try:
                self._open(route)
                return True
            except (OSError, WsHandshakeError):
                # Transport down or edge rejected the handshake (429/502-class):
                # back off and retry. Bad-scheme ValueError still fails fast.
                time.sleep(min(backoff, 5.0))
                backoff = min(backoff * 2, 30.0)
        return route in self._conns

    def _drop_connection(self, route: str, *, injected: bool) -> None:
        try:
            self._conns.pop(route).close()
        except (KeyError, OSError, WsClosed):
            pass
        if injected:
            self.stats.disconnects_injected += 1
        else:
            self.stats.disconnects_natural += 1
        self._pending_gap[route] = "injected" if injected else "natural"
        if route == "public":
            for book in self._books.values():
                book.request_resync("reconnect")
        if self._open_with_retry(route):
            self.stats.reconnects += 1
            if route == "public":
                for symbol in self.config.symbols:
                    self._snapshot_due[symbol] = time.monotonic()  # sync ASAP; drain covers flight.
        elif not self._conns:
            self.stats.stop_reason = "routes-exhausted"
            self.request_stop()

    # -- persistence ---------------------------------------------------------
    def _write_json(self, fh, record: dict[str, Any]) -> None:
        line = json.dumps(record) + "\n"
        fh.write(line)
        self.stats.bytes_written += len(line.encode("utf-8"))

    def _heartbeat(self) -> None:
        (self.run_dir / "heartbeat.json").write_text(json.dumps({
            "run_id": self.config.run_id, "pid": os.getpid(),
            "at_utc": datetime.now(timezone.utc).isoformat(),
            "events_total": self.stats.events_total,
            "per_channel": self.stats.per_channel,
            "depth_resyncs": self.stats.depth_resyncs,
            "disconnects": {"natural": self.stats.disconnects_natural,
                            "injected": self.stats.disconnects_injected},
            "bytes_written": self.stats.bytes_written,
            "stop_reason": self.stats.stop_reason,
        }, indent=2))

    def _write_stats(self) -> None:
        books = {s: {"synced": b.state.synced, "last_update_id": b.state.last_update_id,
                     "resyncs": b.state.resyncs, "applied": b.state.applied,
                     "dropped_stale": b.state.dropped_stale} for s, b in self._books.items()}
        bars = {s: agg.stats() for s, agg in self._bars.items()}
        try:
            clock_end = measure_clock_offset_ms(self._rest_get)
        except OSError:
            clock_end = {}
        (self.run_dir / "run_stats.json").write_text(json.dumps({
            "run_id": self.config.run_id,
            "events_total": self.stats.events_total,
            "malformed": self.stats.malformed,
            "per_channel": self.stats.per_channel,
            "duplicates": self.stats.duplicates,
            "out_of_order": self.stats.out_of_order,
            "gaps": {"natural": self.stats.gaps_natural, "injected": self.stats.gaps_injected},
            "disconnects": {"natural": self.stats.disconnects_natural,
                            "injected": self.stats.disconnects_injected},
            "reconnects": self.stats.reconnects,
            "depth_resyncs": self.stats.depth_resyncs,
            "depth_applied": self.stats.depth_applied,
            "bytes_written": self.stats.bytes_written,
            "stop_reason": self.stats.stop_reason,
            "books": books,
            "bars": bars,
            "clock_offset_start": self._clock_start,
            "clock_offset_end": clock_end,
            "event_age_ms": {"n": self._age_samples.count, "sample": sorted(self._age_samples.samples)},
            "proc_latency_ms": {"n": self._proc_samples.count, "sample": sorted(self._proc_samples.samples)},
        }, indent=2))
