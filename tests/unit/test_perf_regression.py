"""F1.7: performance regression gates (explicit thresholds).

Hot-path budgets with ~10x headroom over measured macOS timings
(sizing 33k/s, monitor 111k/s, ledger fill, rounding). Percentiles
(not means) so one GC pause cannot flake the gate; sustained rates
(not bursts) so slow CI still passes with margin. A genuine 10x
regression fails loudly here instead of in production.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

# (name, min_events_per_s, max_p99_ms)
BUDGETS = {
    "sizing": (2_000.0, 2.0),
    "monitor_tick": (10_000.0, 0.5),
    "ledger_fill": (10_000.0, 1.0),
    "rounding": (100_000.0, 0.5),
}

NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=UTC)


def _percentile(sorted_ms: list[float], pct: float) -> float:
    idx = min(len(sorted_ms) - 1, int(pct * len(sorted_ms)))
    return sorted_ms[idx]


def _check(name: str, samples_ms: list[float]) -> None:
    samples_ms.sort()
    p50 = _percentile(samples_ms, 0.50)
    p99 = _percentile(samples_ms, 0.99)
    rate = 1000.0 / p50 if p50 > 0 else float("inf")
    min_rate, max_p99 = BUDGETS[name]
    print(f"perf[{name}]: {rate:,.0f}/s p50={p50:.4f}ms p99={p99:.4f}ms "
          f"(budget >={min_rate:,.0f}/s, p99<={max_p99}ms)")
    assert rate >= min_rate, f"{name} throughput {rate:.0f}/s < {min_rate}"
    assert p99 <= max_p99, f"{name} p99 {p99:.4f}ms > {max_p99}ms"


def _intent():
    from cryptobot.coordination import DataQuality, ForecastCost, Intent, Side

    return Intent(
        strategy="S", version="1", instrument="BTCUSDT", side=Side.LONG,
        evidence_ts_utc=NOW, entry_low=100.0, entry_high=101.0,
        entry_expiry_utc=NOW + timedelta(seconds=60),
        invalidation_price=99.0, exit_rule="inv", holding_limit_s=60,
        forecast_cost=ForecastCost(5, 5, 5, 0), evidence_ref="r",
        data_quality=DataQuality.CLEAN)


def test_perf_sizing(tmp_path):
    from cryptobot.risk.sizing import plan_size
    from cryptobot.risk.types import RiskConfig

    cfg = RiskConfig()
    samples = []
    for _ in range(2000):
        start = time.perf_counter()
        plan_size(_intent(), 10000.0, cfg)
        samples.append((time.perf_counter() - start) * 1000.0)
    _check("sizing", samples)


def test_perf_monitor_tick(tmp_path):
    from cryptobot.risk import RiskConfig, RiskPolicy
    from cryptobot.risk.types import AccountSnapshot

    policy = RiskPolicy(config=RiskConfig(),
                        state_path=tmp_path / "risk.json",
                        now_utc=lambda: NOW)
    policy.reconcile_day(10000.0)
    acct = AccountSnapshot(
        reconciled_equity=10000.0, marked_equity=10000.0,
        net_liquidation=10000.0, net_realised_global=0.0,
        open_position=False)
    samples = []
    for _ in range(2000):
        start = time.perf_counter()
        policy.monitor_tick(NOW, acct)
        samples.append((time.perf_counter() - start) * 1000.0)
    _check("monitor_tick", samples)


def test_perf_ledger_fill():
    from cryptobot.accounting.ledger import Ledger

    ledger = Ledger(10000.0)
    samples = []
    for i in range(2000):
        start = time.perf_counter()
        ledger.record_fill("BUY" if i % 2 == 0 else "SELL", 0.01,
                           60000.0, 0.01, NOW, f"e{i}")
        samples.append((time.perf_counter() - start) * 1000.0)
    _check("ledger_fill", samples)


def test_perf_rounding():
    from cryptobot.risk.rounding import floor_to_step

    samples = []
    for _ in range(20000):
        start = time.perf_counter()
        floor_to_step(1.23456789, 0.001)
        samples.append((time.perf_counter() - start) * 1000.0)
    _check("rounding", samples)
