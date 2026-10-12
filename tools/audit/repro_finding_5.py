#!/usr/bin/env python3
"""Repro finding 5: select-stranded frames (Worker 5, OP-001). Exit 1 = bug."""
import json
import select
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from cryptobot.market_data.collector import Collector, CollectorConfig
from cryptobot.market_data.ws import WsClient, encode_frame


def _payload(i):
    return json.dumps(
        {"stream": "btcusdt@aggTrade",
         "data": {"e": "aggTrade", "E": 1000, "s": "BTCUSDT", "a": i,
                  "p": "100", "q": "0.5", "f": i, "l": i,
                  "T": 1000, "m": False}}).encode()


def main() -> int:
    client_sock, server_sock = socket.socketpair()
    try:
        server_sock.sendall(encode_frame(0x1, _payload(1), mask=False)
                            + encode_frame(0x1, _payload(2), mask=False))
        # Keep the server side OPEN but idle: kernel is drained after the
        # client's first recv, so select() must report not-readable while a
        # complete second frame sits in the application buffer.
        client = WsClient(client_sock)
        kind, first = client.recv_message(timeout_s=5.0)
        print(f"first recv_message: {kind}, {len(first)} bytes (aggTrade a=1)")
        print(f"application _buf after first recv: {len(client._buf)} bytes")
        readable, _, _ = select.select([client.native_socket], [], [], 0.0)
        print(f"select() readable now: {len(readable)} sockets")
        with tempfile.TemporaryDirectory() as tmp:
            collector = Collector(CollectorConfig(
                symbols=("BTCUSDT",), run_dir=str(Path(tmp) / "run"),
                run_id="audit", capture_set_rule="audit"))
            run_dir = Path(collector.config.run_dir)
            run_dir.mkdir(parents=True, exist_ok=True)
            collector._conns = {"market": client}
            with (run_dir / "raw.jsonl").open("w") as raw_fh, \
                 (run_dir / "events.jsonl").open("w") as events_fh, \
                 (run_dir / "bars.jsonl").open("w") as bars_fh:
                drained = collector._pump_once(raw_fh, events_fh, bars_fh)
            print(f"collector._pump_once drained: {drained} messages")
            print(f"_buf remaining: {len(client._buf)} bytes")
            if drained < 1 and len(client._buf) > 0:
                print("BUG REPRODUCED: complete frame stranded behind quiet select()")
                return 1
            print("OK: buffered frame drained without new readability")
            return 0
    finally:
        try:
            client_sock.close()
        except OSError:
            pass
        try:
            server_sock.close()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
