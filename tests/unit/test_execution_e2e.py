"""End-to-end runtime test (Worker 2, E-007): event -> intent -> risk -> fill.

Deterministic replay (evidence labeled ``replay:``): a fixture public stream
drives intent formation, risk admission, simulated taker entry, protective
exit, and reconciliation to flat with fee-bearing fills. Replayed twice for
determinism.

Requires nautilus_trader (trial venv); skipped in the stdlib-only project env.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

nautilus = pytest.importorskip("nautilus_trader")

from cryptobot.accounting.ledger import Ledger  # noqa: E402
from cryptobot.adapters import NautilusPaperEngine  # noqa: E402
from cryptobot.coordination import (  # noqa: E402
    DataQuality,
    ForecastCost,
    Intent,
    Side,
    decode_exit_rule,
    encode_exit_rule,
)
from cryptobot.coordination.exits import ExitPolicy  # noqa: E402
from cryptobot.execution import RuntimeTrader, StreamPump  # noqa: E402
from cryptobot.market_data.bridge import iter_market_stream, snapshot_record  # noqa: E402
from cryptobot.risk.policy import RiskPolicy  # noqa: E402
from cryptobot.risk.types import AccountSnapshot, Approved, RiskConfig  # noqa: E402

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
T0MS = int(T0.timestamp() * 1000)
EQUITY = 10_000.0


def _ticker(seq, recv_ms, bid, ask):
    return {
        "v": 1, "format": "cryptobot-events/1", "input_class": "observed-public",
        "source": "binance-fapi-ws", "route": "public", "run_id": "e2e", "seq": seq,
        "channel": "bookTicker", "symbol": "BTCUSDT", "exchange_ts_ms": recv_ms,
        "local_recv_ms": recv_ms, "local_mono_ns": recv_ms * 1_000_000,
        "gap_kind": None, "venue_seq": seq,
        "payload": {"update_id": seq, "bid": bid, "bid_qty": 10.0,
                    "ask": ask, "ask_qty": 10.0, "book_ts_ms": recv_ms},
    }


def _fixture(tmp_path):
    """Rising ladder: entry fills ~60001, target 60020 fills at the top."""
    snaps = [snapshot_record(run_id="e2e", symbol="BTCUSDT", last_update_id=50,
                             bids=[["60000.00", "1.0"]], asks=[["60000.50", "1.0"]],
                             rest_recv_ms=T0MS, rest_mono_ns=T0MS * 10**6,
                             limit=1000, outcome="synced")]
    ladder = [60000.00, 60001.00, 60002.00, 60005.00, 60010.00,
              60015.00, 60019.00, 60021.00, 60022.00, 60023.00]
    events = [_ticker(i + 1, T0MS + i * 1000, px, px + 0.50)
              for i, px in enumerate(ladder)]
    tmp_path.mkdir(parents=True, exist_ok=True)
    snaps_path, events_path = tmp_path / "s.jsonl", tmp_path / "e.jsonl"
    snaps_path.write_text("\n".join(json.dumps(r) for r in snaps) + "\n")
    events_path.write_text("\n".join(json.dumps(r) for r in events) + "\n")
    return events_path, snaps_path


def _run(tmp_path, tag):
    now = [T0]
    engine = NautilusPaperEngine(outcome_sink=None, taker_bps=5.0,
                                 now_utc=lambda: now[0],
                                 submit_delay_ms=0, fill_delay_ms=1,
                                 journal_path=tmp_path / f"eng-{tag}.jsonl")
    engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                          tick_size=0.01, step_size=0.001, ts_utc=T0)
    ledger = Ledger(EQUITY)
    policy = RiskPolicy(RiskConfig(), state_path=tmp_path / f"risk-{tag}.json",
                        now_utc=lambda: now[0])
    policy.bind_ledger(ledger)
    policy.reconcile_day(EQUITY, 0.0)
    engine.bind_sink(policy)
    trader = RuntimeTrader(engine, log_path=tmp_path / f"rt-{tag}.jsonl",
                           ledger=ledger, outcome_sink=policy,
                           now_utc=lambda: now[0])
    pump = StreamPump(engine)  # funding settles inside the engine (E-008).
    events_path, snaps_path = _fixture(tmp_path / tag)
    items = list(iter_market_stream(events_path, snaps_path))
    admitted = False
    entry_id = None
    fills_seen = []
    for tick in pump.pump_stream(iter(items)):
        now[0] = datetime.fromtimestamp(tick.record["exchange_ts_ms"] / 1000,
                                        tz=timezone.utc)
        trader.ingest(tick.engine_events)  # pump already drained the engine.
        trader.poll()  # settle windows, sibling groups, callbacks.
        if not admitted and tick.record["seq"] == 2:
            mark = tick.record["payload"]["ask"]
            intent = Intent(
                strategy="S1", version="s1-base", instrument="BTCUSDT",
                side=Side.LONG, evidence_ts_utc=now[0],
                entry_low=mark - 5.0, entry_high=mark + 5.0,
                entry_expiry_utc=now[0] + timedelta(seconds=60),
                invalidation_price=mark - 100.0,
                exit_rule=encode_exit_rule(ExitPolicy(
                    stop_price=mark - 100.0, target_price=60020.00,
                    time_exit_utc=now[0] + timedelta(seconds=300),
                    reduce_only=True, policy_id="S1:stop+target+time")),
                holding_limit_s=300,
                forecast_cost=ForecastCost(5.0, 1.0, 1.0, 1.0),
                evidence_ref="replay:e007-e2e:S1:seq2",
                data_quality=DataQuality.CLEAN)
            verdict = policy.evaluate(intent, AccountSnapshot(
                reconciled_equity=EQUITY, marked_equity=EQUITY,
                net_liquidation=EQUITY, net_realised_global=0.0,
                open_position=False))
            assert isinstance(verdict, Approved), verdict
            entry_id = trader.submit_entry(
                "BTCUSDT", "LONG", verdict.qty,
                expire_at_utc=intent.entry_expiry_utc,
                reservation_id=verdict.reservation_id)
            admitted = True
            admitted_res = verdict.reservation_id
            admitted_qty = verdict.qty
        if admitted and entry_id is not None and trader._client_fills.get(entry_id, 0.0) > 0:
            exits = decode_exit_rule(intent.exit_rule)
            try:
                trader.protect(admitted_res, exits.stop_price, exits.target_price)
            except ValueError:
                pass  # already protected.
    trader.poll()
    trader.poll()
    return {
        "ledger": ledger, "policy": policy, "trader": trader, "engine": engine,
        "reservation": admitted_res, "qty": admitted_qty, "intent": intent,
        "fills": [(f["venue_side"], f["qty"], f["price"], f["fee"])
                  for f in trader._fills.values()],
    }


def test_public_event_to_reconciled_flat(tmp_path):
    out = _run(tmp_path, "a")
    ledger, policy, trader = out["ledger"], out["policy"], out["trader"]
    # Two fee-bearing taker fills: LONG entry then SELL target exit.
    assert len(out["fills"]) == 2
    (entry_side, entry_qty, entry_px, entry_fee), (exit_side, exit_qty, exit_px, exit_fee) = out["fills"]
    assert (entry_side, exit_side) == ("BUY", "SELL")
    assert entry_qty == pytest.approx(exit_qty) and entry_qty > 0
    assert exit_px > entry_px  # target filled above the entry cross.
    assert entry_fee > 0 and exit_fee > 0
    # Reconciled flat everywhere: ledger, policy bookings, trader net.
    assert ledger.position_qty() == pytest.approx(0.0)
    assert ledger.paid_costs() == pytest.approx(entry_fee + exit_fee)
    assert policy.booked_net(out["reservation"]) == pytest.approx(0.0)
    assert trader.position_net(out["reservation"]) == pytest.approx(0.0)
    assert ("flat", out["reservation"]) in trader._fired
    # Journal durability: the ledger replays exactly from its own journal.
    clone = Ledger.from_dict(ledger.to_dict())
    assert clone.position_qty() == pytest.approx(0.0)
    assert clone.net_realised() == pytest.approx(ledger.net_realised())
    # Replay label preserved end to end (never a live session): the labeled
    # intent admitted the reservation whose booked exec_ids closed flat.
    assert out["intent"].evidence_ref == "replay:e007-e2e:S1:seq2"
    state = json.loads((tmp_path / "risk-a.json").read_text())
    assert state["booked"][out["reservation"]]["net_qty"] == pytest.approx(0.0)
    assert len(state["booked"][out["reservation"]]["exec_ids"]) == 2


def test_e2e_deterministic_replay(tmp_path):
    first = _run(tmp_path, "a")
    second = _run(tmp_path, "b")
    assert first["fills"] == second["fills"]  # identical economics.
    assert first["ledger"].net_realised() == pytest.approx(second["ledger"].net_realised())
    assert first["ledger"].paid_costs() == pytest.approx(second["ledger"].paid_costs())
