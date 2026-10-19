"""F1.1 property tests: ledger conservation + fill idempotency (Hypothesis).

Conservation: marked(ref) == pilot + flows + realised + unrealised(ref)
for every fill/funding/flow sequence. Idempotency: duplicate exec_ids
never double-book (ledger + policy sink); booked nets are reorder-
invariant (commutative sums); same-side ledger replays agree.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from itertools import count

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from cryptobot.accounting.ledger import Ledger
from cryptobot.risk.state import Reservation

NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=UTC)
_case = count()

_side = st.sampled_from(["BUY", "SELL"])
_qty = st.floats(min_value=0.001, max_value=100.0,
                 allow_nan=False, allow_infinity=False)
_price = st.floats(min_value=1.0, max_value=100000.0,
                   allow_nan=False, allow_infinity=False)
_fee = st.floats(min_value=0.0, max_value=100.0,
                 allow_nan=False, allow_infinity=False)
_money = st.floats(min_value=-100000.0, max_value=100000.0,
                   allow_nan=False, allow_infinity=False)


def _unrealised(ledger: Ledger, ref: float) -> float:
    qty = ledger.position_qty()
    basis = ledger.entry_basis()
    if qty == 0.0 or basis is None:
        return 0.0
    return qty * (ref - basis)


@given(fills=st.lists(st.tuples(_side, _qty, _price, _fee),
                      min_size=1, max_size=20),
       fundings=st.lists(_money, min_size=0, max_size=5),
       flows=st.lists(_money, min_size=0, max_size=5),
       pilot=st.floats(min_value=100.0, max_value=1000000.0),
       ref=_price)
@settings(max_examples=150, deadline=3000)
def test_ledger_conservation(fills, fundings, flows, pilot, ref):
    ledger = Ledger(pilot)
    ts = NOW
    for i, (side, qty, price, fee) in enumerate(fills):
        ts = ts + timedelta(seconds=1)
        assert ledger.record_fill(side, qty, price, fee, ts, f"f{i}") is True
    for i, amount in enumerate(fundings):
        ts = ts + timedelta(seconds=1)
        assert ledger.record_funding(amount, ts, f"u{i}") is True
    for i, amount in enumerate(flows):
        ts = ts + timedelta(seconds=1)
        assert ledger.record_flow(amount, "external", ts, f"w{i}") is True
    expect = (pilot + ledger.total_flows() + ledger.net_realised()
              + _unrealised(ledger, ref))
    assert math.isclose(ledger.marked_equity(ref), expect,
                        rel_tol=1e-9, abs_tol=1e-6), (
        ledger.marked_equity(ref), expect)


@given(fills=st.lists(st.tuples(_side, _qty, _price, _fee),
                      min_size=1, max_size=10))
@settings(max_examples=100, deadline=2000)
def test_fill_duplication_never_double_books(fills):
    ledger = Ledger(10000.0)
    ts = NOW
    for i, (side, qty, price, fee) in enumerate(fills):
        ts = ts + timedelta(seconds=1)
        assert ledger.record_fill(side, qty, price, fee, ts, f"f{i}") is True
    before = (ledger.marked_equity(100.0), ledger.position_qty(),
              ledger.net_realised(), ledger.paid_costs())
    for i, (side, qty, price, fee) in enumerate(fills):
        assert ledger.record_fill(side, qty, price, fee, ts, f"f{i}") is False
    after = (ledger.marked_equity(100.0), ledger.position_qty(),
             ledger.net_realised(), ledger.paid_costs())
    assert before == after


@given(sides=st.lists(_side, min_size=2, max_size=8),
       qtys=st.lists(_qty, min_size=2, max_size=8))
@settings(max_examples=100, deadline=2000,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_policy_booked_net_reorder_invariant(tmp_path, sides, qtys):
    from cryptobot.risk.policy import RiskPolicy
    from cryptobot.risk.types import RiskConfig

    n = min(len(sides), len(qtys))
    sides, qtys = sides[:n], qtys[:n]
    legs = [(f"e{i}", sides[i], qtys[i]) for i in range(n)]
    base = tmp_path / f"case{next(_case)}"
    base.mkdir(parents=True, exist_ok=True)

    def _book(order, tag):
        pol = RiskPolicy(config=RiskConfig(),
                         state_path=base / f"{tag}.json",
                         now_utc=lambda: NOW)
        pol._state.reservations["r-1"] = Reservation(
            reservation_id="r-1", intent_ref="t", instrument="BTCUSDT",
            side="LONG", notional=100.0, reserved_risk=1.0,
            created_utc=NOW.isoformat(),
            expires_utc=(NOW + timedelta(seconds=60)).isoformat(), qty=1.0)
        for exec_id, venue_side, qty in order:
            pol.note_fill_delta("r-1", exec_id, "BTCUSDT", venue_side,
                                qty, 100.0, 0.01, NOW.isoformat())
            # Duplicate redelivery is ignored.
            pol.note_fill_delta("r-1", exec_id, "BTCUSDT", venue_side,
                                qty, 100.0, 0.01, NOW.isoformat())
        return pol.booked_net("r-1")

    fwd = _book(legs, "fwd")
    rev = _book(list(reversed(legs)), "rev")
    assert math.isclose(fwd, rev, rel_tol=1e-12, abs_tol=1e-12)
    expect = sum(q if s == "BUY" else -q for _, s, q in legs)
    assert math.isclose(fwd, expect, rel_tol=1e-12, abs_tol=1e-12)


@given(qtys=st.lists(_qty, min_size=1, max_size=8),
       prices=st.lists(_price, min_size=1, max_size=8))
@settings(max_examples=100, deadline=2000)
def test_same_side_replay_order_invariant(qtys, prices):
    n = min(len(qtys), len(prices))
    legs = list(zip(qtys[:n], prices[:n], strict=True))

    def _replay(order):
        ledger = Ledger(10000.0)
        ts = NOW
        for i, (qty, price) in enumerate(order):
            ts = ts + timedelta(seconds=1)
            ledger.record_fill("BUY", qty, price, 0.01, ts, f"b{i}")
        return ledger

    a = _replay(legs)
    b = _replay(list(reversed(legs)))
    assert math.isclose(a.position_qty(), b.position_qty(),
                        rel_tol=1e-12, abs_tol=1e-12)
    assert math.isclose(a.marked_equity(100.0), b.marked_equity(100.0),
                        rel_tol=1e-9)
