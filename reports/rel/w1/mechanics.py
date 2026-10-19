"""Checkpoint-A mechanics (W1-side, reference adapter): a real adapter
emission books the authoritative ledger once, drives protection, and
survives restart without double-booking. Joint run with W2's
injected-venue adapter follows on its fixture."""
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptobot.app.config import load_config
from cryptobot.app.engine import EngineOrder
from cryptobot.app.reference import ReferenceEngine
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore

tmp = Path(tempfile.mkdtemp(prefix="w1rel-mech-"))
text = open("configs/paper.toml").read().replace(
    'dir = "runs"', f'dir = "{tmp / "runs"}"', 1)
cfg_path = tmp / "test.toml"
cfg_path.write_text(text)
config = load_config(cfg_path)

store = RunStore(tmp / "runs" / "cryptobot.db")
store.create_run("mech", "replay", "fp", str(tmp / "runs" / "mech"), None)
engine = ReferenceEngine(log_path=tmp / "runs" / "mech" / "om.jsonl",
                         outcome_sink=None, taker_bps=5.0)
session = Session(config, store, tmp / "runs" / "mech", "mech", engine=engine)
session.policy.reconcile_day(120.0, 0.0)

# Admit by hand (labeled mechanics fixture): reserve, submit MARKET.
from cryptobot.risk.state import Reservation
now = session.now_utc()
rid = "r-mech-1"
session.policy._state.reservations[rid] = Reservation(
    reservation_id=rid, intent_ref="mech:1", instrument="BTCUSDT",
    side="LONG", notional=5.0, reserved_risk=1.0,
    created_utc=now.isoformat(),
    expires_utc=(now + timedelta(seconds=600)).isoformat(), qty=0.05)
session.policy.note_executable_qty(rid, 0.05)
session._known_reservations.add(rid)
engine.note_mark("BTCUSDT", 100.0)
cmd = session._new_command("submit", {"role": "entry"})
pre = engine.submit(EngineOrder(
    instrument="BTCUSDT", side="BUY", qty=0.05, kind="MARKET",
    reservation_id=rid, role="entry"))
store.update_command(cmd, "submitted", engine_client_id=pre)
session._submit_ts[pre] = session.now_utc()
session._position = {
    "reservation_id": rid, "instrument": "BTCUSDT",
    "side": "LONG", "entry_pre_id": pre, "entry_id": None, "legs": [],
    "retired": [], "stop": 99.0, "target": 102.0,
    "time_exit": now + timedelta(seconds=600), "legacy_exit": None,
    "protected": False, "protect_attempts": 0, "entry_cap": None,
    "close_ids": [], "emergency_latched": False, "exposure_noted": False,
    "approved_qty": 0.05, "executable_qty": 0.05}
engine.note_mark("BTCUSDT", 100.0)
n = session._drain_engine()
print(f"live: drained={n} ledger_qty={session.ledger.position_qty():.6f} "
      f"booked={session.policy.booked_net(rid):.6f} "
      f"fee={session.ledger.paid_costs():.6f} "
      f"protected={session._position['protected']} "
      f"legs={session._position['legs']}")
assert session.ledger.position_qty() > 0
assert session._position["protected"] is True
fills_live = (session.workdir / "fills.jsonl").read_text().splitlines()
assert len(fills_live) == 1, fills_live
ev_live = store._db.execute(
    "SELECT COUNT(*) FROM execution_events WHERE run_id='mech' AND"
    " kind='fill'").fetchone()[0]
assert ev_live == 1, ev_live

# Restart: fresh objects, same store+workdir; rebuild + recover.
session._persist_local_state()
store.close()
store2 = RunStore(tmp / "runs" / "cryptobot.db")
engine2 = ReferenceEngine(log_path=tmp / "runs" / "mech" / "om.jsonl",
                          outcome_sink=None, taker_bps=5.0)
session2 = Session(config, store2, tmp / "runs" / "mech", "mech",
                   engine=engine2)
session2.policy.reconcile_day(120.0, 0.0)
for rid in session2.policy.live_reservations():
    session2._known_reservations.add(rid)
for rid in session2.policy.unresolved_ids():
    session2._known_reservations.add(rid)
session2._rebuild_booking_state()
engine2.recover(session2._engine_handler)
session2._drain_engine()
print(f"restart: ledger_qty={session2.ledger.position_qty():.6f} "
      f"booked={session2.policy.booked_net(rid):.6f} "
      f"applied={sorted(session2._applied_exec)} "
      f"dup={session2._dup_events}")
assert session2.ledger.position_qty() == session.ledger.position_qty()
assert session2.policy.booked_net(
    rid) == session.policy.booked_net(
        rid)
fills_re = (session2.workdir / "fills.jsonl").read_text().splitlines()
assert len(fills_re) == 1, fills_re  # adopted redelivery: no dup row.
print("MECHANICS-OK ledger-once protection-verified restart-clean")
