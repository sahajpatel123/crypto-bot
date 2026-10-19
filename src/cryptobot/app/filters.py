"""Venue filter sourcing for run-mode strictness (manager-owned).

Builds complete :class:`InstrumentFilter` records from live public
exchangeInfo. Fail-closed: any missing/unparsable required field aborts
with an error — the session never trades on invented filters.

F0.4a adds leverage-bracket parsing for the LIVE liquidation gate.
GET /fapi/v1/leverageBracket is a SIGNED endpoint (needs API
credentials), so live fetching is a credentialed readiness step; the
pure parser below converts an already-fetched payload into tier maps
and is unit-tested without keys.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from cryptobot.market_data.discovery import fetch_exchange_info
from cryptobot.risk.types import InstrumentFilter

__all__ = ["FilterError", "build_run_filters", "parse_brackets_payload"]


class FilterError(ValueError):
    pass


def _required(filters: dict[str, dict], ftype: str, key: str,
              symbol: str) -> float:
    try:
        value = float(filters[ftype][key])
    except (KeyError, TypeError, ValueError):
        raise FilterError(
            f"{symbol}: missing/unparsable {ftype}.{key}") from None
    if value <= 0:
        raise FilterError(f"{symbol}: {ftype}.{key} must be > 0")
    return value


def build_run_filters(
    symbols: list[str],
    *,
    max_notional_cap_usdt: float,
    http_get: Callable[[str, float], tuple[Any, float]] | None = None,
) -> tuple[dict[str, InstrumentFilter], datetime]:
    """Fetch live filters for ``symbols``; returns (filters, asof_utc).

    ``max_notional_cap_usdt`` is the OPERATOR position cap (the venue
    publishes no max-notional filter); it also satisfies completeness until
    V-006-F1 makes it optional. Raises :class:`FilterError` fail-closed.
    """
    if max_notional_cap_usdt <= 0:
        raise FilterError("max_notional_cap_usdt must be > 0")
    if http_get is None:
        payload, _, fetched_at = fetch_exchange_info()
    else:
        payload, _, fetched_at = fetch_exchange_info(http_get=http_get)
    asof = datetime.fromisoformat(fetched_at)
    by_symbol = {str(s.get("symbol", "")).upper(): s
                 for s in payload.get("symbols", [])}
    out: dict[str, InstrumentFilter] = {}
    for symbol in symbols:
        entry = by_symbol.get(symbol.upper())
        if entry is None:
            raise FilterError(f"{symbol}: not on venue")
        if str(entry.get("status", "")).upper() != "TRADING":
            raise FilterError(f"{symbol}: status {entry.get('status')} != TRADING")
        filters = {f["filterType"]: f for f in entry.get("filters", [])}
        tick = _required(filters, "PRICE_FILTER", "tickSize", symbol)
        step = _required(filters, "LOT_SIZE", "stepSize", symbol)
        min_qty = _required(filters, "LOT_SIZE", "minQty", symbol)
        max_qty = _required(filters, "LOT_SIZE", "maxQty", symbol)
        market = filters.get("MARKET_LOT_SIZE", {})
        try:
            market_min = float(market["minQty"])
            market_max = float(market["maxQty"])
        except (KeyError, TypeError, ValueError):
            market_min = market_max = None
        try:
            min_notional = float(filters["MIN_NOTIONAL"]["notional"])
        except (KeyError, TypeError, ValueError):
            raise FilterError(f"{symbol}: missing MIN_NOTIONAL.notional") from None
        if min_notional < 0:
            raise FilterError(f"{symbol}: MIN_NOTIONAL.notional must be >= 0")
        filt = InstrumentFilter(
            min_notional_usdt=min_notional, qty_step=step,
            max_notional_usdt=max_notional_cap_usdt,
            min_qty=min_qty, max_qty=max_qty, tick_size=tick,
            market_min_qty=market_min, market_max_qty=market_max)
        if not filt.complete():
            raise FilterError(f"{symbol}: built record incomplete")
        out[symbol.upper()] = filt
    return out, asof


def parse_brackets_payload(
    payload: Any, symbols: list[str],
) -> dict[str, list[dict]]:
    """Parse a leverageBracket response into {SYMBOL: tiers} (F0.4a).

    Venue shape (Binance USD-M, strings-or-numbers):
    ``[{symbol, brackets: [{bracket, notionalCap, notionalFloor,
    maintMarginRatio, cum, ...}]}]``. Fail-closed: missing symbols,
    empty tiers, or unparsable cap/ratio raise FilterError. ``cum``
    defaults to 0.0 when absent. Tiers are returned sorted by cap.
    """
    if not isinstance(payload, list) or not payload:
        raise FilterError("brackets payload must be a non-empty list")
    if not symbols:
        raise FilterError("brackets: symbols required")
    by_symbol: dict[str, Any] = {}
    for entry in payload:
        if isinstance(entry, dict) and entry.get("symbol"):
            by_symbol[str(entry["symbol"]).upper()] = entry
    out: dict[str, list[dict]] = {}
    for symbol in symbols:
        entry = by_symbol.get(symbol.upper())
        if entry is None:
            raise FilterError(f"{symbol}: no leverageBracket entry")
        tiers = entry.get("brackets")
        if not isinstance(tiers, list) or not tiers:
            raise FilterError(f"{symbol}: empty brackets")
        parsed: list[dict] = []
        for tier in tiers:
            if not isinstance(tier, dict):
                raise FilterError(f"{symbol}: tier not an object")
            try:
                cap = float(tier["notionalCap"])
                ratio = float(tier["maintMarginRatio"])
                cum = float(tier.get("cum", 0.0))
            except (KeyError, TypeError, ValueError):
                raise FilterError(
                    f"{symbol}: tier missing notionalCap/maintMarginRatio"
                ) from None
            if cap <= 0:
                raise FilterError(f"{symbol}: notionalCap must be > 0")
            if not 0.0 <= ratio < 1.0:
                raise FilterError(
                    f"{symbol}: maintMarginRatio must lie in [0, 1)")
            parsed.append({"notionalCap": cap, "maintMarginRatio": ratio,
                           "cum": cum,
                           "bracket": tier.get("bracket")})
        parsed.sort(key=lambda t: t["notionalCap"])
        out[symbol.upper()] = parsed
    return out
