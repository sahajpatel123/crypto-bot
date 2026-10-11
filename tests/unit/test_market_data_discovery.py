"""Discovery unit tests (Worker 2, E-001). Fixture payload is SYNTHETIC."""
from cryptobot.market_data import (
    discover_usdt_perps,
    discovery_summary,
    eligible_symbols,
    fetch_exchange_info,
)
from cryptobot.market_data.discovery import parse_symbol

# SYNTHETIC exchangeInfo-shaped fixture (hand-built, not venue data).
SYNTHETIC_INFO = {
    "symbols": [
        {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT",
         "contractType": "PERPETUAL", "status": "TRADING",
         "pricePrecision": 2, "quantityPrecision": 3,
         "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                     {"filterType": "LOT_SIZE", "stepSize": "0.001"},
                     {"filterType": "MIN_NOTIONAL", "notional": "5"}]},
        {"symbol": "FAKEUSDT", "baseAsset": "FAKE", "quoteAsset": "USDT",
         "contractType": "PERPETUAL", "status": "TRADING",
         "pricePrecision": 4, "quantityPrecision": 0,
         "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.0001"},
                     {"filterType": "LOT_SIZE", "stepSize": "1"},
                     {"filterType": "MIN_NOTIONAL", "notional": "5000"}]},
        {"symbol": "NOFLOORUSDT", "baseAsset": "NF", "quoteAsset": "USDT",
         "contractType": "PERPETUAL", "status": "TRADING",
         "pricePrecision": 3, "quantityPrecision": 1, "filters": []},
        {"symbol": "ETHUSDT", "baseAsset": "ETH", "quoteAsset": "USDT",
         "contractType": "CURRENT_QUARTER", "status": "TRADING",
         "pricePrecision": 2, "quantityPrecision": 3, "filters": []},
        {"symbol": "BTCUSD_PERP", "baseAsset": "BTC", "quoteAsset": "USD",
         "contractType": "PERPETUAL", "status": "TRADING",
         "pricePrecision": 1, "quantityPrecision": 0, "filters": []},
        {"symbol": "OLDUSDT", "baseAsset": "OLD", "quoteAsset": "USDT",
         "contractType": "PERPETUAL", "status": "BREAK",
         "pricePrecision": 2, "quantityPrecision": 1, "filters": []},
    ]
}


def test_discovery_filters_without_whitelist():
    result = discover_usdt_perps(SYNTHETIC_INFO)
    assert [m.symbol for m in result.symbols] == ["BTCUSDT", "FAKEUSDT", "NOFLOORUSDT"]
    assert result.total_symbols_seen == 6


def test_unlisted_symbol_is_discovered_dynamically():
    # FAKEUSDT exists in no list anywhere; attribute filtering must still find it.
    result = discover_usdt_perps(SYNTHETIC_INFO)
    assert "FAKEUSDT" in [m.symbol for m in result.symbols]


def test_parse_extracts_size_economics():
    btc = parse_symbol(SYNTHETIC_INFO["symbols"][0])
    assert (btc.tick_size, btc.step_size, btc.min_notional) == (0.01, 0.001, 5.0)
    assert parse_symbol(SYNTHETIC_INFO["symbols"][2]).min_notional is None


def test_eligibility_is_size_aware_and_deterministic():
    result = discover_usdt_perps(SYNTHETIC_INFO)
    eligible = eligible_symbols(result, max_min_notional_usdt=20.0)
    assert [m.symbol for m in eligible] == ["BTCUSDT", "NOFLOORUSDT"]
    strict = eligible_symbols(result, max_min_notional_usdt=20.0, require_known_floor=True)
    assert [m.symbol for m in strict] == ["BTCUSDT"]
    twice = eligible_symbols(result, max_min_notional_usdt=20.0)
    assert [m.symbol for m in twice] == [m.symbol for m in eligible]


def test_fetch_uses_injected_transport_and_rejects_bad_payload():
    def fake_get(url, timeout):
        assert url.endswith("/fapi/v1/exchangeInfo")
        assert timeout == 5.0
        return SYNTHETIC_INFO, 12.5

    payload, latency_ms, fetched_at = fetch_exchange_info(fake_get, timeout_s=5.0)
    assert payload is SYNTHETIC_INFO and latency_ms == 12.5 and fetched_at

    def bad_get(url, timeout):
        return {"oops": 1}, 1.0

    try:
        fetch_exchange_info(bad_get)
    except ValueError:
        pass
    else:
        raise AssertionError("bad payload must raise")


def test_summary_counts():
    result = discover_usdt_perps(SYNTHETIC_INFO, fetch_latency_ms=3.2)
    summary = discovery_summary(result, eligible_symbols(result))
    assert summary["total_symbols_seen"] == 6
    assert summary["usdt_perp_trading"] == 3
    assert summary["eligible"] == 3
