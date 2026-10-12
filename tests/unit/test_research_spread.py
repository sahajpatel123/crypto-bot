"""Spread profile tests (Worker 1, Q-007)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.research.spread import (
    MODELED_QTY,
    PROFILE_ID,
    SpreadProfile,
    apply_profile,
    profile_spread_bps,
    sensitivity_spreads,
)

T0 = 1_700_000_000_000


def _trade(seq, ms, price=60000.0, qty=0.5, symbol="BTCUSDT"):
    return {"v": 1, "format": "cryptobot-events/1",
            "input_class": "observed-public", "source": "x", "route": "x",
            "run_id": "t", "seq": seq, "channel": "aggTrade", "symbol": symbol,
            "exchange_ts_ms": ms, "local_recv_ms": ms, "local_mono_ns": seq,
            "gap_kind": None, "venue_seq": seq,
            "payload": {"agg_id": seq, "price": price, "qty": qty,
                        "first_id": seq, "last_id": seq, "trade_ts_ms": ms,
                        "buyer_is_maker": False}}


def _bbo(seq, ms, bid=59999.0, ask=60001.0, symbol="BTCUSDT"):
    return {"v": 1, "format": "cryptobot-events/1",
            "input_class": "observed-public", "source": "x", "route": "x",
            "run_id": "t", "seq": seq, "channel": "bookTicker", "symbol": symbol,
            "exchange_ts_ms": ms, "local_recv_ms": ms, "local_mono_ns": seq,
            "gap_kind": None, "venue_seq": 0,
            "payload": {"bid": bid, "ask": ask, "bid_qty": 5.0, "ask_qty": 5.0}}


def test_profile_defaults_and_overrides():
    p = SpreadProfile()
    assert p.profile_id == PROFILE_ID
    assert profile_spread_bps(p, "BTCUSDT") == 1.0
    p2 = SpreadProfile(per_symbol_bps=(("BTCUSDT", 2.5),))
    assert profile_spread_bps(p2, "BTCUSDT") == 2.5
    assert profile_spread_bps(p2, "ETHUSDT") == 1.0


def test_profile_rejects_bad_values():
    for kw in ({"profile_id": "other"}, {"default_bps": 0.0},
               {"default_bps": -1.0},
               {"per_symbol_bps": (("BTCUSDT", 0.0),)}):
        try:
            SpreadProfile(**kw)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {kw}")


def test_sensitivity_multipliers_exact():
    p = SpreadProfile(default_bps=2.0)
    assert sensitivity_spreads(p, "BTCUSDT") == {0.5: 1.0, 1.0: 2.0, 2.0: 4.0}


def test_apply_models_only_quoteless_trade_windows():
    day = [_trade(1, T0 + 200), _trade(2, T0 + 1200),
           _bbo(3, T0 + 1100)]  # window 1 quoted, window 0 not
    merged, manifest = apply_profile(day, "BTCUSDT", 2.0)
    assert manifest["modeled_windows"] == 1
    assert manifest["observed_quote_windows"] == 1
    modeled = [e for e in merged
               if e["payload"].get("quote_source") == PROFILE_ID]
    assert len(modeled) == 1
    m = modeled[0]
    assert m["channel"] == "bookTicker"
    assert m["payload"]["bid_qty"] == MODELED_QTY
    assert m["payload"]["spread_bps_assumed"] == 2.0
    mid = (m["payload"]["bid"] + m["payload"]["ask"]) / 2
    assert mid == 60000.0
    spread = (m["payload"]["ask"] - m["payload"]["bid"]) / mid * 1e4
    assert abs(spread - 2.0) < 1e-9
    # Observed BBO untouched (no quote_source marker, original size kept).
    observed = [e for e in merged if e["channel"] == "bookTicker"
                and "quote_source" not in e["payload"]]
    assert len(observed) == 1 and observed[0]["payload"]["bid_qty"] == 5.0


def test_windows_without_trades_stay_empty():
    day = [_trade(1, T0 + 200)]
    merged, manifest = apply_profile(day, "BTCUSDT", 2.0)
    assert manifest["trade_windows"] == 1
    assert manifest["modeled_windows"] == 1
    assert len(merged) == 2  # one modeled quote, nothing else fabricated


def test_other_symbols_untouched():
    day = [_trade(1, T0 + 200, symbol="ETHUSDT")]
    merged, manifest = apply_profile(day, "BTCUSDT", 2.0)
    assert manifest["modeled_windows"] == 0
    assert merged == day


def test_apply_is_deterministic_and_pure():
    day = [_trade(i + 1, T0 + i * 1000 + 200) for i in range(5)]
    snapshot = [dict(e) for e in day]
    first, m1 = apply_profile(day, "BTCUSDT", 1.5)
    second, m2 = apply_profile(day, "BTCUSDT", 1.5)
    assert first == second and m1 == m2
    assert day == snapshot  # input never mutated


def test_modeled_quotes_sort_into_causal_position():
    day = [_trade(1, T0 + 200), _trade(2, T0 + 1200)]
    merged, _ = apply_profile(day, "BTCUSDT", 1.0)
    ts = [e["exchange_ts_ms"] for e in merged]
    assert ts == sorted(ts)
    assert merged[0]["channel"] == "bookTicker"  # window0 BBO before trade
