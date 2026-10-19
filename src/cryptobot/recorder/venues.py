"""Venue plugin interface + Bybit/OKX stubs (no network; injectable transport)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

Transport = Callable[..., Any]


@runtime_checkable
class VenuePlugin(Protocol):
    name: str

    def normalize_trade(self, raw: dict[str, Any]) -> dict[str, Any]: ...
    def normalize_book_ticker(self, raw: dict[str, Any]) -> dict[str, Any]: ...
    # alias name used by some callers
    def normalize_top_of_book(self, raw: dict[str, Any]) -> dict[str, Any]: ...


def _ts(raw: dict[str, Any], *keys: str) -> int:
    for k in keys:
        if raw.get(k) is not None:
            try:
                return int(float(raw[k]))  # handles "171..." strings
            except Exception:
                pass
    return 0


class BybitPlugin:
    name = "bybit"
    venue = "bybit"

    def __init__(
        self,
        transport: Transport | None = None,
        *,
        enabled: bool = True,
        config: dict[str, Any] | None = None,
    ):
        if config is not None:
            enabled = bool(config.get("bybit_enabled", config.get("enabled", enabled)))
        self.enabled = enabled
        self.transport = transport

    def _require(self) -> None:
        if not self.enabled:
            raise RuntimeError("bybit plugin disabled by config flag")

    def normalize_trade(self, raw: dict[str, Any]) -> dict[str, Any]:
        self._require()
        symbol = raw.get("symbol") or raw.get("s") or "BTCUSDT"
        price = raw.get("price", raw.get("p", raw.get("px")))
        qty = raw.get("size", raw.get("qty", raw.get("q", raw.get("sz"))))
        ts = _ts(raw, "time", "ts", "T", "timestamp", "execTime") or _ts(raw, "E")
        tid = raw.get("id", raw.get("trade_id", raw.get("execId", raw.get("a"))))
        data: dict[str, Any] = {
            "price": float(price) if price is not None else None,
            "qty": float(qty) if qty is not None else None,
            "trade_id": tid,
            "venue": "bybit",
        }
        if raw.get("side") is not None:
            data["side"] = raw["side"]
        return {"stream": "aggTrade", "symbol": str(symbol), "ts": ts, "local_ts": ts, "data": data}

    def normalize_book_ticker(self, raw: dict[str, Any]) -> dict[str, Any]:
        self._require()
        symbol = raw.get("symbol") or raw.get("s") or "BTCUSDT"
        ts = _ts(raw, "ts", "time", "timestamp", "E", "cts")
        bid = raw.get("bid1Price", raw.get("bid_price", raw.get("bp", raw.get("best_bid"))))
        bidq = raw.get("bid1Size", raw.get("bid_qty", raw.get("bq", raw.get("bid_size"))))
        ask = raw.get("ask1Price", raw.get("ask_price", raw.get("ap", raw.get("best_ask"))))
        askq = raw.get("ask1Size", raw.get("ask_qty", raw.get("aq", raw.get("ask_size"))))
        # also support nested bid/ask arrays
        if bid is None and isinstance(raw.get("b"), list) and raw["b"]:
            bid, bidq = raw["b"][0], raw["b"][1] if len(raw["b"]) > 1 else None
        if ask is None and isinstance(raw.get("a"), list) and raw["a"]:
            ask, askq = raw["a"][0], raw["a"][1] if len(raw["a"]) > 1 else None
        data = {
            "bid_price": float(bid) if bid is not None else None,
            "bid_qty": float(bidq) if bidq is not None else None,
            "ask_price": float(ask) if ask is not None else None,
            "ask_qty": float(askq) if askq is not None else None,
            "venue": "bybit",
        }
        return {
            "stream": "bookTicker",
            "symbol": str(symbol),
            "ts": ts,
            "local_ts": ts,
            "data": data,
        }

    normalize_top_of_book = normalize_book_ticker

    def fetch_trades(self, symbol: str = "BTCUSDT") -> list[dict[str, Any]]:
        self._require()
        if self.transport is None:
            return []
        payload = self.transport("trades", symbol=symbol)  # type: ignore[operator]
        items = (
            payload
            if isinstance(payload, list)
            else (payload.get("result", {}).get("list", []) if isinstance(payload, dict) else [])
        )
        return [self.normalize_trade(x) for x in items]


class OKXPlugin:
    name = "okx"
    venue = "okx"

    def __init__(
        self,
        transport: Transport | None = None,
        *,
        enabled: bool = True,
        config: dict[str, Any] | None = None,
    ):
        if config is not None:
            enabled = bool(config.get("okx_enabled", config.get("enabled", enabled)))
        self.enabled = enabled
        self.transport = transport

    def _require(self) -> None:
        if not self.enabled:
            raise RuntimeError("okx plugin disabled by config flag")

    @staticmethod
    def _symbol(raw: dict[str, Any]) -> str:
        s = str(raw.get("symbol") or raw.get("instId") or raw.get("s") or "BTCUSDT")
        # BTC-USDT-SWAP -> BTCUSDT ; BTC-USDT -> BTCUSDT
        return s.replace("-", "").replace("SWAP", "")

    def normalize_trade(self, raw: dict[str, Any]) -> dict[str, Any]:
        self._require()
        price = raw.get("px", raw.get("price", raw.get("p")))
        qty = raw.get("sz", raw.get("qty", raw.get("size", raw.get("q"))))
        ts = _ts(raw, "ts", "time", "timestamp", "T", "E")
        tid = raw.get("tradeId", raw.get("trade_id", raw.get("id", raw.get("a"))))
        data: dict[str, Any] = {
            "price": float(price) if price is not None else None,
            "qty": float(qty) if qty is not None else None,
            "trade_id": tid,
            "venue": "okx",
        }
        if raw.get("side") is not None:
            data["side"] = raw["side"]
        return {
            "stream": "aggTrade",
            "symbol": self._symbol(raw),
            "ts": ts,
            "local_ts": ts,
            "data": data,
        }

    def normalize_book_ticker(self, raw: dict[str, Any]) -> dict[str, Any]:
        self._require()
        ts = _ts(raw, "ts", "time", "timestamp", "E")
        bid = raw.get("bidPx", raw.get("bid_price", raw.get("bp")))
        bidq = raw.get("bidSz", raw.get("bid_qty", raw.get("bq")))
        ask = raw.get("askPx", raw.get("ask_price", raw.get("ap")))
        askq = raw.get("askSz", raw.get("ask_qty", raw.get("aq")))
        if bid is None and isinstance(raw.get("bids"), list) and raw["bids"]:
            b0 = raw["bids"][0]
            bid, bidq = (
                (b0[0], b0[1] if len(b0) > 1 else None) if isinstance(b0, list) else (b0, None)
            )
        if ask is None and isinstance(raw.get("asks"), list) and raw["asks"]:
            a0 = raw["asks"][0]
            ask, askq = (
                (a0[0], a0[1] if len(a0) > 1 else None) if isinstance(a0, list) else (a0, None)
            )
        data = {
            "bid_price": float(bid) if bid is not None else None,
            "bid_qty": float(bidq) if bidq is not None else None,
            "ask_price": float(ask) if ask is not None else None,
            "ask_qty": float(askq) if askq is not None else None,
            "venue": "okx",
        }
        return {
            "stream": "bookTicker",
            "symbol": self._symbol(raw),
            "ts": ts,
            "local_ts": ts,
            "data": data,
        }

    normalize_top_of_book = normalize_book_ticker

    def fetch_trades(self, symbol: str = "BTC-USDT-SWAP") -> list[dict[str, Any]]:
        self._require()
        if self.transport is None:
            return []
        payload = self.transport("trades", symbol=symbol)  # type: ignore[operator]
        items = (
            payload
            if isinstance(payload, list)
            else (payload.get("data", []) if isinstance(payload, dict) else [])
        )
        return [self.normalize_trade(x) for x in items]


_PLUGINS = {"bybit": BybitPlugin, "okx": OKXPlugin}


def create_plugin(
    name: str, config: dict[str, Any] | None = None, transport: Transport | None = None
) -> Any:
    """Factory behind config flags. Returns None when the venue is disabled."""
    key = name.lower()
    if key not in _PLUGINS:
        raise ValueError(f"unknown venue plugin {name!r}")
    cfg = config or {}
    # flag keys: bybit_enabled / okx_enabled or generic enabled
    enabled = cfg.get(f"{key}_enabled", cfg.get("enabled", True))
    if not enabled:
        return None
    return _PLUGINS[key](transport=transport, enabled=True, config=cfg)


get_plugin = create_plugin
get_venue_plugin = create_plugin
