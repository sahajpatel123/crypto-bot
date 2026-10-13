"""Shared portfolio backtest harness (Worker 1, Q-007, B6).

Runs each BASE strategy separately + the combined bot + a cash reference
through the manager ``Session`` path (strategies → selector → risk →
Nautilus engine → ledger → store). One account policy per comparison; all
cooldowns, one-position, expiry, sizing, margin, exits, daily pauses and
protection are enforced BY Session — this module never scores in parallel.

Frozen splits (30-day benchmark day indices): dev 1–15, validation 16–22,
test 23–30. Each (arm-set, split) cell is a FRESH Session run, so no
position, cooldown, or holding window crosses a split boundary (full
purge); every run warms causally on its own split prefix. Test is scored
ONCE: rerunning a completed test split is refused (archive first).

Dataset consumption codes against B5 (``events(symbol, day)``,
``coverage()``, ``manifest_sha()``); E-008 swaps in without harness
changes. Until then the frozen ``synth_benchmark`` datasets run here,
labeled ``synthetic-benchmark``. Quote-less days use the
``research-spread-profile`` (see ``research/spread.py``) with sensitivity
reruns; S5 stays ineligible there with precise reasons.

Command: ``python -m cryptobot.research.backtest --dataset synth_quotes
--out <dir> --config configs/paper.toml``.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path
from typing import Any, Protocol

DEV_DAYS = tuple(range(1, 16))
VAL_DAYS = tuple(range(16, 23))
TEST_DAYS = tuple(range(23, 31))
SPLITS = {"dev": DEV_DAYS, "validation": VAL_DAYS, "test": TEST_DAYS}
ARM_SETS = {
    "S1": ("S1",), "S2": ("S2",), "S3": ("S3",), "S4": ("S4",),
    "S5": ("S5",), "COMBINED": ("S1", "S2", "S3", "S4", "S5"), "CASH": (),
}
FILTER_LABEL = "frozen-assumed"
FROZEN_FILTERS = {
    # symbol -> tick/step/min-notional/precisions (labeled assumption, NOT
    # venue facts; E-008 supplies historical filters for real datasets).
    "BTCUSDT": {"tick_size": 0.01, "step_size": 0.001, "min_notional": 0.0,
                "price_precision": 2, "size_precision": 3},
    "ETHUSDT": {"tick_size": 0.01, "step_size": 0.001, "min_notional": 0.0,
                "price_precision": 2, "size_precision": 3},
    "XRPUSDT": {"tick_size": 0.0001, "step_size": 0.1, "min_notional": 0.0,
                "price_precision": 4, "size_precision": 1},
}
TEST_MARKER = "test-COMPLETED.json"

__all__ = [
    "ARM_SETS",
    "DEV_DAYS",
    "FROZEN_FILTERS",
    "MECHANISM_SPLIT",
    "SPLITS",
    "TEST_DAYS",
    "VAL_DAYS",
    "DatasetHandle",
    "OverlapDedup",
    "PILOT_SYMBOLS",
    "assemble_split_capture",
    "build_partition",
    "compare_runs",
    "curve_signature",
    "day_events_for",
    "day_has_quotes",
    "day_ids_for",
    "fills_signature",
    "filters_for",
    "main",
    "preflight",
    "prepare_split_capture",
    "run_cell",
    "run_comparison",
]


class DatasetHandle(Protocol):
    """B5 reader surface (E-008 implements; synth doubles it for trial)."""

    def events(self, symbol: str, day): ...
    def coverage(self) -> dict: ...
    def manifest_sha(self) -> str: ...


MECHANISM_SPLIT = "mechanism"  # all available days, one run, labeled proof
DEDUP_WINDOW_MS = 60_000  # overlap dupes sort adjacently; bounds the cache
DEDUP_CONFLICT_EXAMPLES = 5


def day_ids_for(dataset: DatasetHandle) -> tuple:
    """Ordered day ids: synth ints, vision IST dates, captured UTC dates."""
    if hasattr(dataset, "days"):
        return tuple(dataset.days())  # type: ignore[no-any-return]
    manifest = dataset.manifest  # type: ignore[attr-defined]
    info = manifest.get("dataset", {})
    if dataset.kind == "vision-archive":  # type: ignore[attr-defined]
        start, end = info["window_ist"]
        return _ist_range(start, end)
    days: set[str] = set()
    for entry in manifest.get("source", []):
        lo, hi = entry.get("ts_min_ms"), entry.get("ts_max_ms")
        if lo is None or hi is None:
            continue
        days.update(_utc_range(lo, hi))
    if not days:
        raise ValueError("no day coverage derivable from manifest")
    return tuple(sorted(days))


def _ist_range(start: str, end: str) -> tuple[str, ...]:
    """Inclusive IST date list (YYYY-MM-DD)."""
    import datetime as _dt

    lo = _dt.date.fromisoformat(start)
    hi = _dt.date.fromisoformat(end)
    out = []
    day = lo
    while day <= hi:
        out.append(day.isoformat())
        day += _dt.timedelta(days=1)
    return tuple(out)


def _utc_range(lo_ms: int, hi_ms: int) -> set[str]:
    import datetime as _dt

    out = set()
    day = _dt.datetime.fromtimestamp(lo_ms / 1000, tz=_dt.timezone.utc).date()
    end = _dt.datetime.fromtimestamp(hi_ms / 1000, tz=_dt.timezone.utc).date()
    while day <= end:
        out.add(day.isoformat())
        day += _dt.timedelta(days=1)
    return out


def _ist_window_ms(ist_day: str) -> tuple[int, int]:
    """IST calendar day as a UTC half-open [lo, hi) ms window."""
    import datetime as _dt

    lo = (_dt.datetime.fromisoformat(f"{ist_day}T00:00:00+05:30").timestamp()
          * 1000)
    return int(lo), int(lo + 86_400_000)


def day_events_for(dataset: DatasetHandle, symbol: str,
                   day_id) -> tuple[list[dict], dict]:
    """Day's normalized events (heartbeats dropped; gaps kept by ts).

    Returns (events, day_info). Raises when the day has no usable source.
    """
    if hasattr(dataset, "days"):
        events = [e for e in dataset.events(symbol, day_id) if e is not None]
        return events, {"day": day_id, "calendar": "synthetic-compressed"}
    manifest = dataset.manifest  # type: ignore[attr-defined]
    kind = dataset.kind  # type: ignore[attr-defined]
    if kind == "vision-archive":
        import datetime as _dt

        lo, hi = _ist_window_ms(day_id)
        utc_days = sorted(_utc_range(lo, hi - 1))
        events = []
        for utc_day in utc_days:
            for e in dataset.events(symbol, utc_day):
                if e is None:
                    continue
                ts = int(e["exchange_ts_ms"])
                if lo <= ts < hi:
                    events.append(e)
        return events, {"day": day_id, "calendar": "IST",
                        "utc_days": utc_days,
                        "window_utc_ms": [lo, hi]}
    events = [e for e in dataset.events(symbol, day_id) if e is not None]
    return events, {"day": day_id, "calendar": "UTC"}


def _entry_symbols(entry: dict) -> list[str]:
    if entry.get("symbols"):
        return list(entry["symbols"])
    if entry.get("symbol"):
        return [entry["symbol"]]
    return []


def _entry_channels(entry: dict) -> list[str]:
    if entry.get("channels"):
        return list(entry["channels"])
    if entry.get("channel"):
        return [entry["channel"]]
    return []


def day_has_quotes(dataset: DatasetHandle, symbol: str, day_id) -> bool:
    """Manifest-based bookTicker expectation for one symbol-day.

    Day-scoped (Q-008 fix): vision matches day-level entries whose UTC
    day falls in the IST window; captured matches runs whose channels
    include bookTicker and whose time range overlaps the day. Assembly
    records OBSERVED per-day quote evidence separately; a mismatch
    between expected and observed is data information, not an error.
    """
    if hasattr(dataset, "days"):
        for d in dataset.coverage()["days"]:
            if d["day"] == day_id:
                return bool(d.get("quotes_observed", False))
        return False
    manifest = dataset.manifest  # type: ignore[attr-defined]
    kind = dataset.kind  # type: ignore[attr-defined]
    if kind == "vision-archive":
        lo, hi = _ist_window_ms(day_id)
        want_utc = _utc_range(lo, hi - 1)
        for entry in manifest.get("source", []):
            if symbol not in _entry_symbols(entry):
                continue
            if entry.get("day") not in want_utc:
                continue
            if "bookTicker" in _entry_channels(entry):
                return True
        return False
    import datetime as _dt

    start = _dt.datetime.strptime(day_id, "%Y-%m-%d").replace(
        tzinfo=_dt.timezone.utc).timestamp() * 1000
    end = start + 86_400_000
    for entry in manifest.get("source", []):
        if symbol not in _entry_symbols(entry):
            continue
        if "bookTicker" not in _entry_channels(entry):
            continue
        lo, hi = entry.get("ts_min_ms"), entry.get("ts_max_ms")
        if lo is None or hi is None:
            return True  # channels known, range unknown: expect quotes
        if lo < end and hi >= start:
            return True
    return False


PARTITION_VERSION = "bt-partition-v1"


def _partition_source_streams(dataset, symbol: str, day_id):
    """Ordered per-source event iterators for one day×symbol (lazy).

    Vision IST day: one stream per covered UTC day (handle order).
    Captured UTC day: one stream per manifest file (file order).
    Synth day: the single generated stream. Heartbeats (None) dropped;
    gaps survive via timestamps.
    """
    if hasattr(dataset, "days"):
        yield (e for e in dataset.events(symbol, day_id) if e is not None)
        return
    kind = dataset.kind
    if kind == "vision-archive":
        lo, hi = _ist_window_ms(day_id)
        for utc_day in sorted(_utc_range(lo, hi - 1)):
            yield _vision_utc_stream(dataset, symbol, utc_day, lo, hi)
        return
    import datetime as _dt

    start = _dt.datetime.strptime(day_id, "%Y-%m-%d").replace(
        tzinfo=_dt.timezone.utc).timestamp() * 1000
    end = start + 86_400_000
    for entry in dataset.manifest.get("source", []):
        if symbol not in _entry_symbols(entry):
            continue
        local = entry.get("local", "")
        if not local:
            continue
        path = Path(local)
        if not path.is_absolute():
            path = dataset.toml_path.parent / path
        if not path.exists():
            continue
        yield _captured_file_stream(path, symbol, start, end)


def _vision_utc_stream(dataset, symbol: str, utc_day: str, lo: int, hi: int):
    for e in dataset.events(symbol, utc_day):
        if e is None:
            continue
        ts = int(e["exchange_ts_ms"])
        if lo <= ts < hi:
            yield e


def _captured_file_stream(path: Path, symbol: str, start: float, end: float):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("symbol") != symbol:
                continue
            ts = int(record.get("exchange_ts_ms")
                     or record.get("local_recv_ms") or 0)
            if start <= ts < end:
                yield record


def _merge_key(event: dict, stream_idx: int) -> tuple:
    # Stable ties: (ts, channel-string, stream order). Matches the legacy
    # global sort for same inputs (stable by construction order).
    return (int(event["exchange_ts_ms"]), str(event.get("channel", "")),
            stream_idx)


def _heap_merge(streams):
    """Lazily merge ordered streams (bounded: one head per stream)."""
    import heapq

    heap: list[tuple] = []
    for idx, stream in enumerate(streams):
        try:
            first = next(stream)
        except StopIteration:
            continue
        heapq.heappush(heap, (_merge_key(first, idx), idx, first, stream))
    while heap:
        _, idx, event, stream = heapq.heappop(heap)
        yield event
        try:
            nxt = next(stream)
        except StopIteration:
            continue
        heapq.heappush(heap, (_merge_key(nxt, idx), idx, nxt, stream))


def build_partition(dataset: DatasetHandle, symbol: str, day_id,
                    path, *, force: bool = False) -> dict:
    """Stream one day×symbol of RAW events into an ordered partition file.

    Checkpointed: rebuild skipped when the sidecar matches (dataset sha +
    version + symbol + day + file size). Returns partition stats incl.
    observed channels and sha256. RAW means pre-spread: sensitivity and
    arm-set runs share partitions and apply spread at assembly.
    """
    import hashlib

    path = Path(path)
    sidecar = path.with_suffix(".json")
    dataset_sha = dataset.manifest_sha()
    if not force and sidecar.exists() and path.exists():
        try:
            cached = json.loads(sidecar.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            cached = {}
        if (cached.get("partition_version") == PARTITION_VERSION
                and cached.get("dataset_manifest_sha") == dataset_sha
                and cached.get("symbol") == symbol
                and cached.get("day") == day_id
                and cached.get("n_bytes") == path.stat().st_size):
            cached["reused"] = True
            return cached
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    channels: dict[str, int] = {}
    n_events = 0
    first_ts: int | None = None
    last_ts: int | None = None
    streams = list(_partition_source_streams(dataset, symbol, day_id))
    with open(path, "w", encoding="utf-8") as fh:
        for event in _heap_merge(streams):
            line = json.dumps(event, sort_keys=True) + "\n"
            fh.write(line)
            digest.update(line.encode("utf-8"))
            n_events += 1
            channels[event.get("channel", "?")] = \
                channels.get(event.get("channel", "?"), 0) + 1
            ts = int(event["exchange_ts_ms"])
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)
    stats = {
        "partition_version": PARTITION_VERSION,
        "dataset_manifest_sha": dataset_sha,
        "dataset_id": _dataset_id(dataset),
        "symbol": symbol, "day": day_id,
        "path": str(path), "n_events": n_events,
        "n_bytes": path.stat().st_size, "sha256": digest.hexdigest(),
        "channels": channels, "first_ts_ms": first_ts,
        "last_ts_ms": last_ts, "reused": False,
    }
    sidecar.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return stats


def filters_for(dataset: DatasetHandle, symbol: str) -> tuple[dict, str]:
    """Instrument filters: manifest-first, frozen-assumed fallback.

    Returns (filter dict, origin label). Manifest filters carry venue
    tick/step/min facts; the fallback is labeled, never venue truth.
    """
    cov = dataset.coverage()
    manifest_syms = (cov.get("filters") or {}).get("symbols", {})
    if symbol in manifest_syms:
        m = manifest_syms[symbol]
        return {
            "tick_size": float(m["tick"]), "step_size": float(m["step"]),
            "min_qty": float(m.get("min_qty", 0.0)),
            "min_notional": float(m.get("min_notional", 0.0)),
            "price_precision": _decimals(m["tick"]),
            "size_precision": _decimals(m["step"]),
        }, "manifest-frozen"
    if symbol in FROZEN_FILTERS:
        return dict(FROZEN_FILTERS[symbol]), FILTER_LABEL
    raise ValueError(f"no filters for {symbol!r} (manifest nor fallback)")


def _decimals(value: float) -> int:
    text = repr(float(value))
    if "e" in text or "E" in text:
        return max(0, -int(text.split("e")[-1].replace("E", "")))
    return len(text.split(".")[1]) if "." in text else 0


def preflight(dataset: DatasetHandle, symbols: tuple[str, ...],
              day_ids: tuple) -> None:
    """Fail fast with a precise error when event data is absent locally."""
    if hasattr(dataset, "days"):
        return  # synthetic: always generatable
    cov = dataset.coverage()
    missing = [s for s in cov["sources"]
               if not s.get("local_exists", False)]
    if not missing:
        return
    have = len(cov["sources"]) - len(missing)
    raise FileNotFoundError(
        f"dataset {cov.get('dataset')}: {len(missing)}/{len(cov['sources'])} "
        f"sources missing locally ({have} present); fetch/preparation is "
        f"W2-owned. Availability fallback: frozen synthetic 30d benchmark "
        f"(labeled) for the split procedure; captured runs for mechanism.")


def _dataset_id(dataset: DatasetHandle) -> str:
    direct = getattr(dataset, "dataset_id", None)
    if direct is not None:
        return str(direct)
    name = dataset.coverage().get("dataset")  # real handle: manifest name
    return str(name) if name else "external"


def _event_identity(event: dict) -> str:
    """Venue event identity for dedup ("" when the event carries none).

    Payload venue ids first (agg_id/trade_id/update ids), then the
    top-level venue_seq many feeds carry outside the payload. Our own
    seq is NEVER identity: assembly renumbers it, and overlapping
    captures number the same venue event differently.
    """
    payload = event.get("payload", {})
    for key in ("agg_id", "trade_id", "id", "update_id", "first_update_id",
                "last_update_id"):
        if payload.get(key) is not None:
            return f"{key}={payload[key]}"
    if payload.get("first_id") is not None:
        return f"ids={payload.get('first_id')}-{payload.get('last_id')}"
    venue_seq = event.get("venue_seq")
    if venue_seq:  # None/0 = "no sequence" on every known feed
        return f"venue_seq={venue_seq}"
    return ""


class OverlapDedup:
    """Bounded overlap deduplicator with conflict detection (Q-008).

    Fingerprint = venue(source) + symbol + channel + timestamp + event
    identity, so different symbols' identical payloads never collapse.
    Identity = payload venue ids, else top-level venue_seq (never our
    renumbered seq). Same fingerprint + same body → drop (counted).
    Same fingerprint + different body WITH identity → conflict
    (recorded, keep-first). Same fingerprint + different body WITHOUT
    identity (repeated quote updates in one millisecond) → both kept,
    no conflict: legitimate repeats are preserved. The cache holds
    only a trailing time window (overlap duplicates sort adjacently),
    keeping memory bounded.
    """

    def __init__(self, window_ms: int = DEDUP_WINDOW_MS) -> None:
        from collections import deque

        self._window_ms = window_ms
        self._seen: dict[str, str] = {}
        self._order: deque[tuple[int, str]] = deque()
        self.dropped = 0
        self.conflicts = 0
        self.examples: list[dict] = []

    def fingerprint(self, event: dict) -> str:
        return "|".join((str(event.get("source", "")),
                         str(event.get("symbol", "")),
                         str(event.get("channel", "")),
                         str(int(event.get("exchange_ts_ms", 0))),
                         _event_identity(event)))

    def check(self, event: dict) -> str:
        """Classify one time-ordered event: keep | drop | conflict-drop."""
        ts = int(event["exchange_ts_ms"])
        while self._order and self._order[0][0] < ts - self._window_ms:
            self._seen.pop(self._order.popleft()[1], None)
        fp = self.fingerprint(event)
        body = json.dumps(event.get("payload", {}), sort_keys=True)
        prev = self._seen.get(fp)
        if prev is None:
            self._seen[fp] = body
            self._order.append((ts, fp))
            return "keep"
        if prev == body:
            self.dropped += 1
            return "drop"
        if _event_identity(event):
            self.conflicts += 1
            if len(self.examples) < DEDUP_CONFLICT_EXAMPLES:
                self.examples.append({"fingerprint": fp, "kept": prev,
                                      "dropped": body})
            return "conflict-drop"
        return "keep"


def _partition_path(partition_dir: Path, dataset: DatasetHandle,
                    symbol: str, day_id) -> Path:
    safe = f"{_dataset_id(dataset)}_{symbol}_{day_id}".replace("/", "_")
    return partition_dir / f"{safe}.jsonl"


def _partition_events(path: Path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def assemble_split_capture(partitions: list[dict], split: str, out_dir,
                           symbols: tuple[str, ...],
                           dataset: DatasetHandle,
                           spread_profile=None,
                           max_events: int | None = None) -> dict:
    """Merge checkpointed RAW partitions into one replay capture (Q-008).

    Streaming: per-partition spread is applied with iter_with_spread
    (single pass, one-window buffer), capture-order is a bounded
    heap-merge of partitions (one head each), and max_events stops the
    merge early — a causal prefix without reading the rest. Peaks at
    O(partitions) held events + one spread window per partition.
    """
    from .spread import PROFILE_ID, iter_with_spread, profile_spread_bps

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    streams = []
    day_manifest = []
    for part in partitions:
        symbol, day = part["symbol"], part["day"]
        raw = _partition_events(Path(part["path"]))
        expected_quotes = day_has_quotes(dataset, symbol, day)
        applied = None
        if not expected_quotes and spread_profile is not None:
            applied = profile_spread_bps(spread_profile, symbol)
            raw = iter_with_spread(raw, symbol, applied)
        streams.append(raw)
        day_manifest.append({
            "day": day, "symbol": symbol,
            "quotes_expected": expected_quotes,
            "quotes_observed_channels": part.get("channels", {}),
            "spread_profile": PROFILE_ID if applied else None,
            "spread_bps_assumed": applied,
            "partition": {k: part[k] for k in
                          ("path", "sha256", "n_events", "n_bytes",
                           "reused", "first_ts_ms", "last_ts_ms")
                          if k in part},
            "n_emitted": 0,
        })
    dedup = OverlapDedup()
    last_agg: dict[str, int] = {}
    n_events = 0
    emitted_per_part = [0] * len(partitions)
    with open(out / "events.jsonl", "w", encoding="utf-8") as fh:
        for event in _heap_merge_indexed(streams):
            merged, part_idx = event
            if dedup.check(merged) != "keep":
                continue
            n_events += 1
            merged["seq"] = n_events
            merged["local_mono_ns"] = n_events
            if merged.get("channel") == "aggTrade":
                agg = int(merged["payload"]["agg_id"])
                sym = str(merged.get("symbol", ""))
                if sym in last_agg and agg <= last_agg[sym]:
                    raise ValueError(
                        f"non-monotonic agg_id on {sym} at seq {n_events}")
                last_agg[sym] = agg
            fh.write(json.dumps(merged) + "\n")
            emitted_per_part[part_idx] += 1
            if max_events is not None and n_events >= max_events:
                break  # causal prefix: unread tail never touched
    truncated = max_events is not None and n_events >= max_events
    for entry, emitted in zip(day_manifest, emitted_per_part):
        entry["n_emitted"] = emitted
    manifest = {
        "prep_version": "streaming-v1",
        "split": split, "days": sorted({p["day"] for p in partitions}),
        "dataset_id": _dataset_id(dataset),
        "dataset_manifest_sha": dataset.manifest_sha(),
        "symbols": list(symbols),
        "n_events": n_events,
        "deduped_repeats": dedup.dropped,
        "conflicting_duplicates": dedup.conflicts,
        "conflict_examples": dedup.examples,
        "truncated_prefix": truncated,
        "max_events": max_events,
        "purge": "fresh Session per cell; no cross-split state",
        "warmup": "causal, on split prefix (config warmup_bars)",
        "day_manifest": day_manifest,
    }
    (out / "day_manifest.json").write_text(json.dumps(manifest, indent=2),
                                           encoding="utf-8")
    return manifest


def _heap_merge_indexed(streams):
    """Heap-merge tagging each event with its source stream index."""
    import heapq

    heap: list[tuple] = []
    for idx, stream in enumerate(streams):
        try:
            first = next(stream)
        except StopIteration:
            continue
        heapq.heappush(heap, (_merge_key(first, idx), idx, first, stream))
    while heap:
        _, idx, event, stream = heapq.heappop(heap)
        yield event, idx
        try:
            nxt = next(stream)
        except StopIteration:
            continue
        heapq.heappush(heap, (_merge_key(nxt, idx), idx, nxt, stream))


def prepare_split_capture(dataset: DatasetHandle, split: str, out_dir,
                          symbols: tuple[str, ...],
                          spread_profile=None,
                          max_events: int | None = None,
                          partition_dir=None) -> dict:
    """Build (checkpointed partitions) + assemble (streaming) a capture."""
    day_ids = day_ids_for(dataset)
    if split == MECHANISM_SPLIT:
        days = day_ids
    elif split in SPLITS:
        positions = SPLITS[split]
        if len(day_ids) < max(positions):
            raise ValueError(
                f"dataset has {len(day_ids)} days; split {split!r} needs "
                f"{max(positions)} (use {MECHANISM_SPLIT} for short data)")
        days = tuple(day_ids[i - 1] for i in positions)
    else:
        raise ValueError(f"unknown split {split!r}")
    preflight(dataset, symbols, days)
    parts = (Path(partition_dir) if partition_dir is not None
             else Path(out_dir) / "_partitions")
    partitions = [build_partition(dataset, symbol, day,
                                  _partition_path(parts, dataset,
                                                  symbol, day))
                  for day in days for symbol in symbols]
    return assemble_split_capture(partitions, split, out_dir, symbols,
                                  dataset, spread_profile, max_events)


def run_cell(base_config_path, capture_dir, strategies: tuple[str, ...],
             run_dir, run_id: str, symbols: tuple[str, ...],
             instrument_filters: dict[str, dict] | None = None,
             filter_origin: str = FILTER_LABEL,
             filters_asof_utc=None,
             require_round: str | None = None,
             require_config: str | None = None,
             round_params: str | None = None) -> dict:
    """One (arm-set, split) cell: fresh Session + Nautilus engine, replay."""
    from cryptobot.adapters import NautilusPaperEngine
    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session
    from cryptobot.app.store import RunStore

    run_path = Path(run_dir)
    if run_path.exists():
        for child in sorted(run_path.rglob("*"), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
    run_path.mkdir(parents=True, exist_ok=True)
    cfg = load_config(base_config_path)
    cfg = dataclasses.replace(cfg, strategies_enabled=tuple(strategies),
                              storage_dir=str(run_path))
    if require_round:
        from pathlib import Path as _Path

        from .allowlist import AllowlistError as _AllowErr
        from .allowlist import verify_effective as _verify_cell
        params = round_params or str(
            _Path(require_round).with_suffix("")) + ".params.json"
        report = _verify_cell(
            list(cfg.strategies_enabled), cfg.strategies_arms,
            list(cfg.strategies_arms_allowlist)
            if cfg.strategies_arms_allowlist is not None else None,
            require_round, params, only_config=require_config,
            label=f"{run_id}:{base_config_path}")
        if not report["ok"]:
            raise _AllowErr(
                f"cell {run_id} disagrees with {require_round}: "
                f"extra={report['extra_arms']} "
                f"missing={report['missing_arms']} "
                f"param_drift={sorted(report['param_diffs'])}")
    store = RunStore(run_path / "store.db")
    from datetime import datetime, timezone
    _EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
    now_cell: dict[str, Any] = {"now": lambda: _EPOCH}
    # Engine delays follow the base config (production parity). E-008's
    # rework (GTC trade-cross, valuation-only marks) resolved the Q-007
    # mark-quote partial-fill pathology, verified by this harness.
    engine = NautilusPaperEngine(
        outcome_sink=None, taker_bps=cfg.taker_bps,
        now_utc=lambda: now_cell["now"](),
        submit_delay_ms=cfg.submit_delay_ms,
        fill_delay_ms=max(1, cfg.fill_delay_ms),
        journal_path=run_path / "engine_journal.jsonl",
        starting_balance_usdt=cfg.paper_capital_usdt)
    filters = instrument_filters or {}
    for symbol in symbols:
        filt = filters.get(symbol) or FROZEN_FILTERS.get(symbol.upper())
        if filt is None:
            raise ValueError(f"no filters for {symbol!r}")
        engine.add_instrument(symbol, price_precision=filt["price_precision"],
                              size_precision=filt["size_precision"],
                              tick_size=filt["tick_size"],
                              step_size=filt["step_size"],
                              min_qty=filt.get("min_qty", 0.0),
                              min_notional=filt["min_notional"])
    session = Session(cfg, store, run_path, run_id, engine=engine)
    # Risk sizes on the same filters the engine enforces (F3: no dust).
    known = instrument_filters or {}
    session.arm_replay_filters(
        {s: (known.get(s) or FROZEN_FILTERS.get(s.upper(), {}))
         for s in symbols}, filter_origin, asof_utc=filters_asof_utc)
    now_cell["now"] = session.now_utc
    # Fills must reach risk/ledger or positions never exist economically
    # (E-007 runtime binds the same sink on the live path).
    engine.bind_sink(session.policy)
    capture = Path(capture_dir)
    with open(capture / "events.jsonl", encoding="utf-8") as _fh:
        input_class = json.loads(_fh.readline())["input_class"]
    report = session.run_replay(capture, expect_class=input_class)
    report["filter_profile"] = {"label": filter_origin,
                                "filters": {s: filters.get(s) or
                                            FROZEN_FILTERS.get(s.upper())
                                            for s in symbols}}
    (run_path / "report.json").write_text(json.dumps(report, indent=2),
                                          encoding="utf-8")
    return {"report": report, "run_dir": str(run_path),
            "journal": str(run_path / "engine_journal.jsonl")}


def _normalize_id(value: Any) -> Any:
    # Nautilus client ids embed a uuid8 suffix (B1 allows varying display
    # ids); the seq prefix is the stable part. Reservation ids are stable.
    if isinstance(value, str) and value.rsplit("-", 1)[-1].strip():
        head, _, tail = value.rpartition("-")
        if head and len(tail) == 8 and all(
                c in "0123456789abcdef" for c in tail):
            return head
    return value


def _journal_records(journal_path) -> list[dict]:
    path = Path(journal_path)
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def fills_signature(journal_path) -> list[tuple]:
    """Normalized fills in journal order: (ts, side, qty, price, fee)."""
    sig = []
    for rec in _journal_records(journal_path):
        if rec.get("event") != "fill":
            continue
        d = rec["detail"]
        sig.append((rec["ts_utc"], _normalize_id(d.get("client_id")),
                    d.get("venue_side"), d.get("qty"), d.get("price"),
                    d.get("fee")))
    return sig


def curve_signature(journal_path) -> list[tuple]:
    """Per-fill cumulative (fee, signed notional): the realized curve."""
    cum_fee = 0.0
    cum_not = 0.0
    curve = []
    for rec in _journal_records(journal_path):
        if rec.get("event") != "fill":
            continue
        d = rec["detail"]
        sgn = 1.0 if str(d.get("venue_side", "")).upper().startswith("B") \
            else -1.0
        cum_fee += float(d.get("fee", 0.0))
        cum_not += sgn * float(d.get("qty", 0.0)) * float(d.get("price", 0.0))
        curve.append((rec["ts_utc"], round(cum_fee, 8), round(cum_not, 8)))
    return curve


def _metrics_signature(report: dict) -> dict:
    return {
        "closing_equity": report["closing_equity"],
        "net_return_pct": report["net_return_pct"],
        "paid_costs": report["paid_costs"],
        "funding_net": report["funding_net"],
        "realised": report["realised"],
        "intents_admitted": report["intents_admitted"],
        "events_seen": report["events_seen"],
        "reject_counts": report["reject_counts"],
    }


def compare_runs(report_a: dict, journal_a, report_b: dict, journal_b) -> dict:
    """Determinism diff: fills + curve + metrics identical?"""
    fills_a, fills_b = fills_signature(journal_a), fills_signature(journal_b)
    curve_a, curve_b = curve_signature(journal_a), curve_signature(journal_b)
    met_a, met_b = _metrics_signature(report_a), _metrics_signature(report_b)
    return {
        "fills_equal": fills_a == fills_b,
        "n_fills": len(fills_a),
        "curve_equal": curve_a == curve_b,
        "metrics_equal": met_a == met_b,
        "metric_diff": {k: [met_a[k], met_b[k]] for k in met_a
                        if met_a[k] != met_b[k]},
        "deterministic": fills_a == fills_b and curve_a == curve_b
                         and met_a == met_b,
    }


def run_comparison(dataset: DatasetHandle, out_dir, base_config_path,
                   symbols: tuple[str, ...], *,
                   splits: tuple[str, ...] = ("dev", "validation", "test"),
                   armsets: tuple[str, ...] = ("S1", "S2", "S3", "S4", "S5",
                                               "COMBINED", "CASH"),
                   spread_profile=None, sensitivity: bool = False,
                   max_events: int | None = None,
                   require_round: str | None = None,
                   require_config: str | None = None,
                   round_params: str | None = None) -> dict:
    """Frozen per-strategy + combined + cash comparison across splits."""
    from .spread import PROFILE_ID, sensitivity_spreads

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if "test" in splits and (out / TEST_MARKER).exists():
        raise RuntimeError(
            "test split already scored once; archive results before rerunning")
    unknown = [a for a in armsets if a not in ARM_SETS]
    if unknown:
        raise ValueError(f"unknown arm-sets: {unknown}")
    bad_splits = [s for s in splits if s not in (*SPLITS, MECHANISM_SPLIT)]
    if bad_splits:
        raise ValueError(f"unknown splits: {bad_splits}")
    resolved = {s: filters_for(dataset, s) for s in symbols}
    instrument_filters = {s: f for s, (f, _) in resolved.items()}
    origins = sorted({origin for _, origin in resolved.values()})
    filters_asof = None
    manifest = getattr(dataset, "manifest", None)
    if isinstance(manifest, dict):
        created = manifest.get("dataset", {}).get("created_utc")
        if created:
            from datetime import datetime
            filters_asof = datetime.fromisoformat(created)
    comparison: dict[str, Any] = {
        "dataset_id": _dataset_id(dataset),
        "dataset_manifest_sha": dataset.manifest_sha(),
        "symbols": list(symbols),
        "splits": list(splits),
        "armsets": list(armsets),
        "filter_profile": "+".join(origins),
        "engine_delays_ms": {"note": "base config values (production "
                                     "parity); E-008 GTC/valuation-only marks "
                                     "verified healthy by this harness"},
        "promotion_rule": "NONE - descriptive baseline; no tuning on any split",
        "cells": {},
        "s5_ineligibility": {},
        "sensitivity": {},
    }
    for split in splits:
        cap_dir = out / "captures" / split
        manifest = prepare_split_capture(dataset, split, cap_dir, symbols,
                                         spread_profile, max_events)
        spread_used = any(d["spread_bps_assumed"]
                          for d in manifest["day_manifest"])
        for armset in armsets:
            run_id = f"{comparison['dataset_id']}-{split}-{armset}"
            run_dir = out / "runs" / split / armset
            cell = run_cell(base_config_path, cap_dir, ARM_SETS[armset],
                            run_dir, run_id, symbols, instrument_filters,
                            "+".join(origins), filters_asof,
                            require_round=require_round,
                            require_config=require_config,
                            round_params=round_params)
            report = cell["report"]
            key = f"{armset}|{split}"
            comparison["cells"][key] = {
                **_metrics_signature(report),
                "n_fills": len(fills_signature(cell["journal"])),
                "run_dir": cell["run_dir"],
            }
            s5_reasons = {k: v for k, v in report["reject_counts"].items()
                          if "depth:" in k or "flow:" in k or "book:" in k}
            if s5_reasons:
                comparison["s5_ineligibility"][key] = {
                    "windows": sum(s5_reasons.values()),
                    "reasons": s5_reasons,
                }
            if sensitivity and spread_used and armset != "CASH":
                assert spread_profile is not None  # spread_used implies it
                for mult in sensitivity_spreads_for(
                        spread_profile, symbols):
                    if mult == 1.0:
                        continue
                    sens_cap = out / "captures" / f"{split}@spread{mult}x"
                    prepare_split_capture(
                        dataset, split, sens_cap, symbols,
                        _scaled_profile(spread_profile, mult), max_events)
                    run_dir_s = out / "runs" / f"{split}@spread{mult}x" / armset
                    run_id_s = f"{run_id}@spread{mult}x"
                    cell_s = run_cell(base_config_path, sens_cap,
                                      ARM_SETS[armset], run_dir_s, run_id_s,
                                      symbols, instrument_filters,
                                      "+".join(origins), filters_asof,
                                      require_round=require_round,
                                      require_config=require_config,
                                      round_params=round_params)
                    rep_s = cell_s["report"]
                    comparison["sensitivity"][f"{key}@spread{mult}x"] = {
                        "multiplier": mult,
                        "closing_equity": rep_s["closing_equity"],
                        "net_return_pct": rep_s["net_return_pct"],
                        "paid_costs": rep_s["paid_costs"],
                        "intents_admitted": rep_s["intents_admitted"],
                        "n_fills": len(fills_signature(cell_s["journal"])),
                        "run_dir": cell_s["run_dir"],
                    }
    if "test" in splits:
        (out / TEST_MARKER).write_text(json.dumps(
            {"test": "scored-once", "cells": sorted(
                k for k in comparison["cells"] if k.endswith("|test"))},
            indent=2), encoding="utf-8")
    (out / "comparison.json").write_text(json.dumps(comparison, indent=2),
                                         encoding="utf-8")
    return comparison


def sensitivity_spreads_for(spread_profile, symbols: tuple[str, ...]) -> dict:
    from .spread import sensitivity_spreads
    out: dict[float, dict] = {}
    for symbol in symbols:
        for mult, bps in sensitivity_spreads(spread_profile, symbol).items():
            out.setdefault(mult, {})[symbol] = bps
    return out


def _scaled_profile(spread_profile, mult: float):
    import dataclasses

    scaled = tuple((s, b * mult)
                   for s, b in spread_profile.per_symbol_bps)
    return dataclasses.replace(spread_profile,
                               default_bps=spread_profile.default_bps * mult,
                               per_symbol_bps=scaled)


PILOT_SYMBOLS = ("BTCUSDT", "ETHUSDT")


def _default_symbols(dataset) -> list[str]:
    """BTC+ETH pilot pair (Q-008): manifest-clipped, BTCUSDT fallback."""
    info = dataset.manifest.get("dataset", {})
    have = (info.get("symbols") or []) if isinstance(info, dict) else []
    if have:
        pair = [s for s in PILOT_SYMBOLS if s in have]
        return pair or [have[0]]
    return ["BTCUSDT"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Portfolio backtest harness")
    parser.add_argument("--dataset", required=True,
                        choices=["synth_quotes", "synth_noquotes",
                                 "captured", "benchmark-30d"])
    parser.add_argument("--out", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--splits", default="dev,validation,test")
    parser.add_argument("--armsets", default=",".join(ARM_SETS))
    parser.add_argument("--symbols", default=None,
                        help="comma-separated (default: dataset symbol)")
    parser.add_argument("--sensitivity", action="store_true",
                        help="spread sensitivity reruns (quote-less data)")
    parser.add_argument("--no-profile", action="store_true",
                        help="skip spread profile even on quote-less data")
    parser.add_argument("--max-events", type=int, default=None,
                        help="causal-prefix cap per split capture (labeled)")
    parser.add_argument("--require-round", default=None, metavar="ROUND_JSON",
                        help="W4-CORR: enforce frozen round registry "
                             "(arm allowlist + param fingerprints) against "
                             "--config before running; aborts on mismatch")
    parser.add_argument("--round-params", default=None, metavar="PARAMS_JSON",
                        help="frozen parameter file for --require-round "
                             "(default: <round>.params.json)")
    parser.add_argument("--require-config", default=None, metavar="CONFIG_ID",
                        help="with --require-round: gate against one "
                             "registry config only (single-arm cells)")
    args = parser.parse_args(argv)
    if args.require_round:
        from pathlib import Path as _Path

        from .allowlist import enforce as _enforce_round
        params = args.round_params or str(
            _Path(args.require_round).with_suffix("")) + ".params.json"
        report = _enforce_round(args.config, args.require_round, params,
                                only_config=args.require_config)
        print(f"round gate: {args.require_round} ok "
              f"arms={report['resolved_count']} "
              f"sha={report['live_fingerprint_sha']}")
    from .spread import SpreadProfile
    from .synth_benchmark import SYMBOL, SynthBenchmark

    if args.dataset in ("synth_quotes", "synth_noquotes"):
        dataset = SynthBenchmark(dataset_id=args.dataset)
        symbols = (SYMBOL,)
        want_profile = args.dataset == "synth_noquotes"
    else:
        from cryptobot.market_data.datasets import open_dataset
        dataset = open_dataset(
            f"datasets/{args.dataset.replace('-', '_')}.toml")
        symbols = tuple(s for s in (args.symbols or "").split(",") if s) \
            or tuple(_default_symbols(dataset))
        want_profile = True  # applied per-day only where quotes are absent
    profile = SpreadProfile() if (want_profile and not args.no_profile) \
        else None
    comparison = run_comparison(
        dataset, args.out, args.config, symbols,
        splits=tuple(s for s in args.splits.split(",") if s),
        armsets=tuple(a for a in args.armsets.split(",") if a),
        spread_profile=profile, sensitivity=args.sensitivity,
        max_events=args.max_events, require_round=args.require_round,
        require_config=args.require_config,
        round_params=args.round_params)
    n = len(comparison["cells"])
    print(f"{args.dataset}: {n} cells "
          f"({args.splits} x {args.armsets}) -> {args.out}/comparison.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
