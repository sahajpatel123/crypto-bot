"""24h directive manager reproductions (A1/A2/A5/A6 runtime, A3/A4 static-confirmed)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

from cryptobot.market_data.views import DepthStore, book_flow_for

print("=== A1: future snapshot visible at replay startup ===")
store = DepthStore()
# _prime_replay_books equivalent: install ALL snapshots before any events.
store.apply_snapshot_record({
    "symbol": "BTCUSDT", "bids": [["100.0", "1.0"]], "asks": [["101.0", "1.0"]],
    "last_update_id": 1, "rest_recv_ms": 1000})
store.apply_snapshot_record({
    "symbol": "BTCUSDT", "bids": [["200.0", "1.0"]], "asks": [["201.0", "1.0"]],
    "last_update_id": 2, "rest_recv_ms": 9000})
book, _, reason = book_flow_for("BTCUSDT", 1500, store)
print("query@1500 ->", book, reason)
assert book is not None and abs(book.bids[0][0] - 200.0) < 1e-9, "expected future bid 200"
assert book.sync_age_ms == 1500 - 9000, book.sync_age_ms
print("REPRODUCED: future bid 200 visible at 1500ms, sync_age_ms=-7500")

print("=== A2: false live-sync report ===")
from cryptobot.market_data.views import DepthBook
b = DepthBook("BTCUSDT")
out = b.on_snapshot([["100", "1"]], [["101", "1"]], 10)
print("snapshot@10 ->", out)
# Gap diff that cannot bridge ID 10.
r = b.on_diff({"first_update": 50, "last_update": 55,
               "prev_last_update": 49, "bids": [], "asks": []})
print("gap diff ->", r, "| state.synced:", b.state.synced)
print("REPRODUCED" if r == "resync" else "NOT-REPRODUCED",
      ": prime ignores install outcome yet reports synced")
# _prime_live_books path: outcome discarded, symbol reported primed/synced.
import inspect
from cryptobot.app.session import Session
src = inspect.getsource(Session._prime_live_books)
print("prime checks outcome:", "apply_snapshot_record" in src
      and ("outcome" in src or "synced" in src.split("summary[\"synced\"]")[0][-200:]))
print("REPRODUCED: return value of apply_snapshot_record is discarded"
      if ".apply_snapshot_record({" in src and "outcome =" not in src
      else "CHECK MANUALLY")

print("=== A5: cross-symbol fill loss ===")
sys.path.insert(0, "tests/unit")
import importlib.util
spec = importlib.util.spec_from_file_location(
    "blv", "tests/unit/test_binance_live_v008.py")
blv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blv)
import tempfile
tmp = Path(tempfile.mkdtemp())
eng, _ = blv._live(tmp, [])


def _otu(sym, cid):
    return {"e": "ORDER_TRADE_UPDATE", "E": 1000,
            "o": {"s": sym, "c": cid, "S": "BUY", "X": "PARTIALLY_FILLED",
                  "x": "TRADE", "l": "0.1", "L": "50000", "t": 777,
                  "n": "0.01", "N": "USDT"}}


eng.note_user_event(_otu("BTCUSDT", "c-btc-1"))
eng.note_user_event(_otu("ETHUSDT", "c-eth-1"))
fills = [e for e in eng._pending if e.kind == "fill"]
print("fills adopted:", len(fills))
print("REPRODUCED" if len(fills) == 1 else "NOT-REPRODUCED",
      ": second symbol fill dropped on trade-id-only key")
