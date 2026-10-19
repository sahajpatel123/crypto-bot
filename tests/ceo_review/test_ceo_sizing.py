"""F-CEO-04: sizing bounds planned loss at the adverse permitted price."""
from helpers import T0, audit_intent

from cryptobot.risk import RiskConfig, plan_size


def _worst_case_loss(plan, adverse_price, stop, stressed_pct):
    return plan.qty * abs(adverse_price - stop) + plan.qty * adverse_price * stressed_pct


def test_long_worst_price_loss_within_budget():
    cfg = RiskConfig()
    intent = audit_intent(T0, low=100, high=110, stop=99)
    plan = plan_size(intent, 1000, cfg)
    stressed = (1 + 1 + 1 + 0) / 10000 * cfg.stress_multiplier
    loss = _worst_case_loss(plan, 110, 99, stressed)
    assert loss <= plan.reserved_risk  # budget 2.5; midpoint sizing gives ~4.57


def test_short_worst_price_loss_within_budget():
    from cryptobot.coordination import Side

    cfg = RiskConfig()
    intent = audit_intent(T0, low=100, high=110, stop=111, side=Side.SHORT)
    plan = plan_size(intent, 1000, cfg)
    stressed = (1 + 1 + 1 + 0) / 10000 * cfg.stress_multiplier
    loss = _worst_case_loss(plan, 100, 111, stressed)
    assert loss <= plan.reserved_risk
