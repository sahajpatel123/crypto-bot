"""Binance USD-M public stream + REST poll definitions for the F3 recorder.

Covers BTCUSDT and ETHUSDT: aggTrade, bookTicker, depth@100ms, markPrice@1s,
and forceOrder (liquidations). Force orders have no per-symbol stream on
Binance USD-M: the venue publishes the all-market ``!forceOrder@arr`` stream
and consumers filter by symbol client-side.

Also ships REST poll specs (open interest, funding rate, premium index), a
USDC-perp presence check over live exchangeInfo (parse, never assume), an
exponential-backoff-with-jitter reconnect helper, and a DepthBook-backed
depth resync helper.
"""
from __future__ import annotations

import random
from typing import Any

from cryptobot.market_data.collector import MARKET_ROUTE, PUBLIC_ROUTE
from cryptobot.market_data.depth import DepthBook
from cryptobot.market_data.discovery import FAPI_BASE_URL

__all__ = [
    "SYMBOLS",
    "WS_CHANNELS",
    "MARKET_CHANNELS",
    "PUBLIC_CHANNELS",
    "FSTREAM_COMBINED",
    "FORCE_ORDER_ALL",
    "REST_POLL_INTERVALS",
    "build_binance_streams",
    "build_binance_urls",
    "open_interest_url",
    "funding_rate_url",
    "premium_index_url",
    "check_usdc_perps",
    "backoff_with_jitter",
    "resync_depth",
    "parse_force_order_message",
    "parse_rest_record",
]

SYMBOLS = ("BTCUSDT", "ETHUSDT")
WS_CHANNELS = ("aggTrade", "bookTicker", "depth@100ms", "markPrice@1s", "forceOrder")
MARKET_CHANNELS = ("aggTrade", "markPrice@1s")
PUBLIC_CHANNELS = ("bookTicker", "depth@100ms")

FSTREAM_COMBINED = "wss://fstream.binance.com/stream?streams="
FORCE_ORDER_ALL = "!forceOrder@arr"

REST_POLL_INTERVALS = {
    "openInterest": 60.0,
    "fundingRate": 300.0,
    "premiumIndex": 60.0,
}


def build_binance_streams(symbols: tuple[str, ...] = SYMBOLS) -> list[str]:
    """Combined-stream names for the recorder's Binance USD-M capture set."""
    streams: list[str] = []
    for symbol in symbols:
        low = symbol.lower()
        streams.append(f"{low}@aggTrade")
        streams.append(f"{low}@bookTicker")
        streams.append(f"{low}@depth@100ms")
        streams.append(f"{low}@markPrice@1s")
    streams.append(FORCE_ORDER_ALL)  # all-market liquidations; filter by symbol.
    return streams


def build_binance_urls(symbols: tuple[str, ...] = SYMBOLS) -> dict[str, str]:
    """Route-grouped websocket URLs (market / public / liquidations).

    Market and public routes mirror the E-006 collector split so the two
    capture paths stay comparable; liquidations ride the documented
    combined-stream endpoint.
    """
    market = "/".join(f"{s.lower()}@{c}" for s in symbols for c in MARKET_CHANNELS)
    public = "/".join(f"{s.lower()}@{c}" for s in symbols for c in PUBLIC_CHANNELS)
    return {
        "market": MARKET_ROUTE + market,
        "public": PUBLIC_ROUTE + public,
        "liquidations": FSTREAM_COMBINED + FORCE_ORDER_ALL,
    }


def open_interest_url(symbol: str, base_url: str = FAPI_BASE_URL) -> str:
    return f"{base_url}/fapi/v1/openInterest?symbol={symbol.upper()}"


def funding_rate_url(symbol: str, *, limit: int = 10, base_url: str = FAPI_BASE_URL) -> str:
    return f"{base_url}/fapi/v1/fundingRate?symbol={symbol.upper()}&limit={int(limit)}"


def premium_index_url(symbol: str, base_url: str = FAPI_BASE_URL) -> str:
    return f"{base_url}/fapi/v1/premiumIndex?symbol={symbol.upper()}"


def check_usdc_perps(exchange_info_payload: dict[str, Any]) -> list[str]:
    """USDC-margined BTC/ETH perp symbols present in an exchangeInfo payload.

    Parses only; never assumes listing status. Matches PERPETUAL contracts
    whose quote (or margin) asset is USDC and whose base asset is BTC or ETH.
    Returns a sorted, deduplicated symbol list ([] when absent or malformed).
    """
    if not isinstance(exchange_info_payload, dict):
        return []
    entries = exchange_info_payload.get("symbols", [])
    if not isinstance(entries, list):
        return []
    found: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            base = str(entry.get("baseAsset", "")).upper()
            quote = str(entry.get("quoteAsset", "")).upper()
            margin = str(entry.get("marginAsset", "") or "").upper()
            contract = str(entry.get("contractType", ""))
            symbol = str(entry.get("symbol", ""))
        except (TypeError, ValueError):
            continue
        if not symbol or contract != "PERPETUAL" or base not in ("BTC", "ETH"):
            continue
        if quote == "USDC" or margin == "USDC":
            found.add(symbol)
    return sorted(found)


def backoff_with_jitter(
    attempt: int,
    *,
    base: float = 1.0,
    cap: float = 60.0,
    rng: random.Random | None = None,
) -> float:
    """Exponential backoff with half-jitter: ``min(cap, base*2^attempt)`` scaled
    uniformly into [0.5x, 1.0x]. ``rng`` accepts a seeded ``random.Random``
    for deterministic tests; otherwise the global RNG is used."""
    grown = min(float(cap), float(base) * (2 ** max(0, int(attempt))))
    draw = rng.random() if rng is not None else random.random()
    return grown * (0.5 + 0.5 * draw)


def resync_depth(symbol: str, rest_snapshot: dict[str, Any]) -> bool:
    """Install a REST depth snapshot into a fresh DepthBook. Returns True when
    the book reports synced. Malformed snapshots return False (never raise)."""
    try:
        book = DepthBook(str(symbol))
        outcome = book.on_snapshot(
            rest_snapshot["bids"], rest_snapshot["asks"], rest_snapshot["lastUpdateId"]
        )
        return outcome == "synced" and book.state.synced
    except (KeyError, TypeError, ValueError):
        return False


def parse_force_order_message(
    message: dict[str, Any],
    *,
    local_recv_ms: int,
    run_id: str,
    seq: int = 0,
) -> dict[str, Any]:
    """Normalize one Binance ``forceOrder`` (liquidation) message.

    Accepts combined-stream envelopes ({"stream","data"}) and bare payloads.
    Raises ValueError on malformed input.
    """
    if "data" in message and "stream" in message:
        payload: Any = message["data"]
    else:
        payload = message
    if not isinstance(payload, dict):
        raise ValueError("forceOrder payload is not an object")
    order = payload.get("o")
    if not isinstance(order, dict):
        raise ValueError("forceOrder payload missing 'o'")
    symbol = str(order.get("s", "")).upper()
    if not symbol:
        raise ValueError("forceOrder has no symbol")
    try:
        return {
            "v": 1,
            "format": "cryptobot-events/1",
            "input_class": "observed-public",
            "source": "binance-fapi-ws",
            "route": "liquidations",
            "run_id": run_id,
            "seq": int(seq),
            "channel": "forceOrder",
            "symbol": symbol,
            "exchange_ts_ms": int(payload["E"]),
            "local_recv_ms": int(local_recv_ms),
            "gap_kind": None,
            "venue_seq": None,
            "payload": {
                "side": str(order["S"]),
                "order_type": str(order["o"]),
                "time_in_force": str(order["f"]),
                "orig_qty": float(order["q"]),
                "price": float(order["p"]),
                "avg_price": float(order["ap"]),
                "status": str(order["X"]),
                "last_filled_qty": float(order["l"]),
                "filled_accum_qty": float(order["z"]),
                "order_ts_ms": int(order["T"]),
            },
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed forceOrder fields: {exc}") from exc


def parse_rest_record(
    kind: str,
    symbol: str,
    payload: Any,
    *,
    local_recv_ms: int,
    run_id: str,
) -> dict[str, Any]:
    """Wrap one REST poll response (openInterest / fundingRate / premiumIndex)
    in a recorder chunk record. Raises ValueError on malformed input."""
    if kind not in REST_POLL_INTERVALS:
        raise ValueError(f"unknown REST poll kind: {kind!r}")
    if not isinstance(payload, (dict, list)):
        raise ValueError(f"{kind} payload is not an object")
    return {
        "v": 1,
        "format": "cryptobot-rest-polls/1",
        "input_class": "observed-public",
        "source": "binance-fapi-rest",
        "route": "rest",
        "run_id": run_id,
        "channel": kind,
        "symbol": str(symbol).upper(),
        "local_recv_ms": int(local_recv_ms),
        "gap_kind": None,
        "payload": payload,
    }
