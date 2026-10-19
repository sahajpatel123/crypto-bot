"""Warmup/eligibility timeline export from replay artifacts (CORR-DATA §5).

Runs a real Session.run_replay over a capture with milestone probes and
exports, all on the replay (exchange-event) clock: first event, first
usable bar, first 130-bar state, first evaluation + first intent per
strategy, gate-ready time, and eligible duration per symbol.

Read-only w.r.t. the capture; writes run artifacts to --workdir.
Run under tools/run_budget.py.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cryptobot.app.config import load_config  # noqa: E402
from cryptobot.app.session import Session  # noqa: E402
from cryptobot.app.store import RunStore  # noqa: E402
from cryptobot.research.backtest import FROZEN_FILTERS  # noqa: E402


def export_warmup(capture: Path, profile: Path, workdir: Path,
                  run_id: str = "warmup-export") -> dict:
    """Replay once with probes; return the milestone timeline."""
    manifest = json.loads((capture / "manifest.json").read_text())
    symbols = manifest.get("symbols", [])
    cfg = load_config(profile)
    workdir.mkdir(parents=True, exist_ok=True)
    store = RunStore(str(workdir / "cryptobot.db"))
    session = Session(cfg, store, str(workdir / run_id), run_id)
    session.policy.reconcile_day(cfg.paper_capital_usdt, 0.0)
    asof = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc)
    session.arm_replay_filters(
        {s: dict(FROZEN_FILTERS.get(s.upper(), {})) for s in symbols},
        "frozen-labeled-assumption", asof_utc=asof)

    ms: dict = {"first_event": None, "first_bar": {}, "ready_130": {},
                "first_eval": {}, "first_intent": {},
                "gate_ready": {}, "capture_end": None}
    t0_ms: list[int | None] = [None]

    def stamp() -> tuple[str, int]:
        now = session.now_utc()
        cur = int(now.timestamp() * 1000)
        if t0_ms[0] is None:
            t0_ms[0] = cur
        return now.isoformat(), cur - t0_ms[0]

    orig_ingest = session._ingest

    def watching_ingest(event, adapters, modules):
        if ms["first_event"] is None:
            # Clock advances inside _ingest; stamp after.
            pass
        before = {s: len(f.bars) for s, f in session._feeds.items()}
        orig_ingest(event, adapters, modules)
        iso, rel = stamp()
        if ms["first_event"] is None:
            ms["first_event"] = {"ts_utc": iso, "rel_ms": rel,
                                 "channel": event.get("channel"),
                                 "symbol": event.get("symbol")}
        for symbol, feed in session._feeds.items():
            n = len(feed.bars)
            if symbol not in ms["first_bar"] and n > before.get(symbol, 0):
                ms["first_bar"][symbol] = {"ts_utc": iso, "rel_ms": rel,
                                           "bars": n}
            if (symbol not in ms["ready_130"]
                    and n >= session.config.warmup_bars):
                ms["ready_130"][symbol] = {"ts_utc": iso, "rel_ms": rel,
                                           "bars": n}
            if symbol not in ms["gate_ready"] and symbol in ms["ready_130"]:
                if session._quote_age_gate(symbol) is None:
                    ms["gate_ready"][symbol] = {"ts_utc": iso, "rel_ms": rel}

    session._ingest = watching_ingest  # type: ignore[method-assign]

    orig_adapters = session._strategy_adapters

    def watching_adapters():
        adapters, modules = orig_adapters()

        class _Rec:
            def __init__(self, name, inner):
                self._name = name
                self._inner = inner
                self.strategy_id = getattr(inner, "strategy_id", name)

            def evaluate(self, view):
                key = f"{self._name}/{view.instrument}"
                outcome = self._inner.evaluate(view)
                iso, rel = stamp()
                if key not in ms["first_eval"]:
                    ms["first_eval"][key] = {
                        "ts_utc": iso, "rel_ms": rel,
                        "reject": outcome.reject_reason,
                        "fired": outcome.intent is not None}
                if outcome.intent is not None and key not in ms["first_intent"]:
                    ms["first_intent"][key] = {"ts_utc": iso, "rel_ms": rel}
                return outcome

        return {n: _Rec(n, a) for n, a in adapters.items()}, modules

    session._strategy_adapters = watching_adapters  # type: ignore[method-assign]

    start = time.monotonic()
    report = session.run_replay(capture)
    elapsed = time.monotonic() - start
    iso, rel = stamp()
    ms["capture_end"] = {"ts_utc": iso, "rel_ms": rel}
    for symbol in symbols:
        if symbol in ms["gate_ready"] and ms["capture_end"]:
            ms.setdefault("eligible_s", {})[symbol] = (
                ms["capture_end"]["rel_ms"]
                - ms["gate_ready"][symbol]["rel_ms"]) / 1000.0
    store.close()
    return {
        "capture": str(capture), "profile": str(profile),
        "profile_version": cfg.profile_version,
        "filter_origin": "frozen-labeled-assumption",
        "warmup_bars": cfg.warmup_bars,
        "replay_elapsed_s": elapsed,
        "events_seen": report.get("events_seen"),
        "intents_admitted": report.get("intents_admitted"),
        "milestones": ms,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Warmup timeline export.")
    ap.add_argument("--capture", required=True, type=Path)
    ap.add_argument("--profile", default=ROOT / "configs" / "paper.toml",
                    type=Path)
    ap.add_argument("--workdir", required=True, type=Path)
    ap.add_argument("--out", default=None, type=Path)
    args = ap.parse_args(argv)
    result = export_warmup(args.capture, args.profile, args.workdir)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
