"""Review-2 defect 5: cross-symbol fill loss (W5-24H).

Two ORDER_TRADE_UPDATE fills with trade ID 777, one BTC and one ETH,
produce only one EngineFill because _trades_booked is keyed by trade ID
alone (both the user-stream path and the lookup path; execution IDs
also omit the symbol).

Required: use venue/account/symbol/trade identity consistently in
user-stream parsing, lookup adoption, journals and ledger execution
IDs; verify duplicate redelivery and distinct-symbol fills.

Fails on base 3cadfca (bug reproduced); passes once fixed.
Strict-xfail marked in tests/audit/conftest.py while open. The
redelivery guard passes both before and after (no overcorrection).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.adapters.binance_live import BinanceLiveEngine

T0MS = 1728720000000


class _DeadTransport:
    def request(self, *args, **kwargs):
        raise AssertionError("user-stream path must not touch the network")


def _engine(tmp_path):
    return BinanceLiveEngine(
        api_key="TESTKEY", api_secret="TESTSECRET",
        journal_path=tmp_path / "live.jsonl", expected_leverage=3,
        run_tag="w5d5", live_enable=True, transport=_DeadTransport())


def _trade_update(symbol, cid, tid, qty=0.5, price=60000.0):
    return {"e": "ORDER_TRADE_UPDATE", "E": T0MS,
            "o": {"s": symbol, "c": cid, "S": "BUY", "X": "FILLED",
                  "x": "TRADE", "l": str(qty), "L": str(price),
                  "n": "0.03", "N": "USDT", "t": str(tid)}}


def _journal(tmp_path):
    return [json.loads(line) for line in
            (tmp_path / "live.jsonl").read_text().splitlines()]


def test_distinct_symbol_same_trade_id_both_booked(tmp_path):
    """BTC/777 + ETH/777 must adopt two fills, not one."""
    engine = _engine(tmp_path)
    engine.note_user_event(_trade_update("BTCUSDT", "cid-btc", 777))
    engine.note_user_event(_trade_update("ETHUSDT", "cid-eth", 777))
    assert engine.filled_qty("cid-btc") == 0.5, "setup broken: BTC fill lost"
    assert engine.filled_qty("cid-eth") == 0.5, (
        "ETH/777 dropped: trade identity ignores symbol")
    adopted = [r for r in _journal(tmp_path)
               if r.get("event") == "fill-adopted"]
    assert len(adopted) == 2, f"expected 2 adopted fills, got {len(adopted)}"


def test_same_symbol_redelivery_stays_idempotent(tmp_path):
    """Same symbol+trade redelivered must still book exactly once."""
    engine = _engine(tmp_path)
    engine.note_user_event(_trade_update("BTCUSDT", "cid-btc", 777))
    engine.note_user_event(_trade_update("BTCUSDT", "cid-btc", 777))
    assert engine.filled_qty("cid-btc") == 0.5
    adopted = [r for r in _journal(tmp_path)
               if r.get("event") == "fill-adopted"]
    assert len(adopted) == 1, f"redelivery double-booked: {len(adopted)}"
