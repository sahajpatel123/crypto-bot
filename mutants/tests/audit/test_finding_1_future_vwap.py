"""Finding 1: future trades affect an earlier modeled quote (Worker 5, OP-001).

Directive section 2: research/spread.py:apply_profile uses the entire
second's VWAP, then emits a quote at window+100ms. Trades at 1050ms/100
and 1950ms/200 produce a 1100ms quote centered at 150, although only
price 100 was known at 1100ms.

Required: modeled quotes must use information available by their
timestamps. Changing future data must not change earlier quotes,
decisions, orders or fills. Retain explicit modeled-liquidity/cost
labels.

These probes FAIL on the 01487ac base (bug reproduced) and PASS once
the causal fix lands. No src/ edits in OP-001.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.research.spread import PROFILE_ID, apply_profile

T0 = 1_700_000_000_000


def _trade(seq, ms, price, qty=1.0, symbol="BTCUSDT"):
    return {"v": 1, "format": "cryptobot-events/1",
            "input_class": "observed-public", "source": "x", "route": "x",
            "run_id": "t", "seq": seq, "channel": "aggTrade", "symbol": symbol,
            "exchange_ts_ms": ms, "local_recv_ms": ms, "local_mono_ns": seq,
            "gap_kind": None, "venue_seq": seq,
            "payload": {"agg_id": seq, "price": price, "qty": qty,
                        "first_id": seq, "last_id": seq, "trade_ts_ms": ms,
                        "buyer_is_maker": False}}


def _modeled(merged):
    return [e for e in merged
            if e["payload"].get("quote_source") == PROFILE_ID]


def _mid(quote):
    return (quote["payload"]["bid"] + quote["payload"]["ask"]) / 2


def test_modeled_quote_uses_only_causal_trades():
    """1100ms quote must center on trades known by 1100ms (100, not 150)."""
    window = T0 + 1000
    day = [_trade(1, window + 50, 100.0), _trade(2, window + 950, 200.0)]
    merged, _ = apply_profile(day, "BTCUSDT", 1.0)
    modeled = _modeled(merged)
    assert len(modeled) == 1, f"expected one modeled quote, got {len(modeled)}"
    q = modeled[0]
    qts = int(q["exchange_ts_ms"])
    causal = [t for t in day if int(t["exchange_ts_ms"]) <= qts]
    assert causal, f"quote at {qts} has no causal trades; must not exist"
    notion = sum(float(t["payload"]["price"]) * float(t["payload"]["qty"])
                 for t in causal)
    qty = sum(float(t["payload"]["qty"]) for t in causal)
    causal_mid = notion / qty
    assert abs(_mid(q) - causal_mid) < 1e-9, (
        f"quote at {qts} centers at {_mid(q)}, causal VWAP is {causal_mid} "
        f"({len(causal)}/{len(day)} trades known by quote time)")


def test_future_mutation_does_not_change_earlier_quotes():
    """Changing a 1950ms trade must not move the 1100ms quote."""
    window = T0 + 1000
    day1 = [_trade(1, window + 50, 100.0), _trade(2, window + 950, 200.0)]
    day2 = [_trade(1, window + 50, 100.0), _trade(2, window + 950, 1000.0)]
    m1, _ = apply_profile(day1, "BTCUSDT", 1.0)
    m2, _ = apply_profile(day2, "BTCUSDT", 1.0)
    early1 = sorted((int(q["exchange_ts_ms"]), q["payload"]["bid"],
                     q["payload"]["ask"]) for q in _modeled(m1)
                    if int(q["exchange_ts_ms"]) <= window + 500)
    early2 = sorted((int(q["exchange_ts_ms"]), q["payload"]["bid"],
                     q["payload"]["ask"]) for q in _modeled(m2)
                    if int(q["exchange_ts_ms"]) <= window + 500)
    assert early1, "expected at least one early modeled quote"
    assert early1 == early2, (
        f"future trade mutation changed earlier quotes: {early1} vs {early2}")


def test_modeled_labels_retained():
    """Fix must keep explicit modeled-liquidity/cost labels."""
    day = [_trade(1, T0 + 200, 60000.0)]
    merged, manifest = apply_profile(day, "BTCUSDT", 2.0)
    modeled = _modeled(merged)
    assert len(modeled) == 1
    payload = modeled[0]["payload"]
    assert payload["quote_source"] == PROFILE_ID
    assert payload["spread_bps_assumed"] == 2.0
    assert manifest["profile_id"] == PROFILE_ID
