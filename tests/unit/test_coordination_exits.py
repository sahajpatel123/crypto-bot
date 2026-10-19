"""Exit-policy codec tests (manager-owned, runtime S2)."""
from datetime import datetime, timezone

import pytest

from cryptobot.coordination.exits import ExitPolicy, decode_exit_rule, encode_exit_rule


def _policy(**kw):
    base = dict(stop_price=99.5, target_price=102.0,
                time_exit_utc=datetime(2026, 10, 12, 5, 0, tzinfo=timezone.utc),
                policy_id="S1:stop+target+time")
    base.update(kw)
    return ExitPolicy(**base)


def test_roundtrip_full_policy():
    p = _policy()
    assert decode_exit_rule(encode_exit_rule(p)) == p


def test_roundtrip_no_target():
    p = _policy(target_price=None)
    decoded = decode_exit_rule(encode_exit_rule(p))
    assert decoded == p and decoded.target_price is None


def test_reduce_only_false_roundtrip():
    assert decode_exit_rule(encode_exit_rule(_policy(reduce_only=False))).reduce_only is False


def test_malformed_rules_rejected():
    good = encode_exit_rule(_policy())
    bad = [good + "|extra=x", good.replace("v1|", "v2|", 1), "not-a-rule",
           good.replace("reduce_only=1", "reduce_only=2"),
           good.replace("stop=99.5", "stop=nan"),
           good.replace("stop=99.5", "stop=-1"),
           ""]
    for rule in bad:
        with pytest.raises(ValueError):
            decode_exit_rule(rule)


def test_constructor_guards():
    with pytest.raises(ValueError):
        _policy(stop_price=0)
    with pytest.raises(ValueError):
        _policy(target_price=float("inf"))
    with pytest.raises(ValueError):
        _policy(time_exit_utc=datetime(2026, 10, 12, 5, 0))  # naive
    with pytest.raises(ValueError):
        _policy(policy_id="a|b")
