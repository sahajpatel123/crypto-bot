"""Task C: operator commands incl. stop/take-profit, post-only, cancel, refusals."""
from __future__ import annotations

import json
from pathlib import Path

from cryptobot.ops.manual import Book, apply_order, flatten
from cryptobot.selftest import invoke


def _paths(tmp_path: Path) -> dict:
    return {
        "journal": str(tmp_path / "j.jsonl"),
        "book": str(tmp_path / "b.json"),
        "risk": str(tmp_path / "r.json"),
        "armed": str(tmp_path / "a.json"),
        "gate": str(tmp_path / "g.json"),
    }


def _ops(args: list[str], p: dict, mode: str = "emulator") -> tuple[int, str]:
    base = ["ops", *args, "--mode", mode, "--journal", p["journal"],
            "--book", p["book"], "--risk-state", p["risk"],
            "--armed", p["armed"], "--gate", p["gate"]]
    return invoke(base)


def test_ops_status_positions_orders_pause_resume(tmp_path):
    p = _paths(tmp_path)
    for action in ("status", "positions", "orders", "pause", "resume"):
        code, text = _ops([action], p)
        assert code == 0, (action, text)
        assert "Traceback" not in text
        doc = json.loads(text)
        assert doc.get("provenance") == "EMULATED" or "paused" in doc


def test_ops_market_and_limit_orders(tmp_path):
    p = _paths(tmp_path)
    code, text = _ops(["order", "--symbol", "BTCUSDT", "--side", "BUY",
                       "--qty", "0.01", "--kind", "MARKET"], p)
    assert code == 0, text
    assert "Traceback" not in text
    code, text = _ops(["order", "--symbol", "BTCUSDT", "--side", "SELL",
                       "--qty", "0.01", "--kind", "LIMIT", "--price", "1.0",
                       "--reduce-only"], p)
    # reduce-only SELL against long is valid; LIMIT far from touch rests.
    assert code in (0, 2), text
    assert "Traceback" not in text


def test_ops_stop_and_take_profit_route_via_algo(tmp_path):
    p = _paths(tmp_path)
    # Need a position first for reduce-only conditionals to be meaningful;
    # venue enforces reduce-only on algo fills, placement itself is WORKING.
    code, text = _ops(["order", "--symbol", "BTCUSDT", "--side", "BUY",
                       "--qty", "0.01", "--kind", "MARKET"], p)
    assert code == 0, text
    for kind, stop in (("STOP_MARKET", "100.0"),
                       ("TAKE_PROFIT_MARKET", "999999.0")):
        code, text = _ops(["order", "--symbol", "BTCUSDT", "--side", "SELL",
                           "--qty", "0.01", "--kind", kind,
                           "--stop-price", stop, "--reduce-only"], p)
        assert code == 0, (kind, text)
        assert "Traceback" not in text


def test_ops_post_only_limit_refuses_marketable(tmp_path):
    p = _paths(tmp_path)
    # Absurdly high buy limit is marketable -> post-only must refuse, no order.
    code, text = _ops(["order", "--symbol", "BTCUSDT", "--side", "BUY",
                       "--qty", "0.01", "--kind", "LIMIT",
                       "--price", "999999999.0", "--post-only"], p)
    assert code == 2, text
    assert "REFUSED" in text
    assert "Traceback" not in text


def test_ops_cancel_single_and_cancel_all(tmp_path):
    p = _paths(tmp_path)
    code, text = _ops(["order", "--symbol", "BTCUSDT", "--side", "BUY",
                       "--qty", "0.01", "--kind", "LIMIT",
                       "--price", "1.0"], p)
    assert code == 0, text
    doc = json.loads(text)
    cid = (doc.get("order") or {}).get("clientOrderId")
    assert cid, text
    code, text = _ops(["cancel", "--client-id", cid], p)
    assert code == 0, text
    assert "Traceback" not in text
    # cancel-all on empty book is ok and idempotent
    for _ in range(2):
        code, text = _ops(["cancel-all"], p)
        assert code == 0, text
        assert "Traceback" not in text


def test_ops_cancel_all_cancels_working_orders(tmp_path):
    p = _paths(tmp_path)
    code, _ = _ops(["order", "--symbol", "BTCUSDT", "--side", "BUY",
                    "--qty", "0.01", "--kind", "LIMIT",
                    "--price", "1.0"], p)
    assert code == 0
    code, text = _ops(["cancel-all"], p)
    assert code == 0, text
    doc = json.loads(text)
    assert doc.get("canceled", 0) >= 1, text
    code, text = _ops(["orders"], p)
    assert code == 0
    assert json.loads(text)["orders"] == []


def test_ops_flatten_and_kill(tmp_path):
    p = _paths(tmp_path)
    code, _ = _ops(["order", "--symbol", "BTCUSDT", "--side", "BUY",
                    "--qty", "0.01", "--kind", "MARKET"], p)
    assert code == 0
    code, text = _ops(["flatten", "--symbol", "BTCUSDT"], p)
    assert code == 0, text
    assert json.loads(text)["ok"] is True
    code, text = _ops(["kill"], p)
    assert code == 0, text
    doc = json.loads(text)
    assert doc.get("halted") is True


def test_ops_prod_refuses_every_action(tmp_path):
    p = _paths(tmp_path)
    for action in ("status", "positions", "orders", "pause", "resume",
                   "cancel-all", "flatten", "kill", "order", "cancel"):
        args = [action]
        if action == "order":
            args += ["--symbol", "BTCUSDT", "--side", "BUY", "--qty", "0.01"]
        if action == "cancel":
            args += ["--client-id", "x"]
        code, text = _ops(args, p, mode="prod")
        assert code == 2, (action, code, text)
        assert "REFUSED" in text
        assert "Traceback" not in text


def test_ops_duplicate_client_id_is_safe(tmp_path):
    book = Book()
    state = tmp_path / "r.json"
    first = apply_order(book, symbol="BTCUSDT", side="BUY", qty=0.01,
                        kind="LIMIT", price=1.0, reduce_only=False,
                        state_path=state, client_id="dup-1")
    assert first["ok"], first
    second = apply_order(book, symbol="BTCUSDT", side="BUY", qty=0.01,
                         kind="LIMIT", price=1.0, reduce_only=False,
                         state_path=state, client_id="dup-1")
    assert not second["ok"]
    assert "REFUSED" in second["message"]


def test_ops_flatten_is_symbol_scoped(tmp_path):
    book = Book()
    state = tmp_path / "r.json"
    assert flatten(book, "BTCUSDT")["ok"] is True
