"""Event parsing tests (Worker 2, E-006). Synthetic payloads only."""
import pytest

from cryptobot.market_data.events import channel_of, parse_message, raw_envelope

BASE = dict(route="market", local_recv_ms=1000, local_mono_ns=2000, seq=7, run_id="test")


def test_channel_mapping():
    assert channel_of("btcusdt@aggTrade") == "aggTrade"
    assert channel_of("ethusdt@bookTicker") == "bookTicker"
    assert channel_of("btcusdt@depth@100ms") == "depth"
    assert channel_of("btcusdt@markPrice@1s") == "markPrice"
    with pytest.raises(ValueError, match="unknown channel"):
        channel_of("btcusdt@kline_1m")


def test_parse_aggtrade_envelope():
    event = parse_message(
        {"stream": "btcusdt@aggTrade",
         "data": {"e": "aggTrade", "E": 900, "s": "BTCUSDT", "a": 11, "p": "100.5",
                  "q": "0.25", "f": 9, "l": 11, "T": 890, "m": False}},
        **BASE)
    assert (event["channel"], event["symbol"], event["venue_seq"]) == ("aggTrade", "BTCUSDT", 11)
    assert event["input_class"] == "observed-public"
    assert event["payload"]["buyer_is_maker"] is False
    assert event["payload"]["qty"] == 0.25


def test_parse_bookticker_depth_markprice():
    book = parse_message(
        {"e": "bookTicker", "u": 5, "s": "ETHUSDT", "b": "10", "B": "1",
         "a": "10.1", "A": "2", "T": 900, "E": 901}, **BASE)
    assert (book["channel"], book["venue_seq"]) == ("bookTicker", 5)
    depth = parse_message(
        {"e": "depthUpdate", "E": 902, "s": "BTCUSDT", "U": 100, "u": 105, "pu": 99,
         "b": [["100", "1"]], "a": [["101", "2"]]}, **BASE)
    assert depth["payload"]["prev_last_update"] == 99
    mark = parse_message(
        {"e": "markPriceUpdate", "E": 903, "s": "BTCUSDT", "p": "100.2",
         "r": "0.0001", "T": 1000000}, **BASE)
    assert mark["payload"]["funding_rate"] == 0.0001
    assert mark["venue_seq"] is None  # markPrice carries no venue sequence.


def test_parse_rejects_malformed():
    with pytest.raises(ValueError, match="no symbol"):
        parse_message({"e": "aggTrade", "E": 1}, **BASE)
    with pytest.raises(ValueError, match="not finite"):
        parse_message({"e": "aggTrade", "E": 1, "s": "X", "a": 1, "p": "NaN",
                       "q": "1", "f": 1, "l": 1, "T": 1, "m": True}, **BASE)
    with pytest.raises(ValueError, match="not an object"):
        parse_message({"stream": "x", "data": [1, 2]}, **BASE)


def test_raw_envelope_preserves_verbatim():
    message = {"stream": "s", "data": {"odd": [1, {"n": None}]}, "extra": 1}
    env = raw_envelope(message, **BASE)
    assert env["raw"] == message and env["input_class"] == "observed-public"
