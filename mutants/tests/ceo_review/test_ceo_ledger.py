"""F-CEO-01: partial-close accounting keeps the remaining entry basis."""
from helpers import T0

from cryptobot.accounting import Ledger


def test_long_partial_reductions_keep_basis():
    ledger = Ledger(1000)
    ledger.record_fill("BUY", 10, 10, 0, T0)
    ledger.record_fill("SELL", 4, 11, 0, T0)
    assert ledger.position_qty() == 6.0
    ledger.record_fill("SELL", 6, 12, 0, T0)
    assert ledger.position_qty() == 0.0
    assert ledger.net_realised() == 16.0  # 4x1 + 6x2; bug reports 76
    assert ledger.marked_equity(12) - 1000 == 16.0


def test_short_partial_reductions_keep_basis():
    ledger = Ledger(1000)
    ledger.record_fill("SELL", 10, 12, 0, T0)
    ledger.record_fill("BUY", 4, 11, 0, T0)
    assert ledger.position_qty() == -6.0
    ledger.record_fill("BUY", 6, 10, 0, T0)
    assert ledger.position_qty() == 0.0
    assert ledger.net_realised() == 16.0  # 4x1 + 6x2


def test_long_reversal_sets_new_basis():
    ledger = Ledger(1000)
    ledger.record_fill("BUY", 10, 10, 0, T0)
    ledger.record_fill("SELL", 14, 12, 0, T0)
    assert ledger.net_realised() == 20.0
    assert ledger.position_qty() == -4.0
    ledger.record_fill("BUY", 4, 11, 0, T0)  # close the short leg +1 each
    assert ledger.net_realised() == 24.0


def test_short_reversal_sets_new_basis():
    ledger = Ledger(1000)
    ledger.record_fill("SELL", 10, 12, 0, T0)
    ledger.record_fill("BUY", 14, 10, 0, T0)
    assert ledger.net_realised() == 20.0
    assert ledger.position_qty() == 4.0
    ledger.record_fill("SELL", 4, 11, 0, T0)
    assert ledger.net_realised() == 24.0


def test_fees_reduce_realised_exactly_once():
    ledger = Ledger(1000)
    ledger.record_fill("BUY", 10, 10, 1, T0)
    ledger.record_fill("SELL", 10, 11, 1, T0)
    assert ledger.net_realised() == 8.0  # 10 price gain minus 2 fees
    assert ledger.paid_costs() == 2.0
