"""E1 harness: the real BinanceLiveEngine over real sockets to MockEx.

Everything here is offline (loopback only) and EMULATED. Keys are throwaway
FAKE values generated per run and held only in memory / the process
environment; no real credential is ever read. Faults are scripted on the
venue (``Emu.fault``) so every scenario is deterministic.
"""
from __future__ import annotations

import contextlib
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptobot.adapters.binance_live import BinanceLiveEngine, UrllibTransport
from cryptobot.adapters.mockex_server import MockEx
from cryptobot.adapters.sandbox_venue import SYMBOLS
from cryptobot.app.engine import EngineOrder

BTC = "BTCUSDT"
ETH = "ETHUSDT"


class SkewClock:
    """Local wall clock that can be stepped (NTP jump) independently."""

    def __init__(self) -> None:
        self.skew = timedelta(0)

    def now(self) -> datetime:
        return datetime.now(UTC) + self.skew

    def step(self, seconds: float) -> None:
        self.skew += timedelta(seconds=seconds)


class Emu:
    """One MockEx on 127.0.0.1 plus engine factories bound to it."""

    def __init__(self, tmp_path: Path, **mock_kw) -> None:
        self.tmp = Path(tmp_path)
        self.secret = "fake-secret-" + secrets.token_hex(12)
        self.key = "fake-key-" + secrets.token_hex(6)
        self.mock = MockEx(api_secret=self.secret, **mock_kw)
        self.port = self.mock.serve()
        self.base = f"http://127.0.0.1:{self.port}"
        self.venue = self.mock.venue
        self.clock = SkewClock()
        self._engines: list[BinanceLiveEngine] = []
        self._saved_sizes = {s: dict(v)["size"] for s, v in SYMBOLS.items()}

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        for engine in self._engines:
            with contextlib.suppress(Exception):
                engine.close()
        self.mock.close()
        for sym, size in self._saved_sizes.items():
            SYMBOLS[sym]["size"] = size  # set_size mutates module state.

    def engine(self, name: str = "e", *, timeout_s: float = 5.0,
               clock: SkewClock | None = None, **kw) -> BinanceLiveEngine:
        clk = clock or self.clock
        engine = BinanceLiveEngine(
            api_key=self.key, api_secret=self.secret,
            journal_path=self.tmp / f"{name}.jsonl", expected_leverage=3,
            run_tag="e1", live_enable=True, demo=False,
            base_url=self.base,
            transport=UrllibTransport(self.base, timeout_s=timeout_s),
            now_utc=clk.now, **kw)
        self._engines.append(engine)
        return engine

    def ready_engine(self, name: str = "e", symbol: str = BTC,
                     **kw) -> BinanceLiveEngine:
        engine = self.engine(name, **kw)
        engine._ensure_ready(symbol)
        return engine

    # -- scripted faults ---------------------------------------------------
    def fault(self, op: str, action: str, **extra) -> dict:
        entry = {"op": op, "action": action, "at": "once", **extra}
        self.venue.cfg.faults.entries.append(entry)
        return entry

    def clear_faults(self) -> None:
        self.venue.cfg.faults.entries.clear()

    # -- venue truth (independent of the engine under test) ------------------
    def position(self, symbol: str = BTC) -> float:
        return float(self.venue.positions.get(symbol, {}).get("qty", 0.0))

    def order_posts(self) -> int:
        """Order-placement POSTs the venue received (incl. algo rail)."""
        return sum(1 for row in self.venue.log
                   if row["method"] == "POST"
                   and row["path"] in ("/fapi/v1/order",
                                       "/fapi/v1/algoOrder"))

    def requests(self, method: str | None = None,
                 path: str | None = None) -> list[dict]:
        return [r for r in self.venue.log
                if (method is None or r["method"] == method)
                and (path is None or r["path"] == path)]

    def open_orders(self) -> list[dict]:
        return list(self.venue.open_orders()) + list(
            self.venue.open_algo_orders())

    def trades(self) -> list[dict]:
        return list(self.venue.trades)


def market_buy(qty: float = 0.002, symbol: str = BTC,
               reservation: str = "r1") -> EngineOrder:
    return EngineOrder(symbol, "BUY", qty, "MARKET", reservation_id=reservation,
                       role="entry")


def journal(engine: BinanceLiveEngine, event: str | None = None) -> list[dict]:
    rows = engine._read_journal()
    return [r for r in rows if event is None or r.get("event") == event]
