"""Tradable-universe scan + ranking + subscription selection (REL-W3-DATA 1).

Reads the venue's live USDT-perpetual metadata plus all-symbols public
market state (24h tickers, book tickers: three REST calls total), ranks
eligible instruments by observable liquidity, spread, depth, recent
volatility and capital/filter feasibility, and selects at most
``max_active`` high-frequency subscriptions — default TWO, because prior
measurements did not support eight. Expansion is an operator decision
after a bounded measured workload passes, never automatic.

Rebalance never drops management of an existing position: the position
symbol is always retained regardless of rank. Everything is
metadata-driven; no hardcoded coin logic (proven by the non-BTC/ETH
precision fixture in tests).
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .discovery import FAPI_BASE_URL, SymbolMeta, discover_usdt_perps, fetch_exchange_info

TICKER_24H_PATH = "/fapi/v1/ticker/24hr"
BOOK_TICKER_PATH = "/fapi/v1/ticker/bookTicker"
DEPTH_PATH = "/fapi/v1/depth"

DEFAULT_MAX_ACTIVE = 2
DEFAULT_CACHE_S = 3600.0
DEFAULT_DEPTH_TOP_K = 10
DEFAULT_DEPTH_LIMIT = 20


@dataclass(frozen=True)
class SymbolRank:
    symbol: str
    quote_volume_24h_usdt: float | None
    spread_bps: float | None
    range_bps_24h: float | None  # Daily-range proxy, NOT realized vol.
    depth_usdt_20: float | None  # Top-20-level notional; None unless enriched.
    min_notional: float | None
    tick_size: float
    step_size: float
    feasible: bool
    infeasible_reason: str
    score: float  # Higher is better; -inf when infeasible/unrankable.


@dataclass(frozen=True)
class UniverseSnapshot:
    metas: tuple[SymbolMeta, ...]
    tickers: dict[str, dict[str, Any]]
    books: dict[str, dict[str, Any]]
    fetched_at_utc: str
    latencies_ms: dict[str, float]
    cache_hit: bool


def _rest(http_get: Callable[[str, float], tuple[Any, float]],
          base_url: str, path: str, timeout_s: float) -> tuple[Any, float]:
    payload, latency_ms = http_get(base_url + path, timeout_s)
    return payload, latency_ms


def scan_universe(http_get: Callable[[str, float], tuple[Any, float]],
                  base_url: str = FAPI_BASE_URL,
                  timeout_s: float = 15.0,
                  *,
                  cache_path: Path | None = None,
                  cache_max_age_s: float = DEFAULT_CACHE_S,
                  now_utc: datetime | None = None) -> UniverseSnapshot:
    """Fetch metadata + all-symbols market state (3 REST calls), cached.

    The cache bounds scan cadence: a fresh cache (younger than
    ``cache_max_age_s``) is reused without any REST call. Stale cache is
    refreshed; refresh failure surfaces loudly (no silent stale reuse).
    """
    now = now_utc or datetime.now(UTC)
    if cache_path is not None and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text())
            age = (now - datetime.fromisoformat(cached["fetched_at_utc"])
                   ).total_seconds()
            if 0 <= age <= cache_max_age_s:
                return UniverseSnapshot(
                    metas=tuple(SymbolMeta(**m)
                                for m in cached["metas"]),
                    tickers=cached["tickers"], books=cached["books"],
                    fetched_at_utc=cached["fetched_at_utc"],
                    latencies_ms=cached["latencies_ms"], cache_hit=True)
        except (ValueError, KeyError, TypeError):
            pass  # Corrupt cache: fall through to a fresh scan.
    latencies: dict[str, float] = {}
    payload, latency_ms, fetched_at = fetch_exchange_info(
        http_get, base_url, timeout_s)
    latencies["exchangeInfo"] = latency_ms
    tickers_raw, latency_ms = _rest(http_get, base_url, TICKER_24H_PATH,
                                    timeout_s)
    latencies["ticker24h"] = latency_ms
    books_raw, latency_ms = _rest(http_get, base_url, BOOK_TICKER_PATH,
                                  timeout_s)
    latencies["bookTicker"] = latency_ms
    result = discover_usdt_perps(payload, fetch_latency_ms=latencies[
        "exchangeInfo"], fetched_at_utc=fetched_at, base_url=base_url)
    tickers = {str(t.get("symbol")): t for t in tickers_raw
               if isinstance(t, dict) and t.get("symbol")}
    books = {str(b.get("symbol")): b for b in books_raw
             if isinstance(b, dict) and b.get("symbol")}
    snapshot = UniverseSnapshot(
        metas=result.symbols, tickers=tickers, books=books,
        fetched_at_utc=fetched_at, latencies_ms=latencies, cache_hit=False)
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({
            "metas": [m.__dict__ for m in snapshot.metas],
            "tickers": tickers, "books": books,
            "fetched_at_utc": fetched_at, "latencies_ms": latencies,
        }))
    return snapshot


def _num(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and result != float("inf") else None


def _spread_bps(book: dict[str, Any] | None) -> float | None:
    if not book:
        return None
    bid = _num(book.get("bidPrice"))
    ask = _num(book.get("askPrice"))
    if bid is None or ask is None or bid <= 0 or ask < bid:
        return None
    mid = (bid + ask) / 2.0
    return (ask - bid) / mid * 1e4 if mid > 0 else None


def _range_bps(ticker: dict[str, Any] | None) -> float | None:
    if not ticker:
        return None
    high = _num(ticker.get("highPrice"))
    low = _num(ticker.get("lowPrice"))
    last = _num(ticker.get("lastPrice"))
    if high is None or low is None or last is None or last <= 0:
        return None
    return max(0.0, high - low) / last * 1e4


def rank_symbols(snapshot: UniverseSnapshot, *,
                 max_min_notional_usdt: float = 10.0,
                 min_quote_volume_24h_usdt: float = 1_000_000.0,
                 max_spread_bps: float = 5.0) -> list[SymbolRank]:
    """Rank eligible symbols. Higher score first; infeasible sink to -inf.

    Feasibility (all must hold): venue TRADING perp with sane tick/step,
    min_notional within budget (unknown floor fails closed), 24h quote
    volume above floor, spread within cap. Score blends log-volume (more
    liquid first) minus spread penalty; range and depth are reported,
    not scored (depth enriches the top-K separately).
    """
    import math
    ranked: list[SymbolRank] = []
    for meta in snapshot.metas:
        ticker = snapshot.tickers.get(meta.symbol)
        book = snapshot.books.get(meta.symbol)
        volume = _num((ticker or {}).get("quoteVolume"))
        spread = _spread_bps(book)
        vrange = _range_bps(ticker)
        feasible, reason = True, ""
        if meta.tick_size <= 0 or meta.step_size <= 0:
            feasible, reason = False, "bad tick/step"
        elif meta.min_notional is None:
            feasible, reason = False, "unknown min-notional floor"
        elif meta.min_notional > max_min_notional_usdt:
            feasible, reason = False, "min-notional exceeds budget"
        elif volume is None or volume < min_quote_volume_24h_usdt:
            feasible, reason = False, "24h volume below floor"
        elif spread is None or spread > max_spread_bps:
            feasible, reason = False, "spread missing/above cap"
        score = (math.log10(max(volume or 0.0, 1.0)) - (spread or 0.0) / 5.0
                 if feasible else float("-inf"))
        ranked.append(SymbolRank(
            symbol=meta.symbol, quote_volume_24h_usdt=volume,
            spread_bps=spread, range_bps_24h=vrange, depth_usdt_20=None,
            min_notional=meta.min_notional, tick_size=meta.tick_size,
            step_size=meta.step_size, feasible=feasible,
            infeasible_reason=reason, score=score))
    ranked.sort(key=lambda r: (-r.score if r.score != float("-inf") else float("inf"),
                               r.symbol))
    return ranked


def fetch_depth_usdt(http_get: Callable[[str, float], tuple[Any, float]],
                     symbol: str, base_url: str = FAPI_BASE_URL,
                     timeout_s: float = 15.0,
                     limit: int = DEFAULT_DEPTH_LIMIT) -> float:
    """Top-`limit`-level bid+ask notional for one symbol (one REST call)."""
    payload, _ = _rest(http_get, base_url,
                       f"{DEPTH_PATH}?symbol={symbol}&limit={limit}",
                       timeout_s)
    total = 0.0
    for side in ("bids", "asks"):
        for level in (payload.get(side) or [])[:limit]:
            try:
                total += float(level[0]) * float(level[1])
            except (TypeError, ValueError, IndexError):
                continue
    if total <= 0:
        raise ValueError(f"empty depth for {symbol}")
    return total


def enrich_top_k_depth(
        ranked: list[SymbolRank],
        http_get: Callable[[str, float], tuple[Any, float]],
        base_url: str = FAPI_BASE_URL, timeout_s: float = 15.0,
        top_k: int = DEFAULT_DEPTH_TOP_K) -> list[SymbolRank]:
    """Fetch depth for the top-K feasible symbols and re-sort stably.

    Depth breaks near-ties only: primary order (feasibility, score)
    never changes, so enrichment cannot promote an infeasible symbol.
    A failed depth fetch keeps depth None and the symbol's rank.
    """
    import math
    feasible = [r for r in ranked if r.feasible][:top_k]
    depths: dict[str, float] = {}
    for rank in feasible:
        try:
            depths[rank.symbol] = fetch_depth_usdt(
                http_get, rank.symbol, base_url, timeout_s)
        except (ValueError, OSError):
            continue
    out = [SymbolRank(**{**r.__dict__, "depth_usdt_20": depths.get(r.symbol)})
           for r in ranked]
    # Stable re-sort: depth adjusts score by at most a tie-break epsilon.
    def key(rank: SymbolRank) -> tuple:
        depth = depths.get(rank.symbol)
        bonus = (math.log10(depth) / 1e6 if depth and depth > 0 else 0.0)
        base = rank.score if rank.score != float("-inf") else float("-inf")
        primary = -base if base != float("-inf") else float("inf")
        return (primary, -bonus, rank.symbol)
    return sorted(out, key=key)


def select_subscriptions(ranked: list[SymbolRank], *,
                         max_active: int = DEFAULT_MAX_ACTIVE,
                         position_symbol: str | None = None) -> list[str]:
    """Pick active HF subscriptions. Position symbol is always retained.

    Rebalance rule: the managed position's symbol stays subscribed no
    matter its rank; remaining slots go to the top feasible symbols.
    Returns at most max_active symbols (fewer when fewer are feasible).
    """
    if max_active < 1:
        raise ValueError("max_active must be >= 1")
    picks: list[str] = []
    if position_symbol:
        picks.append(position_symbol)
    for rank in ranked:
        if len(picks) >= max_active:
            break
        if rank.symbol in picks or not rank.feasible:
            continue
        picks.append(rank.symbol)
    return picks


def scan_and_select(
        http_get: Callable[[str, float], tuple[Any, float]],
        base_url: str = FAPI_BASE_URL, timeout_s: float = 15.0, *,
        cache_path: Path | None = None,
        cache_max_age_s: float = DEFAULT_CACHE_S,
        max_min_notional_usdt: float = 10.0,
        max_active: int = DEFAULT_MAX_ACTIVE,
        position_symbol: str | None = None,
        enrich_depth: bool = True) -> dict[str, Any]:
    """One bounded scan: metadata + ranking + selection + timings."""
    started = time.perf_counter()
    snapshot = scan_universe(http_get, base_url, timeout_s,
                             cache_path=cache_path,
                             cache_max_age_s=cache_max_age_s)
    ranked = rank_symbols(
        snapshot, max_min_notional_usdt=max_min_notional_usdt)
    depth_calls = 0
    if enrich_depth:
        before = [r.symbol for r in ranked if r.feasible][:DEFAULT_DEPTH_TOP_K]
        ranked = enrich_top_k_depth(ranked, http_get, base_url, timeout_s)
        depth_calls = sum(1 for r in ranked
                          if r.depth_usdt_20 is not None)
        assert depth_calls <= len(before)
    picks = select_subscriptions(ranked, max_active=max_active,
                                 position_symbol=position_symbol)
    return {
        "fetched_at_utc": snapshot.fetched_at_utc,
        "cache_hit": snapshot.cache_hit,
        "rest_calls": (0 if snapshot.cache_hit
                       else 3 + depth_calls),
        "latencies_ms": snapshot.latencies_ms,
        "universe": len(snapshot.metas),
        "feasible": sum(1 for r in ranked if r.feasible),
        "picks": picks,
        "ranking": [r.__dict__ for r in ranked[:25]],
        "scan_wall_ms": (time.perf_counter() - started) * 1000.0,
    }
