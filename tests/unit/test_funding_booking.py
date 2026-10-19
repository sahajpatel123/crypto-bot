"""T1.7: settled funding booked in ledger + reconciled vs venue."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import venue_fixtures as venues
from cryptobot.app.config import load_config
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore

ROWS = [
    {"symbol": "BTCUSDT", "incomeType": "FUNDING_FEE", "income": "-1.25",
     "time": 1728720000000, "tranId": 111},
    {"symbol": "BTCUSDT", "incomeType": "FUNDING_FEE", "income": "0.50",
     "time": 1728748800000, "tranId": 112},
]


def test_engine_funding_income_rows(tmp_path):
    script = [("GET", "/fapi/v1/income", {"symbol": "BTCUSDT"},
               ("ok", ROWS))]
    engine, transport = venues.make_engine(tmp_path, script)
    rows = engine.funding_income("BTCUSDT")
    assert [r["tranId"] for r in rows] == [111, 112]
    transport.assert_empty()


class _StubEngine:
    model_label = "t17-stub"
    assumptions = ("stub: t17",)

    def poll(self):
        return []

    def open_orders(self):
        return []

    def funding_income(self, symbol):
        return list(ROWS)


def _session(tmp_path: Path) -> Session:
    text = Path("configs/paper.toml").read_text()
    text = text.replace('mode = "replay"', 'mode = "paper"', 1)
    text = text.replace('kind = "reference"', 'kind = "nautilus"', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    return Session(load_config(cfg_path), store, tmp_path / "run",
                   "t17-run", engine=_StubEngine())


def test_session_books_funding_idempotently_and_reconciles(tmp_path):
    session = _session(tmp_path)
    booked = session.book_settled_funding("BTCUSDT")
    assert booked == 2
    assert session.ledger.funding_net() == -0.75
    # Second pass: venue rows already booked by tranId — no double count.
    assert session.book_settled_funding("BTCUSDT") == 0
    assert session.ledger.funding_net() == -0.75
    rec = session.funding_reconcile("BTCUSDT")
    assert rec["venue_total"] == -0.75
    assert rec["booked_net"] == -0.75
    assert rec["diff"] == 0.0
