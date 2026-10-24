"""V-008 §7: Binance live-adapter recorded contract tests.

No network, no keys (TESTKEY/TESTSECRET sentinels only). The replay
transport asserts request shapes and serves fixture payloads labeled
recorded-shape — hand-built, NOT actual captures.
"""
import copy
import json
from datetime import UTC, datetime

import pytest

import venue_fixtures as venues
from cryptobot.adapters.binance_live import (
    BinanceLiveEngine,
    UnknownOutcomeError,
    VenueHttpError,
    VenueRejectedError,
)
from cryptobot.app.engine import EngineOrder

FIX = venues.FIX
T0MS = venues.T0MS
NOW = venues.NOW
ReplayTransport = venues.ReplayTransport
_live = venues.make_engine
_ready_script = venues.ready_script


@pytest.fixture()
def ready():
    return json.loads((FIX / "readiness.json").read_text())


@pytest.fixture()
def orders():
    return json.loads((FIX / "orders.json").read_text())


def _signed_shape(request):
    _, _, params, headers = request
    assert headers.get("X-MBX-APIKEY") == "TESTKEY"
    assert params.get("recvWindow") == 5000
    sig = params.get("signature", "")
    assert len(sig) == 64 and all(c in "0123456789abcdef" for c in sig)
    assert abs(params.get("timestamp", 0) - T0MS) < 60_000


def _journal_events(tmp_path):
    return [json.loads(line) for line in
            (tmp_path / "live.jsonl").read_text().splitlines()]


# -- default-off -------------------------------------------------------------
def test_ctor_requires_explicit_live_enable(tmp_path):
    with pytest.raises(ValueError, match="disabled"):
        BinanceLiveEngine(api_key="k", api_secret="s",
                          journal_path=tmp_path / "j", expected_leverage=3)
    with pytest.raises(ValueError, match="api_key"):
        BinanceLiveEngine(api_key="", api_secret="",
                          journal_path=tmp_path / "j", expected_leverage=3,
                          live_enable=True)


def test_paper_path_never_instantiates_live(tmp_path):
    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session
    from cryptobot.app.store import RunStore
    text = open("configs/paper.toml").read().replace(
        'dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "test.toml"
    cfg_path.write_text(text)
    session = Session(load_config(cfg_path),
                      RunStore(tmp_path / "runs" / "cryptobot.db"),
                      tmp_path / "runs" / "r", "r")
    assert not isinstance(session.engine, BinanceLiveEngine)


# -- readiness -----------------------------------------------------------------
def test_readiness_sequence_parses_filters_fees(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order",
             {"symbol": "BTCUSDT", "side": "BUY", "type": "MARKET",
              "quantity": "0.001"}, ("ok", orders["orderAck"]))])
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.0019, "MARKET"))
    assert cid.startswith("bl-")
    assert engine.fee_bps("BTCUSDT") == pytest.approx(5.0)
    _signed_shape(transport.requests[-1])
    assert any(e["event"] == "ready" for e in _journal_events(tmp_path))
    transport.assert_empty()


def test_excessive_clock_skew_blocks(tmp_path, ready):
    bad = copy.deepcopy(ready["time"])
    bad["serverTime"] = T0MS + 60_000
    engine, _ = _live(tmp_path, [("GET", "/fapi/v1/time", None, ("ok", bad))])
    with pytest.raises(VenueRejectedError, match="skew"):
        engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))


def test_hedge_mode_blocked(tmp_path, ready):
    bad = copy.deepcopy(ready)
    bad["account"]["positions"][0]["positionSide"] = "LONG"
    script = _ready_script(bad)
    engine, _ = _live(tmp_path, script)
    with pytest.raises(VenueRejectedError, match="one-way"):
        engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))


def test_margin_type_and_leverage_verified(tmp_path, ready):
    bad = copy.deepcopy(ready)
    bad["account"]["positions"][0]["isolated"] = True
    engine, _ = _live(tmp_path, _ready_script(bad))
    with pytest.raises(VenueRejectedError, match="isolated"):
        engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    bad2 = copy.deepcopy(ready)
    bad2["leverage"]["leverage"] = 5
    engine2, _ = _live(tmp_path, _ready_script(bad2))
    with pytest.raises(VenueRejectedError, match="leverage"):
        engine2.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))


# -- submission shapes ------------------------------------------------------------
def test_stop_leg_shape_reduce_only_working_type(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/algoOrder",
             {"symbol": "BTCUSDT", "side": "SELL", "type": "STOP_MARKET",
              "algoType": "CONDITIONAL", "quantity": "0.002",
              "stopPrice": "59990.0", "workingType": "CONTRACT_PRICE",
              "reduceOnly": "true"}, ("ok", orders["algoAck"]))])
    engine.submit(EngineOrder("BTCUSDT", "SELL", 0.0029, "STOP_MARKET",
                              stop_price=59990.03, reduce_only=True,
                              role="stop"))
    _signed_shape(transport.requests[-1])
    assert "newClientOrderId" not in transport.requests[-1][2]
    assert "clientAlgoId" in transport.requests[-1][2]
    transport.assert_empty()


def test_protected_entry_is_limit_ioc_at_rounded_cap(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order",
             {"type": "LIMIT", "price": "60000.5", "timeInForce": "IOC"},
             ("ok", orders["orderAck"]))])
    engine.submit_protected(
        EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"), 60000.53)
    transport.assert_empty()


def test_dust_qty_sends_no_request(tmp_path, ready):
    engine, transport = _live(tmp_path, _ready_script(ready))
    with pytest.raises(ValueError, match="below LOT_SIZE step"):
        engine.submit(EngineOrder("BTCUSDT", "BUY", 0.0009, "MARKET"))
    assert [r[1] for r in transport.requests] == [
        "/fapi/v1/time", "/fapi/v1/exchangeInfo", "/fapi/v1/commissionRate",
        "/fapi/v2/account", "/fapi/v1/leverage"]
    transport.assert_empty()


# -- unknown outcomes ---------------------------------------------------------------
def test_503_unknown_blocks_retry_until_lookup(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("err", 503, None, "Service Unavailable"))])
    cmd = EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET", reservation_id="r-1")
    with pytest.raises(UnknownOutcomeError) as exc:
        engine.submit(cmd)
    cid = exc.value.client_id
    assert engine.unknown_ids() == (cid,)
    with pytest.raises(UnknownOutcomeError, match="lookup must resolve"):
        engine.submit(cmd)
    transport.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
         ("ok", orders["orderQueryFilled"])),
        ("GET", "/fapi/v1/userTrades", {"orderId": 12345},
         ("ok", orders["userTrades"])))
    status = engine.lookup(cid)
    assert status is not None and status.state == "filled"
    assert status.filled_qty == pytest.approx(0.002)
    assert engine.unknown_ids() == ()
    fills = [e for e in engine.poll() if e.kind == "fill"]
    assert [f.payload.qty for f in fills] == [0.001, 0.001]
    assert [f.payload.fee for f in fills] == pytest.approx([0.03, 0.03])
    # Resolved: retry is allowed again.
    transport.append(("POST", "/fapi/v1/order", {"type": "MARKET"},
                      ("ok", orders["orderAck"])))
    engine.submit(cmd)
    transport.assert_empty()


def test_lookup_void_allows_retry(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("err", 0, None, "transport: timed out"))])
    cmd = EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET", reservation_id="r-1")
    with pytest.raises(UnknownOutcomeError) as exc:
        engine.submit(cmd)
    transport.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": exc.value.client_id},
         ("err", 400, -2013, "Order does not exist.")))
    assert engine.lookup(exc.value.client_id) is None
    assert engine.unknown_ids() == ()
    transport.append(("POST", "/fapi/v1/order", {"type": "MARKET"},
                      ("ok", orders["orderAck"])))
    engine.submit(cmd)
    transport.assert_empty()


def test_deterministic_rejection_allows_retry(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("err", 400, -1111, "Bad quantity."))])
    cmd = EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET", reservation_id="r-1")
    with pytest.raises(VenueRejectedError):
        engine.submit(cmd)
    assert engine.unknown_ids() == ()
    transport.append(("POST", "/fapi/v1/order", {"type": "MARKET"},
                      ("ok", orders["orderAck"])))
    engine.submit(cmd)
    transport.assert_empty()


# -- user stream ----------------------------------------------------------------------
def test_user_stream_trade_feeds_poll_fill(tmp_path, ready, orders):
    engine, transport = _live(tmp_path, [])
    payload = copy.deepcopy(orders["userStreamTrade"])
    payload["o"]["c"] = "bl-000001-x"
    engine.note_user_event(payload)
    fills = [e for e in engine.poll() if e.kind == "fill"]
    assert len(fills) == 1
    fill = fills[0].payload
    assert (fill.qty, fill.price, fill.fee) == (0.001, 60000.0, 0.03)
    assert fill.execution_id == "binanceusdm/9f3b2fc5de52/BTCUSDT/777001"
    assert transport.requests == []
    transport.assert_empty()


def test_user_stream_dup_trade_after_lookup_single_fill(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"]))])
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.002, "MARKET"))
    payload = copy.deepcopy(orders["userStreamTrade"])
    payload["o"]["c"] = cid
    engine.note_user_event(payload)
    assert len([e for e in engine.poll() if e.kind == "fill"]) == 1
    # Lookup adopts the tape: trade 777001 is NOT in the tape fixture, so
    # both tape trades are new — 2 more fills, no duplicates of 777001.
    transport.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
         ("ok", orders["orderQueryFilled"])),
        ("GET", "/fapi/v1/userTrades", {"orderId": 12345},
         ("ok", orders["userTrades"])))
    engine.lookup(cid)
    fills = [e for e in engine.poll() if e.kind == "fill"]
    assert len(fills) == 2
    assert {f.payload.execution_id for f in fills} == {
        "binanceusdm/9f3b2fc5de52/BTCUSDT/999001", "binanceusdm/9f3b2fc5de52/BTCUSDT/999002"}
    transport.assert_empty()


def test_user_stream_non_usdt_fee_and_unknown_kind_fail_loud(tmp_path):
    engine, _ = _live(tmp_path, [])
    bad_fee = {"e": "ORDER_TRADE_UPDATE", "E": T0MS,
               "o": {"s": "BTCUSDT", "c": "c", "S": "BUY", "X": "FILLED",
                     "x": "TRADE", "l": "0.001", "L": "1", "n": "0.01",
                     "N": "BNB", "t": 1}}
    with pytest.raises(ValueError, match="non-USDT commission"):
        engine.note_user_event(bad_fee)
    with pytest.raises(ValueError, match="unknown user-stream event"):
        engine.note_user_event({"e": "SOMETHING_NEW"})


# -- orders / margin / funding / lifecycle -----------------------------------------------
def test_open_orders_cached_by_ttl(tmp_path, ready, orders):
    clock = [NOW]
    engine, transport = _live(tmp_path, [], now_utc=lambda: clock[0],
                              open_orders_ttl_s=1.0)
    # Journal one own order; the venue also reports a foreign stray.
    transport.append(*_ready_script(ready),
                     ("POST", "/fapi/v1/order", {"type": "MARKET"},
                      ("ok", orders["orderAck"])))
    own = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    book = copy.deepcopy(orders["openOrders"])
    book[0]["clientOrderId"] = own
    book.append({"clientOrderId": "stray-manual", "symbol": "BTCUSDT",
                 "status": "NEW", "origQty": "1.0", "executedQty": "0.0"})
    pair = [("GET", "/fapi/v1/openOrders", None, ("ok", book)),
            ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", []))]
    transport.append(*pair, *pair)
    first = engine.open_orders()
    assert [s.client_order_id for s in first] == [own]  # stray filtered.
    assert first[0].state == "open" and first[0].qty == 0.001
    assert engine.open_orders() == first  # cached: no second request.
    clock[0] = datetime.fromtimestamp(T0MS / 1000 + 2, tz=UTC)
    engine.open_orders()
    ignored = [e for e in _journal_events(tmp_path)
               if e["event"] == "foreign-orders-ignored"]
    assert sum(e["count"] for e in ignored) == 2  # one per refresh.
    transport.assert_empty()


def test_attach_protection_stop_first_reduce_only(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"]))])
    entry = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.002, "MARKET",
                                      reservation_id="r-7"))
    transport.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": entry},
         ("ok", orders["orderQueryFilled"])),
        ("GET", "/fapi/v1/userTrades", {"orderId": 12345},
         ("ok", orders["userTrades"])),
        ("POST", "/fapi/v1/algoOrder",
         {"type": "STOP_MARKET", "quantity": "0.002", "reduceOnly": "true"},
         ("ok", orders["algoAck"])),
        ("POST", "/fapi/v1/algoOrder",
         {"type": "TAKE_PROFIT_MARKET", "quantity": "0.002",
          "reduceOnly": "true"}, ("ok", orders["algoAck"])))
    legs = engine.attach_protection(entry, 59990.0, 60010.0)
    assert len(legs) == 2
    algos = [(r[1], r[2].get("type")) for r in transport.requests
             if r[0] == "POST" and r[2].get("type") in
             ("STOP_MARKET", "TAKE_PROFIT_MARKET")]
    assert algos == [("/fapi/v1/algoOrder", "STOP_MARKET"),
                     ("/fapi/v1/algoOrder", "TAKE_PROFIT_MARKET")]  # STOP FIRST.
    transport.assert_empty()


def test_account_margin_and_funding_total(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, [("GET", "/fapi/v2/account", None, ("ok", ready["account"])),
                   ("GET", "/fapi/v1/income",
                    {"incomeType": "FUNDING_FEE"}, ("ok", orders["income"]))])
    assert engine.account_margin() == pytest.approx((95.5, 95.5))
    assert engine.venue_funding_total("BTCUSDT") == pytest.approx(-0.03)
    transport.assert_empty()


def test_listen_key_lifecycle_and_close(tmp_path):
    engine, transport = _live(
        tmp_path, [("POST", "/fapi/v1/listenKey", None,
                    ("ok", {"listenKey": "k1"})),
                   ("PUT", "/fapi/v1/listenKey", None, ("ok", {})),
                   ("DELETE", "/fapi/v1/listenKey", None, ("ok", {}))])
    assert engine.open_listen_key() == "k1"
    engine.keepalive_listen_key()
    engine.close()
    for _, _, params, headers in transport.requests:
        assert headers.get("X-MBX-APIKEY") == "TESTKEY"
        assert "signature" not in params  # key header, no signature.
    with pytest.raises(RuntimeError, match="closed"):
        engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    transport.assert_empty()


def test_exit_only_blocks_entries_not_exits(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/algoOrder", {"type": "STOP_MARKET"},
             ("ok", orders["algoAck"]))])
    engine.set_exit_only(True, "halt:daily-loss")
    with pytest.raises(ValueError, match="exit-only"):
        engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    engine.submit(EngineOrder("BTCUSDT", "SELL", 0.001, "STOP_MARKET",
                              stop_price=1.0, reduce_only=True, role="stop"))
    transport.assert_empty()


def test_recover_looks_up_journaled_open_orders(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"]))])
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.002, "MARKET"))
    assert engine._states[cid] == "open"
    transport.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
         ("ok", orders["orderQueryFilled"])),
        ("GET", "/fapi/v1/userTrades", {"orderId": 12345},
         ("ok", orders["userTrades"])))
    pushed: list = []
    engine.recover(pushed.append)
    assert engine._states[cid] == "filled"
    # Recovery-adopted fills flow through the bound handler (contract
    # v1 §2); poll() holds only pre-binding leftovers (none here).
    assert len([e for e in pushed if e.kind == "fill"]) == 2
    assert engine.poll() == []
    transport.assert_empty()


# -- W3-24H restart identities ------------------------------------------------------
def test_cross_symbol_same_trade_id_yields_distinct_fills(tmp_path):
    from cryptobot.accounting import Ledger
    engine, _ = _live(tmp_path, [])
    for sym in ("BTCUSDT", "ETHUSDT"):
        engine.note_user_event({
            "e": "ORDER_TRADE_UPDATE", "E": T0MS,
            "o": {"s": sym, "c": f"c-{sym}", "S": "BUY", "X": "FILLED",
                  "x": "TRADE", "l": "0.001", "L": "100.0", "n": "0.01",
                  "N": "USDT", "t": 777, "i": 1}})
    fills = [e.payload for e in engine.poll() if e.kind == "fill"]
    assert len(fills) == 2  # ID-777: no silent drop, no key collision.
    ids = {f.execution_id for f in fills}
    assert ids == {"binanceusdm/9f3b2fc5de52/BTCUSDT/777",
                   "binanceusdm/9f3b2fc5de52/ETHUSDT/777"}
    ledger = Ledger(10000.0)
    for f in fills:
        assert ledger.record_fill(f.side, f.qty, f.price, f.fee, f.ts_utc,
                                  f.execution_id) is True
    assert len(ledger.to_dict()["journal"]) == 2


def test_restart_rebuilds_unknown_roles_and_blocks(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("err", 503, None, "Service Unavailable"))])
    cmd = EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET", reservation_id="r-1")
    with pytest.raises(UnknownOutcomeError) as exc:
        engine.submit(cmd)
    cid = exc.value.client_id
    # Fresh process, same journal: identities + unknown rebuilt.
    engine2, transport2 = _live(tmp_path, [])
    assert engine2.unknown_ids() == (cid,)
    with pytest.raises(UnknownOutcomeError, match="lookup must resolve"):
        engine2.submit(cmd)
    transport2.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
         ("ok", orders["orderQueryFilled"])),
        ("GET", "/fapi/v1/userTrades", {"orderId": 12345},
         ("ok", orders["userTrades"])))
    assert engine2.lookup(cid) is not None
    assert engine2.unknown_ids() == ()
    assert len([e for e in engine2.poll() if e.kind == "fill"]) == 2
    transport2.assert_empty()


def test_recover_is_idempotent_across_restarts(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"]))])
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.002, "MARKET"))
    script = [
        ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
         ("ok", orders["orderQueryFilled"])),
        ("GET", "/fapi/v1/userTrades", {"orderId": 12345},
         ("ok", orders["userTrades"]))]
    transport.append(*script)
    pushed: list = []
    engine.recover(pushed.append)
    assert len([e for e in pushed if e.kind == "fill"]) == 2
    assert engine.poll() == []
    # Restart + recover again: terminal state rebuilt from the journal,
    # so no request is even sent (empty script would raise) and no fills.
    engine2, transport2 = _live(tmp_path, [])
    pushed2: list = []
    engine2.recover(pushed2.append)
    assert pushed2 == []
    assert engine2.poll() == []
    assert transport2.requests == []
    transport.assert_empty()
    transport2.assert_empty()


def test_restart_dedups_tape_against_stream_booked_trades(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"]))])
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.002, "MARKET"))
    stream = copy.deepcopy(orders["userStreamTrade"])
    stream["o"]["c"] = cid
    stream["o"]["X"] = "PARTIALLY_FILLED"  # non-terminal: recover re-looks-up.
    engine.note_user_event(stream)
    assert engine._states  # stream state tracked pre-restart.
    filled_before = [e for e in engine.poll() if e.kind == "fill"]
    assert len(filled_before) == 1
    # Restart: the stream-booked trade id is rebuilt; the tape replay
    # of the SAME trade id emits nothing new.
    tape = copy.deepcopy(orders["userTrades"])
    tape[0]["id"] = 777001
    tape[1]["id"] = 777001
    engine2, transport2 = _live(tmp_path, [])
    transport2.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
         ("ok", orders["orderQueryFilled"])),
        ("GET", "/fapi/v1/userTrades", {"orderId": 12345}, ("ok", tape)))
    pushed2: list = []
    engine2.recover(pushed2.append)
    assert pushed2 == []
    assert [e for e in engine2.poll() if e.kind == "fill"] == []
    transport2.assert_empty()


# -- W3-24H exchange contract ---------------------------------------------------------
def _algo_submit(engine, transport, orders, **kw):
    kw.setdefault("reservation_id", "r-9")
    cid = engine.submit(EngineOrder("BTCUSDT", "SELL", 0.002, "STOP_MARKET",
                                    stop_price=59990.0, reduce_only=True,
                                    role="stop", **kw))
    assert cid in engine._algo
    return cid


def test_algo_lookup_working_no_trades_call(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/algoOrder", {"type": "STOP_MARKET"},
             ("ok", orders["algoAck"]))])
    cid = _algo_submit(engine, transport, orders)
    transport.append(
        ("GET", "/fapi/v1/algoOrder", {"origClientAlgoId": cid},
         ("ok", orders["algoQueryWorking"])))
    status = engine.lookup(cid)
    assert status is not None and status.state == "open"
    assert engine._triggered.get(cid) is None
    assert [e for e in engine.poll() if e.kind == "fill"] == []
    transport.assert_empty()


def test_algo_lookup_triggered_adopts_triggered_tape(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/algoOrder", {"type": "STOP_MARKET"},
             ("ok", orders["algoAck"]))])
    cid = _algo_submit(engine, transport, orders)
    transport.append(
        ("GET", "/fapi/v1/algoOrder", {"origClientAlgoId": cid},
         ("ok", orders["algoQueryTriggered"])),
        ("GET", "/fapi/v1/userTrades", {"orderId": 12345},
         ("ok", orders["userTrades"])))
    status = engine.lookup(cid)
    # Seam state: a triggered algo is live ("open"); the internal
    # triggered truth stays journaled for fill routing.
    assert status is not None and status.state == "open"
    assert engine._states[cid] == "triggered"
    assert status.version >= 2
    assert engine._triggered[cid] == "12345"
    fills = [e for e in engine.poll() if e.kind == "fill"]
    assert [f.payload.qty for f in fills] == [0.001, 0.001]
    transport.assert_empty()


def test_algo_update_tracks_triggered_id_without_fills(tmp_path):
    engine, transport = _live(tmp_path, [])
    payload = {"E": T0MS, "e": "ALGO_UPDATE",
               "o": {"s": "BTCUSDT", "c": "a-1", "S": "SELL",
                     "X": "TRIGGERED", "x": "TRIGGERED", "i": 777001,
                     "ti": 12345}}
    engine.note_user_event(payload)
    assert engine._states["a-1"] == "triggered"
    assert engine._triggered["a-1"] == "12345"
    assert [e for e in engine.poll() if e.kind == "fill"] == []
    transport.assert_empty()


def test_stop_reject_is_deterministic_and_retryable(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/algoOrder", {"type": "STOP_MARKET"},
             ("err", 400, -1108, "Bad stop price."))])
    cmd = EngineOrder("BTCUSDT", "SELL", 0.002, "STOP_MARKET",
                      stop_price=59990.0, reduce_only=True, role="stop",
                      reservation_id="r-9")
    with pytest.raises(VenueRejectedError):
        engine.submit(cmd)
    assert engine.unknown_ids() == ()
    transport.append(("POST", "/fapi/v1/algoOrder", {"type": "STOP_MARKET"},
                      ("ok", orders["algoAck"])))
    engine.submit(cmd)
    transport.assert_empty()


def test_stop_unknown_blocks_until_lookup(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/algoOrder", {"type": "STOP_MARKET"},
             ("err", 503, None, "Service Unavailable"))])
    cmd = EngineOrder("BTCUSDT", "SELL", 0.002, "STOP_MARKET",
                      stop_price=59990.0, reduce_only=True, role="stop",
                      reservation_id="r-9")
    with pytest.raises(UnknownOutcomeError):
        engine.submit(cmd)
    with pytest.raises(UnknownOutcomeError, match="lookup must resolve"):
        engine.submit(cmd)
    assert engine.unknown_ids() != ()


def test_cancel_unknown_preserves_and_blocks(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"]))])
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET",
                                    reservation_id="r-3"))
    transport.append(("DELETE", "/fapi/v1/order", {"origClientOrderId": cid},
                      ("err", 503, None, "Service Unavailable")))
    with pytest.raises(UnknownOutcomeError):
        engine.cancel(cid, "operating-stop")
    assert engine._states[cid] == "CANCEL_UNKNOWN"
    cmd = EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET", reservation_id="r-3")
    with pytest.raises(UnknownOutcomeError, match="lookup must resolve"):
        engine.submit(cmd)
    transport.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
         ("ok", {**orders["orderQueryFilled"], "executedQty": "0.000",
                 "status": "CANCELED", "cumQuote": "0.0"})))
    engine.cancel(cid, "retry")  # lookup-first resolves, then cancels.
    transport.append(("DELETE", "/fapi/v1/order", {"origClientOrderId": cid},
                      ("ok", {})))
    # Already cancelled at venue per lookup; second cancel still sends
    # (idempotent venue-side) — drain it for a clean script.
    engine._states[cid] = "open"
    engine.cancel(cid, "retry")
    transport.assert_empty()


def test_cancel_on_unknown_looks_up_first(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("err", 0, None, "transport: timed out"))])
    cmd = EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET", reservation_id="r-4")
    with pytest.raises(UnknownOutcomeError) as exc:
        engine.submit(cmd)
    transport.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": exc.value.client_id},
         ("err", 400, -2013, "Order does not exist.")))
    engine.cancel(exc.value.client_id, "stale")  # void: no DELETE sent.
    assert transport.requests[-1][1] == "/fapi/v1/order"  # the lookup, only.
    transport.assert_empty()


def test_cancel_not_found_with_fills_contradicts_loudly(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"]))])
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.002, "MARKET"))
    transport.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
         ("ok", orders["orderQueryFilled"])),
        ("GET", "/fapi/v1/userTrades", {"orderId": 12345},
         ("ok", orders["userTrades"])))
    engine.lookup(cid)  # adopts fills.
    transport.append(("DELETE", "/fapi/v1/order", {"origClientOrderId": cid},
                      ("err", 400, -2013, "Order does not exist.")))
    with pytest.raises(ValueError, match="reconcile manually"):
        engine.cancel(cid, "stale")
    transport.assert_empty()


def test_demo_mode_selects_demo_hosts(tmp_path):
    from cryptobot.adapters.binance_live import DEMO_FAPI_URL, DEMO_FSTREAM_URL
    engine, _ = _live(tmp_path, [], demo=True)
    assert engine._base_url == DEMO_FAPI_URL
    assert engine.stream_host == DEMO_FSTREAM_URL
    journaled = [e for e in _journal_events(tmp_path) if e["event"] == "live-enabled"]
    assert journaled[0]["demo"] is True
    explicit, _ = _live(tmp_path, [], demo=True,
                        base_url="https://custom.example")
    assert explicit._base_url == "https://custom.example"


def test_caller_action_contract():
    from cryptobot.adapters.binance_live import caller_action
    assert caller_action(UnknownOutcomeError("c", "x")) == "lookup_then_retry"
    assert caller_action(VenueRejectedError(400, -1, "x")) == "retry_safe"
    assert caller_action(VenueHttpError(503, None, "x")) == "retry_safe"
    assert caller_action(ValueError("x")) == "abort"
    assert caller_action(RuntimeError("x")) == "abort"


def test_stream_reconnected_heals_gap_via_lookup(tmp_path, ready, orders):
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"]))])
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.002, "MARKET"))
    transport.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
         ("ok", orders["orderQueryFilled"])),
        ("GET", "/fapi/v1/userTrades", {"orderId": 12345},
         ("ok", orders["userTrades"])))
    engine.stream_reconnected()
    assert len([e for e in engine.poll() if e.kind == "fill"]) == 2
    transport.assert_empty()


def test_account_snapshot_reads_venue_account(tmp_path, ready):
    account = copy.deepcopy(ready["account"])
    account.update({"totalWalletBalance": "100.00000000",
                    "totalMarginBalance": "101.50000000"})
    account["positions"] = [
        {"symbol": "BTCUSDT", "positionAmt": "0.002",
         "entryPrice": "60000.00", "markPrice": "60750.00"},
        {"symbol": "ETHUSDT", "positionAmt": "0",
         "entryPrice": "0", "markPrice": "0"}]
    engine, transport = _live(
        tmp_path, [("GET", "/fapi/v2/account", None, ("ok", account))])
    snap = engine.account_snapshot()
    assert snap is not None and snap.complete is True
    assert snap.wallet_equity_usdt == 100.0
    assert snap.available_margin_usdt == 95.5
    assert snap.margin_balance_usdt == 101.5
    assert [(p.instrument, p.qty, p.entry_price, p.mark_price)
            for p in snap.positions] == [
                ("BTCUSDT", 0.002, 60000.00, 60750.00)]
    transport.assert_empty()


def test_account_snapshot_none_when_unreachable(tmp_path):
    # T1.3: idempotent reads retry bounded (3 attempts) before None.
    engine, transport = _live(
        tmp_path, [("GET", "/fapi/v2/account", None,
                    ("err", 503, None, "unavailable"))] * 3)
    assert engine.account_snapshot() is None
    transport.assert_empty()


def test_account_snapshot_incomplete_when_leg_missing(tmp_path):
    engine, transport = _live(
        tmp_path, [("GET", "/fapi/v2/account", None,
                    ("ok", {"totalWalletBalance": "100.0",
                            "availableBalance": "95.5",
                            "positions": []}))])
    snap = engine.account_snapshot()
    assert snap is not None and snap.complete is False
    assert snap.margin_balance_usdt is None
    transport.assert_empty()


# -- CORR exchange boundary: host separation + read-only status ---------------
def test_demo_refuses_production_host(tmp_path):
    from cryptobot.adapters.binance_live import PROD_FAPI_URL
    with pytest.raises(ValueError, match="forbids the production host"):
        BinanceLiveEngine(
            api_key="TESTKEY", api_secret="TESTSECRET",
            journal_path=tmp_path / "j", expected_leverage=3,
            run_tag="bl", live_enable=True, demo=True,
            base_url=PROD_FAPI_URL)


def test_prod_host_never_default(tmp_path):
    from cryptobot.adapters.binance_live import TESTNET_BASE_URL
    engine, _ = _live(tmp_path, [])
    assert engine._base_url == TESTNET_BASE_URL
    engine.close()


def test_venue_status_get_only(tmp_path, ready):
    engine, transport = _live(tmp_path, [
        ("GET", "/fapi/v1/time", None, ("ok", ready["time"])),
        ("GET", "/fapi/v2/account", None, ("ok", ready["account"])),
        ("GET", "/fapi/v1/positionSide/dual", None,
         ("ok", {"dualSidePosition": False})),
        ("GET", "/fapi/v1/exchangeInfo", None,
         ("ok", ready["exchangeInfo"])),
        ("GET", "/fapi/v1/commissionRate", {"symbol": "BTCUSDT"},
         ("ok", ready["commissionRate"])),
        ("GET", "/fapi/v1/openOrders", None, ("ok", [])),
    ])
    try:
        status = engine.venue_status(["BTCUSDT"])
    finally:
        engine.close()
    assert all(method == "GET" for method, _, _, _ in transport.requests)
    assert status["position_mode"] == "one-way"
    assert status["fees_bps"]["BTCUSDT"]["taker_bps"] == pytest.approx(5.0)
    assert "BTCUSDT" in status["filters"]
    assert status["open_orders"] == []
    assert status["clock_skew_ms"] == 0
    transport.assert_empty()
