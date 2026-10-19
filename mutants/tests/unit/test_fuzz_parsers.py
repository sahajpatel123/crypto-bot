"""F1.6: parser fuzzing — malformed/adversarial payloads never crash.

WS message parsing, user-stream ingestion, and REST account views
must fail CLOSED (documented ValueError/TypeError/KeyError, or None)
on any input shape — never an unexpected exception, never a
nonfinite number leaking into a record, never a hang.
"""
from __future__ import annotations

import math
from itertools import count

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

_JSON_SCALAR = st.one_of(
    st.none(), st.booleans(),
    st.integers(min_value=-(2 ** 63), max_value=2 ** 63 - 1),
    st.floats(allow_nan=True, allow_infinity=True),
    st.text(min_size=0, max_size=200),
)
_JSON = st.recursive(
    _JSON_SCALAR,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(min_size=0, max_size=20), children,
                        max_size=5)),
    max_leaves=12)

_ALLOWED = (ValueError, TypeError, KeyError, AttributeError)

_case = count()
_FIXTURE_OK = [HealthCheck.function_scoped_fixture]


def _finite_or_raise(value):
    assert isinstance(value, (int, float)) and math.isfinite(value), value


@given(message=_JSON)
@settings(max_examples=300, deadline=2000)
def test_ws_parse_never_crashes(message):
    import sys

    sys.path.insert(0, "tests")
    from cryptobot.market_data.events import parse_message

    if not isinstance(message, dict):
        message = {"e": "aggTrade", "wrapped": message}
    try:
        record = parse_message(
            message, route="market", local_recv_ms=1_700_000_000_000,
            local_mono_ns=1, seq=1, run_id="fuzz")
    except _ALLOWED:
        return
    _finite_or_raise(record["exchange_ts_ms"])
    _finite_or_raise(record["local_recv_ms"])
    assert record["format"] == "cryptobot-events/1"


@given(payload=_JSON)
@settings(max_examples=200, deadline=3000,
          suppress_health_check=_FIXTURE_OK)
def test_user_stream_never_crashes(tmp_path, payload):
    import venue_fixtures as venues

    if not isinstance(payload, dict):
        return
    case_dir = tmp_path / f"case{next(_case)}"
    case_dir.mkdir(parents=True, exist_ok=True)
    engine, _ = venues.make_engine(case_dir, [])
    try:
        engine.note_user_event(payload)
    except _ALLOWED:
        return


@given(view=_JSON)
@settings(max_examples=200, deadline=3000,
          suppress_health_check=_FIXTURE_OK)
def test_account_view_never_crashes(tmp_path, view):
    import venue_fixtures as venues

    if not isinstance(view, dict):
        return
    case_dir = tmp_path / f"case{next(_case)}"
    case_dir.mkdir(parents=True, exist_ok=True)
    script = [("GET", "/fapi/v2/account", None, ("ok", view))]
    engine, _ = venues.make_engine(case_dir, script)
    try:
        snap = engine.account_snapshot()
    except _ALLOWED + (__import__(
            "cryptobot.adapters.binance_live", fromlist=["VenueHttpError"]
            ).VenueHttpError,):
        return
    if snap is None:
        return
    for field in ("wallet_equity_usdt", "available_margin_usdt"):
        _finite_or_raise(getattr(snap, field))


def test_adversarial_corner_cases():
    """Hand-picked nasties (regression pins, not just random)."""
    from cryptobot.market_data.events import parse_message

    nasties = [
        {},
        {"stream": 12345, "data": None},
        {"stream": "x" * 10000, "data": {"s": "BTCUSDT", "E": 0}},
        {"e": "aggTrade"},  # no symbol
        {"e": "aggTrade", "s": "BTCUSDT"},  # no timestamps
        {"e": "aggTrade", "s": "BTCUSDT", "E": float("inf")},
        {"e": "aggTrade", "s": "BTCUSDT", "E": "not-a-number"},
        {"e": "aggTrade", "s": "BTCUSDT", "E": 2 ** 100},
        {"stream": "btcusdt@aggTrade", "data": []},
        {"stream": "btcusdt@aggTrade", "data": "string-not-dict"},
    ]
    for message in nasties:
        try:
            record = parse_message(
                message, route="market", local_recv_ms=1, local_mono_ns=1,
                seq=1, run_id="fuzz")
        except _ALLOWED:
            continue
        _finite_or_raise(record["exchange_ts_ms"])
