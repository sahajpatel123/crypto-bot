"""F2.1 close-out: stressed P&L (1x/2x) in run reports (T1.9)."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


def test_report_carries_stressed_pnl(tmp_path):
    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session
    from cryptobot.app.store import RunStore

    class _Eng:
        model_label = "pnl-stub"
        assumptions = ("stub",)

        def poll(self):
            return []

        def open_orders(self):
            return []

    text = Path("configs/paper.toml").read_text()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    session = Session(load_config(cfg_path),
                      RunStore(tmp_path / "runs" / "cryptobot.db"),
                      tmp_path / "run", "pnl-run", engine=_Eng())
    now = datetime(2026, 10, 17, tzinfo=UTC)
    session.ledger.record_fill("BUY", 1.0, 100.0, 2.0, now, "e1")
    session.ledger.record_fill("SELL", 1.0, 110.0, 2.0, now, "e2")
    report = session._build_report("test", "synthetic-test")  # noqa: SLF001
    # realised = 10 - 4 = 6; gross = 10; pnl_2x = 10 - 8 = 2.
    assert session.ledger.net_realised() == 6.0
    assert report["pnl_1x"] == 6.0
    assert report["gross_pnl"] == 10.0
    assert report["pnl_2x"] == 2.0
