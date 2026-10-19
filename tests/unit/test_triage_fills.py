"""F0.5 triage batch 6: paper fill economics + dust (B#9, A#7).

B#9 (HIGH): paper fills carry slippage_drift_bps from the pessimistic
book-walk audit (thin books -> positive drift), and the session books
the drift as a conservative cost top-up (never better than
pessimistic). Zero-drift fills book unchanged.
A#7 (MEDIUM): ledger snaps sub-1e-9 dust to exactly flat (no dust
deadlock vs the policy 1e-9 epsilon); shutdown/flatten never chases
dust closes.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path


def test_thin_book_fill_carries_drift():
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.objects import Price, Quantity

    from cryptobot.adapters.paper_engine import NautilusPaperEngine
    from cryptobot.app.engine import EngineOrder

    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    engine = NautilusPaperEngine(submit_delay_ms=0, fill_delay_ms=1)
    engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                          tick_size=0.01, step_size=0.001, ts_utc=t0)

    def quote(i, bid, ask, size=0.01):
        engine.feed(QuoteTick(
            instrument_id=engine.instrument_id("BTCUSDT"),
            bid_price=Price(bid, 2), ask_price=Price(ask, 2),
            bid_size=Quantity(size, 3), ask_size=Quantity(size, 3),
            ts_event=int((t0 + timedelta(seconds=i)).timestamp() * 1e9),
            ts_init=int((t0 + timedelta(seconds=i)).timestamp() * 1e9)))

    quote(0, 60000.00, 60000.50)
    # Thin book (0.01) vs 0.1 order: 10x visible depth.
    engine.submit(EngineOrder("BTCUSDT", "BUY", 0.1, "MARKET"))
    fills = []
    for i in range(1, 6):
        quote(i, 60000.00 + i, 60000.50 + i)
        fills += [e for e in engine.poll() if e.kind == "fill"]
    assert fills, "no fill booked"
    assert any(f.payload.slippage_drift_bps > 0 for f in fills), (
        "thin-book fill priced without pessimistic drift")


def test_session_books_drift_top_up(tmp_path):
    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session
    from cryptobot.app.store import RunStore

    class _Eng:
        model_label = "b6"
        assumptions = ()

        def poll(self):
            return []

        def open_orders(self):
            return []

    text = Path("configs/paper.toml").read_text()
    text = text.replace('mode = "replay"', 'mode = "paper"', 1)
    text = text.replace('kind = "reference"', 'kind = "nautilus"', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    session = Session(load_config(cfg_path),
                      RunStore(tmp_path / "runs" / "cryptobot.db"),
                      tmp_path / "run", "b6-run", engine=_Eng())
    session._position = {"reservation_id": "r-1",  # noqa: SLF001
                         "entry_pre_id": "e-pre", "entry_id": "e-1",
                         "legs": [], "retired": [], "close_ids": []}
    now = datetime(2026, 10, 17, tzinfo=UTC)
    out = session._apply_fill(  # noqa: SLF001
        client_order_id="e-1", execution_id="x-drift",
        instrument="BTCUSDT", side="BUY", qty=1.0, price=60000.0,
        fee=30.0, ts_utc=now, liquidity="taker",
        slippage_drift_bps=10.0)
    assert out == "applied"
    # 10bps of 60k notional = 60 top-up on top of the 30 fee.
    assert session.ledger.paid_costs() == 90.0


def test_dust_snaps_to_flat():
    from cryptobot.accounting.ledger import Ledger

    ledger = Ledger(10000.0)
    ts = datetime(2026, 10, 17, tzinfo=UTC)
    ledger.record_fill("BUY", 0.1, 60000.0, 0.0, ts, "a")
    ledger.record_fill("BUY", 0.2, 60000.0, 0.0, ts, "b")
    ledger.record_fill("SELL", 0.3, 60000.0, 0.0, ts, "c")
    assert ledger.position_qty() == 0.0
    assert ledger.has_position() is False
    assert ledger.entry_basis() is None
