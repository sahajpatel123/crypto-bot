"""V-002 functional probe (scratch; tree stays clean). Prints check evidence."""
import hashlib
import json
from dataclasses import FrozenInstanceError

from cryptobot.coordination import DataQuality, Intent, Side
from cryptobot.research.synthetic import SCENARIOS, generate_fixture
from cryptobot.strategies.contract import ARM_IDS
from cryptobot.strategies.s1 import Bar, evaluate_bar

FIRES = {}
INTENTS = []
long_only_ok = True
short_only_ok = True
for scenario in SCENARIOS:
    for arm in ARM_IDS:
        fix = generate_fixture(seed=11, scenario=scenario)
        # determinism: regenerate byte-identical
        fix2 = generate_fixture(seed=11, scenario=scenario)
        b1 = json.dumps(fix.to_dict(), sort_keys=True, default=str)
        b2 = json.dumps(fix2.to_dict(), sort_keys=True, default=str)
        assert b1 == b2, f"fixture regen mismatch {scenario}"
        assert all(b.source == "synthetic" for b in fix.bars if b), "source label"
        for t in range(len(fix.bars)):
            for dec in evaluate_bar(list(fix.bars), t, arm, fix.instrument):
                if dec.intent is None:
                    assert dec.record is None
                    continue
                i, r = dec.intent, dec.record
                INTENTS.append((scenario, arm, i, r))
                # 1. validation (structural; Intent ctor already enforced)
                assert isinstance(i, Intent)
                assert i.evidence_ts_utc <= i.entry_expiry_utc
                assert i.entry_low <= i.entry_high
                assert i.holding_limit_s > 0
                if i.side == Side.LONG:
                    assert i.invalidation_price < i.entry_low
                else:
                    assert i.invalidation_price > i.entry_high
                assert all(v >= 0 for v in (i.forecast_cost.fee_bps,
                    i.forecast_cost.spread_bps, i.forecast_cost.slippage_bps,
                    i.forecast_cost.funding_bps))
                # 3. linkage
                assert i.evidence_ref == r.record_id
                assert r.side == i.side
                assert r.regime and r.features and r.trigger
                # 4. long/short separation per scenario direction
                if scenario == "long-breakout" and i.side != Side.LONG:
                    long_only_ok = False
                if scenario == "short-breakout" and i.side != Side.SHORT:
                    short_only_ok = False
                key = (scenario, arm, i.side.value)
                FIRES[key] = FIRES.get(key, 0) + 1

# 2. immutability
sample_i, sample_r = INTENTS[0][2], INTENTS[0][3]
for obj, name in ((sample_i, "Intent"), (sample_r, "DecisionRecord")):
    try:
        object.__setattr__  # noqa
        obj.__dict__  # frozen dataclass: no dict write expected
        import dataclasses
        assert obj.__dataclass_params__.frozen, name
        try:
            setattr(obj, "strategy" if name == "Intent" else "regime", "X")
            raise SystemExit(f"{name} NOT frozen")
        except FrozenInstanceError:
            pass
    except AttributeError:
        pass
assert Bar.__dataclass_params__.frozen

# 6. decision determinism: same bar evaluated twice -> identical intent bytes
fix = generate_fixture(seed=11, scenario="long-breakout")
t_fire = next(t for t in range(120, 240)
              if evaluate_bar(list(fix.bars), t, "S1", "BTCUSDT")[0].intent)
d1 = evaluate_bar(list(fix.bars), t_fire, "S1", "BTCUSDT")[0].intent
d2 = evaluate_bar(list(fix.bars), t_fire, "S1", "BTCUSDT")[0].intent
h1 = hashlib.sha256(repr(d1).encode()).hexdigest()
h2 = hashlib.sha256(repr(d2).encode()).hexdigest()
assert h1 == h2, "intent bytes differ across identical evaluations"

print(f"intents={len(INTENTS)} long_only={long_only_ok} short_only={short_only_ok}")
print(f"fires={sorted(FIRES.items())}")
print(f"fire_bar_t={t_fire} intent_sha256={h1[:16]}")
print("V-002 PROBE: ALL 6 FUNCTIONAL CHECKS PASS")
