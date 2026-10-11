"""Dynamic USDT-perpetual metadata discovery (Worker 2, CONTRACTS v0.1.0).

Discovery reads the venue's live ``exchangeInfo`` and filters by contract
attributes only — there is deliberately NO hardcoded symbol whitelist, so new
listings appear and delistings drop out without a code change.

Size-aware eligibility ranks/filters the discovered universe by minimum
trade-size economics (``min_notional`` from MIN_NOTIONAL filters), so strategy
and risk layers never consider symbols the account cannot afford to trade.
"""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

FAPI_BASE_URL = "https://fapi.binance.com"
EXCHANGE_INFO_PATH = "/fapi/v1/exchangeInfo"

CONTRACT_VERSION = "v0.1.0"


@dataclass(frozen=True)
class SymbolMeta:
    symbol: str
    base_asset: str
    quote_asset: str
    contract_type: str
    status: str
    tick_size: float
    step_size: float
    min_notional: float | None  # None when the venue publishes no floor.
    price_precision: int
    quantity_precision: int


@dataclass(frozen=True)
class DiscoveryResult:
    symbols: tuple[SymbolMeta, ...]  # Discovered USDT perps, sorted by symbol.
    total_symbols_seen: int
    base_url: str
    fetched_at_utc: str
    fetch_latency_ms: float
    contract_version: str = CONTRACT_VERSION


def urllib_json_get(url: str, timeout_s: float = 15.0) -> tuple[Any, float]:
    """Default transport: stdlib HTTPS GET returning (parsed JSON, elapsed_ms)."""
    started = time.perf_counter()
    request = urllib.request.Request(url, headers={"User-Agent": "cryptobot-e001-discovery/0.1"})
    with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    return payload, (time.perf_counter() - started) * 1000.0


def fetch_exchange_info(
    http_get: Callable[[str, float], tuple[Any, float]] = urllib_json_get,
    base_url: str = FAPI_BASE_URL,
    timeout_s: float = 15.0,
) -> tuple[dict[str, Any], float, str]:
    """Fetch raw exchangeInfo. Returns (payload, latency_ms, fetched_at_utc)."""
    payload, latency_ms = http_get(base_url + EXCHANGE_INFO_PATH, timeout_s)
    if not isinstance(payload, dict) or "symbols" not in payload:
        raise ValueError("exchangeInfo payload missing 'symbols'")
    fetched_at = datetime.now(timezone.utc).isoformat()
    return payload, latency_ms, fetched_at


def _filter_value(filters: list[dict[str, Any]], ftype: str, key: str) -> float | None:
    for f in filters:
        if f.get("filterType") == ftype and key in f:
            try:
                return float(f[key])
            except (TypeError, ValueError):
                return None
    return None


def parse_symbol(entry: dict[str, Any]) -> SymbolMeta:
    filters = entry.get("filters", []) or []
    return SymbolMeta(
        symbol=str(entry.get("symbol", "")),
        base_asset=str(entry.get("baseAsset", "")),
        quote_asset=str(entry.get("quoteAsset", "")),
        contract_type=str(entry.get("contractType", "")),
        status=str(entry.get("status", "")),
        tick_size=_filter_value(filters, "PRICE_FILTER", "tickSize") or 0.0,
        step_size=_filter_value(filters, "LOT_SIZE", "stepSize") or 0.0,
        min_notional=(
            _filter_value(filters, "MIN_NOTIONAL", "notional")
            or _filter_value(filters, "NOTIONAL", "minNotional")
        ),
        price_precision=int(entry.get("pricePrecision", 0)),
        quantity_precision=int(entry.get("quantityPrecision", 0)),
    )


def discover_usdt_perps(
    payload: dict[str, Any],
    *,
    statuses: tuple[str, ...] = ("TRADING",),
    fetch_latency_ms: float = 0.0,
    fetched_at_utc: str = "",
    base_url: str = FAPI_BASE_URL,
) -> DiscoveryResult:
    """Filter live metadata to USDT-margined perpetuals. No symbol whitelist."""
    seen = 0
    found: list[SymbolMeta] = []
    for entry in payload.get("symbols", []):
        seen += 1
        meta = parse_symbol(entry)
        if meta.contract_type != "PERPETUAL":
            continue
        if meta.quote_asset != "USDT":
            continue
        if meta.status not in statuses:
            continue
        found.append(meta)
    found.sort(key=lambda m: m.symbol)
    return DiscoveryResult(
        symbols=tuple(found),
        total_symbols_seen=seen,
        base_url=base_url,
        fetched_at_utc=fetched_at_utc or datetime.now(timezone.utc).isoformat(),
        fetch_latency_ms=fetch_latency_ms,
    )


def eligible_symbols(
    result: DiscoveryResult,
    *,
    max_min_notional_usdt: float | None = None,
    require_known_floor: bool = False,
) -> tuple[SymbolMeta, ...]:
    """Size-aware eligibility: keep symbols whose minimum notional fits the budget.

    Symbols with an unknown floor (``min_notional is None``) are kept unless
    ``require_known_floor`` is set, and sort after all known-floor symbols.
    """
    kept = [m for m in result.symbols if max_min_notional_usdt is None or m.min_notional is None or m.min_notional <= max_min_notional_usdt]
    if require_known_floor:
        kept = [m for m in kept if m.min_notional is not None]
    kept.sort(key=lambda m: (m.min_notional is None, m.min_notional or 0.0, m.symbol))
    return tuple(kept)


def discovery_summary(result: DiscoveryResult, eligible: tuple[SymbolMeta, ...]) -> dict[str, Any]:
    return {
        "contract_version": result.contract_version,
        "base_url": result.base_url,
        "fetched_at_utc": result.fetched_at_utc,
        "fetch_latency_ms": round(result.fetch_latency_ms, 1),
        "total_symbols_seen": result.total_symbols_seen,
        "usdt_perp_trading": len(result.symbols),
        "eligible": len(eligible),
        "symbols": [m.symbol for m in result.symbols],
    }
