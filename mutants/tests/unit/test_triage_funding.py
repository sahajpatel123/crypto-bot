"""F0.5 triage batch 5: funding truth (A#5, A#8, B#10, B#22).

A#8 (MEDIUM): reconcile compares per-symbol venue vs per-symbol
booked (not global); malformed rows are LOUD (skipped counts), never
silent agreement.
B#22 (LOW): fallback funding ids include the row index (identical
(ms, amount) rows no longer collide).
A#5 (HIGH): paper recover restores settled funding totals (no false
funding-mismatch halt after restart).
B#10 (HIGH): live venue funding is booked on a supervision throttle
(book_settled_funding wired, not orphaned).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def _session_with(engine, tmp_path: Path, run_id="b5-run"):
    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session
    from cryptobot.app.store import RunStore

    text = Path("configs/paper.toml").read_text()
    text = text.replace('mode = "replay"', 'mode = "paper"', 1)
    text = text.replace('kind = "reference"', 'kind = "nautilus"', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    return Session(load_config(cfg_path),
                   RunStore(tmp_path / "runs" / "cryptobot.db"),
                   tmp_path / "run", run_id, engine=engine)


class _IncomeEngine:
    model_label = "b5"
    assumptions = ()

    def __init__(self, rows_by_symbol):
        self._rows = rows_by_symbol

    def poll(self):
        return []

    def open_orders(self):
        return []

    def funding_income(self, symbol):
        return list(self._rows.get(symbol, []))


def test_reconcile_compares_per_symbol(tmp_path):
    btc = [{"income": "-3.0", "time": 1728720000000, "tranId": 1}]
    eth = [{"income": "5.0", "time": 1728720000000, "tranId": 2}]
    engine = _IncomeEngine({"BTCUSDT": btc, "ETHUSDT": eth})
    session = _session_with(engine, tmp_path)
    assert session.book_settled_funding("BTCUSDT") == 1
    assert session.book_settled_funding("ETHUSDT") == 1
    rec = session.funding_reconcile("BTCUSDT")
    assert rec["diff_symbol"] == 0.0, rec
    assert rec["booked_symbol"] == -3.0, rec


def test_malformed_rows_are_loud(tmp_path):
    rows = [{"income": "bogus-not-a-number", "time": 1728720000000,
             "tranId": 9},
            {"income": "-2.0", "time": 1728720000000, "tranId": 10}]
    engine = _IncomeEngine({"BTCUSDT": rows})
    session = _session_with(engine, tmp_path)
    assert session.book_settled_funding("BTCUSDT") == 1
    rec = session.funding_reconcile("BTCUSDT")
    assert rec["skipped_venue"] == 1, rec
    assert rec["venue_total"] == -2.0, rec


def test_identical_fallback_rows_both_book(tmp_path):
    rows = [{"income": "-4.2", "time": 1728720000000},
            {"income": "-4.2", "time": 1728720000000}]
    engine = _IncomeEngine({"BTCUSDT": rows})
    session = _session_with(engine, tmp_path)
    assert session.book_settled_funding("BTCUSDT") == 2
    assert session.ledger.funding_net() == -8.4


def _mark_record(recv_ms, mark, rate=0.0001, next_ms=None):
    return {
        "v": 1, "format": "cryptobot-events/1", "input_class": "observed-public",
        "source": "binance-fapi-ws", "route": "public", "run_id": "r1", "seq": 9,
        "channel": "markPrice", "symbol": "BTCUSDT", "exchange_ts_ms": recv_ms,
        "local_recv_ms": recv_ms, "local_mono_ns": recv_ms * 1_000_000,
        "gap_kind": None, "venue_seq": 9,
        "payload": {"mark": mark, "funding_rate": rate,
                    "next_funding_ms": recv_ms if next_ms is None else next_ms},
    }


def test_paper_recover_restores_settled_funding(tmp_path):
    from datetime import timedelta

    from cryptobot.adapters.paper_engine import NautilusPaperEngine
    from cryptobot.app.engine import EngineOrder
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.objects import Price, Quantity

    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    journal = tmp_path / "paper.jsonl"

    def _mk():
        engine = NautilusPaperEngine(
            submit_delay_ms=0, fill_delay_ms=1, journal_path=str(journal))
        engine.add_instrument("BTCUSDT", price_precision=2,
                              size_precision=3, tick_size=0.01,
                              step_size=0.001, ts_utc=t0)
        return engine

    def _quote(engine, i, bid, ask):
        engine.feed(QuoteTick(
            instrument_id=engine.instrument_id("BTCUSDT"),
            bid_price=Price(bid, 2), ask_price=Price(ask, 2),
            bid_size=Quantity(1.0, 3), ask_size=Quantity(1.0, 3),
            ts_event=int((t0 + timedelta(seconds=i)).timestamp() * 1e9),
            ts_init=int((t0 + timedelta(seconds=i)).timestamp() * 1e9)))

    engine = _mk()
    t0ms = int(t0.timestamp() * 1000)
    _quote(engine, 0, 60000.00, 60000.50)
    engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    _quote(engine, 1, 60001.00, 60001.50)
    assert [e for e in engine.poll() if e.kind == "fill"]
    engine.note_event(_mark_record(t0ms + 1000, 60000.0, rate=0.0001,
                                   next_ms=t0ms + 1000))
    assert [e for e in engine.poll() if e.kind == "funding"]
    before = engine.settled_funding_total()
    assert before != 0.0

    engine2 = _mk()
    engine2.recover(lambda event: None)
    assert engine2.settled_funding_total() == before


def test_supervision_books_live_funding(tmp_path):
    rows = [{"income": "-1.5", "time": 1728720000000, "tranId": 21}]
    engine = _IncomeEngine({"BTCUSDT": rows})
    session = _session_with(engine, tmp_path)
    session.clock.set_ms(1_700_000_000_000)
    session.policy.reconcile_day(120.0, 0.0)
    from cryptobot.app.session import _SymbolFeed
    feed = _SymbolFeed("BTCUSDT", 0)
    feed.mark = 60000.0
    feed.mark_ts = session.now_utc()
    session._feeds["BTCUSDT"] = feed
    booked = session._book_live_funding()  # noqa: SLF001
    assert booked == {"BTCUSDT": 1}, booked
    assert session.ledger.funding_net() == -1.5
    assert session._book_live_funding() == {"BTCUSDT": 0}  # noqa: SLF001
