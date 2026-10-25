"""D1 forward evaluator: run the frozen OI-flush rule and print its verdict.

Frozen specification: ``research/prereg/D1-oi-flush-reversal.md`` plus
``D1-amendment-1.md`` / ``D1-amendment-2.md`` (and any later ``D1-*.md``
amendment present).  Every threshold, grid cell, cost term and gate below is
*parsed out of those files* by :func:`load_rules`; this module does not restate
a frozen number, and a pattern that stops matching is a hard
:class:`PreregParseError`, never a silent default.  The SHA-256 of each file
is bound into every output document.

Protocol enforced here
----------------------
* **Forward only.**  The data root is the recorder's sealed chunk chain
  (``manifest.json`` + ``chunks/*.jsonl.gz``, chain-of-custody hashes).  Only
  forward-dated chunks are read.  The sealed holdout
  (``SPLIT.md``: ``[2024-01-01, 2026-10-18)``) is refused *structurally*:
  :func:`assert_not_sealed_path`, :func:`scan_store` and every record reader
  raise :class:`HoldoutRefusal` before any byte of a sealed chunk is decoded.
  There is no flag, environment variable or code path that opens one.
* **No substitution.**  D1 prices are 1m bar OPENs and its open interest is the
  venue's 5-minute OI; its funding is charged at settlements with an adverse
  imputation rule.  If the recorder does not carry a stream that can produce
  one of those, the evaluator prints ``INSUFFICIENT FORWARD DATA`` and names the
  missing stream instead of standing in a proxy (mid-price for a bar open, the
  premium index for a settled funding rate, two symbols for a 30-symbol
  universe).
* **No tuning.**  There is no parameter search, no cell added or removed, no
  symbol or year subset, and no code path that writes a verdict back into the
  data.  Stage 0 (event counts) runs before any forward price is read, exactly
  as the prereg orders it.

Verdicts
--------
``KILL``          the immediate-kill rule fired (max over cells of gross
                  expectancy minus 1x all-in cost is negative), or an
                  economic gate failed.
``FAIL_DEV``      an economic gate failed on a sample that is otherwise run.
``PASS_DEV``      all eight gates passed.  Not reachable from forward data:
                  gates 6 and 7 are frozen to the DEV calendar (months
                  2020-10..2023-12, years 2020..2023) and a month with no trade
                  counts as not positive, so a forward window can only ever
                  miss them.  That is reported as the gate's failure reason,
                  not papered over with an unregistered forward calendar.
``INSUFFICIENT_FORWARD_DATA``
                  the sample cannot produce a verdict yet: a required stream is
                  absent, or stage 0 is short of 300 events / 100 event days.
                  The first printed line is exactly ``INSUFFICIENT FORWARD
                  DATA`` and every shortfall is listed with what would fix it.

Deliberate scope cut, stated rather than hidden: the optional **maker-entry
diagnostic** variant is not implemented.  The prereg makes it diagnostic only,
ineligible for selection and unable to revive a ``KILL``, so its absence cannot
change any verdict; the output says so explicitly.

The diagnostic never touches orders, API keys or the gate: this is a read-only
research command over recorded public data.  Gate stays NO-GO.
"""

from __future__ import annotations

import argparse
import bisect
import calendar
import datetime as dt
import gzip
import hashlib
import itertools
import json
import math
import random
import re
import statistics
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from cryptobot.research import d1_trials

MIN_MS = 60_000
HOUR_MS = 3_600_000
DAY_MS = 86_400_000
STEP_MS = 5 * MIN_MS  # D1 time grid

REPO_ROOT = Path(__file__).resolve().parents[3]
PREREG_DIR = REPO_ROOT / "research/prereg"
OUTPUT_PATH = REPO_ROOT / "research/autopilot_d/forward/D1.json"

#: Record types that can carry a trade price.  A bar OPEN can be rebuilt from
#: the first trade in the minute, which is the venue's own price at that
#: instant, so this is the prereg's definition rather than a proxy.
PRICE_RECORD_TYPES = frozenset({"agg_trade", "trade"})
KLINE_RECORD_TYPES = frozenset({"kline", "kline_1m"})
OI_RECORD_TYPES = frozenset({"open_interest", "open_interest_hist"})
FUNDING_RECORD_TYPES = frozenset({"funding", "funding_rate", "funding_rate_settled"})
RANKING_RECORD_TYPES = frozenset({"kline_1d", "klines_1d"})

#: ``text -> int`` for the prereg's spelled-out traffic counts.
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


class D1Error(RuntimeError):
    """A D1 protocol violation; the evaluator refuses rather than guesses."""


class PreregParseError(D1Error):
    """A frozen value could not be read out of the preregistration text."""


class HoldoutRefusal(D1Error):
    """A path, chunk or record that would touch the sealed holdout."""


class StoreError(D1Error):
    """The recorder chunk chain is missing, incomplete or broken."""


# --------------------------------------------------------------------------
# 1. Frozen rules, parsed from the preregistration text
# --------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Cell:
    """One taker grid cell ``(W minutes, K sigma, H minutes hold)``."""

    w: int
    k: float
    h: int

    def __str__(self) -> str:  # noqa: D105 - trivial
        return f"(W={self.w},K={self.k:g},H={self.h})"


@dataclass(frozen=True)
class Rules:
    """Every frozen D1 constant, read from the preregistration files."""

    cells: tuple[Cell, ...]
    cell_count: int
    windows: tuple[int, ...]
    shocks: tuple[float, ...]
    holds: tuple[int, ...]
    oi_z_max: float
    sigma_lookback_days: int
    sigma_min_fraction: float
    universe_size: int
    universe_min_age_days: int
    universe_active_hhmm: tuple[int, int]
    metrics_lag_min: int
    entry_offset_min: int
    taker_fee_bps: float
    half_spread_bps: float
    slippage_base_bps: float
    slippage_shock_coef: float
    maker_fee_bps: float
    funding_hours: tuple[int, ...]
    funding_impute_days: int
    stress_multiple: int
    min_events: int
    min_event_days: int
    bootstrap_resamples: int
    bootstrap_seed: int
    pbo_partitions: int
    dsr_min: float
    pbo_max: float
    months_positive_fraction: float
    month_window: tuple[tuple[int, int], tuple[int, int]]
    month_count: int
    min_positive_years: int
    dev_years: tuple[int, ...]
    year_count: int
    year_min_trades: int
    concentration_drop: int
    holdout_start_ms: int
    forward_start_ms: int
    files: tuple[str, ...]
    hashes: Mapping[str, str]

    def nominal_sigma_obs(self, window_min: int) -> int:
        """Nominal trailing-sigma observation count for a ``W``-minute window."""
        return (self.sigma_lookback_days * 1440) // window_min

    def min_sigma_obs(self, window_min: int) -> int:
        """Minimum usable trailing-sigma observations (prereg minimum rule)."""
        nominal = self.nominal_sigma_obs(window_min)
        return max(2, math.ceil(nominal * self.sigma_min_fraction))

    def settlement_hours_utc(self) -> tuple[int, ...]:
        return self.funding_hours


def _utc_ms(year: int, month: int, day: int, hour: int = 0) -> int:
    return int(dt.datetime(year, month, day, hour, tzinfo=dt.UTC).timestamp() * 1000)


@dataclass(frozen=True)
class _Rule:
    """One frozen value: where it lives in the prereg and how to parse it."""

    field: str
    file: str
    pattern: str
    cast: Callable[[Sequence[str]], Any]
    note: str = ""


def _f(groups: Sequence[str]) -> float:
    return float(groups[0])


def _i(groups: Sequence[str]) -> int:
    return int(groups[0])


def _ints(groups: Sequence[str]) -> tuple[int, ...]:
    return tuple(int(float(part)) for part in groups[0].split(","))


def _floats(groups: Sequence[str]) -> tuple[float, ...]:
    return tuple(float(part) for part in groups[0].split(","))


def _pct(groups: Sequence[str]) -> float:
    return int(groups[0]) / 100.0


def _money(groups: Sequence[str]) -> int:
    return int(groups[0].replace(",", ""))


def _word(groups: Sequence[str]) -> int:
    return _NUMBER_WORDS[groups[0].strip().lower()]


_RULES: tuple[_Rule, ...] = (
    # -- signal, grid and universe (D1-oi-flush-reversal.md) ---------------
    _Rule("windows", "D1-oi-flush-reversal.md",
          r"window W \(min\)[^\n]*\n\|[\s\-|]+\n\|([^|]+)\|([^|]+)\|([^|]+)\|",
          lambda g: tuple(sorted(_ints((g[0],)))), "grid windows"),
    _Rule("shocks", "D1-oi-flush-reversal.md",
          r"window W \(min\)[^\n]*\n\|[\s\-|]+\n\|([^|]+)\|([^|]+)\|([^|]+)\|",
          lambda g: tuple(sorted(_floats((g[1],)))), "grid shock thresholds"),
    _Rule("holds", "D1-oi-flush-reversal.md",
          r"window W \(min\)[^\n]*\n\|[\s\-|]+\n\|([^|]+)\|([^|]+)\|([^|]+)\|",
          lambda g: tuple(sorted(_ints((g[2],)))), "grid holding periods"),
    _Rule("cell_count", "D1-oi-flush-reversal.md",
          r"(\d+) x (\d+) x (\d+) = (\d+) cells",
          lambda g: int(g[3]), "frozen cell count"),
    _Rule("oi_z_max", "D1-oi-flush-reversal.md",
          r"z_g <= (-?\d+(?:\.\d+)?)", _f, "OI z-score condition"),
    _Rule("sigma_lookback_days", "D1-oi-flush-reversal.md",
          r"covering the trailing (\d+) days", _i, "sigma lookback"),
    _Rule("sigma_min_pct", "D1-oi-flush-reversal.md",
          r"Minimum (\d+)%\s+of the nominal observation count", _pct,
          "minimum usable sigma observations"),
    _Rule("universe_size", "D1-oi-flush-reversal.md",
          r"take the top N = (\d+)", _i, "universe size"),
    _Rule("universe_min_age_days", "D1-oi-flush-reversal.md",
          r"listing age >= (\d+) days", _i, "universe listing age"),
    _Rule("metrics_lag_min", "D1-oi-flush-reversal.md",
          r"usable only at T\+(\d+) minutes", _i, "metrics availability lag"),
    _Rule("entry_offset_min", "D1-oi-flush-reversal.md",
          r"bar starting at T \+ (\d+) minutes", _i, "taker entry offset"),
    _Rule("universe_active_hhmm", "D1-oi-flush-reversal.md",
          r"active at (\d\d):(\d\d) UTC on the [Ss]econd\s+calendar day",
          lambda g: (int(g[0]), int(g[1])), "monthly reconstitution time"),
    # -- costs -------------------------------------------------------------
    _Rule("taker_fee_bps", "D1-oi-flush-reversal.md",
          r"taker fee (\d+\.\d+) bps", _f, "taker fee per side"),
    _Rule("half_spread_bps", "D1-oi-flush-reversal.md",
          r"half-spread (\d+\.\d+) bp", _f, "half spread per side"),
    _Rule("slippage", "D1-oi-flush-reversal.md",
          r"shock-scaled slippage `(\d+\.\d+) \+ (\d+\.\d+) \* \|r_W\|_bps` bps",
          lambda g: (float(g[0]), float(g[1])), "shock-scaled slippage"),
    _Rule("maker_fee_bps", "D1-oi-flush-reversal.md",
          r"Maker fee (\d+\.\d+) bps", _f, "diagnostic maker fee"),
    _Rule("funding_hours", "D1-oi-flush-reversal.md",
          r"settlement \((\d\d):00, (\d\d):00, (\d\d):00\)",
          lambda g: tuple(int(x) for x in g), "funding settlement hours"),
    _Rule("funding_impute_days", "D1-oi-flush-reversal.md",
          r"in the (\d+) days\s+preceding entry", _i,
          "adverse funding imputation window"),
    _Rule("stress_multiple", "D1-oi-flush-reversal.md",
          r"(\d)x stress: every fee", _i, "cost stress multiple"),
    # -- gates -------------------------------------------------------------
    _Rule("min_events", "D1-oi-flush-reversal.md",
          r"n >= (\d+) events", _i, "minimum events"),
    _Rule("min_event_days", "D1-oi-flush-reversal.md",
          r">= (\d+) distinct event days", _i, "minimum distinct event days"),
    _Rule("bootstrap", "D1-oi-flush-reversal.md",
          r"([\d,]+) resamples, seed (\d+)",
          lambda g: (int(g[0].replace(",", "")), int(g[1])), "day-block bootstrap"),
    _Rule("pbo_partitions", "D1-oi-flush-reversal.md",
          r"into (\d+) consecutive partitions", _i, "CSCV partitions"),
    _Rule("dsr_min", "D1-oi-flush-reversal.md",
          r"DSR >= (\d+\.\d+)", _f, "DSR gate"),
    _Rule("pbo_max", "D1-oi-flush-reversal.md",
          r"PBO <= (\d+\.\d+)", _f, "PBO gate"),
    _Rule("months_positive_pct", "D1-oi-flush-reversal.md",
          r">= (\d+)% positive months", _pct, "positive-months gate"),
    _Rule("month_window", "D1-oi-flush-reversal.md",
          r"calendar months (\d{4})-(\d{2}) \.\. (\d{4})-(\d{2})\s+\((\d+) months\)",
          lambda g: ((int(g[0]), int(g[1])), (int(g[2]), int(g[3]))),
          "frozen DEV month range"),
    _Rule("month_count", "D1-oi-flush-reversal.md",
          r"calendar months (\d{4})-(\d{2}) \.\. (\d{4})-(\d{2})\s+\((\d+) months\)",
          lambda g: int(g[4]), "frozen DEV month count"),
    _Rule("year_gate", "D1-oi-flush-reversal.md",
          r">= (\d+) of the (\d+) DEV years positive at 1x:?\s*([^;]+)",
          lambda g: (int(g[0]), int(g[1]), tuple(sorted({int(y) for y in
                                                         re.findall(r"20\d\d", g[2])}))),
          "DEV year gate"),
    _Rule("year_min_trades", "D1-oi-flush-reversal.md",
          r">= (\d+) trades \(fewer = not positive\)", _i,
          "trades needed for a positive year"),
    _Rule("concentration_drop", "D1-oi-flush-reversal.md",
          r"remove the (\w+) symbols with the largest", _word,
          "concentration gate symbol drop"),
    # -- split enforcement (SPLIT.md) --------------------------------------
    _Rule("dev_cutoff", "SPLIT.md",
          r"C = (\d{4})-(\d{2})-(\d{2})T\d\d:\d\d:\d\dZ",
          lambda g: _utc_ms(int(g[0]), int(g[1]), int(g[2])), "DEV cutoff"),
    _Rule("forward_start", "SPLIT.md",
          r"\| FORWARD \| \((\d{4})-(\d{2})-(\d{2}),",
          lambda g: _utc_ms(int(g[0]), int(g[1]), int(g[2])) + DAY_MS,
          "first forward instant"),
)


def prereg_files(prereg_dir: Path) -> list[Path]:
    """Every frozen D1 document plus the split preregistration."""
    d1 = sorted(prereg_dir.glob("D1-*.md"))
    split = prereg_dir / "SPLIT.md"
    if not d1:
        raise PreregParseError(
            f"no D1 preregistration in {prereg_dir}: the evaluator has nothing "
            f"frozen to apply (expected D1-oi-flush-reversal.md)"
        )
    if not split.is_file():
        raise PreregParseError(f"missing split preregistration {split}")
    return [*d1, split]


def load_rules(prereg_dir: Path | None = None) -> Rules:
    """Parse every frozen D1 constant out of the preregistration text."""
    directory = Path(prereg_dir) if prereg_dir is not None else PREREG_DIR
    paths = prereg_files(directory)
    texts = {path.name: path.read_text(encoding="utf-8") for path in paths}
    values: dict[str, Any] = {}
    for rule in _RULES:
        text = texts.get(rule.file)
        if text is None:
            raise PreregParseError(f"{rule.field}: {rule.file} is missing from {directory}")
        match = re.search(rule.pattern, text)
        if match is None:
            raise PreregParseError(
                f"{rule.field}: pattern {rule.pattern!r} no longer matches "
                f"{rule.file}; the prereg changed and this evaluator must be "
                f"re-read against it ({rule.note})"
            )
        values[rule.field] = rule.cast(match.groups())

    cells = tuple(
        sorted(Cell(w, k, h)
               for w in values["windows"] for k in values["shocks"] for h in values["holds"])
    )
    if len(cells) != values["cell_count"]:
        raise PreregParseError(
            f"grid drift: {len(cells)} cells parsed from the table but the "
            f"prereg says {values['cell_count']}"
        )
    min_positive_years, year_count, dev_years = values["year_gate"]
    if len(dev_years) != year_count:
        raise PreregParseError(
            f"year gate: prereg says {year_count} DEV years, parsed {dev_years}"
        )
    hashes = {name: hashlib.sha256(text.encode("utf-8")).hexdigest()
              for name, text in texts.items()}
    return Rules(
        cells=cells,
        cell_count=values["cell_count"],
        windows=values["windows"],
        shocks=values["shocks"],
        holds=values["holds"],
        oi_z_max=values["oi_z_max"],
        sigma_lookback_days=values["sigma_lookback_days"],
        sigma_min_fraction=values["sigma_min_pct"],
        universe_size=values["universe_size"],
        universe_min_age_days=values["universe_min_age_days"],
        universe_active_hhmm=values["universe_active_hhmm"],
        metrics_lag_min=values["metrics_lag_min"],
        entry_offset_min=values["entry_offset_min"],
        taker_fee_bps=values["taker_fee_bps"],
        half_spread_bps=values["half_spread_bps"],
        slippage_base_bps=values["slippage"][0],
        slippage_shock_coef=values["slippage"][1],
        maker_fee_bps=values["maker_fee_bps"],
        funding_hours=values["funding_hours"],
        funding_impute_days=values["funding_impute_days"],
        stress_multiple=values["stress_multiple"],
        min_events=values["min_events"],
        min_event_days=values["min_event_days"],
        bootstrap_resamples=values["bootstrap"][0],
        bootstrap_seed=values["bootstrap"][1],
        pbo_partitions=values["pbo_partitions"],
        dsr_min=values["dsr_min"],
        pbo_max=values["pbo_max"],
        months_positive_fraction=values["months_positive_pct"],
        month_window=values["month_window"],
        month_count=values["month_count"],
        min_positive_years=min_positive_years,
        dev_years=dev_years,
        year_count=year_count,
        year_min_trades=values["year_min_trades"],
        concentration_drop=values["concentration_drop"],
        holdout_start_ms=values["dev_cutoff"],
        forward_start_ms=values["forward_start"],
        files=tuple(sorted(hashes)),
        hashes=hashes,
    )


# --------------------------------------------------------------------------
# 2. Structural holdout refusal
# --------------------------------------------------------------------------

_SEALED_PATH_PARTS = frozenset({"holdout", "holdout_raw", "sealed", "sealed_holdout"})


def assert_not_sealed_path(path: Path) -> None:
    """Refuse any path that names the sealed holdout, before it is opened."""
    for part in Path(path).resolve().parts:
        if part.strip().lower() in _SEALED_PATH_PARTS:
            raise HoldoutRefusal(
                f"refusing {path}: path component {part!r} names the sealed "
                f"holdout, which D1 never reads (research/prereg/SPLIT.md)"
            )


def assert_forward_window(start_ms: int, end_ms: int, rules: Rules) -> tuple[int, int]:
    """Clamp and vet the evaluation window; refuse anything touching the holdout."""
    if start_ms < rules.forward_start_ms:
        raise HoldoutRefusal(
            f"refusing window from {_iso(start_ms)}: D1 forward data starts at "
            f"{_iso(rules.forward_start_ms)} and the sealed holdout "
            f"[{_iso(rules.holdout_start_ms)}, {_iso(rules.forward_start_ms)}) is "
            f"never opened"
        )
    if end_ms <= start_ms:
        raise D1Error(f"empty window: {_iso(start_ms)} .. {_iso(end_ms)}")
    return start_ms, end_ms


def _record_is_sealed(event_ms: int, rules: Rules) -> bool:
    return rules.holdout_start_ms <= event_ms < rules.forward_start_ms


def _iso(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# 3. Recorder chunk chain
# --------------------------------------------------------------------------

_CHUNK_STAMP = re.compile(r"(\d{8})T(\d{6})Z")


@dataclass(frozen=True)
class ChunkEntry:
    """One sealed recorder chunk, as declared in ``manifest.json``."""

    path: Path
    first_ms: int
    last_ms: int
    records: int
    streams: tuple[str, ...]
    sha256: str
    entry_hash: str
    prev: str
    stamp_ms: int


@dataclass
class Store:
    """The recorder's chunked chain, with its custody checks."""

    root: Path
    entries: list[ChunkEntry]
    chain_head: str
    created_utc: str | None

    def window(self, start_ms: int, end_ms: int) -> list[ChunkEntry]:
        return [e for e in self.entries
                if e.last_ms >= start_ms and e.first_ms < end_ms]

    def stream_names(self, entries: Iterable[ChunkEntry]) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for entry in entries:
            for stream in entry.streams:
                counts[stream] += 1
        return dict(sorted(counts.items()))

    def coverage_ms(self, entries: Iterable[ChunkEntry]) -> tuple[int, int]:
        chosen = list(entries)
        if not chosen:
            raise StoreError(f"no recorder chunks in {self.root}")
        return min(e.first_ms for e in chosen), max(e.last_ms for e in chosen)


def _stamp_from_name(name: str) -> int:
    match = _CHUNK_STAMP.search(name)
    if match is None:
        raise StoreError(f"chunk {name!r} carries no UTC stamp in its name")
    return int(dt.datetime.strptime(match.group(1) + match.group(2),
                                    "%Y%m%d%H%M%S").replace(tzinfo=dt.UTC).timestamp() * 1000)


def scan_store(root: Path, rules: Rules) -> Store:
    """Read ``manifest.json``, verify its hash chain, refuse sealed chunks."""
    root = Path(root)
    assert_not_sealed_path(root)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise StoreError(
            f"no recorder manifest at {manifest_path}: D1 forward data is the "
            f"recorder chain (manifest.json + chunks/*.jsonl.gz), not raw exports"
        )
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    declared = raw.get("entries") or []
    if not declared:
        raise StoreError(f"{manifest_path} declares no chunks")
    entries: list[ChunkEntry] = []
    for item in declared:
        chunk_name = str(item.get("chunk"))
        chunk_path = root / chunk_name
        assert_not_sealed_path(chunk_path)
        stamp_ms = _stamp_from_name(Path(chunk_name).name)
        first_ms = int(item.get("first_ms") or 0)
        last_ms = int(item.get("last_ms") or 0)
        # A chunk with no declared window cannot be proven to sit outside the
        # holdout, so it is refused rather than read and screened later: an
        # unverifiable window is exactly how holdout bytes would slip in.
        if not first_ms or not last_ms:
            raise HoldoutRefusal(
                f"refusing chunk {chunk_name}: the manifest declares no "
                f"first_ms/last_ms, so its window cannot be shown to lie outside "
                f"the sealed holdout [{_iso(rules.holdout_start_ms)}, "
                f"{_iso(rules.forward_start_ms)})"
            )
        # Refusal is by time, not by the manifest's own label: a chunk whose
        # window overlaps the sealed holdout is sealed whatever it is called.
        if rules.holdout_start_ms <= last_ms and first_ms < rules.forward_start_ms:
            raise HoldoutRefusal(
                f"refusing chunk {chunk_name}: its window "
                f"{_iso(first_ms)} .. {_iso(last_ms)} overlaps the sealed "
                f"holdout [{_iso(rules.holdout_start_ms)}, "
                f"{_iso(rules.forward_start_ms)})"
            )
        entries.append(ChunkEntry(
            path=chunk_path,
            first_ms=first_ms,
            last_ms=last_ms,
            records=int(item.get("records") or 0),
            streams=tuple(str(s) for s in (item.get("streams") or ())),
            sha256=str(item.get("sha256") or ""),
            entry_hash=str(item.get("entry_hash") or ""),
            prev=str(item.get("prev") or ""),
            stamp_ms=stamp_ms,
        ))
    entries.sort(key=lambda e: (e.first_ms, e.stamp_ms))
    # Chain of custody: every chunk links to the previous hash; the last link
    # is the manifest's chain head.  A broken chain means the data is not the
    # sealed recording this evaluator is allowed to score.
    prev = entries[0].prev
    if prev != "genesis":
        raise StoreError(f"chunk chain does not start at genesis (got {prev!r})")
    for entry in entries:
        if entry.prev != prev and entry.prev != "genesis":
            raise StoreError(
                f"chunk chain break at {entry.path.name}: prev={entry.prev!r}"
            )
        prev = entry.entry_hash
    chain_head = str(raw.get("chain_head") or "")
    if chain_head and prev and chain_head != prev:
        raise StoreError(
            f"chunk chain head mismatch: manifest says {chain_head!r}, chain "
            f"ends at {prev!r}"
        )
    return Store(root=root, entries=entries, chain_head=chain_head,
                 created_utc=raw.get("created_utc"))


def read_records(store: Store, entries: Sequence[ChunkEntry], rules: Rules,
                 *, verify: bool = True) -> Iterator[dict[str, Any]]:
    """Yield records from forward chunks, verifying each chunk's digest first."""
    for entry in entries:
        assert_not_sealed_path(entry.path)
        if not entry.path.is_file():
            raise StoreError(f"declared chunk {entry.path} is missing")
        blob = entry.path.read_bytes()
        if verify and entry.sha256:
            digest = hashlib.sha256(blob).hexdigest()
            if digest != entry.sha256:
                raise StoreError(
                    f"chunk digest mismatch for {entry.path.name}: manifest "
                    f"{entry.sha256[:16]}..., file {digest[:16]}..."
                )
        text = gzip.decompress(blob).decode("utf-8")
        for line in text.splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            event_ms = record.get("event_ms")
            if not isinstance(event_ms, int) or isinstance(event_ms, bool):
                raise HoldoutRefusal(
                    f"refusing {entry.path.name}: a record carries no integer "
                    f"event_ms, so it cannot be shown to lie outside the sealed "
                    f"holdout [{_iso(rules.holdout_start_ms)}, "
                    f"{_iso(rules.forward_start_ms)})"
                )
            if _record_is_sealed(event_ms, rules):
                raise HoldoutRefusal(
                    f"refusing {entry.path.name}: record stamped "
                    f"{_iso(event_ms)} is inside the sealed holdout"
                )
            yield record


# --------------------------------------------------------------------------
# 4. Stream inventory and the required-stream shortfall
# --------------------------------------------------------------------------


def classify_stream(name: str) -> str:
    """Map a recorder stream name to a D1 capability bucket."""
    lowered = name.strip().lower()
    if "aggtrade" in lowered or lowered.endswith("@trade") or lowered == "trade":
        return "price_trades"
    if "kline" in lowered:
        return "ranking_klines_1d" if "1d" in lowered else "price_klines"
    if "open_interest" in lowered:
        return "open_interest"
    if "funding" in lowered:
        return "funding"
    if "mark" in lowered or "premium" in lowered:
        return "marks"
    if "depth" in lowered or "bookticker" in lowered or lowered == "depth_snapshot":
        return "book"
    return "other"


@dataclass(frozen=True)
class Shortfall:
    """One reason the forward sample cannot answer D1 yet."""

    stream: str
    detail: str
    fix: str

    def as_dict(self) -> dict[str, str]:
        return {"missing": self.stream, "detail": self.detail, "fix": self.fix}


def stream_shortfalls(store: Store, entries: Sequence[ChunkEntry],
                      rules: Rules) -> list[Shortfall]:
    """Report every D1 input the recorder does not yet carry, without proxies."""
    names = store.stream_names(entries)
    buckets: dict[str, list[str]] = defaultdict(list)
    for name in names:
        buckets[classify_stream(name)].append(name)
    found = ", ".join(sorted(names)) or "nothing"

    def have(*keys: str) -> list[str]:
        return [n for key in keys for n in buckets.get(key, ())]

    shortfalls: list[Shortfall] = []
    price = have("price_trades", "price_klines")
    if not price:
        shortfalls.append(Shortfall(
            stream="price_bars_1m",
            detail=(
                "no trade or 1m-kline stream in the recorder chunks "
                f"(found: {found}); D1 prices are the OPEN of each symbol's own "
                "1m bar, and a quoted mid or a depth snapshot is not that price"
            ),
            fix="record the aggTrade stream (or 1m klines) per symbol",
        ))
    oi = buckets.get("open_interest", [])
    if not oi:
        shortfalls.append(Shortfall(
            stream="open_interest",
            detail=f"no open-interest stream in the recorder chunks (found: {found})",
            fix="record the venue's open-interest snapshot at <= 5-minute cadence",
        ))
    funding = buckets.get("funding", [])
    if not funding:
        marks = ", ".join(buckets.get("marks", [])) or "none"
        shortfalls.append(Shortfall(
            stream="funding_settlements",
            detail=(
                "no settled funding-rate stream in the recorder chunks "
                f"(mark/premium streams present: {marks}); D1 charges the "
                "fundingRate paid at 00:00/08:00/16:00 UTC, and the premium "
                "index's next-rate estimate is not a settlement"
            ),
            fix="record the settled fundingRate at each settlement",
        ))
    ranking = have("ranking_klines_1d")
    if not ranking:
        shortfalls.append(Shortfall(
            stream="universe_daily_klines",
            detail=(
                "no daily-kline stream for the point-in-time liquidity universe "
                f"(found: {found}); D1 ranks {rules.universe_size} USD-M perps by "
                "previous-calendar-month quote volume over the full candidate set"
            ),
            fix="record 1d klines (quote_volume) for the full candidate listing",
        ))
    return shortfalls


# --------------------------------------------------------------------------
# 5. Series construction (forward adaptation of the metrics convention)
# --------------------------------------------------------------------------


@dataclass
class SymbolSeries:
    """One symbol's forward inputs on the prereg's clock."""

    symbol: str
    bar_open: dict[int, float] = field(default_factory=dict)
    oi: dict[int, float] = field(default_factory=dict)
    funding: dict[int, float] = field(default_factory=dict)
    daily_quote_volume: dict[str, float] = field(default_factory=dict)
    first_ms: int = 0
    last_ms: int = 0
    _oi_cache: tuple[Any, list[int], list[float]] | None = field(
        default=None, repr=False, compare=False)
    _bar_keys: np.ndarray | None = field(default=None, repr=False, compare=False)

    def price(self, instant_ms: int) -> float | None:
        return self.bar_open.get(instant_ms)

    def bar_starts(self) -> np.ndarray:
        """Sorted bar-start instants, cached for the exit-bar searches."""
        if self._bar_keys is None:
            self._bar_keys = np.array(sorted(self.bar_open), dtype=np.int64)
        return self._bar_keys

    def oi_at(self, instant_ms: int, tolerance_ms: int) -> float | None:
        """Latest OI observation stamped at or before ``instant_ms``.

        Forward adaptation of the prereg's "the row stamped T is a snapshot at
        instant T": the recorder polls OI between grid points, so the snapshot
        used at T is the last observation at or before T (never a later one),
        and it is missing if the poll gap exceeds one grid step.  A missing OI
        value voids the window rather than borrowing the neighbouring value.
        """
        keys, values = self._oi_sorted()
        index = bisect.bisect_right(keys, instant_ms) - 1
        if index < 0:
            return None
        if instant_ms - keys[index] > tolerance_ms:
            return None
        value = values[index]
        return value if value > 0 else None

    def _oi_sorted(self) -> tuple[list[int], list[float]]:
        marker = (id(self.oi), len(self.oi))
        if self._oi_cache is None or self._oi_cache[0] != marker:
            keys = sorted(self.oi)
            self._oi_cache = (marker, keys, [self.oi[stamp] for stamp in keys])
        return self._oi_cache[1], self._oi_cache[2]

    def funding_rate(self, settlement_ms: int) -> float | None:
        return self.funding.get(settlement_ms)

    @property
    def funding_first_ms(self) -> int:
        """First settled funding stamp, on the funding series' own clock.

        The adverse-imputation eligibility test needs the first *funding*
        observation, not the first bar: a long kline backfill with three weeks
        of funding must not look like a full trailing year.
        """
        return min(self.funding) if self.funding else 0

    @property
    def first_listing_day(self) -> str:
        """First daily kline date, the listing date the age rule counts from."""
        return min(self.daily_quote_volume) if self.daily_quote_volume else ""


def _oi_from_record(record: Mapping[str, Any]) -> tuple[str, int, float] | None:
    symbol = str(record.get("symbol") or "").upper()
    event_ms = record.get("event_ms")
    payload = record.get("payload") or {}
    raw = payload.get("openInterest", record.get("openInterest"))
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not isinstance(event_ms, int) or not symbol or value <= 0:
        return None
    return symbol, event_ms, value


def build_series(store: Store, entries: Sequence[ChunkEntry], rules: Rules
                 ) -> tuple[dict[str, SymbolSeries], dict[str, Any]]:
    """Turn forward chunk records into 1m bar opens, 5m OI and funding rates."""
    series: dict[str, SymbolSeries] = {}
    counts: dict[str, int] = defaultdict(int)
    first_trade_in_minute: dict[tuple[str, int], tuple[int, float]] = {}

    def series_for(symbol: str) -> SymbolSeries:
        if symbol not in series:
            series[symbol] = SymbolSeries(symbol=symbol)
        return series[symbol]

    for record in read_records(store, entries, rules):
        kind = str(record.get("type") or "")
        if kind in RANKING_RECORD_TYPES:
            symbol = str(record.get("symbol") or "").upper()
            payload = record.get("payload") or {}
            raw_volume = payload.get(
                "quote_volume", record.get("quote_volume", record.get("qv")))
            raw_stamp = record.get("exchange_open_ms", record.get("event_ms"))
            try:
                volume = float(raw_volume)  # type: ignore[arg-type]
                bar_ms = int(raw_stamp)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if not symbol or volume < 0:
                continue
            day = dt.datetime.fromtimestamp(bar_ms / 1000, tz=dt.UTC).date()
            series_for(symbol).daily_quote_volume[day.isoformat()] = volume
            counts["daily_klines"] += 1
            continue
        if kind in PRICE_RECORD_TYPES or kind in KLINE_RECORD_TYPES:
            symbol = str(record.get("symbol") or "").upper()
            event_ms = record.get("event_ms")
            if not symbol or not isinstance(event_ms, int):
                continue
            if kind in KLINE_RECORD_TYPES:
                raw_open = record.get("o", record.get("open"))
                start_ms = record.get("exchange_open_ms", record.get("bar_start_ms"))
                try:
                    open_px = float(raw_open)  # type: ignore[arg-type]
                    bar_ms = int(start_ms)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    continue
                if open_px <= 0:
                    continue
                item = series_for(symbol)
                item.bar_open[bar_ms] = open_px
                counts["price_bars"] += 1
                continue
            raw_price = record.get("price", record.get("p"))
            try:
                price = float(raw_price)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            bar_ms = (event_ms // MIN_MS) * MIN_MS
            key = (symbol, bar_ms)
            current = first_trade_in_minute.get(key)
            if current is None or event_ms < current[0]:
                first_trade_in_minute[key] = (event_ms, price)
            counts["price_trades"] += 1
        elif kind in OI_RECORD_TYPES:
            parsed = _oi_from_record(record)
            if parsed is None:
                continue
            symbol, event_ms, value = parsed
            series_for(symbol).oi[event_ms] = value
            counts["open_interest"] += 1
        elif kind in FUNDING_RECORD_TYPES:
            symbol = str(record.get("symbol") or "").upper()
            event_ms = record.get("event_ms")
            payload = record.get("payload") or {}
            raw_rate = payload.get("fundingRate", record.get("fundingRate", record.get("r")))
            try:
                rate = float(raw_rate)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if not symbol or not isinstance(event_ms, int):
                continue
            settlement = _settle_instant(event_ms, rules)
            series_for(symbol).funding[settlement] = rate
            counts["funding"] += 1

    for (symbol, bar_ms), (_stamp, price) in first_trade_in_minute.items():
        item = series_for(symbol)
        item.bar_open[bar_ms] = price
        counts["price_bars"] += 1

    for item in series.values():
        stamps = [*item.bar_open, *item.oi, *item.funding]
        if stamps:
            item.first_ms = min(stamps)
            item.last_ms = max(stamps)
    inventory = {
        "symbols": sorted(series),
        "records": dict(sorted(counts.items())),
        "points": {
            symbol: {
                "bars_1m": len(item.bar_open),
                "oi_observations": len(item.oi),
                "funding_settlements": len(item.funding),
                "daily_klines": len(item.daily_quote_volume),
                "first_listing_day": item.first_listing_day,
            }
            for symbol, item in sorted(series.items())
        },
    }
    return series, inventory


def _code_hashes() -> dict[str, str]:
    """SHA-256 of this evaluator's own source files, bound into every output.

    The prereg binds the result to "this document's SHA-256, code hash, data
    manifest"; the prereg and manifest hashes are elsewhere in this document,
    and this is the code half.
    """
    hashes: dict[str, str] = {}
    for path in (Path(__file__), Path(__file__).with_name("d1_trials.py")):
        try:
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:  # pragma: no cover - a frozen bundle without sources
            hashes[path.name] = "unavailable"
    return hashes


def _settle_instant(instant_ms: int, rules: Rules) -> int:
    """Snap a funding record onto the settlement hour it belongs to."""
    hour_ms = (instant_ms // HOUR_MS) * HOUR_MS
    if (instant_ms % HOUR_MS) >= HOUR_MS // 2:
        hour_ms += HOUR_MS
    return hour_ms


@dataclass(frozen=True)
class MonthlyRanking:
    """One frozen monthly reconstitution, computed point-in-time."""

    month: str
    prior_month: str
    active_from_ms: int
    ranked: tuple[str, ...]
    candidates: int
    age_qualified: int

    def as_dict(self, rules: Rules) -> dict[str, Any]:
        return {
            "month": self.month,
            "prior_month": self.prior_month,
            "active_from": _iso(self.active_from_ms),
            "ranked": list(self.ranked),
            "ranked_count": len(self.ranked),
            "needed": rules.universe_size,
            "complete": len(self.ranked) >= rules.universe_size,
            "candidates_in_prior_month": self.candidates,
            "candidates_passing_age": self.age_qualified,
        }


def _month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _month_start_ms(year: int, month: int) -> int:
    return _utc_ms(year, month, 1)


def _month_days(year: int, month: int) -> list[str]:
    count = calendar.monthrange(year, month)[1]
    return [dt.date(year, month, day).isoformat() for day in range(1, count + 1)]


def monthly_rankings(series: Mapping[str, SymbolSeries], rules: Rules,
                     window_start_ms: int, window_end_ms: int
                     ) -> dict[str, MonthlyRanking]:
    """Apply the frozen monthly quote-volume ranking to every month in the window.

    Prereg (universe section): rank candidates by their summed 1d-kline
    ``quote_volume`` over the previous full calendar month M-1, requiring every
    day of M-1 present; require listing age >= 90 days at the start of M; take
    the top N. The ranking is frozen for all of M and becomes active at 00:06
    UTC on the *second* calendar day, so the first day of M never trades. Only
    ``quote_volume`` is used -- never lifetime or holdout volume -- and a symbol
    that stops trading mid-month simply has no bars to enter on.
    """
    first = dt.datetime.fromtimestamp(window_start_ms / 1000, tz=dt.UTC)
    last_ms = max(window_end_ms - 1, window_start_ms)
    last = dt.datetime.fromtimestamp(last_ms / 1000, tz=dt.UTC)
    active_hour, active_minute = rules.universe_active_hhmm
    rankings: dict[str, MonthlyRanking] = {}
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        prior_year, prior_month = _shift_month(year, month, -1)
        required_days = _month_days(prior_year, prior_month)
        month_start = _month_start_ms(year, month)
        listing_deadline = dt.date(year, month, 1) - dt.timedelta(
            days=rules.universe_min_age_days)
        scored: list[tuple[float, str]] = []
        candidates = 0
        aged = 0
        for symbol, item in series.items():
            if not item.daily_quote_volume:
                continue
            candidates += 1
            if any(day not in item.daily_quote_volume for day in required_days):
                continue
            if dt.date.fromisoformat(item.first_listing_day) > listing_deadline:
                continue
            aged += 1
            total = sum(item.daily_quote_volume[day] for day in required_days)
            scored.append((-total, symbol))
        scored.sort()
        rankings[_month_key(year, month)] = MonthlyRanking(
            month=_month_key(year, month),
            prior_month=_month_key(prior_year, prior_month),
            active_from_ms=(month_start + DAY_MS + active_hour * HOUR_MS
                            + active_minute * MIN_MS),
            ranked=tuple(symbol for _volume, symbol in scored[:rules.universe_size]),
            candidates=candidates,
            age_qualified=aged,
        )
        year, month = _shift_month(year, month, 1)
    return rankings


def universe_spans(rankings: Mapping[str, MonthlyRanking]
                   ) -> list[tuple[int, int, frozenset[str]]]:
    """Turn the monthly rankings into (start, end, symbols) spans for a lookup."""
    spans: list[tuple[int, int, frozenset[str]]] = []
    for key in sorted(rankings):
        ranking = rankings[key]
        year, month = (int(part) for part in key.split("-"))
        next_year, next_month = _shift_month(year, month, 1)
        spans.append((ranking.active_from_ms, _month_start_ms(next_year, next_month),
                      frozenset(ranking.ranked)))
    return spans


def complete_rankings(rankings: Mapping[str, MonthlyRanking], rules: Rules
                      ) -> dict[str, MonthlyRanking]:
    """The months whose frozen ranking is actually full.

    Months at the start of the forward window have no complete previous month
    inside forward data, so they carry no ranking and take no signals; that is
    the rule working, not a defect. Only a window with *no* complete ranking
    cannot be evaluated at all.
    """
    return {key: ranking for key, ranking in rankings.items()
            if len(ranking.ranked) >= rules.universe_size}


def universe_shortfall(rankings: Mapping[str, MonthlyRanking], rules: Rules,
                       window_start_ms: int) -> Shortfall | None:
    """Report a window in which the frozen ranking never becomes usable."""
    if not rankings:
        return Shortfall("universe", "no monthly ranking could be built",
                         "record 1d klines for the full candidate listing")
    if complete_rankings(rankings, rules):
        return None
    ordered = [rankings[key] for key in sorted(rankings)]
    short = [ranking for ranking in ordered
             if len(ranking.ranked) < rules.universe_size]
    if not short:
        return None
    worst = short[-1]
    return Shortfall(
        stream="universe",
        detail=(
            f"{worst.month}: {len(worst.ranked)} of {rules.universe_size} ranked "
            f"symbols from {worst.prior_month} quote volume "
            f"({worst.candidates} candidates with daily klines, "
            f"{worst.age_qualified} pass the {rules.universe_min_age_days}-day age "
            f"rule, every day of {worst.prior_month} required); D1 trades only the "
            f"frozen point-in-time top {rules.universe_size}, and a smaller set is "
            f"a different (unregistered) universe"
            + (f"; {len(short)} month(s) short" if len(short) > 1 else "")
        ),
        fix="record the daily klines (quote_volume) of the full candidate listing "
            "so a whole previous calendar month exists inside forward data; the "
            "frozen ranking cannot be built from a partial month",
    )


# --------------------------------------------------------------------------
# 6. Events (stage 0: counts only, no forward price)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Event:
    """A D1 trigger, before any entry/exit price is touched."""

    cell: Cell
    symbol: str
    grid_ms: int
    direction: int
    shock_bps: float


def _trailing_sd(values: np.ndarray, index: int, stride: int, count: int,
                 minimum: int) -> float | None:
    """Reference reader: sample sd of the non-overlapping windows before ``index``.

    Literal transcription of the frozen rule (windows ending at ``T-W``,
    ``T-2W``, ... covering the trailing sigma lookback); kept as the readable
    definition that :func:`_rolling_sd` is tested against.
    """
    if index - stride < 0:
        return None
    segment = values[index - stride::-stride][:count]
    segment = segment[np.isfinite(segment)]
    if len(segment) < minimum:
        return None
    sd = float(np.std(segment, ddof=1))
    if not math.isfinite(sd) or sd <= 0.0:
        return None
    return sd


def _rolling_sd(values: np.ndarray, stride: int, count: int,
                minimum: int) -> np.ndarray:
    """Vectorised equivalent of :func:`_trailing_sd` for every position at once.

    Positions are grouped by residue modulo ``stride``; inside each group the
    frozen non-overlapping windows become an ordinary sliding window, so one
    cumulative-sum pass per group yields the same sample sd in O(n).
    """
    result = np.full(len(values), np.nan)
    if len(values) <= count * stride:
        return result
    for residue in range(stride):
        block = values[residue::stride]
        if len(block) <= count:
            continue
        finite = np.isfinite(block)
        filled = np.where(finite, block, 0.0)
        sum1 = np.concatenate(([0.0], np.cumsum(filled)))
        sum2 = np.concatenate(([0.0], np.cumsum(filled * filled)))
        count_ok = np.concatenate(([0.0], np.cumsum(finite.astype(float))))
        ends = np.arange(count, len(block) + 1)
        total1 = sum1[ends] - sum1[ends - count]
        total2 = sum2[ends] - sum2[ends - count]
        usable = count_ok[ends] - count_ok[ends - count]
        variance = (total2 - total1 * total1 / np.maximum(usable, 1.0)) / np.maximum(
            usable - 1.0, 1.0)
        ok = (usable >= minimum) & (usable >= 2) & (variance > 0)
        positions = (ends - 1) * stride + residue + stride
        inside = positions < len(values)
        result[positions[inside]] = np.where(ok, np.sqrt(np.maximum(variance, 0.0)),
                                             np.nan)[inside]
    return result


def detect_events(item: SymbolSeries, cell: Cell, rules: Rules, *,
                  window_start_ms: int, window_end_ms: int,
                  spans: Sequence[tuple[int, int, frozenset[str]]] | None = None
                  ) -> list[Event]:
    """Trigger events for one symbol and one cell, on the prereg's clock.

    Reads only past prices and past OI: the shock and both trailing sigmas are
    computed from information stamped at or before ``T``; no entry or exit
    price is looked at here, which is what lets stage 0 run first.
    """
    if not item.bar_open or not item.oi:
        return []
    first = ((min(item.first_ms, window_start_ms) + STEP_MS - 1) // STEP_MS) * STEP_MS
    last = max(item.last_ms, window_start_ms)
    if last < first:
        return []
    steps = np.arange(first, last + 1, STEP_MS, dtype=np.int64)
    if len(steps) < 2:
        return []
    tolerance = STEP_MS
    opens = np.full(len(steps), np.nan)
    ois = np.full(len(steps), np.nan)
    for index, instant in enumerate(steps):
        price = item.price(int(instant))
        if price is not None and price > 0:
            opens[index] = math.log(price)
        oi_value = item.oi_at(int(instant), tolerance)
        if oi_value is not None:
            ois[index] = math.log(oi_value)

    stride = cell.w // 5
    if stride < 1:
        return []
    returns = np.full(len(steps), np.nan)
    oi_changes = np.full(len(steps), np.nan)
    returns[stride:] = opens[stride:] - opens[:-stride]
    oi_changes[stride:] = ois[stride:] - ois[:-stride]

    nominal = rules.nominal_sigma_obs(cell.w)
    minimum = rules.min_sigma_obs(cell.w)
    sd_returns = _rolling_sd(returns, stride, nominal, minimum)
    sd_oi = _rolling_sd(oi_changes, stride, nominal, minimum)
    with np.errstate(divide="ignore", invalid="ignore"):
        z_returns = returns / sd_returns
        z_oi = oi_changes / sd_oi
    inside = (steps >= window_start_ms) & (steps < window_end_ms)
    triggered = (np.abs(z_returns) >= cell.k) & (z_oi <= rules.oi_z_max) & inside
    triggered &= np.isfinite(z_returns) & np.isfinite(z_oi)
    if spans is not None:
        # The frozen monthly universe, applied at the trigger instant: a symbol
        # outside that month's ranking is not a D1 candidate for that month.
        allowed = np.zeros(len(steps), dtype=bool)
        for span_start, span_end, symbols in spans:
            if item.symbol in symbols:
                allowed |= (steps >= span_start) & (steps < span_end)
        triggered &= allowed
    events: list[Event] = []
    for index in np.nonzero(triggered)[0]:
        shock = float(returns[index])
        events.append(Event(
            cell=cell,
            symbol=item.symbol,
            grid_ms=int(steps[index]),
            direction=1 if shock <= 0 else -1,
            shock_bps=abs(shock) * 1e4,
        ))
    return events


def overlap_filtered(events: Sequence[Event], cell: Cell, rules: Rules, *,
                     window_end_ms: int) -> list[Event]:
    """Keep only the events the frozen no-overlap rule can actually enter.

    Prereg stage 0 counts events "using the trigger (past prices and OI) and the
    no-overlap rule only": an event whose scheduled entry falls inside a
    position already open on that symbol, or whose scheduled exit reaches the
    data cutoff, never becomes a trade, so it must not be counted either. This
    touches no forward price.
    """
    entry_offset = rules.entry_offset_min * MIN_MS
    hold = cell.h * MIN_MS
    kept: list[Event] = []
    busy_until = -1
    for event in sorted(events, key=lambda item: item.grid_ms):
        entry_ms = event.grid_ms + entry_offset
        if entry_ms < busy_until:
            continue
        if entry_ms + hold >= window_end_ms:
            continue
        kept.append(event)
        busy_until = entry_ms + hold
    return kept


def stage0_report(events: Mapping[Cell, Sequence[Event]], rules: Rules) -> dict[str, Any]:
    """Per-cell counts only: no return, no cost, no forward price."""
    cells: dict[str, Any] = {}
    eligible = 0
    for cell in rules.cells:
        chosen = events.get(cell, ())
        days = {dt.datetime.fromtimestamp(e.grid_ms / 1000, tz=dt.UTC).date()
                for e in chosen}
        by_year: dict[str, int] = defaultdict(int)
        by_month: dict[str, int] = defaultdict(int)
        by_symbol: dict[str, int] = defaultdict(int)
        for event in chosen:
            stamp = dt.datetime.fromtimestamp(event.grid_ms / 1000, tz=dt.UTC)
            by_year[str(stamp.year)] += 1
            by_month[f"{stamp.year:04d}-{stamp.month:02d}"] += 1
            by_symbol[event.symbol] += 1
        ok = len(chosen) >= rules.min_events and len(days) >= rules.min_event_days
        eligible += int(ok)
        cells[str(cell)] = {
            "events": len(chosen),
            "event_days": len(days),
            "events_by_year": dict(sorted(by_year.items())),
            "events_by_month": dict(sorted(by_month.items())),
            "events_by_symbol": dict(sorted(by_symbol.items())),
            "eligible": ok,
        }
    return {
        "cells": cells,
        "eligible_cells": eligible,
        "prereg_verdict": "UNDERPOWERED" if eligible == 0 else "POWERED",
        "min_events": rules.min_events,
        "min_event_days": rules.min_event_days,
    }


# --------------------------------------------------------------------------
# 7. Trades, costs and funding
# --------------------------------------------------------------------------


@dataclass
class Trade:
    """One unit-notional fade trade with its frozen cost accounting."""

    cell: Cell
    symbol: str
    direction: int
    entry_ms: int
    exit_ms: int
    entry_px: float
    exit_px: float
    gross_bps: float
    cost_1x_bps: float
    cost_2x_bps: float
    funding_1x_bps: float
    funding_2x_bps: float
    net_1x_bps: float
    net_2x_bps: float
    imputed_funding: bool
    forced_exit_data_end: bool

    @property
    def entry_day(self) -> str:
        return dt.datetime.fromtimestamp(self.entry_ms / 1000, tz=dt.UTC).date().isoformat()

    @property
    def entry_month(self) -> str:
        stamp = dt.datetime.fromtimestamp(self.entry_ms / 1000, tz=dt.UTC)
        return f"{stamp.year:04d}-{stamp.month:02d}"

    @property
    def entry_year(self) -> int:
        return dt.datetime.fromtimestamp(self.entry_ms / 1000, tz=dt.UTC).year


def _funding_cost(item: SymbolSeries, entry_ms: int, exit_ms: int, direction: int,
                  rules: Rules) -> tuple[float, float, bool, bool]:
    """Signed funding over ``(entry, exit]``; adverse impute when a record is missing.

    Returns ``(cost_1x_bps, cost_2x_bps, imputed, eligible)``.  ``eligible`` is
    False when the adverse imputation has no full trailing year to stand on, in
    which case the prereg makes the symbol ineligible at entry.
    """
    settlements: list[int] = []
    day_start = (entry_ms // DAY_MS) * DAY_MS
    day = day_start
    while day <= exit_ms:
        for hour in rules.settlement_hours_utc():
            instant = day + hour * HOUR_MS
            if entry_ms < instant <= exit_ms:
                settlements.append(instant)
        day += DAY_MS
    s_pay = 1 if direction > 0 else -1
    cost_1x = 0.0
    cost_2x = 0.0
    imputed = False
    for instant in settlements:
        rate = item.funding_rate(instant)
        if rate is None:
            imputed = True
            span_start = entry_ms - rules.funding_impute_days * DAY_MS
            if not item.funding_first_ms or item.funding_first_ms > span_start:
                return 0.0, 0.0, True, False
            trailing = [abs(value) for stamp, value in item.funding.items()
                        if span_start < stamp <= entry_ms]
            if not trailing:
                return 0.0, 0.0, True, False
            rate = max(trailing)
            per_settlement = rate * 1e4  # both LONG and SHORT pay the debit
            cost_1x += per_settlement
            cost_2x += rules.stress_multiple * per_settlement
            continue
        per_settlement = s_pay * rate * 1e4
        cost_1x += per_settlement
        if per_settlement > 0:
            cost_2x += rules.stress_multiple * per_settlement
        # credits are set to zero under stress: nothing added for a negative cost
    return cost_1x, cost_2x, imputed, True


def round_trip_cost_bps(shock_bps: float, rules: Rules, *, stress: bool = False) -> float:
    """Taker round trip at 1x or under the 2x stress, per the frozen cost model."""
    per_side = (rules.taker_fee_bps + rules.half_spread_bps
                + rules.slippage_base_bps + rules.slippage_shock_coef * shock_bps)
    if stress:
        per_side *= rules.stress_multiple
    return 2.0 * per_side


def simulate(item: SymbolSeries, events: Sequence[Event], cell: Cell, rules: Rules,
             *, window_end_ms: int) -> tuple[list[Trade], dict[str, int]]:
    """Enter at ``T+6m``, exit at ``T+6m+H``, one position per symbol per cell."""
    entry_offset = rules.entry_offset_min * MIN_MS
    hold = cell.h * MIN_MS
    trades: list[Trade] = []
    dropped = {"no_entry_bar": 0, "no_exit_bar": 0, "overlap": 0,
               "funding_ineligible": 0, "past_data_end": 0}
    busy_until = -1
    scheduled: set[int] = set()
    for event in sorted(events, key=lambda e: e.grid_ms):
        entry_ms = event.grid_ms + entry_offset
        if entry_ms in scheduled:
            continue
        if entry_ms < busy_until:
            dropped["overlap"] += 1
            continue
        exit_target = entry_ms + hold
        # Frozen cutoff rule: an entry is forbidden when its scheduled exit is
        # at or past the cutoff. Booking a shortened hold instead would add
        # trades the rule excludes.
        if entry_ms >= window_end_ms or exit_target >= window_end_ms:
            dropped["past_data_end"] += 1
            continue
        entry_px = item.price(entry_ms)
        if entry_px is None:
            dropped["no_entry_bar"] += 1
            continue
        exit_ms = exit_target
        forced = False
        # A missing exit bar (a gap, or a delisting) exits at the first later
        # bar that is still inside the window, else at the last available bar.
        exit_px = item.price(exit_target)
        if exit_px is None:
            bars = item.bar_starts()
            index = int(np.searchsorted(bars, max(exit_target, entry_ms + 1), side="left"))
            if index < len(bars) and bars[index] < window_end_ms:
                exit_ms = int(bars[index])
                exit_px = item.price(exit_ms)
            else:
                last_index = int(np.searchsorted(bars, window_end_ms, side="left")) - 1
                if last_index < 0 or bars[last_index] < entry_ms:
                    dropped["past_data_end"] += 1
                    continue
                exit_ms = int(bars[last_index])
                exit_px = item.price(exit_ms)
                forced = True
        if exit_px is None or exit_ms <= entry_ms:
            dropped["no_exit_bar"] += 1
            continue
        gross = 1e4 * event.direction * (exit_px / entry_px - 1.0)
        cost_1x = round_trip_cost_bps(event.shock_bps, rules)
        cost_2x = round_trip_cost_bps(event.shock_bps, rules, stress=True)
        funding_1x, funding_2x, imputed, eligible = _funding_cost(
            item, entry_ms, exit_ms, event.direction, rules)
        if not eligible:
            dropped["funding_ineligible"] += 1
            continue
        scheduled.add(entry_ms)
        busy_until = exit_ms
        trades.append(Trade(
            cell=cell, symbol=item.symbol, direction=event.direction,
            entry_ms=entry_ms, exit_ms=exit_ms, entry_px=entry_px, exit_px=exit_px,
            gross_bps=gross, cost_1x_bps=cost_1x, cost_2x_bps=cost_2x,
            funding_1x_bps=funding_1x, funding_2x_bps=funding_2x,
            net_1x_bps=gross - cost_1x - funding_1x,
            net_2x_bps=gross - cost_2x - funding_2x,
            imputed_funding=imputed, forced_exit_data_end=forced,
        ))
    return trades, dict(sorted(dropped.items()))


# --------------------------------------------------------------------------
# 8. Statistics and the eight gates
# --------------------------------------------------------------------------


def _phi(z: float) -> float:
    return statistics.NormalDist().cdf(z)


def _phi_inv(p: float) -> float:
    return statistics.NormalDist().inv_cdf(p)


def _mean(values: Sequence[float]) -> float:
    return float(np.mean(values)) if len(values) else 0.0


def _sd(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    value = float(np.std(values, ddof=1))
    return value if math.isfinite(value) else 0.0


def sharpe_unannualised(values: Sequence[float]) -> float:
    """``mean/sd`` in the prereg's unannualised event-day units (0 if sd=0)."""
    if len(values) < 2:
        return 0.0
    sd = _sd(values)
    return _mean(values) / sd if sd > 0 else 0.0


def daily_means(trades: Sequence[Trade], field_name: str = "net_1x_bps"
                ) -> dict[str, float]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for trade in trades:
        buckets[trade.entry_day].append(float(getattr(trade, field_name)))
    return {day: _mean(values) for day, values in buckets.items()}


def day_block_bootstrap_ci(trades: Sequence[Trade], rules: Rules,
                           *, field_name: str = "net_1x_bps",
                           alpha: float = 0.05) -> tuple[float, float]:
    """Day-block bootstrap CI of the mean net trade return (frozen seed)."""
    buckets: dict[str, list[float]] = defaultdict(list)
    for trade in trades:
        buckets[trade.entry_day].append(float(getattr(trade, field_name)))
    days = sorted(buckets)
    if not days:
        return 0.0, 0.0
    rng = random.Random(rules.bootstrap_seed)
    means: list[float] = []
    for _ in range(rules.bootstrap_resamples):
        pooled: list[float] = []
        for _ in range(len(days)):
            pooled.extend(buckets[days[rng.randrange(len(days))]])
        means.append(_mean(pooled))
    means.sort()
    low_index = max(0, int((alpha / 2.0) * len(means)))
    high_index = min(len(means) - 1, int((1.0 - alpha / 2.0) * len(means)))
    return means[low_index], means[high_index]


def deflated_sharpe(selected_sr: float, cell_srs: Mapping[Cell, float],
                    day_values: Sequence[float], n_trials: int) -> dict[str, float]:
    """D1's own DSR: dispersion of its 8 cells, penalised by program trials N.

    Deliberately not ``slow_stats.dsr_detail``: the prereg fixes this exact
    calculation (``V`` over the 8 frozen cells, ``SR0`` from ``N``, then the
    selected cell's skew/kurtosis correction).
    """
    gamma = 0.5772156649
    srs = np.array([cell_srs[cell] for cell in sorted(cell_srs)], dtype=float)
    variance = float(np.var(srs, ddof=1)) if len(srs) > 1 else 0.0
    sr0 = math.sqrt(max(variance, 0.0)) * (
        (1.0 - gamma) * _phi_inv(1.0 - 1.0 / n_trials)
        + gamma * _phi_inv(1.0 - 1.0 / (n_trials * math.e))
    )
    n_days = len(day_values)
    values = np.asarray(day_values, dtype=float)
    skew = float(statistics.mean((values - values.mean()) ** 3)
                 / (values.std(ddof=1) ** 3)) if n_days > 2 and values.std(ddof=1) > 0 else 0.0
    kurt = float(np.mean((values - values.mean()) ** 4)
                 / (values.std(ddof=0) ** 4)) if n_days > 1 and values.std(ddof=0) > 0 else 3.0
    denom = 1.0 - skew * selected_sr + (kurt - 1.0) / 4.0 * selected_sr ** 2
    if n_days < 2 or denom <= 0:
        dsr = 0.0
        denom = max(denom, 0.0)
    else:
        dsr = _phi((selected_sr - sr0) * math.sqrt(n_days - 1) / math.sqrt(denom))
    return {
        "V": variance,
        "SR0": sr0,
        "n_days": float(n_days),
        "skew": skew,
        "kurtosis": kurt,
        "DSR": dsr,
        "denominator": math.sqrt(denom),
    }


def _array_split_sizes(n: int, partitions: int) -> list[int]:
    """``numpy.array_split`` sizes: the remainder goes to the earliest blocks."""
    base = n // partitions
    extra = n % partitions
    return [base + (1 if index < extra else 0) for index in range(partitions)]


def pbo_cscv(daily: Mapping[Cell, Sequence[float]], rules: Rules) -> dict[str, Any]:
    """CSCV probability of backtest overfitting, exactly as the prereg words it."""
    cells = sorted(daily)
    partitions = rules.pbo_partitions
    if len(cells) < 2 or partitions < 2 or partitions % 2:
        return {"PBO": 1.0, "splits": 0, "note": "PBO undefined for this grid"}
    length = min(len(daily[cell]) for cell in cells)
    if length < partitions:
        return {"PBO": 1.0, "splits": 0, "note": "fewer calendar days than partitions"}
    sizes = _array_split_sizes(length, partitions)
    edges = [0]
    for size in sizes:
        edges.append(edges[-1] + size)
    blocks = [list(range(edges[i], edges[i + 1])) for i in range(partitions)]
    series = {cell: list(daily[cell])[:length] for cell in cells}
    splits = 0
    overfit = 0
    for combo in itertools.combinations(range(partitions), partitions // 2):
        in_sample = [index for block in combo for index in blocks[block]]
        out_sample = [index for block in range(partitions) if block not in combo
                      for index in blocks[block]]
        is_sr = {cell: sharpe_unannualised([series[cell][i] for i in in_sample])
                 for cell in cells}
        best = min(cells, key=lambda cell: (-is_sr[cell], cell))
        oos_sr = {cell: sharpe_unannualised([series[cell][i] for i in out_sample])
                  for cell in cells}
        worse = sum(1 for cell in cells
                    if cell != best and oos_sr[cell] < oos_sr[best])
        rank_fraction = worse / (len(cells) - 1)
        splits += 1
        if rank_fraction < 0.5:
            overfit += 1
    return {"PBO": overfit / splits if splits else 1.0, "splits": splits}


@dataclass
class Gates:
    """The eight gates of the frozen spec, each with its own evidence."""

    items: list[dict[str, Any]] = field(default_factory=list)

    def add(self, number: int, name: str, passed: bool | None, detail: str,
            **values: Any) -> None:
        self.items.append({
            "gate": number,
            "name": name,
            "status": "pass" if passed is True else "fail" if passed is False
                      else "not_evaluable",
            "passed": passed,
            "detail": detail,
            **values,
        })

    @property
    def failed(self) -> list[dict[str, Any]]:
        return [item for item in self.items if item["passed"] is False]

    @property
    def not_evaluable(self) -> list[dict[str, Any]]:
        return [item for item in self.items if item["passed"] is None]


def evaluate_cells(trades_by_cell: Mapping[Cell, Sequence[Trade]], rules: Rules, *,
                   n_trials: int | None, n_trials_problem: str | None = None,
                   trial_count_trusted: bool = False,
                   window: tuple[int, int] | None = None,
                   calendar_days: Sequence[str] | None = None) -> dict[str, Any]:
    """Apply the immediate-kill rule, cell selection and the eight gates.

    ``n_trials`` is honoured only when ``trial_count_trusted`` is set, which
    :func:`evaluate_forward` does exactly once, from
    :func:`d1_trials.trial_count_ready`. There is no CLI switch and no other
    caller: a DSR number can only come from the frozen constant plus its
    amending document, never from an argument someone typed.
    """
    if n_trials is not None and not trial_count_trusted:
        raise D1Error(
            "refusing an unverified trial count: N_TRIALS comes only from "
            "src/cryptobot/research/d1_trials.py plus its amending document, "
            "and amendment 2 forbids substituting any other number"
        )
    cells = list(rules.cells)
    day_series = {cell: daily_means(trades_by_cell.get(cell, ())) for cell in cells}
    cell_sr_1x = {cell: sharpe_unannualised(list(day_series[cell].values()))
                  for cell in cells}
    gross = {cell: _mean([t.gross_bps for t in trades_by_cell.get(cell, ())])
             for cell in cells}
    all_in_1x = {cell: _mean([t.cost_1x_bps + t.funding_1x_bps
                              for t in trades_by_cell.get(cell, ())])
                 for cell in cells}
    margin = {cell: gross[cell] - all_in_1x[cell] for cell in cells}
    traded = [cell for cell in cells if trades_by_cell.get(cell)]
    kills = [cell for cell in traded if margin[cell] < 0]
    # Frozen rule: a cell with no trades has no expectancy at all, so it cannot
    # cover its cost either; the kill fires when no traded cell covers cost.
    immediate_kill = bool(traded) and max(margin[cell] for cell in traded) < 0
    doc: dict[str, Any] = {
        "immediate_kill": {
            "fired": bool(immediate_kill),
            "rule": "max_i(gross_i - all_in_cost_1x_i) < 0",
            "per_cell": {
                str(cell): {
                    "trades": len(trades_by_cell.get(cell, ())),
                    "gross_bps": gross[cell],
                    "all_in_cost_1x_bps": all_in_1x[cell],
                    "gross_minus_cost_bps": margin[cell],
                }
                for cell in cells
            },
            "cells_with_negative_margin": [str(cell) for cell in kills],
        },
    }
    if immediate_kill:
        doc["verdict"] = "KILL"
        doc["gates"] = []
        return doc
    doc["immediate_kill"]["note"] = (
        "at least one cell has non-negative gross minus all-in cost, so the "
        "kill rule does not fire on its own"
        if not immediate_kill else ""
    )

    # Selection (prereg: eligible cells only, largest 1x Sharpe, tie by cell).
    eligibility = {}
    for cell in cells:
        chosen = trades_by_cell.get(cell, ())
        days = len(day_series[cell])
        eligibility[cell] = (len(chosen) >= rules.min_events
                             and days >= rules.min_event_days
                             and margin[cell] >= 0)
    eligible = [cell for cell in cells if eligibility[cell]]
    doc["selection"] = {
        "eligible_cells": [str(cell) for cell in eligible],
        "criterion": "largest unannualised 1x day Sharpe among eligible cells, "
                     "ties by lexicographically smallest (W,K,H)",
        "cell_sharpe_1x": {str(cell): cell_sr_1x[cell] for cell in cells},
    }
    if not eligible:
        doc["verdict"] = "UNDERPOWERED"
        doc["gates"] = []
        doc["shortfall_stage"] = "stage0"
        return doc
    selected = min(eligible, key=lambda cell: (-cell_sr_1x[cell], cell))
    chosen = list(trades_by_cell[selected])
    doc["selection"]["selected_cell"] = str(selected)
    doc["selection"]["selected_sharpe_1x"] = cell_sr_1x[selected]

    gates = Gates()
    # Gate 1: sample size.
    gates.add(1, "n >= events and event days",
              len(chosen) >= rules.min_events
              and len(day_series[selected]) >= rules.min_event_days,
              f"{len(chosen)} trades on {len(day_series[selected])} event days "
              f"(needs {rules.min_events} and {rules.min_event_days})",
              trades=len(chosen), event_days=len(day_series[selected]))
    # Gate 2: net of 2x costs.
    mean_2x = _mean([trade.net_2x_bps for trade in chosen])
    gates.add(2, "mean net > 0 at 2x costs", mean_2x > 0,
              f"mean net {mean_2x:.3f} bps at {rules.stress_multiple}x costs",
              mean_net_2x_bps=mean_2x)
    # Gate 3: day-block bootstrap CI at 1x.
    low, high = day_block_bootstrap_ci(chosen, rules)
    gates.add(3, "day-block bootstrap 95% CI lower bound > 0", low > 0,
              f"mean net 1x CI [{low:.3f}, {high:.3f}] bps over "
              f"{rules.bootstrap_resamples} resamples (seed {rules.bootstrap_seed})",
              ci_low_bps=low, ci_high_bps=high)
    # Gate 4: DSR with the program-level trial count.
    day_values = [day_series[selected][day] for day in sorted(day_series[selected])]
    if n_trials is None:
        gates.add(4, f"DSR >= {rules.dsr_min:.2f}", None,
                  f"not evaluated: {n_trials_problem or 'trial count not frozen'}; "
                  f"no DSR number is reported and no PASS is possible until "
                  f"src/cryptobot/research/d1_trials.py carries N_TRIALS",
                  dsr=None, n_trials=None)
    else:
        dsr = deflated_sharpe(cell_sr_1x[selected], cell_sr_1x, day_values, n_trials)
        gates.add(4, f"DSR >= {rules.dsr_min:.2f}", dsr["DSR"] >= rules.dsr_min,
                  f"DSR {dsr['DSR']:.4f} with N={n_trials} (upper bound -> "
                  f"conservative), SR0 {dsr['SR0']:.4f}, V {dsr['V']:.6f}, "
                  f"n_days {int(dsr['n_days'])}, skew {dsr['skew']:.3f}, "
                  f"kurtosis {dsr['kurtosis']:.3f}",
                  dsr=dsr["DSR"], n_trials=n_trials, intermediates=dsr)
    # Gate 5: PBO over the 8 cells on the full calendar-day series.
    calendar = list(calendar_days) if calendar_days is not None else sorted(
        {day for cell in cells for day in day_series[cell]}
    )
    daily_matrix = {
        cell: [day_series[cell].get(day, 0.0) for day in calendar] for cell in cells
    }
    pbo = pbo_cscv(daily_matrix, rules)
    gates.add(5, f"PBO <= {rules.pbo_max:.2f}", pbo["PBO"] <= rules.pbo_max,
              f"PBO {pbo['PBO']:.4f} over {pbo['splits']} CSCV splits"
              + (f" ({pbo['note']})" if pbo.get("note") else ""),
              pbo=pbo["PBO"])
    # Gate 6: positive months on the frozen DEV calendar.
    month_stats = _month_gate(chosen, rules)
    gates.add(6, f">= {rules.months_positive_fraction:.0%} positive months",
              month_stats["fraction"] >= rules.months_positive_fraction,
              month_stats["detail"], fraction=month_stats["fraction"])
    # Gate 7: positive DEV years.
    year_stats = _year_gate(chosen, rules)
    gates.add(7, f">= {rules.min_positive_years} of {rules.year_count} DEV years positive",
              year_stats["positive"] >= rules.min_positive_years,
              year_stats["detail"], positive_years=year_stats["positive"])
    # Gate 8: concentration.
    concentration = _concentration_gate(chosen, rules)
    gates.add(8, "pooled mean > 0 after dropping the top contributors",
              concentration["passed"], concentration["detail"],
              dropped=concentration["dropped"])
    doc["gates"] = gates.items

    if gates.failed:
        doc["verdict"] = "FAIL_DEV"
    elif gates.not_evaluable:
        doc["verdict"] = "BLOCKED"
        doc["verdict_detail"] = "; ".join(item["detail"] for item in gates.not_evaluable)
    else:
        doc["verdict"] = "PASS_DEV"
    return doc


def _month_gate(trades: Sequence[Trade], rules: Rules) -> dict[str, Any]:
    months = _month_keys(rules)
    buckets: dict[str, list[float]] = defaultdict(list)
    for trade in trades:
        buckets[trade.entry_month].append(trade.net_1x_bps)
    positive = [month for month in months
                if buckets.get(month) and _mean(buckets[month]) > 0]
    missing = [month for month in months if not buckets.get(month)]
    fraction = len(positive) / len(months) if months else 0.0
    return {
        "fraction": fraction,
        "positive": len(positive),
        "detail": (
            f"{len(positive)}/{len(months)} frozen-calendar months positive at 1x "
            f"(needs {rules.months_positive_fraction:.0%}); "
            f"{len(missing)} of those months have no trade at all, and the "
            f"prereg counts a month with no trade as not positive"
            if missing else
            f"{len(positive)}/{len(months)} frozen-calendar months positive at 1x"
        ),
    }


def _month_keys(rules: Rules) -> list[str]:
    (start_year, start_month), (end_year, end_month) = rules.month_window
    keys: list[str] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        keys.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    if len(keys) != rules.month_count:
        raise PreregParseError(
            f"month gate: prereg says {rules.month_count} months, "
            f"{rules.month_window} expands to {len(keys)}"
        )
    return keys


def _year_gate(trades: Sequence[Trade], rules: Rules) -> dict[str, Any]:
    buckets: dict[int, list[float]] = defaultdict(list)
    for trade in trades:
        buckets[trade.entry_year].append(trade.net_1x_bps)
    positive = 0
    rows = {}
    for year in rules.dev_years:
        values = buckets.get(year, [])
        ok = len(values) >= rules.year_min_trades and _mean(values) > 0
        positive += int(ok)
        rows[str(year)] = {
            "trades": len(values),
            "mean_net_1x_bps": _mean(values),
            "positive": ok,
        }
    return {
        "positive": positive,
        "detail": (
            f"{positive} of {len(rules.dev_years)} frozen DEV years positive at 1x "
            f"with >= {rules.year_min_trades} trades each; "
            + ", ".join(f"{year}:{row['trades']} trades"
                        for year, row in rows.items())
        ),
        "years": rows,
    }


def _concentration_gate(trades: Sequence[Trade], rules: Rules) -> dict[str, Any]:
    contribution: dict[str, float] = defaultdict(float)
    for trade in trades:
        contribution[trade.symbol] += trade.net_1x_bps
    ranked = sorted(contribution, key=lambda symbol: (-contribution[symbol], symbol))
    dropped = ranked[:rules.concentration_drop]
    remaining = [trade for trade in trades if trade.symbol not in set(dropped)]
    pooled = _mean([trade.net_1x_bps for trade in remaining])
    return {
        "passed": bool(remaining) and pooled > 0,
        "dropped": dropped,
        "detail": (
            f"dropping {', '.join(dropped) or 'nothing'} leaves "
            f"{len(remaining)} trades with pooled mean {pooled:.3f} bps at 1x"
        ),
    }


# --------------------------------------------------------------------------
# 9. The command
# --------------------------------------------------------------------------


def evaluate_forward(root: Path, *, prereg_dir: Path | None = None,
                     n_trials: int | None = None,
                     n_trials_problem: str | None = None,
                     start_ms: int | None = None, end_ms: int | None = None,
                     verify_chunks: bool = True) -> dict[str, Any]:
    """Run D1 over forward recorder data and return the verdict document."""
    rules = load_rules(prereg_dir)
    store = scan_store(Path(root), rules)
    store_start, store_end = store.coverage_ms(store.entries)
    # A requested window is vetted, never silently clamped: asking for data
    # before the forward start is a holdout request and is refused as one.
    window_start = start_ms if start_ms is not None else store_start
    window_end = end_ms if end_ms is not None else store_end
    window_start, window_end = assert_forward_window(window_start, window_end, rules)
    entries = store.window(window_start, window_end)
    if not entries:
        raise StoreError(
            f"no recorder chunks overlap {_iso(window_start)} .. {_iso(window_end)}"
        )

    doc: dict[str, Any] = {
        "hypothesis": "D1 open-interest flush reversal (forward)",
        "prereg": {
            "files": list(rules.files),
            "sha256": dict(rules.hashes),
            "code_sha256": _code_hashes(),
            "note": "every rule below is parsed from these files at run time",
        },
        "protocol": {
            "split": "forward only; sealed holdout never opened",
            "holdout": [_iso(rules.holdout_start_ms), _iso(rules.forward_start_ms)],
            "window": [_iso(window_start), _iso(window_end)],
            "store": str(store.root),
            "manifest_chain_head": store.chain_head,
            "manifest_created_utc": store.created_utc,
            "chunks_in_window": len(entries),
            "records_declared": sum(entry.records for entry in entries),
            "orders": "none - read-only research over recorded public data",
            "gate": "NO-GO (unchanged by this command)",
        },
        "streams": store.stream_names(entries),
        "diagnostic_maker": {
            "implemented": False,
            "why": (
                "the prereg makes the maker-entry variant diagnostic only, "
                "ineligible for selection and unable to revive a KILL; its "
                "absence cannot change any verdict in this document"
            ),
        },
        "rules": {
            "cells": [str(cell) for cell in rules.cells],
            "oi_z_max": rules.oi_z_max,
            "sigma_lookback_days": rules.sigma_lookback_days,
            "sigma_min_fraction": rules.sigma_min_fraction,
            "metrics_lag_min": rules.metrics_lag_min,
            "entry_offset_min": rules.entry_offset_min,
            "universe_size": rules.universe_size,
            "universe_min_age_days": rules.universe_min_age_days,
            "universe_active_utc": (
                f"{rules.universe_active_hhmm[0]:02d}:"
                f"{rules.universe_active_hhmm[1]:02d}"),
            "taker_fee_bps": rules.taker_fee_bps,
            "half_spread_bps": rules.half_spread_bps,
            "slippage_base_bps": rules.slippage_base_bps,
            "slippage_shock_coef": rules.slippage_shock_coef,
            "funding_hours_utc": list(rules.funding_hours),
            "stress_multiple": rules.stress_multiple,
            "dsr_min": rules.dsr_min,
            "pbo_max": rules.pbo_max,
        },
        "trial_count": {
            "N_TRIALS": n_trials,
            "problem": n_trials_problem,
            "source": "src/cryptobot/research/d1_trials.py",
            "label": (
                "conservative: N is an upper bound on trials, so SR0 is at "
                "least as strict as reality" if n_trials is not None
                else "not frozen: DSR is not computed and no PASS is possible"
            ),
        },
        "window_days": round((window_end - window_start) / DAY_MS, 3),
    }

    shortfalls = stream_shortfalls(store, entries, rules)
    if shortfalls:
        doc["stream_shortfalls"] = [item.as_dict() for item in shortfalls]
        doc["verdict"] = "INSUFFICIENT_FORWARD_DATA"
        doc["shortfall_stage"] = "streams"
        return doc

    series, inventory = build_series(store, entries, rules)
    doc["series"] = inventory
    rankings = monthly_rankings(series, rules, window_start, window_end)
    doc["universe"] = {
        "rule": (
            f"top {rules.universe_size} by summed 1d quote_volume over the "
            f"previous full calendar month, every day of that month required, "
            f"listing age >= {rules.universe_min_age_days} days at the start of "
            f"the month, active {rules.universe_active_hhmm[0]:02d}:"
            f"{rules.universe_active_hhmm[1]:02d} UTC on the second calendar day"
        ),
        "months": {key: ranking.as_dict(rules) for key, ranking in sorted(rankings.items())},
        "survivorship": (
            "candidates are the symbols the recorder carries daily klines for; "
            "whether that listing covers delisted USD-M perps is unverified, so "
            "the universe is not claimed unbiased"
        ),
    }
    complete = complete_rankings(rankings, rules)
    doc["universe"]["complete_months"] = sorted(complete)
    doc["universe"]["skipped_months"] = {
        key: {
            "ranked_count": len(ranking.ranked),
            "reason": (
                f"no whole {ranking.prior_month} inside forward data "
                f"(the ranking needs every day of it), so this month takes no "
                f"signals; that is the frozen rule, not a data error"
            ),
        }
        for key, ranking in sorted(rankings.items()) if key not in complete
    }
    universe_problem = universe_shortfall(rankings, rules, window_start)
    if universe_problem is not None:
        doc["stream_shortfalls"] = [universe_problem.as_dict()]
        doc["verdict"] = "INSUFFICIENT_FORWARD_DATA"
        doc["shortfall_stage"] = "universe"
        return doc

    spans = universe_spans(complete)
    events_by_cell: dict[Cell, list[Event]] = {}
    for cell in rules.cells:
        collected: list[Event] = []
        for symbol in sorted(series):
            triggered = detect_events(series[symbol], cell, rules,
                                      window_start_ms=window_start,
                                      window_end_ms=window_end, spans=spans)
            # Stage 0 counts what the no-overlap rule can enter, and nothing else.
            collected.extend(overlap_filtered(triggered, cell, rules,
                                              window_end_ms=window_end))
        events_by_cell[cell] = sorted(collected, key=lambda e: (e.grid_ms, e.symbol))
    stage0 = stage0_report(events_by_cell, rules)
    doc["stage0"] = stage0
    if stage0["eligible_cells"] == 0:
        # The prereg's own word for a data-complete but short sample is
        # UNDERPOWERED; the renderer still leads with the frozen refusal string.
        doc["verdict"] = "UNDERPOWERED"
        doc["shortfall_stage"] = "stage0"
        doc["shortfall"] = [
            f"cell {cell}: {stage0['cells'][str(cell)]['events']} events on "
            f"{stage0['cells'][str(cell)]['event_days']} event days "
            f"(needs {rules.min_events} and {rules.min_event_days})"
            for cell in rules.cells
        ]
        return doc

    trades_by_cell: dict[Cell, list[Trade]] = {}
    exclusions: dict[str, Any] = {}
    for cell in rules.cells:
        cell_trades: list[Trade] = []
        cell_exclusions: dict[str, int] = defaultdict(int)
        per_symbol: dict[str, list[Event]] = defaultdict(list)
        for event in events_by_cell[cell]:
            per_symbol[event.symbol].append(event)
        for symbol, symbol_events in sorted(per_symbol.items()):
            made, dropped = simulate(series[symbol], symbol_events, cell, rules,
                                     window_end_ms=window_end)
            cell_trades.extend(made)
            for key, value in dropped.items():
                cell_exclusions[key] += value
        trades_by_cell[cell] = cell_trades
        exclusions[str(cell)] = dict(sorted(cell_exclusions.items()))
    doc["exclusions"] = exclusions
    doc["cost_2x_note"] = (
        f"{rules.stress_multiple}x stress doubles fees, spread and slippage, "
        f"doubles funding debits and sets funding credits to zero"
    )

    calendar_days = sorted({trade.entry_day for cell in rules.cells
                            for trade in trades_by_cell[cell]})
    result = evaluate_cells(trades_by_cell, rules, n_trials=n_trials,
                            n_trials_problem=n_trials_problem,
                            trial_count_trusted=True,
                            window=(window_start, window_end),
                            calendar_days=calendar_days)
    doc.update(result)
    doc["trade_summary"] = {
        str(cell): {
            "trades": len(trades_by_cell[cell]),
            "imputed_funding": sum(1 for t in trades_by_cell[cell] if t.imputed_funding),
            "forced_exit_data_end": sum(1 for t in trades_by_cell[cell]
                                        if t.forced_exit_data_end),
            "mean_gross_bps": _mean([t.gross_bps for t in trades_by_cell[cell]]),
            "mean_net_1x_bps": _mean([t.net_1x_bps for t in trades_by_cell[cell]]),
            "mean_net_2x_bps": _mean([t.net_2x_bps for t in trades_by_cell[cell]]),
        }
        for cell in rules.cells
    }
    return doc


def render(doc: Mapping[str, Any]) -> str:
    """Human-readable verdict: the verdict line first, then its evidence."""
    verdict = str(doc.get("verdict"))
    lines: list[str] = []
    if verdict == "INSUFFICIENT_FORWARD_DATA":
        lines.append("INSUFFICIENT FORWARD DATA")
    elif verdict == "UNDERPOWERED":
        # The command's refusal string, then the preregistration's own word for
        # the same state, so neither vocabulary is hidden from the reader.
        lines.append("INSUFFICIENT FORWARD DATA")
        lines.append("frozen verdict: UNDERPOWERED (data complete, sample too small)")
    else:
        lines.append(f"VERDICT: {verdict}")
    protocol = doc.get("protocol") or {}
    if protocol:
        lines.append(f"window: {' .. '.join(protocol.get('window', []))} "
                     f"({doc.get('window_days')} days)")
        lines.append(f"store: {protocol.get('store')} "
                     f"({protocol.get('chunks_in_window')} chunks in window)")
    stage = doc.get("shortfall_stage")
    if stage:
        lines.append(f"shortfall stage: {stage}")
    for item in doc.get("stream_shortfalls") or ():
        lines.append(f"  - {item['missing']}: {item['detail']}")
        lines.append(f"    fix: {item['fix']}")
    for line in doc.get("shortfall") or ():
        lines.append(f"  - {line}")
    universe = doc.get("universe") or {}
    if universe.get("months"):
        for month, row in universe["months"].items():
            lines.append(f"universe {month}: {row['ranked_count']}/{row['needed']} "
                         f"ranked from {row['prior_month']} quote volume "
                         f"(active {row['active_from']})")
    stage0 = doc.get("stage0")
    if stage0:
        lines.append("stage 0 (counts only, no forward price read):")
        for cell, row in stage0["cells"].items():
            lines.append(f"  {cell}: {row['events']} events / {row['event_days']} days"
                         f"{'' if row['eligible'] else '  (not eligible)'}")
    kill = doc.get("immediate_kill")
    if kill and kill.get("fired"):
        lines.append("immediate-kill rule fired: no cell covers its 1x all-in cost")
        for cell, row in kill["per_cell"].items():
            lines.append(f"  {cell}: gross {row['gross_bps']:.2f} bps - all-in "
                         f"{row['all_in_cost_1x_bps']:.2f} bps = "
                         f"{row['gross_minus_cost_bps']:.2f} bps")
    selection = doc.get("selection") or {}
    if selection.get("selected_cell"):
        lines.append(f"selected cell: {selection['selected_cell']} "
                     f"(1x day Sharpe {selection['selected_sharpe_1x']:.3f})")
    for gate in doc.get("gates") or ():
        mark = {"pass": "PASS", "fail": "FAIL", "not_evaluable": "N/A"}[gate["status"]]
        lines.append(f"  gate {gate['gate']} {mark}: {gate['name']} - {gate['detail']}")
    trial = doc.get("trial_count") or {}
    if trial:
        if trial.get("N_TRIALS") is None:
            lines.append(f"trial count: NOT FROZEN - {trial.get('problem')}")
        else:
            lines.append(f"trial count: N={trial['N_TRIALS']} ({trial.get('label')})")
    if doc.get("verdict_detail"):
        lines.append(f"blocked: {doc['verdict_detail']}")
    lines.append("orders: none; gate: NO-GO")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cryptobot research d1-eval",
        description="D1 forward evaluator over the sealed recorder chunk chain "
                    "(research/prereg/D1-*.md). Read-only; no orders, no keys.",
    )
    parser.add_argument("--recorder-root", default="data/recorder",
                        help="recorder root holding manifest.json and chunks/")
    parser.add_argument("--prereg-dir", default=None,
                        help="directory holding the frozen D1 preregistration")
    parser.add_argument("--repo-root", default=str(REPO_ROOT),
                        help="checkout root used to locate the trial-count amendment")
    parser.add_argument("--start", default=None,
                        help="ISO instant; earlier data is never read")
    parser.add_argument("--end", default=None, help="ISO instant, exclusive")
    parser.add_argument("--no-verify-chunks", action="store_true",
                        help="skip per-chunk sha256 verification (audits only)")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="write the verdict document to this path")
    args = parser.parse_args(argv)

    def _instant(text: str | None) -> int | None:
        if text is None:
            return None
        stamp = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=dt.UTC)
        return int(stamp.timestamp() * 1000)

    # The only way a DSR number can exist: the frozen constant plus its
    # amending document. There is deliberately no flag to supply one.
    n_trials, problem = d1_trials.trial_count_ready(Path(args.repo_root))
    try:
        doc = evaluate_forward(
            Path(args.recorder_root),
            prereg_dir=Path(args.prereg_dir) if args.prereg_dir else None,
            n_trials=n_trials,
            n_trials_problem=problem,
            start_ms=_instant(args.start),
            end_ms=_instant(args.end),
            verify_chunks=not args.no_verify_chunks,
        )
    except (HoldoutRefusal, StoreError, PreregParseError, D1Error) as error:
        print(f"D1 refused: {error}", file=sys.stderr)
        return 2
    text = render(doc)
    print(text)
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    return 0 if doc["verdict"] not in {"KILL", "FAIL_DEV"} else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
