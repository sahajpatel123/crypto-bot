"""Normalized public-stream event records (Worker 2, E-006).

Every captured venue message becomes one normalized record carrying full
provenance: exchange event time, local wall-clock receipt, monotonic
processing time, venue/channel sequence IDs, route, labels, and config.
Raw payloads are preserved verbatim alongside (see collector storage).

No microstructure is ever fabricated: buy_frac/spread-class quantities are
computed only from actually observed fields (trade side flags, BBO quotes),
and missing inputs stay missing.
"""
from __future__ import annotations

import math
from typing import Any

from .recorder import INPUT_OBSERVED

EVENT_FORMAT = "cryptobot-events/1"

CHANNELS = ("aggTrade", "bookTicker", "depth", "markPrice")


def _finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} is not numeric: {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} is not finite: {value!r}")
    return number


def _int_ms(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} is not a millisecond timestamp: {value!r}")
    return int(value)


def channel_of(stream: str) -> str:
    """Map a combined-stream name (or bare event type) to a known channel."""
    low = stream.lower()
    if "aggtrade" in low:
        return "aggTrade"
    if "bookticker" in low:
        return "bookTicker"
    if low.startswith("depth") or "@depth" in low or low == "depthupdate":
        return "depth"
    if "markprice" in low:
        return "markPrice"
    raise ValueError(f"unknown channel for stream: {stream!r}")


def parse_message(
    message: dict[str, Any],
    *,
    route: str,
    local_recv_ms: int,
    local_mono_ns: int,
    seq: int,
    run_id: str,
) -> dict[str, Any]:
    """Parse one decoded websocket message into a normalized event record.

    Accepts combined-stream envelopes ({"stream","data"}) and bare payloads.
    Raises ValueError on malformed input; the collector counts and quarantines
    such messages instead of crashing.
    """
    if "data" in message and "stream" in message:
        stream_name = str(message["stream"])
        payload = message["data"]
    else:
        stream_name = str(message.get("e", ""))
        payload = message
    if not isinstance(payload, dict):
        raise ValueError("message payload is not an object")
    channel = channel_of(stream_name or payload.get("e", ""))
    symbol = str(payload.get("s", "")).upper()
    if not symbol:
        raise ValueError("message has no symbol")
    exchange_ts_ms = _int_ms(payload.get("E", payload.get("T")), "event time")
    record: dict[str, Any] = {
        "v": 1,
        "format": EVENT_FORMAT,
        "input_class": INPUT_OBSERVED,
        "source": "binance-fapi-ws",
        "route": route,
        "run_id": run_id,
        "seq": seq,
        "channel": channel,
        "symbol": symbol,
        "exchange_ts_ms": exchange_ts_ms,
        "local_recv_ms": int(local_recv_ms),
        "local_mono_ns": int(local_mono_ns),
        "gap_kind": None,  # set by the collector on natural/injected discontinuities.
        "venue_seq": None,
        "payload": {},
    }
    if channel == "aggTrade":
        record["venue_seq"] = int(payload["a"])
        record["payload"] = {
            "agg_id": int(payload["a"]),
            "price": _finite(payload["p"], "trade price"),
            "qty": _finite(payload["q"], "trade qty"),
            "first_id": int(payload["f"]),
            "last_id": int(payload["l"]),
            "trade_ts_ms": _int_ms(payload["T"], "trade time"),
            "buyer_is_maker": bool(payload["m"]),
        }
    elif channel == "bookTicker":
        record["venue_seq"] = int(payload["u"])
        record["payload"] = {
            "update_id": int(payload["u"]),
            "bid": _finite(payload["b"], "bid"),
            "bid_qty": _finite(payload["B"], "bid qty"),
            "ask": _finite(payload["a"], "ask"),
            "ask_qty": _finite(payload["A"], "ask qty"),
            "book_ts_ms": _int_ms(payload.get("T", payload.get("E")), "book time"),
        }
    elif channel == "depth":
        record["venue_seq"] = int(payload["u"])
        record["payload"] = {
            "first_update": int(payload["U"]),
            "last_update": int(payload["u"]),
            "prev_last_update": int(payload["pu"]),
            "bids": [[_finite(p, "bid price"), _finite(q, "bid qty")] for p, q in payload["b"]],
            "asks": [[_finite(p, "ask price"), _finite(q, "ask qty")] for p, q in payload["a"]],
        }
    elif channel == "markPrice":
        record["payload"] = {
            "mark": _finite(payload["p"], "mark price"),
            "funding_rate": _finite(payload["r"], "funding rate"),
            "next_funding_ms": _int_ms(payload["T"], "next funding time"),
        }
        for key in ("i", "P"):
            if key in payload and payload[key] is not None:
                record["payload"][key] = _finite(payload[key], f"mark field {key}")
    return record


def raw_envelope(
    message: dict[str, Any],
    *,
    route: str,
    local_recv_ms: int,
    local_mono_ns: int,
    seq: int,
    run_id: str,
) -> dict[str, Any]:
    """Wrap the verbatim venue message with receipt provenance (raw file)."""
    return {
        "v": 1,
        "format": EVENT_FORMAT,
        "input_class": INPUT_OBSERVED,
        "source": "binance-fapi-ws",
        "route": route,
        "run_id": run_id,
        "seq": seq,
        "local_recv_ms": int(local_recv_ms),
        "local_mono_ns": int(local_mono_ns),
        "raw": message,
    }
