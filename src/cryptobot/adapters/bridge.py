"""Live public-market bridge iterator (Worker 2, E-007).

:func:`live_events` streams NORMALIZED public events (the same record shape
the file collector writes to ``events.jsonl``) for the session live-paper
loop. Public data only — no credentials, no private endpoints, no order
submission on this path.

Depth diffs are normalized but NOT synchronized here; consumers needing the
synced book use :func:`cryptobot.market_data.bridge.iter_market_stream`
(file captures with persisted snapshots) and sync client-side.
"""
from __future__ import annotations

import json
import select
import socket
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

from cryptobot.market_data.collector import MARKET_ROUTE, PUBLIC_ROUTE, select_capture_set
from cryptobot.market_data.discovery import (
    FAPI_BASE_URL,
    discover_usdt_perps,
    fetch_exchange_info,
    urllib_json_get,
)
from cryptobot.market_data.events import parse_message
from cryptobot.market_data.ws import WsClient, WsClosed

__all__ = ["live_events"]

_MARKET_STREAMS = ("aggTrade", "markPrice@1s")
_PUBLIC_STREAMS = ("bookTicker", "depth@100ms")


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
) -> Iterator[dict[str, Any]]:
    """Yield normalized public events until the consumer stops iterating.

    ``symbols=None`` selects the top-``max_symbols`` USDT perps by 24h quote
    volume via live discovery (recomputed once per call); an explicit list is
    used verbatim (upper-cased). Each record matches the file-collector event
    shape (``v/format/input_class/source/route/run_id/seq/channel/symbol/
    exchange_ts_ms/local_recv_ms/local_mono_ns/gap_kind/venue_seq/payload``).
    Reconnects are labeled ``gap_kind="natural"`` on the next record per
    route; routes-exhausted raises ConnectionError (never trade blind).
    """
    if symbols is not None:
        chosen = tuple(s.upper() for s in symbols)
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
    run_id = f"live-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    conns: dict[str, WsClient] = {}
    pending_gap: dict[str, str | None] = {"market": None, "public": None}
    reconnects = {"market": 0, "public": 0}
    seq = 0

    def _open(route: str) -> None:
        sock = connect(_stream_url(route, chosen))
        sock.native_socket.settimeout(0.2)
        conns[route] = sock

    try:
        for route in ("market", "public"):
            _open(route)
        while True:
            if not conns:
                time.sleep(0.2)
                continue
            try:
                readable, _, _ = select.select(
                    [c.native_socket for c in conns.values()], [], [], 0.2)
            except (OSError, ValueError):
                readable = []
            routes = {id(c.native_socket): r for r, c in conns.items()}
            for sock in readable:
                route = routes.get(id(sock))
                if route is None:
                    continue
                try:
                    kind, payload_bytes = conns[route].recv_message(timeout_s=10.0)
                except WsClosed:
                    reconnects[route] += 1
                    if reconnects[route] > max_reconnects:
                        raise ConnectionError(
                            f"routes-exhausted: {route} exceeded "
                            f"{max_reconnects} reconnects") from None
                    time.sleep(min(2.0 ** reconnects[route], 10.0))
                    try:
                        _open(route)
                    except OSError:
                        continue
                    pending_gap[route] = "natural"
                    continue
                if kind != "text":
                    continue
                try:
                    message = json.loads(payload_bytes.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    continue  # malformed frame: skip, stream continues.
                seq += 1
                recv_wall = int(time.time() * 1000)
                recv_mono = time.perf_counter_ns()
                try:
                    event = parse_message(message, route=route, local_recv_ms=recv_wall,
                                          local_mono_ns=recv_mono, seq=seq, run_id=run_id)
                except (ValueError, KeyError, TypeError):
                    continue  # unparseable message: skip, stream continues.
                gap = pending_gap.get(route)
                if gap is not None:
                    event["gap_kind"] = gap
                    pending_gap[route] = None
                yield event
    finally:
        for conn in conns.values():
            try:
                conn.close()
            except (OSError, WsClosed):
                pass
