"""V-008 §7: booked-total accessor + sizing emits exact step multiples."""
from conftest import NOW, build_account, build_intent, load_fixture, make_policy
from cryptobot.risk import Approved
from cryptobot.risk.rounding import floor_to_step

INTENTS = load_fixture("risk_intents.json")
ACCOUNTS = load_fixture("risk_accounts.json")
TS = "2026-10-11T12:00:00+00:00"


def test_booked_total_zero_by_default(tmp_path):
    policy = make_policy(tmp_path)
    assert policy.booked_total_qty() == 0.0


def test_booked_total_sums_nets(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)
    policy.note_fill_delta(out.reservation_id, "e1", "BTCUSDT", "BUY",
                           0.5, 100.0, 0.0, TS)
    policy.note_fill_delta(out.reservation_id, "e2", "BTCUSDT", "BUY",
                           0.25, 101.0, 0.0, TS)
    assert policy.booked_total_qty() == 0.75


def test_booked_total_eps_rounds_to_zero(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)
    policy.note_fill_delta(out.reservation_id, "e1", "BTCUSDT", "BUY",
                           0.5, 100.0, 0.0, TS)
    policy.note_fill_delta(out.reservation_id, "e2", "BTCUSDT", "SELL",
                           0.5, 100.0, 0.0, TS)
    assert policy.booked_total_qty() == 0.0


def test_approved_qty_is_exact_step_multiple(tmp_path):
    from cryptobot.risk import InstrumentFilter
    filt = InstrumentFilter(min_notional_usdt=5.0, qty_step=0.01,
                            min_qty=0.01, max_qty=1000.0, tick_size=0.1)
    policy = make_policy(tmp_path, instrument_filters={"BTCUSDT": filt},
                         filters_asof_utc=NOW)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)
    assert out.qty == floor_to_step(out.qty, 0.01)
    assert out.qty > 0
