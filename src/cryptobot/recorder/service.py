"""RecorderService: long-running capture orchestration (F3 data engine).

Owns a :class:`DurableWriter`, Binance WS stream loops (market / public /
liquidations), REST pollers (open interest / funding rate / premium index),
and a disk-budget monitor that only ever alerts — it never deletes data.
A low-disk condition sets a stop reason and halts capture loops; the owner
calls :meth:`stop` for a clean, fsync'd shutdown.

All network I/O is isolated in ``_net_*`` methods honouring injectable
``ws_factory`` / ``http_get`` so the service imports and its offline paths
(status/verify) run without network.
"""
from __future__ import annotations

import contextlib
import json
import logging
import random
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptobot.market_data.depth import DepthBook
from cryptobot.market_data.discovery import FAPI_BASE_URL, urllib_json_get
from cryptobot.market_data.events import parse_message
from cryptobot.market_data.ws import WsClient, WsClosed

from .integrity import build_report
from .plugins import BybitPlugin, OKXPlugin
from .streams import (
    REST_POLL_INTERVALS,
    SYMBOLS,
    backoff_with_jitter,
    build_binance_urls,
    funding_rate_url,
    open_interest_url,
    parse_force_order_message,
    parse_rest_record,
    premium_index_url,
)
from .writer import DurableWriter

__all__ = ["RecorderConfig", "RecorderService"]

logger = logging.getLogger(__name__)


@dataclass
class RecorderConfig:
    symbols: tuple[str, ...] = SYMBOLS
    run_id: str = "recorder"
    queue_size: int = 100_000
    fsync_every_n: int = 1000
    fsync_every_s: float = 5.0
    rest_base_url: str = FAPI_BASE_URL
    disk_min_free_bytes: int = 5_000_000_000
    disk_check_s: float = 30.0
    clean_stop_on_low_disk: bool = True
    depth_snapshot_limit: int = 1000
    enable_bybit: bool = False
    enable_okx: bool = False
    ws_factory: Callable[[str], Any] | None = None
    http_get: Callable[[str, float], tuple[Any, float]] | None = None
    alert: Callable[[str], None] | None = None
    poll_intervals: dict[str, float] = field(
        default_factory=lambda: dict(REST_POLL_INTERVALS))


class RecorderService:
    def __init__(self, config: RecorderConfig, run_dir: str | Path) -> None:
        self.config = config
        self.run_dir = Path(run_dir)
        self.writer = DurableWriter(
            self.run_dir, queue_size=config.queue_size,
            fsync_every_n=config.fsync_every_n, fsync_every_s=config.fsync_every_s)
        self._books = {s: DepthBook(s) for s in config.symbols}
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._seq = 0
        self._seq_lock = threading.Lock()
        self._start_mono = 0.0
        self._stop_reason = ""
        self._last_seq = 0
        self._started = False
        self._rng = random.Random()
        self._venues = []
        if config.enable_bybit:
            self._venues.append(BybitPlugin())
        if config.enable_okx:
            self._venues.append(OKXPlugin())

    # -- network isolation (injectable) ----------------------------------
    def _net_connect(self, url: str) -> Any:
        factory = self.config.ws_factory or WsClient.connect
        return factory(url)

    def _net_http_get(self, url: str, timeout_s: float) -> tuple[Any, float]:
        fn = self.config.http_get or urllib_json_get
        return fn(url, timeout_s)

    def _net_disk_free(self) -> int:
        path = self.run_dir
        while not path.exists():  # status-before-start: measure nearest real ancestor.
            path = path.parent
        return shutil.disk_usage(str(path)).free

    def _net_wall_ms(self) -> int:
        return int(time.time() * 1000)

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        """Start the writer, stream loops, REST pollers, and disk monitor."""
        if self._started:
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.writer.start()
        self._start_mono = time.monotonic()
        self._started = True
        urls = build_binance_urls(self.config.symbols)
        for route, url in urls.items():
            self._spawn(f"stream-{route}", self._stream_loop, route, url)
        self._spawn("rest-poller", self._poll_loop)
        self._spawn("disk-monitor", self._disk_loop)

    def stop(self) -> None:
        """Signal loops to halt, join threads, and seal the writer."""
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=30.0)
        self._threads = []
        self.writer.close()
        if not self._stop_reason:
            self._stop_reason = "stopped"

    def status(self) -> dict[str, Any]:
        """Uptime, per-stream counts, drops, gaps, last seq, disk free."""
        try:
            disk_free = self._net_disk_free()
        except OSError:
            disk_free = -1
        uptime = (time.monotonic() - self._start_mono) if self._started else 0.0
        return {
            "run_id": self.config.run_id,
            "running": self._started and not self._stop.is_set(),
            "uptime_s": round(uptime, 1),
            "per_stream": self.writer.counts,
            "drops": self.writer.dropped,
            "gaps": self.writer.gapped_intervals,
            "last_seq": self._last_seq,
            "disk_free_bytes": disk_free,
            "disk_min_free_bytes": self.config.disk_min_free_bytes,
            "stop_reason": self._stop_reason,
            "books": {s: {"synced": b.state.synced,
                           "last_update_id": b.state.last_update_id} for s, b in self._books.items()},
            "writer_thread_error": repr(self.writer.thread_error) if self.writer.thread_error else None,
        }

    def verify(self) -> dict[str, Any]:
        """Offline integrity report over the current run directory."""
        return build_report(self.run_dir)

    # -- loops -----------------------------------------------------------
    def _spawn(self, name: str, fn: Callable, *args: Any) -> None:
        thread = threading.Thread(target=fn, args=args, name=f"recorder-{name}", daemon=True)
        thread.start()
        self._threads.append(thread)

    def _next_seq(self) -> int:
        with self._seq_lock:
            self._seq += 1
            self._last_seq = self._seq
            return self._seq

    def _stream_loop(self, route: str, url: str) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                conn = self._net_connect(url)
            except Exception as exc:  # transport down: back off, retry, stay loud.
                logger.warning("recorder %s connect failed (%r); retrying", route, exc)
                if self._sleep_backoff(attempt):
                    return
                attempt += 1
                continue
            attempt = 0
            try:
                self._serve_connection(route, conn)
            except WsClosed as exc:
                logger.warning("recorder %s closed (%s); reconnecting", route, exc)
            except Exception as exc:  # never let one route kill the recorder.
                logger.exception("recorder %s error: %r", route, exc)
            finally:
                with contextlib.suppress(Exception):
                    conn.close()
            if self._sleep_backoff(attempt):
                return
            attempt += 1

    def _sleep_backoff(self, attempt: int) -> bool:
        """Sleep the reconnect backoff; True when stop was requested."""
        delay = backoff_with_jitter(attempt, rng=self._rng)
        return self._stop.wait(timeout=delay)

    def _serve_connection(self, route: str, conn: Any) -> None:
        while not self._stop.is_set():
            self.writer.rotate_if_needed(datetime.now(UTC))
            try:
                message = conn.recv_message_nowait()
            except AttributeError:
                message = conn.recv_message(timeout_s=0.2)
            if message is None:
                time.sleep(0.01)
                continue
            kind, payload = message
            if kind != "text":
                continue
            recv_ms = self._net_wall_ms()
            try:
                decoded = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue
            seq = self._next_seq()
            try:
                if route == "liquidations":
                    event = parse_force_order_message(
                        decoded, local_recv_ms=recv_ms,
                        run_id=self.config.run_id, seq=seq)
                else:
                    event = parse_message(
                        decoded, route=route, local_recv_ms=recv_ms,
                        local_mono_ns=time.perf_counter_ns(), seq=seq,
                        run_id=self.config.run_id)
            except (ValueError, KeyError, TypeError):
                continue
            self._ingest_depth(event)
            self.writer.append(event["channel"], event)

    def _ingest_depth(self, event: dict[str, Any]) -> None:
        if event.get("channel") != "depth":
            return
        book = self._books.get(event.get("symbol", ""))
        if book is None:
            return
        outcome = book.on_diff(event["payload"])
        if outcome == "resync":
            book.request_resync("chain-break")
            self._snapshot_symbol(event["symbol"])

    def _snapshot_symbol(self, symbol: str) -> None:
        try:
            payload, _ = self._net_http_get(
                f"{self.config.rest_base_url}/fapi/v1/depth?symbol={symbol}"
                f"&limit={self.config.depth_snapshot_limit}", 15.0)
            self._books[symbol].on_snapshot(payload["bids"], payload["asks"],
                                            payload["lastUpdateId"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("recorder depth snapshot failed for %s: %r", symbol, exc)

    def _poll_loop(self) -> None:
        builders = {"openInterest": open_interest_url, "fundingRate": funding_rate_url,
                    "premiumIndex": premium_index_url}
        next_due = {k: 0.0 for k in builders}
        while not self._stop.is_set():
            now = time.monotonic()
            for kind, build in builders.items():
                interval = self.config.poll_intervals.get(
                    kind, REST_POLL_INTERVALS.get(kind, 60.0))
                if now < next_due[kind]:
                    continue
                next_due[kind] = now + interval
                for symbol in self.config.symbols:
                    if self._stop.is_set():
                        return
                    try:
                        if kind == "fundingRate":
                            url = build(symbol, base_url=self.config.rest_base_url)
                        else:
                            url = build(symbol, self.config.rest_base_url)
                        payload, _ = self._net_http_get(url, 15.0)
                        record = parse_rest_record(
                            kind, symbol, payload,
                            local_recv_ms=self._net_wall_ms(), run_id=self.config.run_id)
                        self.writer.append(kind, record)
                    except (OSError, ValueError, KeyError, TypeError) as exc:
                        logger.warning("recorder REST poll %s %s failed: %r", kind, symbol, exc)
            self._stop.wait(timeout=1.0)

    def _disk_loop(self) -> None:
        while not self._stop.is_set():
            try:
                free = self._net_disk_free()
            except OSError:
                free = -1
            if free >= 0 and free < self.config.disk_min_free_bytes:
                message = (f"recorder disk budget breached: free={free} < "
                           f"min={self.config.disk_min_free_bytes} at {self.run_dir}")
                logger.error(message)
                if self.config.alert is not None:
                    try:
                        self.config.alert(message)
                    except Exception:
                        logger.exception("recorder alert callback failed")
                if self.config.clean_stop_on_low_disk:
                    self._stop_reason = "low-disk"
                    self._stop.set()  # halt capture; owner calls stop() to seal.
                    return
            self._stop.wait(timeout=self.config.disk_check_s)
