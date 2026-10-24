"""User-stream reader tests: gaps, reconnect, heal (Worker 2, release)."""
import copy
import json
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import venue_fixtures as venues
from cryptobot.adapters.user_stream import UserStreamReader

FIX = venues.FIX
T0MS = venues.T0MS
NOW = venues.NOW
ReplayTransport = venues.ReplayTransport
_live = venues.make_engine
_ready_script = venues.ready_script


class FakeSocket:
    """Scripted envelopes; None entries are timeouts; 'die' kills."""

    def __init__(self, script):
        self.script = deque(script)
        self.closed = False

    def recv(self, timeout_s):
        assert not self.closed
        if not self.script:
            return None
        item = self.script.popleft()
        if item == "die":
            raise ConnectionError("socket died")
        return item

    def close(self):
        self.closed = True


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def _reader(engine, sockets, clock):
    made = []

    def factory(key):
        sock = sockets[len(made)]
        made.append(key)
        return sock

    reader = UserStreamReader(engine, factory, keepalive_s=1500.0,
                              now=clock,
                              sleep=lambda s: clock.advance(s))
    return reader, made


def test_connect_heals_then_dispatches(tmp_path):
    orders = json.loads((FIX / "orders.json").read_text())
    engine, transport = _live(tmp_path, [
        ("POST", "/fapi/v1/listenKey", None, ("ok", {"listenKey": "K1"})),
        ("GET", "/fapi/v1/order", None, ("ok", orders["orderQueryFilled"])),
        ("GET", "/fapi/v1/userTrades", None, ("ok", orders["userTrades"])),
    ])
    # Journaled open order from a previous process (submit-intent only).
    (tmp_path / "live.jsonl").write_text(json.dumps({
        "ts_utc": NOW.isoformat(), "event": "submit-intent",
        "client_id": "bl-old-1", "symbol": "BTCUSDT", "side": "BUY",
        "kind": "MARKET", "qty": 0.002, "role": "entry",
        "reservation_id": "r1"}) + "\n", encoding="utf-8")
    engine2, transport2 = _live(tmp_path, transport.script)
    trade = copy.deepcopy(orders["userStreamTrade"])
    trade["o"]["c"] = "bl-old-1"
    sockets = [FakeSocket([trade, None])]
    clock = Clock()
    pushed: list = []
    engine2.bind_sink(pushed.append)
    reader, made = _reader(engine2, sockets, clock)
    assert reader.poll_once() == "event"  # connect + heal + dispatch.
    assert made == ["K1"]
    assert reader.poll_once() == "idle"  # live socket, nothing new.
    assert engine2.order_status("bl-old-1").state == "filled"
    assert [e.kind for e in pushed].count("fill") == 3  # tape 2 + stream 1.
    assert reader.connected
    transport2.assert_empty()
    reader.close()


def test_silence_is_idleness_never_a_gap(tmp_path):
    engine, transport = _live(tmp_path, [
        ("POST", "/fapi/v1/listenKey", None, ("ok", {"listenKey": "K1"})),
        ("PUT", "/fapi/v1/listenKey", None, ("ok", {})),
    ])
    sockets = [FakeSocket([])]
    clock = Clock()
    reader, made = _reader(engine, sockets, clock)
    assert reader.poll_once() == "healed"  # first connect heals.
    clock.advance(1400.0)  # long silence: still idle, same socket.
    assert reader.poll_once() == "idle"
    assert made == ["K1"] and not sockets[0].closed
    clock.advance(100.0)  # keepalive tick, still no reconnect.
    assert reader.poll_once() == "keepalive"
    assert made == ["K1"] and reader.connected
    journal = (tmp_path / "live.jsonl").read_text(encoding="utf-8")
    assert journal.count("stream-reconnected") == 1  # connect-only heal.
    transport.assert_empty()
    reader.close()


def test_listen_key_expiry_reopens_and_heals(tmp_path):
    engine, transport = _live(tmp_path, [
        ("POST", "/fapi/v1/listenKey", None, ("ok", {"listenKey": "K1"})),
        ("POST", "/fapi/v1/listenKey", None, ("ok", {"listenKey": "K2"})),
    ])
    sockets = [FakeSocket([{"e": "listenKeyExpired", "E": T0MS}]),
               FakeSocket([])]
    clock = Clock()
    reader, made = _reader(engine, sockets, clock)
    assert reader.poll_once() == "event"
    assert not reader.connected  # dead socket dropped with the key.
    assert reader.poll_once() == "healed"  # reopened + redialed.
    assert made == ["K1", "K2"]
    journal = (tmp_path / "live.jsonl").read_text(encoding="utf-8")
    assert "listen-key-expired" in journal
    assert journal.count("stream-reconnected") == 2
    transport.assert_empty()
    reader.close()


def test_socket_error_heals_with_backoff_then_recovers(tmp_path):
    engine, transport = _live(tmp_path, [
        ("POST", "/fapi/v1/listenKey", None, ("ok", {"listenKey": "K1"})),
    ])
    sock = FakeSocket([None])
    clock = Clock()
    reader, made = _reader(engine, [sock], clock)
    assert reader.poll_once() == "healed"  # connected (heal: nothing open).
    sock.script.append("die")
    reader._factory = lambda key: (_ for _ in ()).throw(
        ConnectionError("dial refused"))
    # Socket dies; the redial fails too -> backoff, no throw.
    assert reader.poll_once() == "backoff"
    assert reader.poll_once() == "backoff"  # still inside backoff.
    clock.advance(2.0)
    fresh = FakeSocket([])
    reader._factory = lambda key: (made.append(key), fresh)[1]
    assert reader.poll_once() == "healed"
    assert reader.connected
    transport.assert_empty()
    reader.close()


def test_keepalive_ticks_without_events(tmp_path):
    engine, transport = _live(tmp_path, [
        ("POST", "/fapi/v1/listenKey", None, ("ok", {"listenKey": "K1"})),
        ("PUT", "/fapi/v1/listenKey", None, ("ok", {})),
    ])
    sockets = [FakeSocket([])]
    clock = Clock()
    reader, _ = _reader(engine, sockets, clock)
    assert reader.poll_once() == "healed"  # first connect heals.
    clock.advance(1499.0)
    assert reader.poll_once() == "idle"
    clock.advance(1.0)
    assert reader.poll_once() == "keepalive"
    transport.assert_empty()
    reader.close()
