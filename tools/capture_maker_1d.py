#!/usr/bin/env python3
"""1-day maker-data capture — 10GB-budget engineered (owner directive).

Captures exactly the data class the STUDY-04 P1 maker measurement consumes:
bookTicker (touch), aggTrades, markPrice@1s — for a pinned symbol pair —
at a measured-fit size: bookTicker events are emitted ONLY when the touch
PRICE changes (quantity churn is ~95% of raw bookTicker volume and is
useless to the fill models), with a 50ms per-symbol minimum interval as a
belt-and-braces bound. Output is gzip-streamed JSONL in the repo's
cryptobot-events/1 shape (the STUDY-04 tool consumes it directly). No raw
duplicate. Storage cap default 10GB (owner constraint), graceful
storage-bound stop, resumable conventions (STOP file, SIGTERM), heartbeat
with per-channel rates, manifest with sha256 at stop.

Fidelity disclosure (prereg amendment A2): between emitted updates the
consumer sees the last emitted touch; a touch that moves and returns
within the 50ms window is never observed. This is second-order for
touch-following fill models and is bounded and disclosed, not hidden.

No credentials, no orders, public streams only. Owner-directed lane.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import signal
import socket
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cryptobot.market_data.ws import WsClient  # noqa: E402

MARKET_URL = ("wss://fstream.binance.com/market/stream?streams="
              "{lo}@aggTrade/{hi}@aggTrade/{lo}@markPrice@1s/{hi}@markPrice@1s")
PUBLIC_URL = ("wss://fstream.binance.com/public/stream?streams="
              "{lo}@bookTicker/{hi}@bookTicker")
HEARTBEAT_S = 30.0


class Capture:
    def __init__(self, out_dir: Path, symbols: tuple[str, str],
                 cap_bytes: int, min_interval_ms: int = 50) -> None:
        self.out_dir = out_dir
        self.symbols = symbols
        self.cap_bytes = cap_bytes
        self.min_interval_ms = min_interval_ms
        self.seq = 0
        self.counts: dict[str, int] = {}
        self.dedup_skipped = 0
        self.throttle_skipped = 0
        self.reconnects = 0
        self.last_touch: dict[str, tuple[float, float]] = {}
        self.last_emit_ms: dict[str, int] = {}
        self.stop_reason: str | None = None
        self._since_flush = 0
        self._stop = False
        self.gz = gzip.open(out_dir / "events.jsonl.gz", "at",
                            compresslevel=6, encoding="utf-8")
        out_dir.mkdir(parents=True, exist_ok=True)

    def request_stop(self, reason: str) -> None:
        self.stop_reason = reason
        self._stop = True

    def _emit(self, route: str, channel: str, symbol: str,
              exchange_ts_ms: int, payload: dict) -> None:
        self.seq += 1
        self.counts[f"{route}/{channel}/{symbol}"] = \
            self.counts.get(f"{route}/{channel}/{symbol}", 0) + 1
        rec = {"v": 1, "format": "cryptobot-events/1",
               "input_class": "observed-public", "source": "binance-fapi-ws",
               "route": route, "seq": self.seq, "channel": channel,
               "symbol": symbol, "exchange_ts_ms": exchange_ts_ms,
               "local_recv_ms": int(time.time() * 1000),
               "gap_kind": None, "payload": payload}
        self.gz.write(json.dumps(rec, separators=(",", ":")) + "\n")
        # crash-safety: flush every 5000 events so a hard kill loses at
        # most a few thousand records, never the run
        self._since_flush += 1
        if self._since_flush >= 5000:
            self.gz.flush()
            self._since_flush = 0

    def handle_book(self, symbol: str, p: dict, recv_ms: int) -> None:
        bid, ask = float(p["b"]), float(p["a"])
        prev = self.last_touch.get(symbol)
        now_ms = int(recv_ms)
        last = self.last_emit_ms.get(symbol, 0)
        if prev is not None and prev == (bid, ask):
            self.dedup_skipped += 1
            return
        if now_ms - last < self.min_interval_ms and prev is not None:
            self.throttle_skipped += 1
            self.last_touch[symbol] = (bid, ask)  # track truth, emit later
            return
        self.last_touch[symbol] = (bid, ask)
        self.last_emit_ms[symbol] = now_ms
        self._emit("public", "bookTicker", symbol, int(p.get("T", recv_ms)),
                   {"bid": bid, "ask": ask, "bid_qty": float(p.get("B", 0)),
                    "ask_qty": float(p.get("A", 0)), "book_ts_ms": now_ms})

    def handle_trade(self, symbol: str, p: dict) -> None:
        self._emit("market", "aggTrade", symbol, int(p["T"]),
                   {"agg_id": p["a"], "price": float(p["p"]),
                    "qty": float(p["q"]), "trade_ts_ms": int(p["T"]),
                    "buyer_is_maker": p["m"]})

    def handle_mark(self, symbol: str, p: dict) -> None:
        self._emit("market", "markPrice", symbol, int(p["E"]),
                   {"mark_price": float(p["p"]), "ts": int(p["E"])})

    def bytes_written(self) -> int:
        # flushed-on-disk size (the gzip writer buffers internally; the cap
        # and the heartbeat must both see the truth on disk)
        try:
            return self.out_dir.joinpath("events.jsonl.gz").stat().st_size
        except OSError:
            return 0

    def heartbeat(self, t0: float) -> None:
        if self._since_flush:          # heartbeat always reports disk truth
            self.gz.flush()
            self._since_flush = 0
        hb = {"run_id": self.out_dir.name,
              "at_utc": datetime.now(timezone.utc).isoformat(),
              "events_total": self.seq,
              "bytes_written": self.bytes_written(),
              "cap_bytes": self.cap_bytes,
              "elapsed_s": round(time.time() - t0, 1),
              "per_channel": dict(self.counts),
              "book_dedup_skipped": self.dedup_skipped,
              "book_throttle_skipped": self.throttle_skipped,
              "reconnects": self.reconnects,
              "stop_reason": self.stop_reason}
        (self.out_dir / "heartbeat.json").write_text(json.dumps(hb, indent=1))

    def finalize(self) -> None:
        self.gz.close()
        path = self.out_dir / "events.jsonl.gz"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = {"run_id": self.out_dir.name,
                    "stopped_utc": datetime.now(timezone.utc).isoformat(),
                    "stop_reason": self.stop_reason,
                    "events_total": self.seq,
                    "bytes_written": self.bytes_written(),
                    "sha256_events_gz": digest,
                    "symbols": list(self.symbols),
                    "per_channel": dict(self.counts),
                    "book_dedup_skipped": self.dedup_skipped,
                    "book_throttle_skipped": self.throttle_skipped,
                    "reconnects": self.reconnects,
                    "input_class": "observed-public",
                    "note": "bookTicker emitted on touch PRICE change only "
                            "(>=50ms per symbol); qty churn omitted by design"}
        (self.out_dir / "manifest.json").write_text(json.dumps(manifest,
                                                               indent=1))


def pump(conn: WsClient, cap: Capture, route: str,
         lo: str, hi: str) -> None:
    """Drain one connection until stop; reconnect with backoff on error."""
    lo, hi = lo.lower(), hi.lower()
    while not cap._stop:
        try:
            msg = conn.recv_message(timeout_s=5.0)
        except (socket.timeout, TimeoutError):
            continue
        except Exception:
            cap.reconnects += 1
            try:
                conn.close()
            except Exception:
                pass
            time.sleep(min(2 ** min(cap.reconnects, 4), 16))
            try:
                url = (MARKET_URL if route == "market" else PUBLIC_URL).format(
                    lo=lo, hi=hi)
                conn = WsClient.connect(url)
            except Exception:
                continue
            continue
        if msg is None:
            continue
        kind, data = msg
        try:
            wrap = json.loads(data)
            stream = wrap.get("stream", "")
            payload = wrap.get("data", {})
        except json.JSONDecodeError:
            continue
        recv_ms = int(time.time() * 1000)
        symbol = stream.split("@")[0].upper()
        if "@bookTicker" in stream:
            cap.handle_book(symbol, payload, recv_ms)
        elif "@aggTrade" in stream:
            cap.handle_trade(symbol, payload)
        elif "@markPrice" in stream:
            cap.handle_mark(symbol, payload)
        if cap.bytes_written() >= cap.cap_bytes:
            cap.request_stop("storage-bound")
            return


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-base", type=Path, required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    ap.add_argument("--duration-s", type=int, default=86_400)
    ap.add_argument("--storage-cap-gb", type=float, default=10.0)
    args = ap.parse_args()
    symbols = tuple(s.strip().upper() for s in args.symbols.split(","))
    out_dir = args.run_base / args.run_id
    if out_dir.exists() and (out_dir / "manifest.json").exists():
        print(f"REFUSED: {out_dir} already complete")
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = Capture(out_dir, symbols, int(args.storage_cap_gb * 1e9))
    signal.signal(signal.SIGTERM, lambda *_: cap.request_stop("sigterm"))
    signal.signal(signal.SIGINT, lambda *_: cap.request_stop("sigint"))
    (out_dir / "STOP").unlink(missing_ok=True)
    lo, hi = symbols
    t0 = time.time()
    conns = []
    for route, url_t in (("market", MARKET_URL), ("public", PUBLIC_URL)):
        url = url_t.format(lo=lo.lower(), hi=hi.lower())
        conns.append((WsClient.connect(url), route, lo, hi))
    print(f"CAPTURING {symbols} -> {out_dir} cap={args.storage_cap_gb}GB",
          flush=True)
    last_hb = 0.0
    # single-threaded alternating drain: recv_message_nowait keeps one
    # bursting route from starving the other (E-009 semantics)
    while not cap._stop:
        progressed = False
        for conn, route, lo_, hi_ in conns:
            try:
                msg = conn.recv_message_nowait()
            except Exception:
                cap.reconnects += 1
                try:
                    conn.close()
                except Exception:
                    pass
                time.sleep(min(2 ** min(cap.reconnects, 4), 16))
                try:
                    url = (MARKET_URL if route == "market"
                           else PUBLIC_URL).format(lo=lo_.lower(),
                                                   hi=hi_.lower())
                    conns[conns.index((conn, route, lo_, hi_))] = \
                        (WsClient.connect(url), route, lo_, hi_)
                except Exception:
                    pass
                continue
            if msg is None:
                continue
            progressed = True
            _, data = msg
            try:
                wrap = json.loads(data)
                stream = wrap.get("stream", "")
                payload = wrap.get("data", {})
            except json.JSONDecodeError:
                continue
            recv_ms = int(time.time() * 1000)
            symbol = stream.split("@")[0].upper()
            if "@bookTicker" in stream:
                cap.handle_book(symbol, payload, recv_ms)
            elif "@aggTrade" in stream:
                cap.handle_trade(symbol, payload)
            elif "@markPrice" in stream:
                cap.handle_mark(symbol, payload)
        if cap.bytes_written() >= cap.cap_bytes:
            cap.request_stop("storage-bound")
            break
        if (out_dir / "STOP").exists():
            cap.request_stop("stop-file")
            break
        if time.time() - t0 >= args.duration_s:
            cap.request_stop("duration-elapsed")
            break
        if time.time() - last_hb >= HEARTBEAT_S:
            cap.heartbeat(t0)
            last_hb = time.time()
        if not progressed:
            time.sleep(0.002)  # 2ms idle: bounded latency, no busy spin
    cap.finalize()
    cap.heartbeat(t0)
    print(f"STOPPED ({cap.stop_reason}) events={cap.seq} "
          f"bytes={cap.bytes_written()}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
