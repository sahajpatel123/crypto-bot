"""F0.4c: explicit parameterized paper fill model (replaces 1-tick rule).

The T1.9 FillModel(prob_slippage=1.0) "always one tick adverse" rule is
replaced by PaperFillParams: versioned, provenance-stamped (ASSUMED
until F2.2 calibrates from demo-drill/paper/live fills), with spread /
slippage / latency / empty-book terms. The engine threads the params
into nautilus latency + matching and audits every fill against the
pessimistic book-walk price (never better than pessimistic).
"""
from __future__ import annotations

import random

import pytest

from cryptobot.execution.fill_realism import PaperFillParams, pessimistic_fill_price


def test_default_params_explicit_assumed():
    params = PaperFillParams.default_pessimistic()
    assert params.version == 1
    assert params.provenance == "ASSUMED"
    assert params.spread_bps > 0
    assert params.slippage_bps > 0
    assert params.latency_ms_p95 > 0
    assert params.empty_book_bps > 0
    assert params.fill_model_note  # documents the nautilus mapping
    d = params.to_dict()
    assert PaperFillParams.from_dict(d) == params


def test_calibration_loader_rejects_unknown_version():
    params = PaperFillParams.default_pessimistic()
    bad = dict(params.to_dict(), version=999)
    with pytest.raises(ValueError, match="version"):
        PaperFillParams.from_dict(bad)


def test_never_improves_price_seeded():
    rng = random.Random(20261017)
    for _ in range(200):
        n = rng.randint(1, 5)
        base = rng.uniform(10.0, 60000.0)
        # BUY levels ascending (ask side, best first).
        asks = [(base + i * base * 0.0001, rng.uniform(0.01, 2.0))
                for i in range(n)]
        qty = rng.uniform(0.01, 3.0)
        lat = rng.uniform(0.0, 10.0)
        px = pessimistic_fill_price("BUY", qty=qty, levels=asks,
                                    latency_bps=lat)
        best = asks[0][0]
        assert px >= best, (px, best)
        # SELL levels descending (bid side, best first).
        bids = [(base - i * base * 0.0001, rng.uniform(0.01, 2.0))
                for i in range(n)]
        pxs = pessimistic_fill_price("SELL", qty=qty, levels=bids,
                                     latency_bps=lat)
        assert pxs <= bids[0][0], (pxs, bids[0][0])


def test_engine_accepts_fill_params(tmp_path):
    from cryptobot.adapters.paper_engine import NautilusPaperEngine

    params = PaperFillParams.default_pessimistic()
    engine = NautilusPaperEngine(fill_params=params)
    assert engine.fill_params == params
    # Latency model driven by params, not a hardcoded 50ms.
    assert engine.fill_delay_ms == params.latency_ms_p95


def test_audit_flags_optimistic_fill(tmp_path):
    from cryptobot.adapters.paper_engine import NautilusPaperEngine

    params = PaperFillParams.default_pessimistic()
    engine = NautilusPaperEngine(fill_params=params)
    # BBO ask 100 x1.0; nautilus reports fill at 100 (no slip).
    audit = engine.slippage_audit(
        side="BUY", qty=0.5, nautilus_price=100.0,
        levels=[(100.0, 1.0)], symbol="BTCUSDT")
    assert audit["pessimistic_price"] >= 100.0
    assert audit["drift_bps"] >= 0.0
    # Deep qty against thin book: pessimistic walks + penalty.
    audit2 = engine.slippage_audit(
        side="BUY", qty=5.0, nautilus_price=100.0,
        levels=[(100.0, 1.0)], symbol="BTCUSDT")
    assert audit2["pessimistic_price"] > audit["pessimistic_price"]
    assert audit2["drift_bps"] > audit["drift_bps"]
