"""C2-FWD recorder: matches research C2 rules, idempotent, catch-up safe."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import random
from pathlib import Path

from cryptobot.research import c_family

_spec = importlib.util.spec_from_file_location(
    "forward_c2", Path(__file__).resolve().parents[2] / "tools/forward_c2.py")
fwd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fwd)

D0 = dt.date(2027, 1, 4)  # Monday
DAYS = [(D0 + dt.timedelta(days=k)).isoformat() for k in range(90)]


class FakeFetcher:
    def __init__(self, n=12, seed=9):
        rng = random.Random(seed)
        self.closes, self.fund = {}, {}
        for k in range(n):
            px, c, f = 50.0, {}, {}
            for d in DAYS:
                px *= 1 + rng.gauss(0, 0.04)
                c[d], f[d] = px, rng.gauss(0.0001, 0.0002)
            self.closes[f"S{k:02d}USDT"], self.fund[f"S{k:02d}USDT"] = c, f

    def trading_symbols(self):
        return sorted(self.closes)

    def quote_volume_30d(self, symbol, end_day):
        return 1.0

    def mark_closes(self, symbol, start, end):
        return {d: v for d, v in self.closes[symbol].items() if start <= d <= end}

    def funding(self, symbol, start, end):
        return {d: v for d, v in self.fund[symbol].items() if start <= d <= end}


def test_matches_research_engine(tmp_path):
    f = FakeFetcher()
    first = DAYS[c_family.MIN_HISTORY_DAYS]
    (tmp_path / "state.json").write_text(json.dumps({"last_booked": first}))
    end = DAYS[80]
    fwd.record(tmp_path, f, today=fwd._shift(end, 1))
    rows = [json.loads(x) for x in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    ref = c_family.run(c_family.SPECS["C2"], f.closes, f.fund,
                       start=DAYS[0], end=end)
    assert [r["day"] for r in rows] == [r.day for r in ref]
    for got, want in zip(rows, ref, strict=True):
        assert abs(got["net_bps"] - want.net_bps) < 1e-6
        assert abs(got["turnover"] - want.turnover) < 1e-9


def test_rerun_same_day_appends_nothing(tmp_path):
    f = FakeFetcher()
    (tmp_path / "state.json").write_text(json.dumps({"last_booked": DAYS[40]}))
    assert fwd.record(tmp_path, f, today=DAYS[50]) == 9
    assert fwd.record(tmp_path, f, today=DAYS[50]) == 0
    h = fwd.health(tmp_path)
    assert h["scored_days"] == 9 and h["gaps"] == [] and not h["ready_to_score"]
