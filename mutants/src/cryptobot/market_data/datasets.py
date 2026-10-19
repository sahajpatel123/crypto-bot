"""Frozen-dataset reader for backtests (W2, E-009; B5).

:func:`open_dataset` opens a manifest TOML (``vision-archive`` or
``captured-runs`` kind) and returns a handle with ``.events(symbol, day)``,
``.coverage()``, and ``.manifest_sha()``. Event streams are normalized to
the live record schema (``input_class="observed-archive"`` /
``"observed-public"``) with B3 idle heartbeats (``None``, one per idle
virtual second). Reads stream (Parquet iterators + bounded heap merge for
vision; line iteration for captures) — a day table or a month of ticks is
never loaded into one list — and replay performs no fetch (offline after
preparation). :func:`verify_dataset` checks every derived file present and
hash-matching before a run.

``local`` paths in the manifest resolve against the TOML's own directory
(portable dataset dirs) unless absolute (durable machine-local bulk).

Vision archives require transform v2 (causal close availability, explicit
absent funding); v1 derivations (close-at-open lookahead) fail closed.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import tomllib
from pathlib import Path
from typing import Any, Iterator

__all__ = ["DatasetHandle", "open_dataset", "verify_dataset"]

_HEARTBEAT_IDLE_MS = 1000
_TRANSFORM_VERSION = 2
_STREAM_BATCH_ROWS = 65536


def open_dataset(toml: str | Path) -> "DatasetHandle":
    """Open a frozen-dataset manifest; raises on unknown kind/version."""
    path = Path(toml)
    manifest = tomllib.loads(path.read_bytes().decode("utf-8"))
    return DatasetHandle(path, manifest)


def verify_dataset(handle: "DatasetHandle") -> list[str]:
    """Check every manifest ``local`` file present and hash-matching.

    Vision sources verify ``derived_sha256`` (source archives were verified
    at freeze/resume time); captured runs verify ``sha256`` (the file
    itself). Returns problem descriptions; empty means verified.
    """
    problems: list[str] = []
    for entry in handle.manifest.get("source", []):
        local = entry.get("local", "")
        label = entry.get("day") or entry.get("month") or entry.get("file") or local
        if not local:
            problems.append(f"{entry.get('symbol', '?')}/{label}: no local path")
            continue
        resolved = handle._resolve(local)
        if not resolved.exists():
            problems.append(f"{entry.get('symbol', '?')}/{label}: missing {local}")
            continue
        want = entry.get("derived_sha256") or entry.get("sha256")
        if not want:
            problems.append(f"{entry.get('symbol', '?')}/{label}: no hash recorded")
            continue
        digest = hashlib.sha256()
        with open(resolved, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        if digest.hexdigest() != want:
            problems.append(f"{entry.get('symbol', '?')}/{label}: hash mismatch for {local}")
    return problems


class DatasetHandle:
    """Handle over one frozen manifest (offline; streaming reads)."""

    def __init__(self, toml_path: Path, manifest: dict[str, Any]) -> None:
        self.toml_path = toml_path
        self.manifest = manifest
        dataset = manifest.get("dataset", {})
        kind = dataset.get("kind")
        if kind not in ("vision-archive", "captured-runs"):
            raise ValueError(f"unknown dataset kind: {kind!r}")
        if dataset.get("manifest_version") != 1:
            raise ValueError("unsupported manifest_version (want 1)")
        self.kind = kind
        if kind == "vision-archive":
            transform = dataset.get("transform_version")
            if transform != _TRANSFORM_VERSION:
                raise ValueError(
                    f"stale vision transform v{transform} (want v{_TRANSFORM_VERSION}): "
                    "rebuild with prepare_benchmark_30d.py; v1 minute closes "
                    "carry lookahead and v1 funding invents zeros")
        self._sha: str | None = None

    # -- manifest-level -------------------------------------------------
    def manifest_sha(self) -> str:
        """sha256 of the manifest TOML bytes (run fingerprint input)."""
        if self._sha is None:
            self._sha = hashlib.sha256(self.toml_path.read_bytes()).hexdigest()
        return self._sha

    def coverage(self) -> dict[str, Any]:
        """Per-source inventory + gaps from the manifest (stats locals, no reads)."""
        sources = []
        for entry in self.manifest.get("source", []):
            local = entry.get("local", "")
            resolved = self._resolve(local) if local else None
            sources.append({**entry, "local_exists": bool(resolved and resolved.exists())})
        return {
            "dataset": self.manifest.get("dataset", {}).get("name"),
            "kind": self.kind,
            "manifest_sha": self.manifest_sha(),
            "transform_version": self.manifest.get("dataset", {}).get(
                "transform_version"),
            "sources": sources,
            "gaps": list(self.manifest.get("gap", [])),
            "filters": self.manifest.get("filters", {}),
        }

    def _resolve(self, local: str) -> Path:
        candidate = Path(local)
        if candidate.is_absolute():
            return candidate
        return (self.toml_path.parent / candidate)

    # -- event streams --------------------------------------------------
    def events(self, symbol: str, day: str) -> Iterator[dict[str, Any] | None]:
        """Normalized events for one symbol + UTC day, with None heartbeats.

        ``day`` is a ``YYYY-MM-DD`` UTC date. Each ``None`` marks one idle
        virtual second (B3); the session advances its virtual clock 1 s per
        ``None`` and ticks timers on every wake.
        """
        if self.kind == "vision-archive":
            yield from self._vision_events(symbol, day)
        else:
            yield from self._captured_events(symbol, day)

    # -- vision-archive ---------------------------------------------------
    def _vision_events(self, symbol: str, day: str) -> Iterator[dict[str, Any] | None]:
        streams = []
        for order, channel in enumerate(("aggTrade", "markPrice")):
            entry = self._vision_source(symbol, day, channel)
            if entry is None:
                continue  # channel missing for this symbol/day (manifest gap).
            streams.append(self._stream_parquet_channel(entry, symbol, channel,
                                                        order))
        merged = heapq.merge(*streams, key=lambda item: (item[0], item[1]))
        run_id = f"replay:{self.manifest_sha()[:8]}:{symbol}:{day}"
        seq = 0
        last_ts: int | None = None
        for ts, _, event in merged:
            if last_ts is not None:
                idle = last_ts + _HEARTBEAT_IDLE_MS
                while idle < ts:
                    yield None
                    idle += _HEARTBEAT_IDLE_MS
            seq += 1
            event["run_id"] = run_id
            event["seq"] = seq
            yield event
            last_ts = ts

    def _vision_source(self, symbol: str, day: str,
                       channel: str) -> dict[str, Any] | None:
        for entry in self.manifest.get("source", []):
            if (entry.get("symbol") == symbol and entry.get("day") == day
                    and entry.get("channel") == channel):
                return entry
        return None

    def _stream_parquet_channel(self, entry: dict[str, Any], symbol: str,
                                channel: str, order: int,
                                ) -> Iterator[tuple[int, int, dict[str, Any]]]:
        """Yield (ts, order, event) per row via bounded Parquet batch reads."""
        import pyarrow.parquet as pq

        streamer = pq.ParquetFile(str(self._resolve(entry["local"])))
        for batch in streamer.iter_batches(batch_size=_STREAM_BATCH_ROWS):
            cols = {name: batch.column(batch.schema.get_field_index(name)).to_pylist()
                    for name in batch.schema.names}
            n = batch.num_rows
            for i in range(n):
                ts = int(cols["ts_ms"][i])
                if channel == "aggTrade":
                    payload = {
                        "agg_id": int(cols["agg_id"][i]), "price": float(cols["price"][i]),
                        "qty": float(cols["qty"][i]),
                        "first_id": int(cols["first_id"][i]),
                        "last_id": int(cols["last_id"][i]),
                        "trade_ts_ms": ts,
                        "buyer_is_maker": bool(cols["buyer_is_maker"][i]),
                    }
                    venue_seq: int | None = int(cols["agg_id"][i])
                else:
                    rate = cols["funding_rate"][i]
                    payload = {
                        "mark": float(cols["mark"][i]),
                        "open_time": int(cols["open_time"][i]),
                        "close_time": int(cols["close_time"][i]),
                        "funding_rate": None if rate is None else float(rate),
                        "funding_status": str(cols["funding_status"][i]),
                        "next_funding_ms": int(cols["next_funding_ms"][i]),
                    }
                    venue_seq = None
                yield ts, order, {
                    "v": 1, "format": "cryptobot-events/1",
                    "input_class": "observed-archive", "source": "binance-vision",
                    "route": "market", "run_id": "", "seq": 0,
                    "channel": channel, "symbol": symbol,
                    "exchange_ts_ms": ts, "local_recv_ms": ts,
                    "local_mono_ns": ts * 1_000_000, "gap_kind": None,
                    "venue_seq": venue_seq, "payload": payload,
                }

    # -- captured-runs ----------------------------------------------------
    def _captured_events(self, symbol: str, day: str) -> Iterator[dict[str, Any] | None]:
        import datetime as _dt

        start = _dt.datetime.strptime(day, "%Y-%m-%d").replace(
            tzinfo=_dt.timezone.utc).timestamp() * 1000
        end = start + 86_400_000
        run_id = f"replay:{self.manifest_sha()[:8]}:{symbol}:{day}"
        seq = 0
        last_ts: int | None = None
        for entry in self.manifest.get("source", []):
            if symbol not in entry.get("symbols", []):
                continue
            with open(self._resolve(entry["local"]), encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    if record.get("symbol") != symbol:
                        continue
                    ts = int(record.get("exchange_ts_ms")
                             or record.get("local_recv_ms") or 0)
                    if not (start <= ts < end):
                        continue
                    if last_ts is not None:
                        idle = last_ts + _HEARTBEAT_IDLE_MS
                        while idle < ts:
                            yield None
                            idle += _HEARTBEAT_IDLE_MS
                    seq += 1
                    record["run_id"] = run_id
                    record["seq"] = seq
                    yield record
                    last_ts = ts
