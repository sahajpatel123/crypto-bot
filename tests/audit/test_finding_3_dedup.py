"""Finding 3: dedup deletes another symbol's event (Worker 5, OP-001).

Directive section 2: prepare_split_capture fingerprints channel,
timestamp and payload without symbol. Two different symbols with
identical quote payloads become one event.

Required: include venue, symbol, channel and appropriate event
identity. Preserve legitimate repeated updates and detect conflicting
duplicates.

These probes FAIL on the 01487ac base (bug reproduced) and PASS once
the identity fix lands. No src/ edits in OP-001.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.research.backtest import MECHANISM_SPLIT, prepare_split_capture

T0 = 1_700_000_000_000


def _bbo(symbol, ts, bid=60000.0, ask=60001.0, seq=1, venue_seq=0):
    return {"v": 1, "format": "cryptobot-events/1",
            "input_class": "synthetic-benchmark", "source": "x", "route": "x",
            "run_id": "t", "seq": seq, "channel": "bookTicker", "symbol": symbol,
            "exchange_ts_ms": ts, "local_recv_ms": ts, "local_mono_ns": seq,
            "gap_kind": None, "venue_seq": venue_seq,
            "payload": {"bid": bid, "ask": ask, "bid_qty": 5.0, "ask_qty": 5.0}}


class _TwoSymbol:
    """Minimal B5-shaped handle: one day, same quote on two symbols."""

    dataset_id = "audit-two-symbol"

    def __init__(self, events_by_symbol):
        self._events = events_by_symbol

    def days(self):
        return (1,)

    def events(self, symbol, day):
        assert day == 1
        for e in self._events.get(symbol, []):
            yield dict(e)

    def coverage(self):
        return {"days": [{"day": 1, "quotes_observed": True}]}

    def manifest_sha(self):
        return "a" * 64


def _read_events(cap_dir):
    lines = (Path(cap_dir) / "events.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_cross_symbol_identical_quotes_preserved(tmp_path):
    """Same channel/ts/payload on BTC and ETH must both survive."""
    ts = T0 + 1000
    payload_events = {
        "BTCUSDT": [_bbo("BTCUSDT", ts, seq=1)],
        "ETHUSDT": [_bbo("ETHUSDT", ts, seq=1)],
    }
    manifest = prepare_split_capture(
        _TwoSymbol(payload_events), MECHANISM_SPLIT, tmp_path / "cap",
        ("BTCUSDT", "ETHUSDT"))
    events = _read_events(tmp_path / "cap")
    symbols = sorted(e["symbol"] for e in events)
    assert manifest["n_events"] == 2, (
        f"expected 2 events (one per symbol), manifest says "
        f"{manifest['n_events']}")
    assert symbols == ["BTCUSDT", "ETHUSDT"], (
        f"cross-symbol dedup deleted an event; kept symbols: {symbols}")


def test_legitimate_repeated_updates_preserved(tmp_path):
    """Same-symbol same-ts same-payload with distinct venue_seq are distinct."""
    ts = T0 + 2000
    payload_events = {
        "BTCUSDT": [_bbo("BTCUSDT", ts, seq=1, venue_seq=101),
                    _bbo("BTCUSDT", ts, seq=2, venue_seq=102)],
    }
    manifest = prepare_split_capture(
        _TwoSymbol(payload_events), MECHANISM_SPLIT, tmp_path / "cap",
        ("BTCUSDT",))
    events = _read_events(tmp_path / "cap")
    assert manifest["n_events"] == 2, (
        f"legitimate repeats collapsed: kept {manifest['n_events']}/2")
    assert sorted(e["venue_seq"] for e in events) == [101, 102]


def test_conflicting_duplicates_detected(tmp_path):
    """Same identity with different payloads must be flagged, not silent."""
    ts = T0 + 3000
    payload_events = {
        "BTCUSDT": [_bbo("BTCUSDT", ts, bid=60000.0, seq=1, venue_seq=201),
                    _bbo("BTCUSDT", ts, bid=61000.0, seq=2, venue_seq=201)],
    }
    try:
        manifest = prepare_split_capture(
            _TwoSymbol(payload_events), MECHANISM_SPLIT, tmp_path / "cap",
            ("BTCUSDT",))
    except ValueError as exc:
        assert "conflict" in str(exc).lower() or "duplicate" in str(exc).lower(), (
            f"conflict must be named explicitly, got: {exc}")
        return
    conflicts = manifest.get("conflicts", manifest.get("conflicting_duplicates"))
    assert conflicts, (
        f"same venue_seq 201 with bids 60000 vs 61000 kept silently; "
        f"manifest must report conflicts, got keys {sorted(manifest)}")
