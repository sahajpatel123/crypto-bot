"""Public-data recorder: kline capture with exchange/local timestamps (Worker 2, E-001).

Recording format ``cryptobot-recording/1`` (JSONL):
  line 0: header  {"type": "header", "format": ..., "input_class": ...,
                   "source", "symbol", "channel", "capture_cmd",
                   "started_utc", "interval_ms"}
  lines 1..n:     {"type": "kline", "seq", "exchange_open_ms",
                   "exchange_close_ms", "local_recv_ms", "o/h/l/c/v",
                   "closed", ...}
  last line: footer {"type": "footer", "stats": {...}}

``input_class`` is mandatory and is either ``observed-public`` (venue data)
or ``synthetic`` (generated locally). Synthetic and observed recordings must
never be mixed; the replayer surfaces the label on every replay.

Gap detection: closed-klines form an exact ``interval_ms`` grid on
``exchange_open_ms``; missing grid steps are gaps. Stale detection: a closed
kline whose ``local_recv_ms - exchange_close_ms`` exceeds the threshold was
observed too late to trade and is flagged stale.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RECORDING_FORMAT = "cryptobot-recording/1"
INPUT_OBSERVED = "observed-public"
INPUT_SYNTHETIC = "synthetic"


@dataclass(frozen=True)
class GapRange:
    first_missing_open_ms: int
    last_missing_open_ms: int
    missing_count: int


@dataclass(frozen=True)
class RecordingStats:
    count: int
    closed_count: int
    gaps: tuple[GapRange, ...] = field(default_factory=tuple)
    stale_count: int = 0
    max_lag_ms: int | None = None  # max local_recv - exchange_close over closed klines.
    first_open_ms: int | None = None
    last_open_ms: int | None = None


def analyze_klines(
    records: Iterable[dict[str, Any]],
    interval_ms: int,
    *,
    stale_after_ms: int = 30_000,
) -> RecordingStats:
    klines = sorted(
        (r for r in records if r.get("type") == "kline"),
        key=lambda r: (int(r["exchange_open_ms"]), int(r.get("seq", 0))),
    )
    if not klines:
        return RecordingStats(count=0, closed_count=0)
    closed = [k for k in klines if k.get("closed")]
    gaps: list[GapRange] = []
    if closed:
        step = interval_ms
        prev_open = int(closed[0]["exchange_open_ms"])
        for k in closed[1:]:
            cur = int(k["exchange_open_ms"])
            if cur > prev_open + step:
                missing_first = prev_open + step
                missing_last = cur - step
                # Merge contiguous missing grid steps into one range.
                if gaps and gaps[-1].last_missing_open_ms + step == missing_first:
                    prev = gaps.pop()
                    gaps.append(GapRange(prev.first_missing_open_ms, missing_last,
                                         prev.missing_count + (missing_last - missing_first) // step + 1))
                else:
                    gaps.append(GapRange(missing_first, missing_last,
                                         (missing_last - missing_first) // step + 1))
            prev_open = cur
    stale = 0
    max_lag: int | None = None
    for k in closed:
        lag = int(k["local_recv_ms"]) - int(k["exchange_close_ms"])
        max_lag = lag if max_lag is None else max(max_lag, lag)
        if lag > stale_after_ms:
            stale += 1
    return RecordingStats(
        count=len(klines),
        closed_count=len(closed),
        gaps=tuple(gaps),
        stale_count=stale,
        max_lag_ms=max_lag,
        first_open_ms=int(closed[0]["exchange_open_ms"]) if closed else None,
        last_open_ms=int(closed[-1]["exchange_open_ms"]) if closed else None,
    )


def stats_to_dict(stats: RecordingStats) -> dict[str, Any]:
    return {
        "count": stats.count,
        "closed_count": stats.closed_count,
        "gaps": [
            {"first_missing_open_ms": g.first_missing_open_ms,
             "last_missing_open_ms": g.last_missing_open_ms,
             "missing_count": g.missing_count}
            for g in stats.gaps
        ],
        "stale_count": stats.stale_count,
        "max_lag_ms": stats.max_lag_ms,
        "first_open_ms": stats.first_open_ms,
        "last_open_ms": stats.last_open_ms,
    }


class KlineRecorder:
    """Append-only JSONL kline recorder."""

    def __init__(
        self,
        path: str | Path,
        *,
        symbol: str,
        channel: str,
        interval_ms: int,
        input_class: str,
        source: str,
        capture_cmd: str,
    ) -> None:
        if input_class not in (INPUT_OBSERVED, INPUT_SYNTHETIC):
            raise ValueError(f"input_class must be {INPUT_OBSERVED} or {INPUT_SYNTHETIC}")
        self.path = Path(path)
        self.interval_ms = interval_ms
        self._seq = 0
        self._file = self.path.open("w", encoding="utf-8")
        header = {
            "type": "header",
            "format": RECORDING_FORMAT,
            "input_class": input_class,
            "source": source,
            "symbol": symbol,
            "channel": channel,
            "interval_ms": interval_ms,
            "capture_cmd": capture_cmd,
            "started_utc": datetime.now(UTC).isoformat(),
        }
        self._file.write(json.dumps(header) + "\n")

    @property
    def seq(self) -> int:
        return self._seq

    def record_rest_kline(self, row: list[Any], local_recv_ms: int) -> dict[str, Any]:
        """Record one Binance REST kline row (12-field array).

        The last REST row is usually the still-forming candle; a row whose
        exchange close time lies in the future cannot be closed, so the flag
        is derived from timestamps rather than assumed.
        """
        close_ms = int(row[6])
        record = {
            "type": "kline",
            "seq": self._seq,
            "exchange_open_ms": int(row[0]),
            "o": str(row[1]),
            "h": str(row[2]),
            "l": str(row[3]),
            "c": str(row[4]),
            "v": str(row[5]),
            "exchange_close_ms": close_ms,
            "closed": close_ms <= int(local_recv_ms),
            "local_recv_ms": int(local_recv_ms),
        }
        self._seq += 1
        self._file.write(json.dumps(record) + "\n")
        return record

    def record_event_kline(self, event: dict[str, Any], local_recv_ms: int) -> dict[str, Any]:
        """Record one websocket-style kline event payload (k object)."""
        k = event.get("k", event)
        record = {
            "type": "kline",
            "seq": self._seq,
            "exchange_open_ms": int(k["t"]),
            "o": str(k["o"]),
            "h": str(k["h"]),
            "l": str(k["l"]),
            "c": str(k["c"]),
            "v": str(k["v"]),
            "exchange_close_ms": int(k["T"]),
            "closed": bool(k.get("x", False)),
            "local_recv_ms": int(local_recv_ms),
        }
        self._seq += 1
        self._file.write(json.dumps(record) + "\n")
        return record

    def finish(self, *, stale_after_ms: int = 30_000) -> RecordingStats:
        self._file.flush()
        records = [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        stats = analyze_klines(records, self.interval_ms, stale_after_ms=stale_after_ms)
        self._file.write(json.dumps({"type": "footer", "stats": stats_to_dict(stats)}) + "\n")
        self._file.close()
        return stats

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()
