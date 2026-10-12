"""Live-bridge iterator tests (Worker 2, E-007). Fakes only, no network."""
import json
import socket
from collections import deque

import pytest

from cryptobot.adapters.bridge import live_events
from cryptobot.market_data.ws import WsClosed


class FakeLiveConn:
    def __init__(self, script=()):
        self.sock, self.peer = socket.socketpair()
        self.script = deque(script)
        if self.script:
            self.peer.send(b"x")
        self.closed = False
        self.recvs = 0

    @property
    def native_socket(self):
        return self.sock

    def recv_message(self, timeout_s=None):
        self.recvs += 1
        if not self.script:
            raise WsClosed("drained")
        item = self.script.popleft()
        if not self.script:
            self.sock.setblocking(False)
            try:
                self.sock.recv(1)
            except OSError:
                pass
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True
        try:
            self.sock.close()
        except OSError:
            pass


def _trade(symbol="BTCUSDT", agg_id=1, price="100", ts=1000):
    return ("text", json.dumps({
        "stream": f"{symbol.lower()}@aggTrade",
        "data": {"e": "aggTrade", "E": ts, "s": symbol, "a": agg_id,
                 "p": price, "q": "0.5", "f": agg_id, "l": agg_id,
                 "T": ts, "m": False}}).encode())


def _ticker(symbol="BTCUSDT", bid="100", ask="101", ts=1000):
    return ("text", json.dumps({
        "stream": f"{symbol.lower()}@bookTicker",
        "data": {"u": 7, "s": symbol, "b": bid, "B": "1.5",
                 "a": ask, "A": "2.5", "T": ts, "E": ts}}).encode())


def _take(it, n):
    out = []
    for event in it:
        out.append(event)
        if len(out) >= n:
            break
    it.close()
    return out


def test_explicit_symbols_stream_normalized_events():
    market = FakeLiveConn([_trade()])
    public = FakeLiveConn([_ticker()])
    conns = {"market": market, "public": public}

    def connect(url):
        return conns["market" if "/market/" in url else "public"]

    events = _take(live_events(symbols=["BTCUSDT"], connect=connect), 2)
    assert len(events) == 2
    by_channel = {e["channel"]: e for e in events}
    trade, ticker = by_channel["aggTrade"], by_channel["bookTicker"]
    assert trade["input_class"] == "observed-public"
    assert trade["symbol"] == "BTCUSDT" and trade["route"] == "market"
    assert trade["payload"]["price"] == 100.0
    assert trade["run_id"].startswith("live-") and trade["seq"] >= 1
    assert ticker["payload"]["bid"] == 100.0 and ticker["route"] == "public"
    assert ticker["run_id"] == trade["run_id"]  # one run id per iterator.
    assert market.closed and public.closed  # generator close releases sockets.


def test_symbols_validation():
    with pytest.raises(ValueError, match="non-empty"):
        list(live_events(symbols=[]))
    with pytest.raises(ValueError, match="max_symbols"):
        list(live_events(symbols=["A", "B", "C"], max_symbols=2))


def test_discovery_selects_top_by_quote_volume():
    seen_urls = []

    def rest_get(url, timeout):
        seen_urls.append(url)
        if url.endswith("/fapi/v1/exchangeInfo"):
            return {"symbols": [
                {"symbol": "BTCUSDT", "status": "TRADING",
                 "contractType": "PERPETUAL", "quoteAsset": "USDT",
                 "baseAsset": "BTC", "pricePrecision": 2,
                 "quantityPrecision": 3, "filters": []},
                {"symbol": "ETHUSDT", "status": "TRADING",
                 "contractType": "PERPETUAL", "quoteAsset": "USDT",
                 "baseAsset": "ETH", "pricePrecision": 2,
                 "quantityPrecision": 3, "filters": []},
            ]}, 1.0
        return [{"symbol": "BTCUSDT", "quoteVolume": "9"},
                {"symbol": "ETHUSDT", "quoteVolume": "10"}], 1.0

    market = FakeLiveConn([_trade("ETHUSDT")])
    public = FakeLiveConn([_ticker("ETHUSDT")])
    conns = {"market": market, "public": public}

    def connect(url):
        assert "ethusdt@" in url and "btcusdt@" not in url  # top-1 only.
        return conns["market" if "/market/" in url else "public"]

    events = _take(live_events(symbols=None, max_symbols=1,
                               connect=connect, rest_get=rest_get), 2)
    assert {e["symbol"] for e in events} == {"ETHUSDT"}


def test_reconnect_labels_natural_gap_and_continues():
    market = FakeLiveConn([WsClosed("boom"), _trade()])
    public = FakeLiveConn([_ticker()])

    def connect(url):
        return market if "/market/" in url else public

    it = live_events(symbols=["BTCUSDT"], connect=connect)
    events = _take(it, 2)
    trade = next(e for e in events if e["channel"] == "aggTrade")
    assert trade["gap_kind"] == "natural"
    assert market.recvs >= 2  # reconnected and kept streaming.


def test_routes_exhausted_raises_instead_of_trading_blind():
    def connect(url):
        return FakeLiveConn([WsClosed("down")])

    it = live_events(symbols=["BTCUSDT"], connect=connect, max_reconnects=1)
    with pytest.raises(ConnectionError, match="routes-exhausted"):
        for _ in it:
            pass


def test_malformed_frames_skipped_stream_continues():
    market = FakeLiveConn([("text", b"not json{"), _trade(price="100")])
    public = FakeLiveConn([])

    def connect(url):
        return market if "/market/" in url else public

    it = live_events(symbols=["BTCUSDT"], connect=connect)
    events = _take(it, 1)
    assert events[0]["channel"] == "aggTrade"
