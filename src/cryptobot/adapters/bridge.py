"""Live public-market bridge iterator (Worker 2, E-008).

:func:`live_events` streams NORMALIZED public events (the same record shape
the file collector writes to ``events.jsonl``) for the session live-paper
loop. Public data only — no credentials, no private endpoints, no order
submission on this path.

Depth diffs are normalized but NOT synchronized here; consumers needing the
synced book use :func:`cryptobot.market_data.bridge.iter_market_stream`
(file captures with persisted snapshots) and sync client-side.

Liveness (B3): the iterator yields ``None`` as a 1 s idle heartbeat, so the
consumer never blocks more than ~1 s on ``next()`` in steady state — each
wake (event or ``None``) ticks session timers, and the pump advances engine
time on ``None`` so stops/GTD expire in quiet markets. Cumulative stats go
to the optional ``stats`` dict (updated in place). The only unbounded-ish
op is the socket dial itself (bounded by the callee: ``WsClient.connect``
defaults to a 10 s timeout); reconnect backoff sleeps are chunked so
heartbeats keep flowing through them.

Transport (E-009): routes are polled round-robin via
``recv_message_nowait`` — one message per route per pass — so complete
application-buffered messages and TLS pending data drain without awaiting
new kernel readability, and a bursting route cannot starve a quiet one.
``select`` is only an idle sleep. A route holding incomplete bytes for
over 5 s is treated as sick and reconnected.
"""
from __future__ import annotations

import json
import select
import time
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

from cryptobot.market_data.collector import MARKET_ROUTE, PUBLIC_ROUTE, select_capture_set
from cryptobot.market_data.discovery import (
    FAPI_BASE_URL,
    fetch_exchange_info,
    urllib_json_get,
)
from cryptobot.market_data.events import parse_message
from cryptobot.market_data.ws import WsClient, WsClosed

__all__ = ["live_events"]

_MARKET_STREAMS = ("aggTrade", "markPrice@1s")
_PUBLIC_STREAMS = ("bookTicker", "depth@100ms")

_SELECT_TIMEOUT_S = 0.2
_STALE_PARTIAL_S = 5.0  # buffered-but-incomplete bytes this old mean a sick connection.


def _stream_url(route: str, symbols: tuple[str, ...]) -> str:
    base = MARKET_ROUTE if route == "market" else PUBLIC_ROUTE
    kinds = _MARKET_STREAMS if route == "market" else _PUBLIC_STREAMS
    streams = "/".join(f"{s.lower()}@{k}" for s in symbols for k in kinds)
    return base + streams


def live_events(
    symbols: list[str] | tuple[str, ...] | None = None,
    max_symbols: int = 8,
    *,
    connect: Callable[[str], WsClient] = WsClient.connect,
    rest_get: Callable = urllib_json_get,
    max_reconnects: int = 10,
    heartbeat_every_s: float = 1.0,
    stats: dict[str, Any] | None = None,
    stale_partial_s: float = _STALE_PARTIAL_S,
    ws_host: str | None = None,
    max_hf_subscriptions: int | None = None,
) -> Iterator[dict[str, Any] | None]:
    """Yield normalized public events until the consumer stops iterating.

    ``symbols=None`` selects the top-``max_symbols`` USDT perps by 24h quote
    volume via live discovery (recomputed once per call); an explicit list is
    used verbatim (upper-cased). Each record matches the file-collector event
    shape (``v/format/input_class/source/route/run_id/seq/channel/symbol/
    exchange_ts_ms/local_recv_ms/local_mono_ns/gap_kind/venue_seq/payload``).
    Reconnects are labeled ``gap_kind="natural"`` on the next record per
    route; routes-exhausted raises ConnectionError (never trade blind).

    ``None`` is yielded whenever the stream has been quiet for
    ``heartbeat_every_s`` (B3 1 s idle heartbeat; heartbeats do not consume
    run seq). When ``stats`` is given it is updated in place on every wake
    with ``events``, ``heartbeats``, ``reconnects`` (per route),
    ``malformed_frames``, ``uptime_s``, ``symbols``, and ``pending_gap``.
    A route holding incomplete buffered bytes for over ``stale_partial_s``
    is reconnected as sick (quiet routes with zero bytes never trip).
    """
    if symbols is not None:
        chosen = tuple(s.upper() for s in symbols)
        if max_hf_subscriptions is not None:
            # T2.2: honour the HF subscription cap — evaluate at most
            # this many symbols (default evaluating set BTC/ETH).
            chosen = chosen[:max(0, int(max_hf_subscriptions))]
        if not chosen:
            raise ValueError("symbols must be non-empty when given")
        if len(chosen) > max_symbols:
            raise ValueError(f"{len(chosen)} symbols exceed max_symbols={max_symbols}")
    else:
        payload, _, _ = fetch_exchange_info(rest_get, FAPI_BASE_URL)
        chosen, _, _ = select_capture_set(payload, rest_get, FAPI_BASE_URL,
                                          top_n=max_symbols)
        if not chosen:
            raise RuntimeError("discovery returned no symbols")
    run_id = f"live-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    conns: dict[str, WsClient] = {}
    pending_gap: dict[str, str | None] = {"market": None, "public": None}
    reconnects = {"market": 0, "public": 0}
    counts = {"events": 0, "heartbeats": 0, "malformed": 0}
    seq = 0
    start_mono = time.perf_counter_ns()
    last_yield_mono = start_mono

    def _open(route: str) -> None:
        url = _stream_url(route, chosen)
        if ws_host:
            # Demo/test routing (P5): sockets dial the adapter's stream
            # host instead of production fstream.
            import urllib.parse
            parts = urllib.parse.urlsplit(url)
            host = ws_host.split("://", 1)[-1].rstrip("/")
            url = urllib.parse.urlunsplit(
                (parts.scheme, host, parts.path, parts.query, parts.fragment))
        sock = connect(url)
        sock.native_socket.settimeout(_SELECT_TIMEOUT_S)
        conns[route] = sock

    def _heartbeat_due() -> bool:
        return ((time.perf_counter_ns() - last_yield_mono) / 1e9
                >= heartbeat_every_s)

    def _refresh_stats() -> None:
        if stats is None:
            return
        stats.update({
            "events": counts["events"], "heartbeats": counts["heartbeats"],
            "reconnects": dict(reconnects),
            "malformed_frames": counts["malformed"],
            "uptime_s": (time.perf_counter_ns() - start_mono) / 1e9,
            "symbols": list(chosen),
            "pending_gap": {r: (g is not None) for r, g in pending_gap.items()},
        })

    def _heartbeat() -> None:
        nonlocal last_yield_mono
        last_yield_mono = time.perf_counter_ns()
        counts["heartbeats"] += 1
        _refresh_stats()
        return None

    def _reconnect(route: str) -> Iterator[None]:
        """Back off (chunked, beats flow), reopen, and label the gap natural."""
        reconnects[route] += 1
        if reconnects[route] > max_reconnects:
            raise ConnectionError(
                f"routes-exhausted: {route} exceeded "
                f"{max_reconnects} reconnects") from None
        deadline = time.monotonic() + min(2.0 ** reconnects[route], 10.0)
        while time.monotonic() < deadline:  # chunked: beats flow through.
            time.sleep(max(0.0, min(_SELECT_TIMEOUT_S, deadline - time.monotonic())))
            if _heartbeat_due():
                yield _heartbeat()
        try:
            _open(route)
        except OSError:
            return
        last_msg_mono[route] = time.perf_counter_ns()
        pending_gap[route] = "natural"

    def _normalize(route: str, kind: str, payload_bytes: bytes,
                   ) -> dict[str, Any] | None:
        nonlocal seq, last_yield_mono
        if kind != "text":
            counts["malformed"] += 1
            return None
        try:
            message = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            counts["malformed"] += 1
            return None  # malformed frame: skip, stream continues.
        seq += 1
        recv_wall = int(time.time() * 1000)
        recv_mono = time.perf_counter_ns()
        try:
            event = parse_message(message, route=route, local_recv_ms=recv_wall,
                                  local_mono_ns=recv_mono, seq=seq, run_id=run_id)
        except (ValueError, KeyError, TypeError):
            counts["malformed"] += 1
            return None  # unparseable message: skip, stream continues.
        gap = pending_gap.get(route)
        if gap is not None:
            event["gap_kind"] = gap
            pending_gap[route] = None
        last_yield_mono = recv_mono
        last_msg_mono[route] = recv_mono
        counts["events"] += 1
        _refresh_stats()
        return event

    last_msg_mono = {"market": start_mono, "public": start_mono}
    turn: list[str] = ["market", "public"]  # rotated each pass: fair service.
    try:
        for route in ("market", "public"):
            _open(route)
        while True:
            if _heartbeat_due():
                yield _heartbeat()
            if not conns:
                time.sleep(_SELECT_TIMEOUT_S)
                continue
            progressed = False
            for route in list(turn):
                conn = conns.get(route)
                if conn is None:
                    continue
                try:
                    message = conn.recv_message_nowait()
                except WsClosed:
                    yield from _reconnect(route)
                    progressed = True
                    continue
                if message is None:
                    continue
                progressed = True
                event = _normalize(route, *message)
                if event is not None:
                    yield event
            turn = turn[1:] + turn[:1]
            if progressed:
                continue  # work-conserving: never sleep while messages flow.
            now_mono = time.perf_counter_ns()
            for route, conn in conns.items():
                buffered = getattr(conn, "buffered_bytes", 0)
                if buffered and (now_mono - last_msg_mono[route]) / 1e9 > stale_partial_s:
                    yield from _reconnect(route)  # sick: bytes never assemble.
                    break
            else:
                # Idle: sleep until kernel data or the next beat (never spin).
                beat_in = heartbeat_every_s - (now_mono - last_yield_mono) / 1e9
                try:
                    select.select([c.native_socket for c in conns.values()],
                                  [], [], max(0.0, min(_SELECT_TIMEOUT_S, beat_in)))
                except (OSError, ValueError):
                    time.sleep(_SELECT_TIMEOUT_S)  # dead socket set: never spin.
    finally:
        for conn in conns.values():
            try:
                conn.close()
            except (OSError, WsClosed):
                pass
