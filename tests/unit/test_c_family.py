"""Family C engine: no look-ahead, cost and funding accounting."""
from __future__ import annotations

import datetime as dt
import random

from cryptobot.research import c_family


def _days(n: int) -> list[str]:
    d0 = dt.date(2022, 1, 3)  # a Monday
    return [(d0 + dt.timedelta(days=k)).isoformat() for k in range(n)]


def _market(n: int = 160, syms: int = 10, seed: int = 5):
    rng = random.Random(seed)
    days = _days(n)
    closes, funding = {}, {}
    for k in range(syms):
        px, series, fund = 100.0, {}, {}
        for d in days:
            px *= 1 + rng.gauss(0.0, 0.03)
            series[d] = px
            fund[d] = rng.gauss(0.0001, 0.0003)
        closes[f"S{k}"], funding[f"S{k}"] = series, fund
    return days, closes, funding


def test_no_lookahead_future_prices_do_not_change_past_results():
    days, closes, funding = _market()
    cut = days[120]
    for spec in c_family.SPECS.values():
        base = c_family.run(spec, closes, funding, start=days[0], end=cut)
        shocked = {s: {d: (v * (3.0 if d > cut else 1.0)) for d, v in c.items()}
                   for s, c in closes.items()}
        again = c_family.run(spec, shocked, funding, start=days[0], end=cut)
        assert base == again, spec.name


def test_costs_and_funding_booked():
    days = _days(80)
    closes = {f"S{k}": {d: 100.0 * (1.01 ** i) for i, d in enumerate(days)}
              for k in range(2)}
    funding = {s: {d: 0.001 for d in days} for s in closes}
    out = c_family.run(c_family.SPECS["C1"], closes, funding,
                       start=days[0], end=days[-1])
    first, later = out[0], out[5]
    # uptrend: fully long; one entry of 1.0 gross notional, then no trades
    assert abs(first.turnover - 1.0) < 1e-12 and later.turnover == 0.0
    # +1% move, minus 10bps funding paid by longs, minus 9bps entry cost
    assert abs(first.net_bps - (100.0 - 10.0 - 9.0)) < 1e-6
    assert abs(later.net_bps - 90.0) < 1e-6


def test_weekly_specs_rebalance_only_on_mondays():
    days, closes, funding = _market()
    out = c_family.run(c_family.SPECS["C2"], closes, funding,
                       start=days[0], end=days[-1])
    for r in out:
        prev = (dt.date.fromisoformat(r.day) - dt.timedelta(days=1))
        if r.turnover > 0 and r is not out[0]:
            assert prev.weekday() == 0, r.day
