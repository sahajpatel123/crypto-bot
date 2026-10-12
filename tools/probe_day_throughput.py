"""Manager throughput probe: one real BTC day -> capture -> Session replay."""
import json
import sys
import time
from pathlib import Path

from cryptobot.app.config import load_config
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore
from cryptobot.market_data.datasets import open_dataset

OUT = Path("benchprobe/day1")
CAP = OUT / "cap"
RUN = OUT / "run"


def main() -> None:
    t0 = time.monotonic()
    CAP.mkdir(parents=True, exist_ok=True)
    handle = open_dataset("datasets/benchmark_30d.toml")
    n = 0
    with (CAP / "events.jsonl").open("w") as fh:
        for ev in handle.events("BTCUSDT", "2026-09-12"):
            if ev is None:
                continue
            fh.write(json.dumps(ev, sort_keys=True) + "\n")
            n += 1
    t_prep = time.monotonic() - t0
    print(f"prep: {n} events in {t_prep:.1f}s", flush=True)

    from cryptobot.adapters import NautilusPaperEngine
    cfg = load_config("configs/paper.toml")
    store = RunStore(OUT / "store.db")
    engine = NautilusPaperEngine(
        outcome_sink=None, taker_bps=cfg.taker_bps,
        now_utc=lambda: __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc),
        submit_delay_ms=cfg.submit_delay_ms,
        fill_delay_ms=max(1, cfg.fill_delay_ms),
        journal_path=RUN / "engine_journal.jsonl",
        starting_balance_usdt=cfg.paper_capital_usdt)
    session = Session(cfg, store, RUN, "probe-day1", engine=engine)
    t1 = time.monotonic()
    report = session.run_replay(CAP, expect_class="observed-archive")
    t_run = time.monotonic() - t1
    print(f"replay: {t_run:.1f}s admits={report['intents_admitted']} "
          f"events={report['events_seen']}", flush=True)
    print(f"throughput: {report['events_seen'] / max(t_run, 0.01):,.0f} ev/s",
          flush=True)
    store.close()


if __name__ == "__main__":
    sys.exit(main())
