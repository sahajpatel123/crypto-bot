"""Manager E-008 replay proof: frozen day -> pump(replay) -> engine fills."""
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/tmp/cryto-bot-w2-e008/src")

from cryptobot.adapters import NautilusPaperEngine
from cryptobot.app.engine import EngineOrder
from cryptobot.execution.runtime_feed import StreamPump
from cryptobot.market_data.datasets import open_dataset

T0 = datetime(2026, 9, 12, tzinfo=timezone.utc)
engine = NautilusPaperEngine(
    outcome_sink=None, taker_bps=5.0, now_utc=lambda: T0,
    submit_delay_ms=0, fill_delay_ms=1, journal_path=None,
    starting_balance_usdt=10_000.0, strict_replay=True)
engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                      tick_size=0.01, step_size=0.001, ts_utc=T0)

# Guard: reference/fake engines refused on the economic path.
from cryptobot.app.reference import ReferenceEngine
try:
    StreamPump(ReferenceEngine(log_path="/tmp/ref.jsonl", outcome_sink=None,
                               taker_bps=5.0))
    raise SystemExit("GUARD DID NOT FIRE")
except ValueError as exc:
    print("GUARD ok:", str(exc)[:60])

pump = StreamPump(engine)
h = open_dataset("data/bench30d/benchmark_30d.toml")
stream = h.events("BTCUSDT", "2026-09-12")
prints = []  # observed trade prints (price, ts)
submitted = False
fill = None
n = 0
for tick in pump.pump_live(stream, replay=True):
    n += 1
    if tick.record is not None and tick.record["channel"] == "aggTrade":
        prints.append((tick.record["payload"]["price"],
                       tick.record["exchange_ts_ms"]))
    if not submitted and len(prints) >= 2000:
        engine.submit(EngineOrder(instrument="BTCUSDT", side="BUY", qty=0.01,
                                  kind="MARKET", role="entry"))
        submitted = True
    for ev in tick.engine_events:
        if ev.kind == "fill" and fill is None:
            fill = ev.payload
    if n >= 6000:
        break

assert submitted and fill is not None, "no fill in slice"
px = {p for p, _ in prints}
assert any(abs(fill.price - p) < 1e-9 for p in px), (fill.price, len(px))
print(f"FILL at trade cross: {fill.price} (fee {fill.fee:.4f})")
print("engine clock still Sep-12:", engine.now_utc.isoformat()[:10])
print("pump stats:", pump.stats)
print("engine stats:", engine.stats)
print("REPLAY PROOF GREEN")
