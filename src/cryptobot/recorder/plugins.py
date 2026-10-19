"""Venue plugin interface + Bybit/OKX stubs (F3 data engine).

Only the Binance path is implemented. Bybit and OKX exist as explicitly
marked STUBS behind config flags: constructing one with ``enabled=False``
(the default) raises :class:`PluginDisabled` on any use, and the enabled
path raises ``NotImplementedError`` with a TODO. Endpoint references below
are from memory and labelled UNVERIFIED — confirm against live venue docs
before implementing.
"""
from __future__ import annotations

from typing import Any, Protocol

__all__ = [
    "VenuePlugin",
    "PluginDisabled",
    "BybitPlugin",
    "OKXPlugin",
    "BYBIT_ENDPOINTS_UNVERIFIED",
    "OKX_ENDPOINTS_UNVERIFIED",
]


class PluginDisabled(Exception):
    """Raised when a venue plugin is used without enabled=True."""


class VenuePlugin(Protocol):
    """Interface every venue capture plugin implements."""

    @property
    def name(self) -> str: ...

    def streams(self) -> list[str]:
        """Channel/topic names this venue would subscribe to."""
        ...

    def connect(self) -> None:
        """Open venue connections (WS and/or REST session)."""
        ...

    def poll_once(self) -> list[dict[str, Any]]:
        """Collect one batch of normalized events (empty when idle)."""
        ...

    def close(self) -> None:
        """Release venue connections."""
        ...


# UNVERIFIED (from memory): confirm against live Bybit V5 docs before use.
BYBIT_ENDPOINTS_UNVERIFIED = {
    "ws_public_linear": "wss://stream.bybit.com/v5/public/linear",
    "ws_topics": ["publicTrade.{base}USDT", "orderbook.1.{base}USDT"],
    "rest_tickers": "https://api.bybit.com/v5/market/tickers?category=linear&symbol={symbol}",
    "rest_orderbook": "https://api.bybit.com/v5/market/orderbook?category=linear&symbol={symbol}",
    "notes": "Linear perps, BTC/ETH only. Auth not required for public topics.",
}

# UNVERIFIED (from memory): confirm against live OKX docs before use.
OKX_ENDPOINTS_UNVERIFIED = {
    "ws_public": "wss://ws.okx.com:8443/ws/v5/public",
    "ws_channels": ["trades", "books"],
    "ws_inst_ids": ["BTC-USDT-SWAP", "ETH-USDT-SWAP"],
    "rest_ticker": "https://www.okx.com/api/v5/market/ticker?instId={inst_id}",
    "rest_books": "https://www.okx.com/api/v5/market/books?instId={inst_id}",
    "notes": "USDT-margined perpetual swaps (SWAP instType), BTC/ETH only.",
}


class BybitPlugin:
    """STUB: Bybit V5 linear-perp trades + top-of-book for BTC/ETH.

    TODO: implement connect()/poll_once() against BYBIT_ENDPOINTS_UNVERIFIED
    (verify endpoints first), normalizing to cryptobot-events/1 records.
    """

    def __init__(self, symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT"),
                 enabled: bool = False) -> None:
        self._symbols = tuple(symbols)
        self._enabled = bool(enabled)

    @property
    def name(self) -> str:
        return "bybit"

    def streams(self) -> list[str]:
        self._require_enabled()
        out: list[str] = []
        for symbol in self._symbols:
            base = symbol.replace("USDT", "")
            out.append(f"publicTrade.{base}USDT")
            out.append(f"orderbook.1.{base}USDT")
        return out

    def connect(self) -> None:
        self._require_enabled()
        raise NotImplementedError(
            "STUB: Bybit plugin not implemented. TODO: subscribe to "
            "BYBIT_ENDPOINTS_UNVERIFIED['ws_public_linear'] topics; verify "
            "endpoints against live Bybit V5 docs first."
        )

    def poll_once(self) -> list[dict[str, Any]]:
        self._require_enabled()
        raise NotImplementedError("STUB: Bybit plugin not implemented (see connect TODO).")

    def close(self) -> None:
        return None

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise PluginDisabled("BybitPlugin requires enabled=True (stub; not implemented)")


class OKXPlugin:
    """STUB: OKX USDT-margined swap trades + books for BTC/ETH.

    TODO: implement connect()/poll_once() against OKX_ENDPOINTS_UNVERIFIED
    (verify endpoints first), normalizing to cryptobot-events/1 records.
    """

    def __init__(self, symbols: tuple[str, ...] = ("BTC-USDT-SWAP", "ETH-USDT-SWAP"),
                 enabled: bool = False) -> None:
        self._symbols = tuple(symbols)
        self._enabled = bool(enabled)

    @property
    def name(self) -> str:
        return "okx"

    def streams(self) -> list[str]:
        self._require_enabled()
        return [f"{ch}:{inst}" for inst in self._symbols for ch in ("trades", "books")]

    def connect(self) -> None:
        self._require_enabled()
        raise NotImplementedError(
            "STUB: OKX plugin not implemented. TODO: subscribe to "
            "OKX_ENDPOINTS_UNVERIFIED['ws_public'] channels; verify "
            "endpoints against live OKX docs first."
        )

    def poll_once(self) -> list[dict[str, Any]]:
        self._require_enabled()
        raise NotImplementedError("STUB: OKX plugin not implemented (see connect TODO).")

    def close(self) -> None:
        return None

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise PluginDisabled("OKXPlugin requires enabled=True (stub; not implemented)")
