"""W3-30MIN §4 drill proofs (run under tools/run_budget.py).

tick:   stop recognition + tick cadence under a 2s-blocked producer.
burst:  control-step p50/p95/p99 under a rapid event burst.
preflight: §9 gate evidence on configs/prod.toml.
all:    the above, one JSON evidence doc to stdout (and --out).

Bounds: stop recognized (run returned) within 1s of the instruction
despite the 2s producer block; burst p99 control-step under 250ms.
Exit 1 on any bound violation, 0 with the evidence otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from cryptobot.app.config import load_config  # noqa: E402
from cryptobot.app.session import Session, WallClock  # noqa: E402
from cryptobot.app.store import RunStore  # noqa: E402


class _StubEngine:
    model_label = "drill-stub"
    assumptions = ("stub: 30min drill",)

    def __init__(self):
        self.advance_calls: list = []
        self._now = datetime(2020, 1, 1, tzinfo=timezone.utc)

    @property
    def now_utc(self):
        return self._now

    def advance_to(self, ts_utc):
        self.advance_calls.append(ts_utc)
        self._now = ts_utc

    def poll(self):
        return []

    def pop_events(self, max_events: int = 1000):
        return []

    def note_mark(self, instrument, price):
        pass

    def set_exit_only(self, halted, reason=""):
        pass

    def recover(self, sink):
        pass

    def close(self):
        pass

    def unknown_ids(self):
        return []

    def resolve(self, cid):
        return None

    def cancel(self, cid, reason):
        pass


def _session(tmpdir: str, name: str):
    text = (ROOT / "configs" / "paper.toml").read_text()
    text = text.replace('mode = "replay"', 'mode = "paper"', 1)
    text = text.replace('kind = "reference"', 'kind = "nautilus"', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmpdir}/runs"', 1)
    cfg_path = Path(tmpdir) / "paper.toml"
    cfg_path.write_text(text)
    cfg = load_config(cfg_path)
    store = RunStore(str(Path(tmpdir) / "runs" / "cryptobot.db"))
    engine = _StubEngine()
    session = Session(cfg, store, str(Path(tmpdir) / "runs" / name), name,
                      clock=WallClock(), engine=engine)
    session.policy.reconcile_day(120.0, 0.0)
    session.arm_replay_filters(
        {"BTCUSDT": {"tick_size": 0.10, "step_size": 0.001,
                     "min_qty": 0.001, "min_notional": 5.0}},
        origin="drill", asof_utc=datetime.now(timezone.utc))
    session._init_run_files()
    return session, store, engine


def drill_tick() -> dict:
    """Stop recognition + tick cadence under a 2s producer block."""
    out: dict = {}
    with tempfile.TemporaryDirectory(prefix="drill-tick-") as tmp:
        session, store, _ = _session(tmp, "tick-stop")
        try:
            session._stop_flag = "stop"
            start = time.monotonic()

            def gen():
                time.sleep(2.0)
                yield None

            session.run_live(gen(), duration_s=30)
            out["stop_recognized_in_s"] = time.monotonic() - start
        finally:
            store.close()
    with tempfile.TemporaryDirectory(prefix="drill-tick2-") as tmp:
        session, store, engine = _session(tmp, "tick-cadence")
        try:

            def gen2():
                time.sleep(2.0)
                yield None

            start = time.monotonic()
            session.run_live(gen2(), duration_s=30)
            out["block_elapsed_s"] = time.monotonic() - start
            out["ticks_during_2s_block"] = len(engine.advance_calls)
        finally:
            store.close()
    out["bound_stop_s"] = 1.0
    out["bound_min_ticks"] = 7
    out["pass"] = (out["stop_recognized_in_s"] <= 1.0
                   and out["ticks_during_2s_block"] >= 7)
    return out


def drill_burst(n_events: int = 2000) -> dict:
    """Control-step latencies under a rapid burst."""
    with tempfile.TemporaryDirectory(prefix="drill-burst-") as tmp:
        session, store, _ = _session(tmp, "burst")
        try:
            base_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

            def gen():
                for i in range(n_events):
                    yield {"channel": "bookTicker", "symbol": "BTCUSDT",
                           "input_class": "observed-public",
                           "exchange_ts_ms": base_ms + i,
                           "local_recv_ms": base_ms + i + 1,
                           "payload": {"bid": 99.99, "ask": 100.01}}

            start = time.monotonic()
            report = session.run_live(gen(), duration_s=600)
            elapsed = time.monotonic() - start
            step = report["latency_ms"]["control_step"]
            out = {"n_events": n_events, "elapsed_s": elapsed,
                   "control_step_ms": step,
                   "dropped_feed_events": report["dropped_feed_events"],
                   "bound_p99_ms": 250.0,
                   "pass": (step["p99_ms"] or 0) < 250.0}
            return out
        finally:
            store.close()


def drill_preflight() -> dict:
    import preflight
    report = preflight.check_config(ROOT / "configs" / "prod.toml")
    return {"config": "configs/prod.toml", "ok": report["ok"],
            "mode": report["mode"], "submission": report["submission"],
            "checks": [(c["name"], c["ok"]) for c in report["checks"]],
            "pass": report["ok"] is True}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="W3-30MIN drill proofs.")
    ap.add_argument("--drill", default="all",
                    choices=("tick", "burst", "preflight", "all"))
    ap.add_argument("--events", type=int, default=2000)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    evidence: dict = {"drill": "W3-30MIN §4+§9", "pass": True}
    if args.drill in ("tick", "all"):
        evidence["tick"] = drill_tick()
    if args.drill in ("burst", "all"):
        evidence["burst"] = drill_burst(args.events)
    if args.drill in ("preflight", "all"):
        evidence["preflight"] = drill_preflight()
    evidence["pass"] = all(v.get("pass", False)
                            for k, v in evidence.items()
                            if k not in ("drill", "pass"))
    text = json.dumps(evidence, indent=2, sort_keys=True)
    print(text)
    if args.out:
        args.out.write_text(text)
    return 0 if evidence["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
