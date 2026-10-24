"""E1.4: point-in-time universe, listing age, no-lookahead proof."""
from __future__ import annotations

import pandas as pd
import pytest

pytest.importorskip("pandas")


def _panel(symbols_days_vol):
    """{symbol: DataFrame(open_time, close, quote_volume)} synthetic."""
    frames = {}
    for sym, start, days, vol in symbols_days_vol:
        idx = pd.date_range("2023-01-01", periods=300, freq="D", tz="UTC")
        qv = [vol] * 300
        frames[sym] = pd.DataFrame({
            "open_time": idx, "close": 100.0, "quote_volume": qv})
        frames[sym] = frames[sym].iloc[start:start + days].reset_index(drop=True)
    return frames


def test_eligible_uses_trailing_data_only():
    from cryptobot.research.universe import eligible_universe

    frames = _panel([("OLD", 0, 300, 1e6), ("NEW", 200, 100, 1e9)])
    asof = pd.Timestamp("2023-06-01", tz="UTC")
    # NEW lists later with huge volume; asof is before its listing.
    out = eligible_universe(asof, frames, top_n=5, min_listing_age_days=90)
    assert "OLD" in out and "NEW" not in out


def test_no_lookahead_future_volume_ignored():
    from cryptobot.research.universe import eligible_universe

    frames = _panel([("A", 0, 300, 1e6), ("B", 0, 300, 1e6)])
    # B explodes AFTER asof; A is steady. Trailing-30d at asof ties.
    asof = pd.Timestamp("2023-03-01", tz="UTC")
    later = frames["B"]["open_time"] > asof
    frames["B"].loc[later, "quote_volume"] = 1e12
    out = eligible_universe(asof, frames, top_n=1, min_listing_age_days=30)
    # Tie broken deterministically (by symbol name), NOT by future volume.
    assert out == ["A"]
    out2 = eligible_universe(pd.Timestamp("2023-05-01", tz="UTC"), frames,
                             top_n=1, min_listing_age_days=30)
    assert out2 == ["B"]  # once the volume is trailing, B wins


def test_listing_age_and_floor_enforced():
    from cryptobot.research.universe import eligible_universe

    frames = _panel([("OLD", 0, 300, 1e6), ("YOUNG", 250, 50, 1e9)])
    asof = pd.Timestamp("2023-10-01", tz="UTC")
    out = eligible_universe(asof, frames, top_n=5, min_listing_age_days=90,
                            min_quote_volume_30d=1e7)
    assert "YOUNG" not in out  # listed ~40d before asof
    out = eligible_universe(asof, frames, top_n=5, min_listing_age_days=90,
                            min_quote_volume_30d=1e12)
    assert out == []  # floor above everyone


def test_universe_history_is_deterministic_and_causal():
    from cryptobot.research.universe import universe_history

    frames = _panel([("A", 0, 300, 1e6), ("B", 100, 200, 2e6)])
    dates = [pd.Timestamp("2023-03-01", tz="UTC"),
             pd.Timestamp("2023-06-01", tz="UTC")]
    h1 = universe_history(dates, frames, top_n=5, min_listing_age_days=30)
    h2 = universe_history(dates, frames, top_n=5, min_listing_age_days=30)
    assert h1 == h2
    assert h1[dates[0]] == ["A"]  # B not yet listed
    assert set(h1[dates[1]]) == {"A", "B"}


def test_liquidity_table_sums_quote_volume():
    from cryptobot.research.universe import liquidity_table

    frames = _panel([("A", 0, 10, 1e6), ("B", 0, 10, 2e6)])
    tab = liquidity_table(frames)
    assert tab["B"] == pytest.approx(2e7)
    assert tab["A"] == pytest.approx(1e7)
import json
from datetime import UTC, datetime, timedelta

from cryptobot.market_data.universe import (
    enrich_top_k_depth,
    rank_symbols,
    scan_and_select,
    scan_universe,
    select_subscriptions,
)


def _meta(symbol, tick="0.10", step="0.001", notional="5", px=2, qty=3,
          status="TRADING", ctype="PERPETUAL", quote="USDT"):
    return {"symbol": symbol, "baseAsset": symbol.replace(quote, ""),
            "quoteAsset": quote, "contractType": ctype, "status": status,
            "pricePrecision": px, "quantityPrecision": qty,
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": tick},
                {"filterType": "LOT_SIZE", "stepSize": step},
                {"filterType": "MIN_NOTIONAL", "notional": notional}]}


def _venue(symbols=("BTCUSDT", "ETHUSDT"), volumes=None, spreads=None):
    metas = [_meta(s) for s in symbols]
    volumes = volumes or {}
    spreads = spreads or {}
    tickers = [{"symbol": s,
                "quoteVolume": str(volumes.get(s, 50_000_000.0)),
                "highPrice": "101.0", "lowPrice": "99.0",
                "lastPrice": "100.0"} for s in symbols]
    books = []
    for s in symbols:
        half = spreads.get(s, 1.0) / 2 / 1e4 * 100.0
        books.append({"symbol": s, "bidPrice": str(100.0 - half),
                      "askPrice": str(100.0 + half)})
    calls = {"n": 0}

    def http_get(url, timeout):
        calls["n"] += 1
        if url.endswith("/fapi/v1/exchangeInfo"):
            return {"symbols": metas}, 5.0
        if url.endswith("/fapi/v1/ticker/24hr"):
            return tickers, 6.0
        if url.endswith("/fapi/v1/ticker/bookTicker"):
            return books, 7.0
        if "/fapi/v1/depth" in url:
            return {"bids": [["100.0", "10.0"]],
                    "asks": [["100.1", "10.0"]]}, 8.0
        raise AssertionError(f"unexpected {url}")

    return http_get, calls


def test_scan_three_calls_then_cache(tmp_path):
    http_get, calls = _venue()
    cache = tmp_path / "uni.json"
    first = scan_universe(http_get, cache_path=cache)
    assert calls["n"] == 3
    assert first.cache_hit is False
    assert len(first.metas) == 2
    second = scan_universe(http_get, cache_path=cache)
    assert calls["n"] == 3  # cache hit: zero new calls.
    assert second.cache_hit is True
    assert [m.symbol for m in second.metas] == ["BTCUSDT", "ETHUSDT"]


def test_stale_or_corrupt_cache_refreshes(tmp_path):
    http_get, calls = _venue()
    cache = tmp_path / "uni.json"
    scan_universe(http_get, cache_path=cache)
    assert calls["n"] == 3
    stale = json.loads(cache.read_text())
    stale["fetched_at_utc"] = (datetime.now(UTC)
                               - timedelta(hours=2)).isoformat()
    cache.write_text(json.dumps(stale))
    scan_universe(http_get, cache_path=cache, cache_max_age_s=3600.0)
    assert calls["n"] == 6  # stale: full rescan.
    cache.write_text("{corrupt")
    scan_universe(http_get, cache_path=cache)
    assert calls["n"] == 9  # corrupt: full rescan, never silent reuse.


def test_ranking_feasibility_and_order():
    http_get, _ = _venue(
        ("BTCUSDT", "ETHUSDT", "THINUSDT", "WIDEUSDT"),
        volumes={"BTCUSDT": 500_000_000.0, "ETHUSDT": 200_000_000.0,
                 "THINUSDT": 10_000.0, "WIDEUSDT": 300_000_000.0},
        spreads={"BTCUSDT": 1.0, "ETHUSDT": 1.5, "THINUSDT": 1.0,
                 "WIDEUSDT": 50.0})
    snapshot = scan_universe(http_get)
    ranked = rank_symbols(snapshot)
    by_symbol = {r.symbol: r for r in ranked}
    assert by_symbol["THINUSDT"].feasible is False
    assert by_symbol["WIDEUSDT"].feasible is False
    feasible = [r.symbol for r in ranked if r.feasible]
    assert feasible == ["BTCUSDT", "ETHUSDT"]  # volume first.
    assert by_symbol["BTCUSDT"].range_bps_24h == 200.0
    import pytest
    assert by_symbol["BTCUSDT"].spread_bps == pytest.approx(1.0)


def test_unknown_floor_fails_closed():
    metas = [_meta("NOFLOORUSDT", notional="0")]
    metas[0]["filters"] = [f for f in metas[0]["filters"]
                           if f["filterType"] != "MIN_NOTIONAL"]

    def http_get(url, timeout):
        if url.endswith("exchangeInfo"):
            return {"symbols": metas}, 1.0
        if url.endswith("ticker/24hr"):
            return [{"symbol": "NOFLOORUSDT", "quoteVolume": "1e9",
                     "highPrice": "1.0", "lowPrice": "1.0",
                     "lastPrice": "1.0"}], 1.0
        return [{"symbol": "NOFLOORUSDT", "bidPrice": "1.0",
                 "askPrice": "1.0"}], 1.0

    ranked = rank_symbols(scan_universe(http_get))
    assert ranked[0].feasible is False
    assert "floor" in ranked[0].infeasible_reason


def test_enrich_depth_never_promotes_infeasible():
    http_get, calls = _venue(("BTCUSDT", "THINUSDT"),
                             volumes={"BTCUSDT": 5e8, "THINUSDT": 1e4})
    ranked = rank_symbols(scan_universe(http_get))
    enriched = enrich_top_k_depth(ranked, http_get, top_k=10)
    assert calls["n"] == 4  # 3 scan + 1 depth (only feasible top-K).
    by_symbol = {r.symbol: r for r in enriched}
    assert by_symbol["BTCUSDT"].depth_usdt_20 == 2001.0
    assert by_symbol["THINUSDT"].depth_usdt_20 is None
    assert [r.symbol for r in enriched] == ["BTCUSDT", "THINUSDT"]


def test_select_two_and_retain_position():
    http_get, _ = _venue(("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    ranked = rank_symbols(scan_universe(http_get))
    assert select_subscriptions(ranked) == ["BTCUSDT", "ETHUSDT"]
    # Position symbol retained even when unranked/infeasible.
    assert select_subscriptions(ranked, position_symbol="THINUSDT") == [
        "THINUSDT", "BTCUSDT"]
    assert select_subscriptions(ranked, max_active=1,
                                position_symbol="ETHUSDT") == ["ETHUSDT"]
    import pytest
    with pytest.raises(ValueError):
        select_subscriptions(ranked, max_active=0)


def test_non_btc_eth_precision_generality():
    """Metadata-driven selection + rounding for other precisions."""
    from cryptobot.risk.rounding import floor_to_step, round_to_tick
    metas = [_meta("SOLUSDT", tick="0.01", step="0.1", notional="5",
                   px=2, qty=1),
             _meta("DOGEUSDT", tick="0.00001", step="1", notional="5",
                   px=5, qty=0)]

    def http_get(url, timeout):
        if url.endswith("exchangeInfo"):
            return {"symbols": metas}, 1.0
        if url.endswith("ticker/24hr"):
            return [{"symbol": s, "quoteVolume": "2e8", "highPrice": "2.0",
                     "lowPrice": "1.0", "lastPrice": "1.5"}
                    for s in ("SOLUSDT", "DOGEUSDT")], 1.0
        return [{"symbol": s, "bidPrice": "1.4999", "askPrice": "1.5001"}
                for s in ("SOLUSDT", "DOGEUSDT")], 1.0

    snapshot = scan_universe(http_get)
    assert [m.symbol for m in snapshot.metas] == ["DOGEUSDT", "SOLUSDT"]
    ranked = rank_symbols(snapshot)
    assert all(r.feasible for r in ranked)
    assert select_subscriptions(ranked) == ["DOGEUSDT", "SOLUSDT"]
    sol = next(m for m in snapshot.metas if m.symbol == "SOLUSDT")
    doge = next(m for m in snapshot.metas if m.symbol == "DOGEUSDT")
    # Rounding consumes discovered precision; no hardcoded coin logic.
    assert round_to_tick(1.567, sol.tick_size) == 1.57
    assert floor_to_step(3.37, sol.step_size) == 3.3
    assert round_to_tick(0.123456, doge.tick_size) == 0.12346
    assert floor_to_step(7.9, doge.step_size) == 7.0


def test_max_hf_subscriptions_config():
    from cryptobot.app.config import load_config
    for name in ("paper.toml", "prod.toml", "demo.toml"):
        assert load_config(f"configs/{name}").max_hf_subscriptions == 2


def test_scan_and_select_shape(tmp_path):
    http_get, _ = _venue()
    report = scan_and_select(http_get, cache_path=tmp_path / "u.json")
    assert report["picks"] == ["BTCUSDT", "ETHUSDT"]
    assert report["rest_calls"] == 5  # 3 scan + 2 depth.
    assert report["universe"] == 2 and report["feasible"] == 2
    assert len(report["ranking"]) == 2
    cached = scan_and_select(http_get, cache_path=tmp_path / "u.json")
    assert cached["cache_hit"] is True
    assert cached["rest_calls"] == 0
