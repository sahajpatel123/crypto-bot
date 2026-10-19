"""M1 integrated vertical slice on SYNTHETIC data (manager-owned).

Flow: SYNTH_V1 fixture -> labelled synthetic recording -> REAL replay
input boundary (load + input-class assert + deterministic replay) -> real
S1 baseline intent (ARM_BASE) -> coordinator -> real risk gate (SliceRisk
over the V-004 policy + ledger) -> shared OrderManager + shared fault
venue -> booked ledger -> closed-trade report.

One virtual clock drives strategies, execution, risk and accounting.
Lifecycle: partial entry fill, sibling protection, crash/restart with
exposure open, entry-remainder expiry (cancelled, never released while
exposed), stop-triggered protective exit, verified sibling cancel, flat
reconciliation. Includes one demonstrably rejected trade (stale/expired
intent). Every input here is synthetic; not a validated trading system.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptobot.accounting import Ledger
from cryptobot.coordination import Coordinator, DataQuality, ForecastCost, Intent, Side
from cryptobot.execution import FakeVenue, OrderManager
from cryptobot.market_data.recorder import (
    INPUT_SYNTHETIC, RECORDING_FORMAT, analyze_klines, stats_to_dict,
)
from cryptobot.market_data.replayer import (
    assert_input_class, load_recording, replay, replay_hash,
)
from cryptobot.research.synthetic import SCENARIO_LONG, generate_fixture
from cryptobot.risk import SliceRisk
from cryptobot.strategies.contract import ARM_BASE
from cryptobot.strategies.s1 import Bar, evaluate_side


def _record_synthetic_klines(path: Path, bars: list[Bar], symbol: str) -> None:
    """Write fixture bars as a labelled synthetic recording (JSONL).

    OHLCV travel as the standard kline fields; the remaining synthetic
    feature fields ride as explicit extras so replay transports them
    losslessly. Nothing is fabricated: every value comes from the fixture.
    """
    header = {
        "type": "header", "format": RECORDING_FORMAT,
        "input_class": INPUT_SYNTHETIC, "source": "SYNTH_V1:long-breakout:seed11",
        "symbol": symbol, "channel": "synthetic-1s", "interval_ms": 1000,
        "capture_cmd": "tools/m1_vertical_slice.py (fixture preparation)",
        "started_utc": datetime.now(timezone.utc).isoformat(),
    }
    lines = [json.dumps(header)]
    for seq, b in enumerate(bars):
        open_ms = int(b.ts_utc.timestamp() * 1000)
        close_ms = open_ms + 1000
        lines.append(json.dumps({
            "type": "kline", "seq": seq,
            "exchange_open_ms": open_ms, "exchange_close_ms": close_ms,
            "local_recv_ms": close_ms + 5,
            "o": str(b.open), "h": str(b.high), "l": str(b.low),
            "c": str(b.close), "v": str(b.volume),
            "trades": b.trades, "buy_frac": b.buy_frac,
            "spread_bps": b.spread_bps, "closed": True,
        }))
    records = [json.loads(line) for line in lines[1:]]
    stats = analyze_klines(records, 1000)
    lines.append(json.dumps({"type": "footer", "stats": stats_to_dict(stats)}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _bars_from_replay(path: Path, symbol: str) -> tuple[list[Bar], str, dict]:
    """Load the recording through the real replay boundary (synthetic only)."""
    header, records = load_recording(path)
    assert_input_class(header, INPUT_SYNTHETIC)
    sha = replay_hash(records)
    bars = [
        Bar(ts_utc=datetime.fromtimestamp(e.exchange_open_ms / 1000, tz=timezone.utc),
            open=float(e.payload["o"]), high=float(e.payload["h"]),
            low=float(e.payload["l"]), close=float(e.payload["c"]),
            volume=float(e.payload["v"]), trades=int(e.payload["trades"]),
            buy_frac=float(e.payload["buy_frac"]),
            spread_bps=float(e.payload["spread_bps"]),
            source="synthetic-replay:SYNTH_V1:long-breakout:seed11")
        for e in replay(records)
    ]
    stats = stats_to_dict(analyze_klines(records, 1000))
    assert not stats["gaps"] and stats["stale_count"] == 0, "M1 recording must be clean"
    _ = symbol
    return bars, sha, stats


def main() -> int:
    parser = argparse.ArgumentParser(description="M1 integrated synthetic slice")
    parser.add_argument("--out", default="reports/m1_report.json")
    args = parser.parse_args()

    t0 = datetime.now(timezone.utc).replace(microsecond=0)
    cell = [t0]
    clock = lambda: cell[0]

    # Fixture preparation (pre-recording): find the first LONG fire at/after
    # bar 120 using only bars visible at each step. The signal itself is
    # generated from REPLAYED bars below; the fixture is dropped afterwards.
    fixture = generate_fixture(seed=11, scenario=SCENARIO_LONG)
    fire_t = next(
        (t for t in range(120, len(fixture.bars))
         if evaluate_side(list(fixture.bars), t, Side.LONG, ARM_BASE,
                           "BTCUSDT").intent is not None),
        None,
    )
    assert fire_t is not None, "SYNTH_V1 long-breakout must fire S1 LONG"
    shift = (t0 - timedelta(seconds=5)) - fixture.bars[fire_t].ts_utc
    prefix = []
    for b in fixture.bars[:fire_t + 1]:
        assert b is not None, "recorded prefix must be complete"
        prefix.append(Bar(ts_utc=b.ts_utc + shift, open=b.open, high=b.high,
                          low=b.low, close=b.close, volume=b.volume,
                          trades=b.trades, buy_frac=b.buy_frac,
                          spread_bps=b.spread_bps, source=b.source))
    del fixture

    with tempfile.TemporaryDirectory(prefix="m1_") as workdir:
        work = Path(workdir)
        rec_path = work / "m1_synth.jsonl"
        _record_synthetic_klines(rec_path, prefix, "BTCUSDT")
        bars, replay_sha, replay_stats = _bars_from_replay(rec_path, "BTCUSDT")
        assert [b.close for b in bars] == [b.close for b in prefix], \
            "replay must transport closes losslessly"
        assert len(bars) == fire_t + 1 and bars[fire_t].ts_utc == t0 - timedelta(seconds=5)

        s1 = evaluate_side(bars, fire_t, Side.LONG, ARM_BASE, "BTCUSDT")
        assert s1.intent is not None and s1.record is not None, "replayed S1 must fire"
        good = s1.intent
        assert good.evidence_ref == s1.record.record_id, "intent must point at its record"
        forecast = ForecastCost(fee_bps=5, spread_bps=5, slippage_bps=5, funding_bps=0)
        stale = Intent("S1", "0.1.0-stub", "BTCUSDT", Side.LONG, t0 - timedelta(seconds=120),
                       67000.0, 67010.0, t0 - timedelta(seconds=1), 66850.0,
                       "invalidation-or-300s", 300, forecast, "synthetic-decision-2",
                       DataQuality.CLEAN)
        coord = Coordinator()
        decision = coord.select([good, stale], t0)
        assert decision.accepted is good, "coordinator must pick the valid intent"
        assert stale in decision.rejected, "stale intent must be rejected"

        equity = 100.0  # synthetic USDT
        mid = (good.entry_low + good.entry_high) / 2
        state_path = work / "risk_state.json"
        ledger_path = work / "ledger.json"
        log_path = work / "orders.jsonl"
        gate = SliceRisk(state_path=state_path, day_start_equity=equity, now_utc=clock)
        venue = FakeVenue()
        manager = OrderManager(venue, log_path=log_path, now_utc=clock,
                               outcome_sink=gate.policy)

        rdec = gate.evaluate(decision.accepted, mid)
        assert rdec.ok, f"risk must approve the good intent: {rdec.reason}"
        assert rdec.reason.startswith("risk-policy:"), rdec.reason
        assert rdec.reservation_id is not None
        rid = rdec.reservation_id

        # Entry with an injected partial fill: half fills now, protection
        # attaches to the filled half while the remainder is still live.
        venue.fail_next_submit("partial", fractions=(0.5, 0.5))
        entry = manager.submit_entry("BTCUSDT", "LONG", rdec.qty, mid,
                                     expire_at_utc=t0 + timedelta(seconds=30),
                                     reservation_id=rid)
        assert entry.filled_qty == rdec.qty * 0.5, "half must fill immediately"
        stop_px = good.invalidation_price
        target_px = mid + (mid - stop_px)
        stop, target = manager.attach_siblings(entry, stop_price=stop_px,
                                               target_price=target_px)
        assert stop.qty == entry.filled_qty and target.qty == entry.filled_qty
        assert gate.ledger.position_qty() == entry.filled_qty, "delta must reach ledger"

        # Crash with exposure open: drop process objects (the venue models the
        # exchange and survives), then rebuild from durable records.
        gate.ledger.save(ledger_path)
        fills_before = len(venue.fills)
        del manager
        del gate
        gate2 = SliceRisk(state_path=state_path, day_start_equity=equity, now_utc=clock)
        gate2.ledger = Ledger.load(ledger_path)
        gate2.policy.bind_ledger(gate2.ledger)
        manager2 = OrderManager.recover(venue, log_path, now_utc=clock,
                                        outcome_sink=gate2.policy)
        assert gate2.ledger.position_qty() == entry.filled_qty, "ledger must survive restart"
        assert gate2.policy.booked_net(rid) == entry.filled_qty, "booked exposure must agree"
        assert len(venue.fills) == fills_before, "no phantom fills across restart"

        # Entry remainder expires: cancel is issued, but the reservation is
        # never released while exposure lives; risk keeps blocking new entries.
        cell[0] = t0 + timedelta(seconds=35)
        events = manager2.poll()
        assert any(e.get("event") == "expired" for e in events), "remainder must expire"
        assert not any(str(e.get("event", "")).startswith("callback:release") for e in events)
        manager2.poll()
        manager2.poll()  # settle window passes fill-free.
        probe = Intent("S1", good.version, "BTCUSDT", Side.LONG, cell[0],
                       good.entry_low, good.entry_high, cell[0] + timedelta(seconds=15),
                       good.invalidation_price, good.exit_rule, good.holding_limit_s,
                       good.forecast_cost, "synthetic-exposure-probe", DataQuality.CLEAN)
        nxt = gate2.evaluate(probe, mid)
        assert not nxt.ok and nxt.reason.startswith("risk-policy:rejected:exposure"), nxt.reason

        # Protective exit: drive the market through the stop; the stop fills,
        # the target sibling is cancelled (verified), the position goes flat.
        venue.set_last_price("BTCUSDT", stop_px - 1.0)
        events = manager2.poll()
        assert any(e.get("event", "").startswith("sibling-cancelled-after") for e in events), \
            "losing sibling must be cancelled after the winner fills"
        assert gate2.ledger.position_qty() == 0.0, "ledger must be flat"
        assert gate2.policy.booked_net(rid) == 0.0, "booked exposure must net to zero"
        assert not gate2.policy.live_reservations(), "no live reservations may strand"
        assert gate2.policy.unresolved_ids() == (), "no unresolved exposure may strand"

        # Closed-trade accounting on ACTUAL synthetic values (stopped-out loss).
        ref = stop_px - 1.0
        realised = gate2.ledger.net_realised()
        marked = gate2.ledger.marked_equity(ref)
        netliq = gate2.ledger.net_liquidation(ref, 15.0)
        paid = gate2.ledger.paid_costs()
        expected = entry.filled_qty * (ref - mid)
        assert abs(realised - expected) < 1e-6, (realised, expected)
        assert paid == 0.0, "fake venue models no fees"
        assert abs(marked - (equity + realised)) < 1e-6, "balances must reconcile"
        assert netliq == marked, "flat position: net-liq equals marked"
        assert len(venue.fills) == 2, "exactly entry-half + stop-half may fill"

        # Risk is unblocked again once flat: a fresh intent approves.
        fresh = Intent("S1", good.version, "BTCUSDT", Side.LONG, cell[0],
                       good.entry_low, good.entry_high, cell[0] + timedelta(seconds=15),
                       good.invalidation_price, good.exit_rule, good.holding_limit_s,
                       good.forecast_cost, "synthetic-post-flat", DataQuality.CLEAN)
        reopen = gate2.evaluate(fresh, ref)
        assert reopen.ok, f"flat risk must approve again: {reopen.reason}"
        assert reopen.reservation_id is not None
        gate2.release(reopen.reservation_id)

    report = {
        "slice": "M1",
        "synthetic": True,
        "input_class": "synthetic",
        "recording": "SYNTH_V1:long-breakout:seed11 via cryptobot-recording/1",
        "replay_sha256": replay_sha,
        "replay_events": replay_stats["count"],
        "evidence_bar": fire_t,
        "coordinator_reason": decision.reason,
        "rejected_count": len(decision.rejected),
        "risk": rdec.reason,
        "notional": rdec.notional_usdt,
        "fills": len(venue.fills),
        "fees": paid,
        "fee_label": "venue-models-no-fee",
        "realised": realised,
        "unrealised_at_ref": marked - equity - realised,
        "net_liquidation": netliq,
        "venue": "shared-fake:fault-simulator(partial-then-stop-exit)",
        "recovery": "crash-with-exposure: orders/risk/ledger rebuilt, fills/booked/cash agree",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
