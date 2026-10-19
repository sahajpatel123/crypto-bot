"""Recorder stream-definition tests: URLs, USDC check, backoff, resync.

Offline only: canned exchangeInfo payloads, seeded RNG, in-memory DepthBook.
No network.
"""
import random

from cryptobot.recorder.streams import (
    backoff_with_jitter,
    build_binance_streams,
    build_binance_urls,
    check_usdc_perps,
    funding_rate_url,
    open_interest_url,
    premium_index_url,
    resync_depth,
)


def test_stream_names_cover_all_channels_for_btc_and_eth():
    streams = build_binance_streams()
    for symbol in ("btcusdt", "ethusdt"):
        for channel in ("aggTrade", "bookTicker", "depth@100ms", "markPrice@1s"):
            assert f"{symbol}@{channel}" in streams
    assert any("forceOrder" in s for s in streams)  # liquidations included.


def test_stream_urls_group_required_channels():
    urls = build_binance_urls()
    assert set(urls) == {"market", "public", "liquidations"}
    assert "aggTrade" in urls["market"] and "markPrice@1s" in urls["market"]
    assert "bookTicker" in urls["public"] and "depth@100ms" in urls["public"]
    assert "forceOrder" in urls["liquidations"]
    for url in urls.values():
        assert url.startswith("wss://")


def test_rest_poll_urls_point_at_fapi_endpoints():
    assert open_interest_url("BTCUSDT").endswith("/fapi/v1/openInterest?symbol=BTCUSDT")
    assert "/fapi/v1/fundingRate?symbol=ETHUSDT" in funding_rate_url("ETHUSDT")
    assert premium_index_url("btcusdt").endswith("/fapi/v1/premiumIndex?symbol=BTCUSDT")


def _exchange_info(*entries):
    return {"symbols": list(entries)}


def _entry(symbol, base, quote, contract="PERPETUAL", status="TRADING"):
    return {"symbol": symbol, "baseAsset": base, "quoteAsset": quote,
            "contractType": contract, "status": status}


def test_usdc_check_finds_btc_eth_perps_when_present():
    payload = _exchange_info(
        _entry("BTCUSDT", "BTC", "USDT"),
        _entry("BTCUSDC", "BTC", "USDC"),
        _entry("ETHUSDC", "ETH", "USDC"),
        _entry("SOLUSDC", "SOL", "USDC"),  # out of scope base: ignored.
        _entry("BTCUSD_240927", "BTC", "USD", contract="CURRENT_QUARTER"),  # not perp.
    )
    assert check_usdc_perps(payload) == ["BTCUSDC", "ETHUSDC"]


def test_usdc_check_empty_when_absent_or_malformed():
    usdt_only = _exchange_info(_entry("BTCUSDT", "BTC", "USDT"),
                               _entry("ETHUSDT", "ETH", "USDT"))
    assert check_usdc_perps(usdt_only) == []
    assert check_usdc_perps({}) == []
    assert check_usdc_perps({"symbols": "not-a-list"}) == []
    assert check_usdc_perps({"symbols": [None, 42, {"symbol": "BTCUSDC"}]}) == []


def test_backoff_bounded_capped_and_seeded():
    first = backoff_with_jitter(3, rng=random.Random(0))
    again = backoff_with_jitter(3, rng=random.Random(0))
    assert first == again  # seeded RNG is deterministic.
    for attempt in range(12):
        value = backoff_with_jitter(attempt, rng=random.Random(attempt))
        grown = min(60.0, 1.0 * (2 ** attempt))
        assert 0.5 * grown <= value <= grown  # half-jitter bounds.
    assert backoff_with_jitter(100, rng=random.Random(1)) <= 60.0  # capped.
    assert backoff_with_jitter(-5, rng=random.Random(2)) <= 1.0  # attempt floors at 0.


def test_backoff_is_jittered_not_constant():
    values = {backoff_with_jitter(4, rng=random.Random(seed)) for seed in range(10)}
    assert len(values) > 1


def test_depth_resync_via_depthbook_smoke():
    snapshot = {"bids": [["100", "1"]], "asks": [["101", "1"]], "lastUpdateId": 50}
    assert resync_depth("BTCUSDT", snapshot) is True
    assert resync_depth("BTCUSDT", {"bids": [], "asks": []}) is False  # missing id.
    assert resync_depth("BTCUSDT", "not-a-dict") is False
