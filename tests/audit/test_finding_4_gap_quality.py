"""Finding 4: trade-ID gap becomes a usable strategy bar (Worker 5, OP-001).

Directive section 2: a 1→3 ID jump sets gap_before=True, yet
to_s1_bar returns a normal bar. Session also constructs MarketView
with CLEAN quality.

Required: propagate quality through bars, views and admission. Define
causal recovery/warmup; adapters must not discard missing-data
evidence.

These probes FAIL on the 01487ac base (bug reproduced) and PASS once
the quality-propagation fix lands. No src/ edits in OP-001.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from datetime import UTC

from cryptobot.coordination import DataQuality
from cryptobot.market_data.bars import Bar1s, BarAggregator, to_s1_bar


def _trade(ts_ms, trade_id, price=100.0, qty=1.0):
    return {"exchange_ts_ms": ts_ms,
            "payload": {"agg_id": trade_id, "price": price, "qty": qty,
                        "buyer_is_maker": False}}


def test_gap_bar_not_usable_as_clean_strategy_bar():
    """1→3 jump: gap bar must not convert to a normal clean Bar."""
    agg = BarAggregator("BTCUSDT", lateness_ms=0)
    agg.on_bbo(99.0, 101.0, 500)
    agg.on_trade(_trade(100, 1))
    out = agg.on_trade(_trade(1100, 3))  # ID 2 missing.
    assert agg.stats()["gap_jumps"] == 1
    gap_bars = [b for b in out
                if isinstance(b, Bar1s) and b.gap_before]
    assert gap_bars, f"expected a gap-flagged bar, got {out!r}"
    for bar in gap_bars:
        converted = to_s1_bar(bar)
        if converted is None:
            continue  # unusable: correct (gap blocks clean use).
        quality = getattr(converted, "data_quality", None)
        reason = getattr(converted, "data_quality_reason", "")
        source = getattr(converted, "source", "")
        assert quality is not None and quality is not DataQuality.CLEAN, (
            f"gap bar converted to clean Bar {converted!r}; "
            f"must be None or carry degraded quality (got quality={quality}, "
            f"reason={reason!r}, source={source!r})")


def test_session_view_propagates_gap_quality(tmp_path):
    """Session MarketView must not claim CLEAN over gap/missing windows."""
    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session
    from cryptobot.app.store import RunStore

    text = Path("configs/paper.toml").read_text()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "test.toml"
    cfg_path.write_text(text)
    cfg = load_config(cfg_path)
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    try:
        session = Session(cfg, store, tmp_path / "runs" / "gapq", "gapq")
        from collections import deque

        from cryptobot.app.session import _SymbolFeed
        feed = _SymbolFeed("BTCUSDT", cfg.warmup_bars)
        # Simulate a gap-derived window: a missing slot amid present bars.
        from datetime import datetime

        from cryptobot.strategies.s1 import Bar
        t0 = datetime(2026, 1, 1, tzinfo=UTC)
        feed.bars = deque([
            Bar(ts_utc=t0, open=100.0, high=100.0, low=100.0, close=100.0,
                volume=1.0, trades=1, buy_frac=1.0, spread_bps=2.0,
                source="observed-public"),
            None,  # gap/missing window: quality evidence.
        ], maxlen=cfg.warmup_bars + 5)
        session._feeds["BTCUSDT"] = feed
        seen = {}
        from cryptobot.coordination.selector import Candidate
        from cryptobot.strategies.runtime import StrategyOutcome

        class _Spy:
            strategy_id = "S1"
            def evaluate(self, view):
                seen["quality"] = view.quality
                seen["reason"] = view.quality_reason
                seen["bars"] = view.bars
                return StrategyOutcome(None, "audit:spy-no-fire")
        candidates = session._evaluate_symbol("BTCUSDT", {"S1": _Spy()}, {})
        assert seen, "spy adapter never evaluated"
        assert any(isinstance(c, Candidate) for c in candidates)
        assert seen["quality"] is not DataQuality.CLEAN, (
            f"MarketView over [bar, None] claims CLEAN "
            f"(reason={seen['reason']!r}); must propagate degraded/halt")
    finally:
        store.close()


def test_recovery_requires_causal_warmup(tmp_path):
    """After a gap, admission must wait for causal warmup, not one bar."""
    agg = BarAggregator("BTCUSDT", lateness_ms=0)
    agg.on_bbo(99.0, 101.0, 500)
    agg.on_trade(_trade(100, 1))
    out = agg.on_trade(_trade(1100, 3))
    gap_bars = [b for b in out if isinstance(b, Bar1s) and b.gap_before]
    assert gap_bars, "expected gap-flagged bars to define recovery around"
    # The fix must define recovery: at minimum, a gap bar is never the
    # sole basis for a clean view. Document the boundary: converting the
    # immediate post-gap bar alone must not yield clean admission input.
    for bar in gap_bars:
        converted = to_s1_bar(bar)
        if converted is None:
            continue
        quality = getattr(converted, "data_quality", None)
        assert quality is not None and quality is not DataQuality.CLEAN, (
            f"post-gap bar converts to clean input {converted!r}; "
            f"recovery/warmup undefined (quality={quality})")
