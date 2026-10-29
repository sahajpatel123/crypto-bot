#!/usr/bin/env python3
"""V-REG forward volatility-spike fade evaluator (six cells, one look).

Prereg: ``research/prereg/V-reg-forward.md`` (FROZEN before any forward
read, freeze commit 9806c81). Every rule, cost term, gate and stopping
condition in this file is transcribed from that document; if the two ever
disagree, the prereg wins and this file is the bug.

Forward window only: files dated strictly after 2026-10-17 (daily) and
months strictly after 2026-10 (monthly). The October monthly funding file
is holdout-dated and is never decoded -- not for warm-up, RV/ADV20/sigma
seeding, funding imputation baselines, or anything else. Every file is checksum-verified against its
manifest record (built from the published .CHECKSUM at fetch) on EVERY run,
including resumed files; unknown or tampered files are refused, never used.

Data source: the Binance Vision CDN only (``data.binance.vision``).
Perp-only execution: UM perp klines + UM funding only. Spot files are
NOT inputs and are never requested.

Usage
-----
    python tools/forward_vreg.py fetch    [--root data/forward_vreg]
    python tools/forward_vreg.py status   [--root data/forward_vreg]
    python tools/forward_vreg.py run      [--root data/forward_vreg] [--force]
    python tools/forward_vreg.py verify   [--root data/forward_vreg]

``fetch`` downloads and checksum-verifies the forward files, writing a
manifest of sha256 digests. ``status`` reports coverage, per-cell round
trips, the blocking gate and days to first possible PASS (no return
statistics: that would be a look). ``run`` fires the one-shot verdict at
90 days + 20 round trips in EVERY cell; it refuses while UNDERPOWERED and
refuses to overwrite a verdict that has already fired. ``verify``
recomputes every number from checksummed inputs and diffs it against the
stored verdict; it never writes, and it refuses while UNDERPOWERED (no
early peeking path).

There is deliberately no ``all`` shortcut that fires the verdict: the one
look stays a deliberate step.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import itertools
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cryptobot.research import slow_stats as ST  # noqa: E402
from cryptobot.research.lake import read_funding_zip, read_klines_zip  # noqa: E402
from cryptobot.research.slow_stats import _phi, _phi_inv  # noqa: E402

# Intentional use of slow_stats' own normal CDF/inverse (exact erf /
# Acklam): the N=12/N=25 DSR sensitivities need q(N) at a different N than
# the vector they average over, so the ratio must use the identical
# approximation. Verified equal to dsr_detail on standard inputs by test.

# -- frozen constants (research/prereg/V-reg-forward.md) ------------------------
VISION = "https://data.binance.vision"
S3LIST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"

CUTOFF_DAY = dt.date(2026, 10, 17)      # forward iff strictly after
CUTOFF_MONTH = "2026-10"                # forward iff strictly after
FORWARD_CLOCK_START = "2026-11-01"      # first day with forward-only funding
UNIVERSE = ("BTCUSDT", "ETHUSDT")

PERP_TAKER_BPS = 7.5
PERP_SPREAD_BPS = 1.0
FILL_BPS = {"perp": PERP_TAKER_BPS + PERP_SPREAD_BPS}
FEES_PER_ROUND_TRIP_BPS = 2.0 * FILL_BPS["perp"]  # 17 bps + impact

R_VALUES = (1.5, 2.0, 2.5)
H_VALUES = (2, 5)
CELLS: tuple[tuple[float, int], ...] = tuple(
    (r, h) for r in R_VALUES for h in H_VALUES)

RV_SHORT_H = 120            # 5d window, hourly bars strictly before D
RV_LONG_H = 1440            # 60d window, hourly bars strictly before D
BAR_PRESENCE_MIN = 0.95     # >= 95% of nominal bars in each RV window
# Integer-exact form of the 95% rule (19/20): float 0.95 * nominal can
# sit on either side of the boundary across platforms, which would move
# the first decision day. n present bars pass iff n * 20 >= 19 * nominal.
BAR_PRESENCE_NUM = 19
BAR_PRESENCE_DEN = 20
ADV_WINDOW = 20
PARTICIPATION_CAP = 0.01     # Q <= 1% of ADV20

E0 = 1000.0
PERIODS = 365
BOOTSTRAP_BLOCK_D = 30
BOOTSTRAP_ROUNDS = 1000
NW_LAG = 30

MIN_FORWARD_DAYS = 90
MIN_ROUND_TRIPS = 20         # in EVERY cell
REGIME_MILESTONE_DAYS = 180  # report-only, never a verdict

GATE_SHARPE = 0.70
GATE_SHARPE_2X = 0.30        # strict: prereg prints "> 0.30"
GATE_DSR = 0.80
GATE_PBO = 0.30
GATE_PLATEAU = 0.70
GATE_DD = 0.35
GATE_MEDIAN_PARTICIPATION = 0.01
GATE_MAX_PARTICIPATION = 0.05
GATE_NW_T = 2.0
GATE_BOOTSTRAP_LOWER_Q = 0.20
YEARS_NEEDED = 2
YEAR_MIN_DAYS = 60
N_DSR = 6                    # the 6 V-REG forward cells (own mechanism family)
PBO_PARTITIONS = 8
PBO_MIN_DAYS = 8             # below this the bespoke PBO refuses (fail-closed)

PREREG_PATH = "research/prereg/V-reg-forward.md"
VERDICT_DIR = ROOT / "reports/hypotheses"
VERDICT_NAME = "V-reg-forward.json"
DEFAULT_ROOT = ROOT / "data/forward_vreg"
TRACKED_MANIFEST = ROOT / "research/forward_vreg_data_manifest.json"

DAY_RE = re.compile(r"-(\d{4}-\d{2}-\d{2})\.zip$")
MONTH_RE = re.compile(r"-(\d{4}-\d{2})\.zip$")


class InputBeforeForwardWindow(RuntimeError):
    """An input file or row predates the forward window. Never tolerated."""


class ChecksumRefusal(RuntimeError):
    """A data file failed checksum/pinning verification. Never tolerated."""


# -- clock --------------------------------------------------------------------
def forward_clock_start() -> pd.Timestamp:
    return pd.Timestamp(FORWARD_CLOCK_START, tz="UTC")


# -- provenance binding -------------------------------------------------------
def _code_hashes() -> dict[str, str]:
    """SHA-256 of this evaluator's own source files, bound into every output.

    Pattern follows d1_eval._code_hashes: the evaluator plus the statistics
    module it actually executes (everything else is stdlib/numpy/pandas).
    """
    hashes: dict[str, str] = {}
    paths = [Path(__file__),
             ROOT / "src/cryptobot/research/slow_stats.py"]
    for path in paths:
        try:
            hashes[path.name] = hashlib.sha256(
                path.read_bytes()).hexdigest()
        except OSError:  # pragma: no cover - frozen bundle without sources
            hashes[path.name] = "unavailable"
    return hashes


def _prereg_sha256() -> str:
    return hashlib.sha256(
        (ROOT / PREREG_PATH).read_bytes()).hexdigest()


def _frozen_config() -> dict:
    """The frozen study parameters, hashed into every output."""
    return {
        "r_values": list(R_VALUES),
        "h_values": list(H_VALUES),
        "universe": list(UNIVERSE),
        "rv_short_h": RV_SHORT_H, "rv_long_h": RV_LONG_H,
        "bar_presence_min": BAR_PRESENCE_MIN,
        "perp_taker_bps": PERP_TAKER_BPS,
        "perp_spread_bps": PERP_SPREAD_BPS,
        "fees_per_round_trip_bps": FEES_PER_ROUND_TRIP_BPS,
        "adv_window": ADV_WINDOW,
        "participation_cap": PARTICIPATION_CAP,
        "e0": E0,
        "min_forward_days": MIN_FORWARD_DAYS,
        "min_round_trips_per_cell": MIN_ROUND_TRIPS,
        "gates": {"sharpe": GATE_SHARPE, "sharpe_2x": GATE_SHARPE_2X,
                  "dsr": GATE_DSR, "pbo": GATE_PBO,
                  "plateau": GATE_PLATEAU, "drawdown": GATE_DD,
                  "median_participation": GATE_MEDIAN_PARTICIPATION,
                  "max_participation": GATE_MAX_PARTICIPATION,
                  "newey_west_t": GATE_NW_T, "years": YEARS_NEEDED,
                  "year_min_days": YEAR_MIN_DAYS},
        "n_dsr": N_DSR, "pbo_partitions": PBO_PARTITIONS,
    }


def _config_sha256() -> str:
    return hashlib.sha256(
        json.dumps(_frozen_config(), sort_keys=True).encode()).hexdigest()


def _bindings() -> dict:
    return {"prereg": PREREG_PATH, "prereg_sha256": _prereg_sha256(),
            "code_sha256": _code_hashes(),
            "config_sha256": _config_sha256()}


# -- Vision fetch (same mechanics as forward_fcarry) -------------------------
class VisionClient:
    def __init__(self, delay: float = 0.30, timeout: float = 60.0,
                 retries: int = 4) -> None:
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.requests = 0

    def _polite(self) -> None:
        time.sleep(self.delay)
        self.requests += 1

    def get(self, url: str) -> bytes:
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            self._polite()
            req = urllib.request.Request(
                url, headers={"User-Agent": "cryptobot-vreg-forward/1"})
            try:
                with urllib.request.urlopen(req,
                                            timeout=self.timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                if exc.code in (403, 404):
                    raise
                last = exc
            except Exception as exc:  # noqa: BLE001 - retried, then raised
                last = exc
            time.sleep(min(2 ** attempt, 8))
        raise RuntimeError(f"GET failed: {url}: {last}")

    def list_keys(self, prefix: str) -> list[dict]:
        out: list[dict] = []
        token: str | None = None
        while True:
            qs = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
            if token:
                qs["continuation-token"] = token
            url = S3LIST + "/?" + urllib.parse.urlencode(qs)
            root = ET.fromstring(self.get(url))
            for obj in root.findall(f"{S3_NS}Contents"):
                key = obj.findtext(f"{S3_NS}Key") or ""
                size = obj.findtext(f"{S3_NS}Size") or "0"
                out.append({"key": key, "size": int(size)})
            trunc = (root.findtext(f"{S3_NS}IsTruncated") or "").lower()
            if trunc != "true":
                return out
            token = root.findtext(f"{S3_NS}NextContinuationToken")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def download_verified(client: VisionClient, key: str, dest: Path) -> dict:
    """Fetch one Vision key; the published .CHECKSUM is read on EVERY call,
    including resumed files, and a mismatch refetches rather than trusts."""
    url = VISION + "/" + key
    want = client.get(url + ".CHECKSUM").decode().split()[0]
    if dest.exists() and _sha256_file(dest) == want:
        return {"sha256": want, "bytes": dest.stat().st_size,
                "resumed": True, "verified": True}
    if dest.exists():
        dest.unlink()
    blob = client.get(url)
    got = _sha256_bytes(blob)
    if got != want:
        raise RuntimeError(
            f"checksum mismatch for {key}: want={want[:16]} got={got[:16]}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(blob)
    os.replace(tmp, dest)
    return {"sha256": got, "bytes": len(blob), "resumed": False,
            "verified": True}


def file_window(name: str) -> tuple[str, str]:
    m = DAY_RE.search(name)
    if m:
        return "day", m.group(1)
    m = MONTH_RE.search(name)
    if m:
        return "month", m.group(1)
    raise ValueError(f"no YYYY-MM[-DD] date in {name!r}")


def is_forward_file(name: str) -> bool:
    kind, stamp = file_window(name)
    if kind == "day":
        return stamp > CUTOFF_DAY.isoformat()
    return stamp > CUTOFF_MONTH


def _safe_forward(name: str) -> bool:
    try:
        return is_forward_file(name)
    except ValueError:
        return False


def assert_forward_files(names: list[str]) -> None:
    bad = [n for n in names if not _safe_forward(n)]
    if bad:
        raise InputBeforeForwardWindow(
            "refusing to run: pre-window input(s) requested: "
            + ", ".join(sorted(bad)[:10]))


def wanted_prefixes(symbol: str) -> dict[str, str]:
    # Perp-only execution: spot files are NOT inputs and are never planned.
    return {"perp": f"data/futures/um/daily/klines/{symbol}/1h/",
            "funding": f"data/futures/um/monthly/fundingRate/{symbol}/"}


def local_path(root: Path, dataset: str, symbol: str, name: str) -> Path:
    return root / dataset / symbol / name


def _row_count(path: Path) -> int:
    try:
        import zipfile
        with zipfile.ZipFile(path) as zf:
            inner = zf.namelist()[0]
            with zf.open(inner) as fh:
                return sum(1 for _ in fh) - 1  # header-excluded decode
    except Exception:  # noqa: BLE001 - best effort; decode errors surface
        return -1


def plan_files(client: VisionClient) -> list[dict]:
    jobs = []
    for symbol in UNIVERSE:
        for dataset, prefix in wanted_prefixes(symbol).items():
            for rec in client.list_keys(prefix):
                name = rec["key"].rsplit("/", 1)[-1]
                if not name.endswith(".zip"):
                    continue  # .CHECKSUM siblings are metadata, not data
                try:
                    ok = is_forward_file(name)
                except ValueError:
                    continue  # undated junk is never planned
                if not ok:
                    continue  # pre-window files are never fetched
                jobs.append({"key": rec["key"], "dataset": dataset,
                             "symbol": symbol, "name": name})
    return jobs


def fetch(root: Path, client: VisionClient,
          manifest_out: Path | None = None) -> dict:
    """Download + verify the forward set; write the manifest (tracked copy)."""
    root = Path(root)
    files = []
    for job in plan_files(client):
        dest = local_path(root, job["dataset"], job["symbol"], job["name"])
        rec = download_verified(client, job["key"], dest)
        rec.update({"key": job["key"], "path": str(dest),
                    "dataset": job["dataset"], "symbol": job["symbol"],
                    "name": job["name"],
                    "url": VISION + "/" + job["key"],
                    "retrieved_at": dt.datetime.now(dt.UTC).isoformat(),
                    "rows": _row_count(dest)})
        files.append(rec)
    manifest = {"format": "cryptobot-vreg-forward-manifest/1",
                "generated_utc": dt.datetime.now(dt.UTC).isoformat(),
                **_bindings(),
                "source": VISION, "cutoff_day": CUTOFF_DAY.isoformat(),
                "cutoff_month": CUTOFF_MONTH,
                "forward_clock_start": FORWARD_CLOCK_START,
                "files": sorted(files, key=lambda r: r["key"])}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=1))
    if manifest_out is not None:
        Path(manifest_out).write_text(json.dumps(manifest, indent=1))
    return manifest


# -- loading (forward-window + checksum enforced, every run) -------------------
def _series_ms(idx: pd.Series) -> pd.Series:
    naive = pd.to_datetime(idx, utc=True).dt.tz_localize(None)
    return naive.astype("datetime64[ms]").astype("int64")


def _read_kline_zip(path: Path) -> pd.DataFrame:
    df = read_klines_zip(path)
    return pd.DataFrame({
        "open_ms": _series_ms(df["open_time"]),
        "open": df["open"].astype(float),
        "close": df["close"].astype(float),
        "quote_volume": df["quote_volume"].astype(float),
    })


def _read_funding_zip(path: Path) -> pd.DataFrame:
    df = read_funding_zip(path)
    return pd.DataFrame({
        "calc_ms": _series_ms(df["calc_time"]),
        "rate": df["last_funding_rate"].astype(float),
    })


def _assert_forward_frame(df: pd.DataFrame, stamp_col: str, src: Path) -> None:
    if df.empty:
        return
    first = pd.Timestamp(int(df[stamp_col].min()), unit="ms", tz="UTC")
    if first <= pd.Timestamp(CUTOFF_DAY, tz="UTC").replace(hour=23, minute=59,
                                                           second=59):
        raise InputBeforeForwardWindow(
            f"{src.name}: earliest row {first.isoformat()} is not after "
            f"{CUTOFF_DAY.isoformat()}")


def file_row_window(name: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    kind, stamp = file_window(name)
    start = pd.Timestamp(stamp, tz="UTC")
    if kind == "day":
        return start, start + pd.Timedelta(days=1)
    return start, start + pd.offsets.MonthBegin(1)


def _assert_rows_in_file_window(df: pd.DataFrame, stamp_col: str,
                                name: str) -> None:
    """Every row must fall inside its own file's date window (renames caught).

    The earliest-row-only check was not enough: a ``2026-10`` funding file
    trimmed to 2026-10-18..31 and renamed ``2026-11`` has a forward-looking
    earliest row and would have passed, importing precisely the 14
    holdout-dated days this prereg permanently excludes.
    """
    if df.empty:
        return
    start, end = file_row_window(name)
    idx = pd.to_datetime(df[stamp_col], unit="ms", utc=True)
    outside = idx[(idx < start) | (idx >= end)]
    if len(outside):
        raise InputBeforeForwardWindow(
            f"{name}: {len(outside)} of {len(idx)} row(s) fall outside the "
            f"file's own window [{start.isoformat()}, {end.isoformat()}); "
            f"first offender {outside.min().isoformat()}")


def _manifest_records(root: Path) -> dict[str, dict]:
    """sha256 records for this root, keyed by relative path.

    The manifest is written by fetch from the published .CHECKSUM values;
    every status/run/verify re-verifies every file against it. Files on
    disk without a record are unpinned inputs and are refused.
    """
    manifest_path = Path(root) / "manifest.json"
    if not manifest_path.exists():
        return {}
    doc = json.loads(manifest_path.read_text())
    out = {}
    for rec in doc.get("files", []):
        rel = str(Path(rec["dataset"]) / rec["symbol"] / rec["name"])
        out[rel] = rec
    return out


def _verify_file(path: Path, rel: str, records: dict[str, dict]) -> dict:
    rec = records.get(rel)
    if rec is None:
        raise ChecksumRefusal(
            f"refusing to run: {rel} has no manifest record (unpinned input)")
    got = _sha256_file(path)
    if got != rec.get("sha256"):
        raise ChecksumRefusal(
            f"refusing to run: checksum mismatch for {rel}: "
            f"manifest={str(rec.get('sha256'))[:16]} disk={got[:16]}")
    return rec


def load_frames(root: Path) -> tuple[dict[str, dict[str, pd.DataFrame]], dict]:
    """Build per-symbol {perp, funding} forward-only frames.

    Every zip is checksum-verified against the manifest before it is
    decoded; returns (frames, data_manifest) for output binding.
    """
    root = Path(root)
    records = _manifest_records(root)
    manifest_files: list[dict] = []
    out: dict[str, dict[str, pd.DataFrame]] = {}
    for symbol in UNIVERSE:
        frames: dict[str, pd.DataFrame] = {}
        for dataset in ("perp", "funding"):
            folder = root / dataset / symbol
            zips = sorted(folder.glob("*.zip")) if folder.exists() else []
            names = [p.name for p in zips]
            assert_forward_files(names)
            for p in zips:
                _verify_file(p, str(Path(dataset) / symbol / p.name),
                             records)
            if dataset == "funding":
                parts = []
                for p in zips:
                    part = _read_funding_zip(p)
                    _assert_rows_in_file_window(part, "calc_ms", p.name)
                    parts.append(part)
                df = (pd.concat(parts, ignore_index=True)
                      if parts else pd.DataFrame(columns=["calc_ms", "rate"]))
                if len(df):
                    _assert_forward_frame(df, "calc_ms", folder)
                    df = df.sort_values("calc_ms").drop_duplicates(
                        "calc_ms").reset_index(drop=True)
                frames["funding"] = df
            else:
                parts = []
                for p in zips:
                    part = _read_kline_zip(p)
                    _assert_rows_in_file_window(part, "open_ms", p.name)
                    parts.append(part)
                df = (pd.concat(parts, ignore_index=True) if parts else
                      pd.DataFrame(columns=["open_ms", "open", "close",
                                            "quote_volume"]))
                if len(df):
                    _assert_forward_frame(df, "open_ms", folder)
                    df = df.sort_values("open_ms").drop_duplicates(
                        "open_ms").reset_index(drop=True)
                frames[dataset] = df
            for p in zips:
                rel = str(Path(dataset) / symbol / p.name)
                manifest_files.append(
                    {"path": rel, "sha256": records[rel]["sha256"],
                     "rows": int(len(parts[zips.index(p)]))})
        out[symbol] = frames
    manifest_files.sort(key=lambda r: r["path"])
    return out, {"files": manifest_files}


def coverage(frames: dict[str, dict[str, pd.DataFrame]]) -> dict:
    out: dict[str, dict] = {}
    for symbol, f in frames.items():
        per: dict[str, dict] = {}
        for dataset in ("perp", "funding"):
            df = f.get(dataset)
            col = {"perp": "open_ms",
                   "funding": "calc_ms"}[dataset]
            if df is None or df.empty:
                per[dataset] = {"rows": 0, "first": None, "last": None}
                continue
            idx = pd.to_datetime(df[col], unit="ms", utc=True)
            per[dataset] = {"rows": int(len(df)),
                            "first": str(idx.min().date()),
                            "last": str(idx.max().date())}
        out[symbol] = per
    return out


# -- the V-REG book (per cell) --------------------------------------------------
@dataclass
class VregConfig:
    e0: float = E0
    r: float = 1.5
    h: int = 2
    adverse_mult: float = 1.0
    adv_window: int = ADV_WINDOW
    participation_cap: float = PARTICIPATION_CAP


@dataclass
class Position:
    symbol: str
    side: int                # +1 LONG / -1 SHORT (== s_pay for funding)
    qty: float               # signed
    entry_day: pd.Timestamp
    entry_time: pd.Timestamp  # open time of the entry bar
    entry_price: float
    entry_notional: float     # Q at entry; denominator for bps stats
    entry_cost: float         # fee+spread+impact cash paid at entry
    mark_prev: float          # last mark used for margin accrual
    funding_cash: float = 0.0  # signed funding cash added since entry
    imputed_n: int = 0


@dataclass
class Book:
    cash: float
    cfg: VregConfig
    positions: dict[str, Position] = field(default_factory=dict)
    fills: list[dict] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    round_trips: int = 0
    hold_days: list[float] = field(default_factory=list)
    funding_income: float = 0.0
    fees_paid: float = 0.0

    def cost_of(self, notional: float, *, sigma: float,
                adv: float) -> tuple[float, float]:
        """(cash cost, participation) for one perp fill of ``notional``."""
        if adv <= 0 or notional <= 0:
            return 0.0, 0.0
        m = self.cfg.adverse_mult
        fee = notional * FILL_BPS["perp"] / 1e4 * m
        participation = notional / adv
        impact = notional * 0.5 * sigma * math.sqrt(participation) * m
        return fee + impact, participation

    def fill(self, *, day: str, symbol: str, notional: float,
             price: float, sigma: float, adv: float) -> tuple[float, float]:
        cost, part = self.cost_of(notional, sigma=sigma, adv=adv)
        self.cash -= cost
        self.fees_paid += cost
        self.fills.append({"day": day, "symbol": symbol, "venue": "perp",
                           "notional": notional, "participation": part,
                           "cost": cost, "sigma_d": sigma, "adv20": adv,
                           "price": price})
        return cost, part


class FundingImputationRefused(RuntimeError):
    """A missing settlement cannot be imputed: no funding observed yet.

    Fail-closed per prereg: the affected forward day cannot count and is
    dropped from the day count, never scored with zero funding.
    """

    def __init__(self, symbol: str, settlement: pd.Timestamp,
                 day: pd.Timestamp) -> None:
        super().__init__(
            f"{symbol}: no funding observed before missing settlement "
            f"{settlement.isoformat()}; forward day {day.date()} cannot "
            f"count")
        self.symbol = symbol
        self.settlement = settlement
        self.day = day


def _trailing_stats(bars: pd.DataFrame, boundary: pd.Timestamp, *,
                    window: int = ADV_WINDOW) -> tuple[float, float]:
    """(sigma_d, ADV20) from bars strictly before ``boundary`` (no fallback)."""
    past = bars[bars.index < boundary]
    if past.empty:
        return 0.0, 0.0
    assert past.index.max() < boundary  # PIT: decision after every input
    day_close = past["close"].resample("1D").last().dropna()
    day_qv = past["quote_volume"].resample("1D").sum(min_count=1).dropna()
    day_close = day_close.tail(window + 1)
    day_qv = day_qv.tail(window)
    if len(day_qv) < window or len(day_close) < 2:
        return 0.0, 0.0
    rets = np.log(day_close.astype(float)).diff().dropna()
    sigma = float(rets.std(ddof=1)) if len(rets) >= 2 else 0.0
    adv = float(day_qv.median())
    return (sigma if sigma > 0 else 0.0), (adv if adv > 0 else 0.0)


def _trailing_from_market(mkt: _Market, day: pd.Timestamp, *,
                          window: int = ADV_WINDOW) -> tuple[float, float]:
    """Vectorized _trailing_stats twin (identical values, sliced arrays)."""
    closes, qvs = mkt.trailing_daily(day, window=window)
    if len(qvs) < window or len(closes) < 2:
        return 0.0, 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        rets = np.diff(np.log(closes.astype(float)))
    rets = rets[~np.isnan(rets)]  # dropna twin (keeps inf, like pandas)
    sigma = float(np.std(rets, ddof=1)) if len(rets) >= 2 else 0.0
    adv = float(np.median(qvs))
    return (sigma if sigma > 0 else 0.0), (adv if adv > 0 else 0.0)


class _Market:
    """Precomputed per-symbol arrays: one O(n log n) build, O(window)
    point-in-time slices after that.

    A decision day needs the 1440h RV window plus 21 daily closes; doing
    full-frame boolean masks and a 1D resample per symbol per day per
    cell is O(days^2) per simulation. The precomputed sorted arrays
    answer every slice with searchsorted; values are identical to the
    mask/resample formulation (pinned by the parity test).
    """

    __slots__ = ("t", "o", "c", "qv", "ret_t", "ret_v", "d_day", "d_close",
                 "d_qv")

    def __init__(self, bars: pd.DataFrame) -> None:
        if bars.empty:
            z64 = np.zeros(0, dtype="datetime64[ms]")
            zf = np.zeros(0, dtype=float)
            self.t = z64
            self.o = zf
            self.c = zf
            self.qv = zf
            self.ret_t = z64
            self.ret_v = zf
            self.d_day = np.zeros(0, dtype="datetime64[D]")
            self.d_close = zf
            self.d_qv = zf
            return
        b = bars.sort_index()
        idx = b.index
        self.t = idx.values.astype("datetime64[ms]")
        self.o = b["open"].to_numpy(dtype=float)
        self.c = b["close"].to_numpy(dtype=float)
        self.qv = b["quote_volume"].to_numpy(dtype=float)
        # Hourly log returns between closes exactly 1h apart (vectorized);
        # gapped pairs are skipped, never interpolated.
        step = np.diff(self.t).astype("timedelta64[ms]").astype(np.int64)
        one_h = np.int64(3_600_000)
        ok = step == one_h
        ratio = self.c[1:] / self.c[:-1]
        rets = np.full(len(ratio), np.nan)
        with np.errstate(divide="ignore", invalid="ignore"):
            np.log(ratio, out=rets, where=(ratio > 0))
        # A return needs two strictly positive closes (reference skips
        # non-positive pairs; a both-negative log would wrongly pass).
        good = (ok & np.isfinite(rets)
                & (self.c[:-1] > 0) & (self.c[1:] > 0))
        self.ret_t = self.t[1:][good]
        self.ret_v = rets[good]
        # Daily last close + summed quote volume per UTC calendar day.
        days = self.t.astype("datetime64[D]")
        uniq, first, counts = np.unique(days, return_index=True,
                                       return_counts=True)
        order = np.argsort(first, kind="stable")
        uniq, first, counts = uniq[order], first[order], counts[order]
        last = first + counts - 1
        self.d_day = uniq
        self.d_close = self.c[last]
        qv_cs = np.concatenate(([0.0], np.cumsum(self.qv)))
        self.d_qv = qv_cs[last + 1] - qv_cs[first]

    def rv_windows(self, day: pd.Timestamp) -> tuple[np.ndarray, int,
                                                    np.ndarray, int]:
        """(short_rets, short_n_bars, long_rets, long_n_bars) strictly
        before ``day``. Point-in-time by construction (asserted)."""
        end = np.datetime64(day.tz_convert(None).to_datetime64(), "ms")
        lo_s = end - np.timedelta64(RV_SHORT_H, "h")
        lo_l = end - np.timedelta64(RV_LONG_H, "h")
        i0 = int(np.searchsorted(self.t, lo_s, side="left"))
        j0 = int(np.searchsorted(self.t, lo_l, side="left"))
        i1 = int(np.searchsorted(self.t, end, side="left"))
        assert i1 == 0 or self.t[i1 - 1] < end  # PIT: inputs before use
        n_s, n_l = i1 - i0, i1 - j0
        if n_l and not np.all(np.isfinite(self.c[j0:i1])):
            # A non-finite close anywhere in the long window poisons the
            # reference std (NaN -> no decision); mirror it fail-closed.
            z = np.zeros(0)
            return z, n_s, z, n_l
        rs0 = int(np.searchsorted(self.ret_t, lo_s, side="left"))
        rs1 = int(np.searchsorted(self.ret_t, end, side="left"))
        rl0 = int(np.searchsorted(self.ret_t, lo_l, side="left"))
        rl1 = rs1
        return (self.ret_v[rs0:rs1], i1 - i0,
                self.ret_v[rl0:rl1], i1 - j0)

    def trailing_daily(self, day: pd.Timestamp, *,
                       window: int) -> tuple[np.ndarray, np.ndarray]:
        """(closes tail(window+1), qv tail(window)) for calendar days
        strictly before ``day``. Identical values to the resample form."""
        end = np.datetime64(day.date(), "D")
        k = int(np.searchsorted(self.d_day, end, side="left"))
        return self.d_close[max(0, k - window - 1):k], \
            self.d_qv[max(0, k - window):k]

    def mark(self, day: pd.Timestamp) -> float:
        end = np.datetime64(day.tz_convert(None).to_datetime64(), "ms")
        k = int(np.searchsorted(self.t, end, side="left")) - 1
        return float(self.c[k]) if k >= 0 else 0.0

    def first_close_in(self, lo: pd.Timestamp, day: pd.Timestamp) -> float:
        lo64 = np.datetime64(lo.tz_convert(None).to_datetime64(), "ms")
        k = int(np.searchsorted(self.t, lo64, side="left"))
        return float(self.c[k]) if k < len(self.c) else 0.0


def _prep(frames: dict[str, pd.DataFrame]) -> dict:
    out = {}
    df = frames.get("perp")
    if df is None or df.empty:
        out["perp"] = pd.DataFrame(columns=["open", "close",
                                            "quote_volume"])
    else:
        d = df.copy()
        d.index = pd.to_datetime(d["open_ms"], unit="ms", utc=True)
        out["perp"] = d[["open", "close", "quote_volume"]].sort_index()
    out["market"] = _Market(out["perp"])
    f = frames.get("funding")
    if f is None or f.empty:
        out["funding"] = pd.Series(dtype=float)
    else:
        s = pd.Series(f["rate"].to_numpy(dtype=float),
                      index=pd.to_datetime(f["calc_ms"], unit="ms", utc=True))
        out["funding"] = s.sort_index()
    return out


def _price_at(bars: pd.DataFrame, boundary: pd.Timestamp,
              column: str = "close") -> float:
    past = bars[bars.index < boundary]
    if past.empty:
        return 0.0
    return float(past[column].iloc[-1])


def _fill_bar(bars: pd.DataFrame,
              boundary: pd.Timestamp) -> tuple[pd.Timestamp, float]:
    """(open time, open price) of the first bar at/after ``boundary``.

    Falls back to (``boundary``, last close) when no later bar exists
    (the final study day): time never falls back before the decision,
    so settlement inclusion (entry_time, exit_time] stays well defined.
    """
    at_or_after = bars[bars.index >= boundary]
    if not at_or_after.empty:
        return at_or_after.index[0], float(at_or_after["open"].iloc[0])
    return boundary, _price_at(bars, boundary)


def _fill_bar_price(bars: pd.DataFrame, boundary: pd.Timestamp) -> float:
    return _fill_bar(bars, boundary)[1]


def decision_days(perp: pd.DataFrame) -> list[pd.Timestamp]:
    if perp.empty:
        return []
    days = pd.date_range(perp.index.min().floor("D"),
                         perp.index.max().floor("D"), freq="D")
    return [d for d in days if d >= forward_clock_start()]


def _day_has_inputs(prep: dict, day: pd.Timestamp) -> bool:
    """A forward day needs every input: perp bars plus a settlement.

    Bars alone are not a day (no funding to charge the book); funding
    alone is not a day (the mark needs perp bars inside the preceding
    forward day). Both symbols are required: the book is fixed BOTH.
    Counting a day without its marks scores it off a stale price.
    """
    lo, hi = day - pd.Timedelta(days=1), day
    for s in UNIVERSE:
        p = prep.get(s)
        if p is None or p["perp"].empty:
            return False
        has_bars = len(
            p["perp"][(p["perp"].index >= lo) & (p["perp"].index < hi)]) > 0
        has_funding = (not p["funding"].empty and len(
            p["funding"][(p["funding"].index > lo)
                          & (p["funding"].index <= hi)]) > 0)
        if not (has_bars and has_funding):
            return False
    return True


def study_days(prep: dict) -> list[pd.Timestamp]:
    """The shared study clock over the full universe (all cells agree)."""
    days: list[pd.Timestamp] = []
    for s in UNIVERSE:
        if "perp" in prep.get(s, {}):
            days = sorted(set(days) | set(decision_days(prep[s]["perp"])))
    return [d for d in days if _day_has_inputs(prep, d)]


def _presence_ok(n_present: int, nominal: int) -> bool:
    """>= 95% of nominal bars present, in exact integer arithmetic."""
    return n_present * 20 >= 19 * nominal


def _window_returns(bars: pd.DataFrame, day: pd.Timestamp,
                    window_h: int) -> tuple[list[float], int]:
    """Hourly log returns over the ``window_h`` hours strictly before ``day``.

    Returns (returns, n_bars_present). A return links two closes exactly
    1h apart; gapped pairs are skipped, never interpolated. Point-in-time:
    every bar used opens strictly before ``day`` (asserted).
    """
    lo = day - pd.Timedelta(hours=window_h)
    in_window = bars[(bars.index >= lo) & (bars.index < day)]
    n_present = len(in_window)
    if in_window.empty:
        return [], 0
    assert in_window.index.max() < day  # PIT: decision after every input
    ext = bars[(bars.index >= lo - pd.Timedelta(hours=1))
               & (bars.index < day)].sort_index()
    closes = ext["close"].to_numpy(dtype=float)
    idx = ext.index
    rets = []
    for i in range(1, len(closes)):
        if idx[i] - idx[i - 1] != pd.Timedelta(hours=1):
            continue  # gapped pair: skipped, never interpolated
        if closes[i - 1] <= 0 or closes[i] <= 0:
            continue
        rets.append(float(math.log(closes[i] / closes[i - 1])))
    return rets, n_present


def _rv_signal_from_market(mkt: _Market, day: pd.Timestamp) -> dict | None:
    """Vectorized _rv_signal twin (identical values, searchsorted slices)."""
    rets_s, n_s, rets_l, n_l = mkt.rv_windows(day)
    if not _presence_ok(n_s, RV_SHORT_H):
        return None
    if not _presence_ok(n_l, RV_LONG_H):
        return None
    if len(rets_s) < 2 or len(rets_l) < 2:
        return None
    rv_s = float(np.std(rets_s, ddof=1))
    rv_l = float(np.std(rets_l, ddof=1))
    if not math.isfinite(rv_s) or not math.isfinite(rv_l) or rv_l <= 0:
        return None
    lo_s = day - pd.Timedelta(hours=RV_SHORT_H)
    first_close = mkt.first_close_in(lo_s, day)
    last_close = mkt.mark(day)
    if first_close <= 0 or last_close <= 0:
        return None
    tr = float(math.log(last_close / first_close))
    if not math.isfinite(tr):
        return None
    return {"ratio": rv_s / rv_l, "tr": tr,
            "rv_short": rv_s, "rv_long": rv_l}


def _rv_signal(bars: pd.DataFrame,
               day: pd.Timestamp) -> dict | None:
    """Vol-expansion signal inputs for one symbol at decision day ``day``.

    Returns None when no decision is possible (windows unfilled,
    RV_long <= 0, or degenerate returns). Otherwise
    {ratio, tr, rv_short, rv_long}: Ratio(D) = RV_short/RV_long and the
    trailing 120h log return TR(D). Fail-closed: anything short of the
    frozen requirements is no decision, never a forced trade.
    """
    if bars.empty:
        return None
    rets_s, n_s = _window_returns(bars, day, RV_SHORT_H)
    rets_l, n_l = _window_returns(bars, day, RV_LONG_H)
    if not _presence_ok(n_s, RV_SHORT_H):
        return None
    if not _presence_ok(n_l, RV_LONG_H):
        return None
    if len(rets_s) < 2 or len(rets_l) < 2:
        return None
    rv_s = float(np.std(rets_s, ddof=1))
    rv_l = float(np.std(rets_l, ddof=1))
    if not math.isfinite(rv_s) or not math.isfinite(rv_l) or rv_l <= 0:
        return None
    lo_s = day - pd.Timedelta(hours=RV_SHORT_H)
    in_short = bars[(bars.index >= lo_s) & (bars.index < day)]
    first_close = float(in_short["close"].iloc[0])
    last_close = _price_at(bars, day)
    if first_close <= 0 or last_close <= 0:
        return None
    tr = float(math.log(last_close / first_close))
    if not math.isfinite(tr):
        return None
    return {"ratio": rv_s / rv_l, "tr": tr,
            "rv_short": rv_s, "rv_long": rv_l}

def _expected_settlements(lo: pd.Timestamp,
                          hi: pd.Timestamp) -> list[pd.Timestamp]:
    """The 8h funding grid (00/08/16 UTC) strictly inside (``lo``, ``hi``]."""
    return [t for t in (lo + pd.Timedelta(hours=h) for h in (8, 16, 24))
            if lo < t <= hi]


def _funding_accrual(funding: pd.Series, *, entry_time: pd.Timestamp,
                     lo: pd.Timestamp, hi: pd.Timestamp,
                     exit_bound: pd.Timestamp | None,
                     qty: float, side: int, mark: float,
                     adverse: bool, symbol: str,
                     day: pd.Timestamp) -> tuple[float, int]:
    """Signed funding cash added over (``lo``, ``hi``] for one position.

    Observed settlements charge s_pay * rate (LONG pays +rate, SHORT
    receives). A missing expected settlement charges an adverse debit:
    the largest absolute rate observed SO FAR (point-in-time, strictly
    before the missing slot), both sides pay, flagged by the count.
    Never books missing funding as zero. If nothing has been observed
    yet, the imputation is REFUSED (fail-closed: the day cannot count).
    At 2x, funding debits double and credits go to zero.
    """
    if mark <= 0 or qty == 0:
        return 0.0, 0
    total, imputed = 0.0, 0
    for slot in _expected_settlements(lo, hi):
        if slot <= entry_time:
            continue
        if exit_bound is not None and slot > exit_bound:
            continue
        if slot in funding.index:
            v = funding.loc[slot]
            rate = float(np.atleast_1d(np.asarray(v, dtype=float))[0])
            signed_cost = side * rate * abs(qty) * mark
            delta = -signed_cost
            if adverse:
                delta = 2.0 * delta if delta < 0 else 0.0
            total += delta
            continue
        if funding.empty:
            raise FundingImputationRefused(symbol, slot, day)
        pit = funding[funding.index < slot]
        if pit.empty:
            raise FundingImputationRefused(symbol, slot, day)
        assert pit.index.max() < slot  # PIT: baseline strictly before use
        worst = float(np.abs(pit.to_numpy(dtype=float)).max())
        delta = -worst * abs(qty) * mark  # both sides pay the adverse debit
        if adverse:
            delta *= 2.0
        total += delta
        imputed += 1
    return total, imputed


def simulate(frames_by_symbol: dict[str, dict[str, pd.DataFrame]],
             cfg: VregConfig,
             exclude_days: set[pd.Timestamp] | None = None) -> dict:
    """Run one frozen V-REG cell book point-in-time (ledger + audit).

    Fixed BOTH-symbols book, perp-only: equity is cash at all times
    (variation margin settles daily). Same-day sequencing: scheduled
    exits process before entries are evaluated.
    """
    prep = {s: _prep(f) for s, f in frames_by_symbol.items()}
    excluded = exclude_days or set()
    days = [d for d in study_days(prep) if d not in excluded]
    adverse = cfg.adverse_mult != 1.0
    book = Book(cash=cfg.e0, cfg=cfg)
    rows: list[dict] = []
    prev_equity = cfg.e0
    for day in days:
        # 1) accrue margin + funding over (day-1d, day] for open positions.
        # Exits are known before accrual so the exit bound is exact.
        exits: dict[str, tuple[pd.Timestamp, float]] = {}
        for symbol, pos in book.positions.items():
            if day >= pos.entry_day + pd.Timedelta(days=cfg.h):
                exits[symbol] = _fill_bar(prep[symbol]["perp"], day)
        for symbol, pos in list(book.positions.items()):
            p = prep[symbol]
            mark_now = _price_at(p["perp"], day)
            book.cash += pos.qty * (mark_now - pos.mark_prev)
            exit_bound = exits[symbol][0] if symbol in exits else None
            delta, n_imp = _funding_accrual(
                p["funding"], entry_time=pos.entry_time,
                lo=day - pd.Timedelta(days=1), hi=day,
                exit_bound=exit_bound, qty=pos.qty, side=pos.side,
                mark=mark_now, adverse=adverse, symbol=symbol, day=day)
            book.cash += delta
            book.funding_income += delta
            pos.funding_cash += delta
            pos.imputed_n += n_imp
            pos.mark_prev = mark_now
        equity = book.cash
        # 2) scheduled exits first (a symbol exiting today is flat for
        # today's decision and IS eligible for a new entry at D).
        for symbol in UNIVERSE:
            if symbol not in exits:
                continue
            pos = book.positions.pop(symbol)
            p = prep[symbol]
            exit_time, exit_px = exits[symbol]
            sigma, adv = _trailing_from_market(p["market"], day)
            book.cash += pos.qty * (exit_px - pos.mark_prev)
            exit_cost, _ = book.fill(
                day=str(day.date()), symbol=symbol,
                notional=abs(pos.qty) * exit_px, price=exit_px,
                sigma=sigma, adv=adv)
            side = pos.side
            gross_bps = 1e4 * side * (exit_px / pos.entry_price - 1.0)
            allin_bps = ((pos.entry_cost + exit_cost - pos.funding_cash)
                         / pos.entry_notional * 1e4)
            book.trades.append({
                "symbol": symbol, "side": "LONG" if side > 0 else "SHORT",
                "entry_day": str(pos.entry_day.date()),
                "exit_day": str(day.date()),
                "entry_price": pos.entry_price, "exit_price": exit_px,
                "qty": pos.qty, "notional": pos.entry_notional,
                "gross_bps": gross_bps, "allin_bps": allin_bps,
                "net_bps": gross_bps - allin_bps,
                "imputed_funding": pos.imputed_n > 0,
                "n_imputed": pos.imputed_n})
            book.round_trips += 1
            book.hold_days.append(
                float((day - pos.entry_day) / pd.Timedelta(days=1)))
        # 3) entries: flat symbols whose vol ratio clears R fade the move.
        equity = book.cash
        for symbol in UNIVERSE:
            if symbol in book.positions:
                continue
            p = prep.get(symbol)
            if not p or p["perp"].empty:
                continue
            sig = _rv_signal_from_market(p["market"], day)
            if sig is None or sig["ratio"] < cfg.r:
                continue
            tr = sig["tr"]
            if tr == 0.0:
                continue  # exact-zero trailing move: no trade
            side = 1 if tr < 0 else -1
            sigma, adv = _trailing_from_market(p["market"], day)
            if not (sigma > 0 and adv > 0):
                continue  # ADV20/sigma windows must be filled too
            notional = min(0.5 * equity, cfg.participation_cap * adv)
            if notional <= 0:
                continue
            entry_time, entry_px = _fill_bar(p["perp"], day)
            if entry_px <= 0:
                continue
            qty = side * notional / entry_px
            entry_cost, _ = book.fill(
                day=str(day.date()), symbol=symbol, notional=notional,
                price=entry_px, sigma=sigma, adv=adv)
            book.positions[symbol] = Position(
                symbol=symbol, side=side, qty=qty, entry_day=day,
                entry_time=entry_time, entry_price=entry_px,
                entry_notional=notional, entry_cost=entry_cost,
                mark_prev=entry_px)
        equity = book.cash
        rows.append({"day": str(day.date()),
                     "equity": equity,
                     "net_ret": (equity / prev_equity - 1.0)
                     if prev_equity > 0 else 0.0,
                     "open_positions": sorted(book.positions),
                     "fills": len([f for f in book.fills
                                   if f["day"] == str(day.date())])})
        prev_equity = equity
    return {"rows": rows, "fills": book.fills, "trades": book.trades,
            "book": book, "round_trips": book.round_trips,
            "funding_income": book.funding_income,
            "fees_paid": book.fees_paid,
            "mean_hold_days": (float(np.mean(book.hold_days))
                               if book.hold_days else 0.0)}


def _run_cell_set(frames_by_symbol: dict[str, dict[str, pd.DataFrame]],
                  *, adverse: bool) -> tuple[dict, list[str]]:
    """Run all 6 cells with one shared, fail-closed study clock.

    A funding-imputation refusal drops the affected forward day from the
    day count for every cell (never scored with zero funding) and the
    set re-runs; study-day funding cover makes refusals unreachable in
    practice, so this loop is defense in depth, exercised by test stubs.
    Returns (per-cell results, dropped day strings).
    """
    excluded: set[pd.Timestamp] = set()
    for _ in range(1001):
        try:
            out = {}
            for cell in CELLS:
                r, h = cell
                cfg = VregConfig(r=r, h=h,
                                 adverse_mult=2.0 if adverse else 1.0)
                out[cell] = simulate(frames_by_symbol, cfg,
                                     exclude_days=excluded)
            return out, sorted(str(d.date()) for d in excluded)
        except FundingImputationRefused as exc:
            excluded.add(exc.day)
    raise RuntimeError("imputation-refusal loop did not converge")


# -- gates ---------------------------------------------------------------------
def _cell_key(cell: tuple[float, int]) -> str:
    return f"R={cell[0]:g}/H={cell[1]}"


# NOTE: V-REG reuses no external number as evidence. There are no B4/B4b
# readers here by design: Gate 3 counts N = 6 = the 6 V-REG forward cells
# (own mechanism family), and the trial Sharpe vector is the 6 V-REG
# forward cell Sharpes. Any future "external Sharpe" input would violate
# the prereg's refusal list; the no-external-numbers test pins this.


def _qterm(k: int) -> float:
    """The Bailey-Lopez de Prado trial-count term (same _phi_inv as DSR)."""
    gamma = 0.5772156649
    return ((1 - gamma) * _phi_inv(1 - 1 / k)
            + gamma * _phi_inv(1 - 1 / (k * math.e)))


def _dsr_with_n(selected_returns: list[float], vector_for_v: list[float],
                n_for_q: int, *, hold_days: float | None) -> dict:
    """DSR with V averaged over ``vector_for_v`` and q() at ``n_for_q``.

    Identical to slow_stats.dsr_detail when n_for_q == len(vector); the
    N=12/N=25 report-only sensitivities need the decoupled form. Equality
    with dsr_detail on standard inputs is pinned by test, so this cannot
    silently diverge.
    """
    base = ST.dsr_detail(list(selected_returns), list(vector_for_v),
                         hold_days=hold_days)
    k = int(base["n_trials"])
    if n_for_q == k or k <= 1 or base["expected_max"] == 0.0:
        out = dict(base)
        out["n_for_q"] = k
        return out
    ratio = _qterm(n_for_q) / _qterm(k)
    expected_max = float(base["expected_max"]) * ratio
    inner = float(base["inner"])
    n_eff = float(base["n_eff"])
    sr = float(base["sr"])
    if inner <= 0 or n_eff <= 1:
        dsr = 1.0 if sr > expected_max else 0.0
    else:
        stat = (sr - expected_max) * math.sqrt(n_eff - 1) / math.sqrt(inner)
        dsr = _phi(stat)
    out = dict(base)
    out.update({"expected_max": expected_max, "dsr": dsr,
                "n_for_q": n_for_q})
    return out


def _pbo_bespoke(cell_returns: dict[tuple[float, int], list[float]]) -> dict:
    """Bespoke Gate-4 PBO, implemented VERBATIM from the prereg.

    CSCV over the 6 cells on the full calendar-day series of mean net daily
    return. 8 consecutive partitions with numpy.array_split semantics
    (sizes differ by at most one day; remainder days go to the earliest
    partitions). All 70 ways to choose 4 partitions in-sample; the
    highest in-sample daily Sharpe is selected (exact ties broken by
    lexicographically smallest (R, H)).
    lambda = other cells with strictly lower OOS Sharpe, divided by 5.
    The selected cell takes the lowest rank within its OOS tie group;
    tied cells do not count as lower-scoring competitors; an all-tied
    OOS set has lambda = 0. PBO = fraction of splits with lambda < 0.5.
    Deterministic (no seed). Substituting slow_stats.pbo_cscv is
    FORBIDDEN (opposite lambda scale, different block edges).

    Returns {pbo, lambdas, best_keys, n_splits, edges}; the gate consumes
    ["pbo"]. Refuses (fail-closed) on short/ragged/non-finite input.
    """
    keys = sorted(cell_returns)
    if len(keys) != len(CELLS):
        raise ValueError(f"PBO needs the 6 frozen cells, got {len(keys)}")
    series = [list(cell_returns[k]) for k in keys]
    n = len(series[0])
    if any(len(s) != n for s in series):
        raise ValueError("PBO needs equal-length cell series")
    if n < PBO_MIN_DAYS:
        raise ValueError(f"PBO needs >= {PBO_MIN_DAYS} days, got {n}")
    for s in series:
        for v in s:
            if not math.isfinite(float(v)):
                raise ValueError("PBO requires finite returns")
    base, rem = divmod(n, PBO_PARTITIONS)
    sizes = [base + (1 if i < rem else 0) for i in range(PBO_PARTITIONS)]
    edges = list(itertools.accumulate([0] + sizes))
    blocks = [list(range(edges[i], edges[i + 1]))
              for i in range(PBO_PARTITIONS)]
    lambdas: list[float] = []
    best_keys: list[tuple[float, int]] = []
    for combo in itertools.combinations(range(PBO_PARTITIONS),
                                        PBO_PARTITIONS // 2):
        in_set = set(combo)
        is_idx = [i for b in combo for i in blocks[b]]
        oos_idx = [i for b in range(PBO_PARTITIONS) if b not in in_set
                   for i in blocks[b]]
        is_sr = [ST.sharpe([series[c][i] for i in is_idx], PERIODS)
                 for c in range(len(keys))]
        order = sorted(range(len(keys)),
                       key=lambda c: (-is_sr[c], keys[c][0], keys[c][1]))
        best = order[0]
        best_keys.append(keys[best])
        oos_sr = [ST.sharpe([series[c][i] for i in oos_idx], PERIODS)
                  for c in range(len(keys))]
        lower = sum(1 for c in range(len(keys))
                    if c != best and oos_sr[c] < oos_sr[best])
        lambdas.append(lower / 5.0)
    return {"pbo": sum(1 for lam in lambdas if lam < 0.5) / len(lambdas),
            "lambdas": lambdas, "best_keys": best_keys,
            "n_splits": len(lambdas), "edges": edges}


def _plateau_detail(cell_sharpes: dict[tuple[float, int], float]) -> dict:
    """plateau_fraction over the 3x2 grid, fail-closed on a bad shape.

    Cells are inserted in (R, H) order so the best-cell tie-break matches
    the selection rule (lexicographically smallest).
    """
    ordered = {c: cell_sharpes[c] for c in sorted(cell_sharpes)}
    if any(not math.isfinite(float(v)) for v in ordered.values()):
        raise ValueError("plateau refused: non-finite input Sharpe")
    try:
        value = ST.plateau_fraction(ordered)
    except Exception as exc:
        raise ValueError(f"plateau refused: {exc}") from exc
    if not math.isfinite(float(value)):
        raise ValueError("plateau refused: non-finite fraction")
    keys = list(ordered)
    best = max(keys, key=lambda k: ordered[k])
    neigh = [k for k in keys if k != best and sum(
        1 for a, b in zip(k, best, strict=True) if a != b) == 1]
    return {"value": float(value),
            "best": _cell_key(best),
            "neighbours": [_cell_key(k) for k in neigh],
            "positive_neighbours": sum(1 for k in neigh
                                       if ordered[k] > 0)}


def _select_cell(cell_sharpes: dict[tuple[float, int], float],
                 eligible: set[tuple[float, int]]) -> tuple[float, int]:
    """Largest 1x Sharpe among eligible cells; ties to lexicographically
    smallest (R, H). Non-finite never wins."""
    def key(cell: tuple[float, int]) -> tuple[float, float, int]:
        sr = cell_sharpes.get(cell, float("-inf"))
        sr = sr if math.isfinite(sr) else float("-inf")
        return (-sr, cell[0], cell[1])
    return min(eligible, key=key)


def _participation_stats(fills: list[dict]) -> dict:
    parts = [f["participation"] for f in fills if f["participation"] > 0]
    if not parts:
        return {"n": 0, "median": None, "max": None}
    return {"n": len(parts), "median": float(np.median(parts)),
            "max": float(max(parts))}


def years_assessable_forward_day() -> int:
    """Forward days needed before gate 6 (>= 2 positive years) exists.

    Under the 2026-11-01 clock: 2026 supplies 61 forward days, and 2027
    reaches 60 forward days on 2027-03-01, forward day 61 + 60 = 121.
    A 90-day look cannot PASS; a PASS first becomes possible on day 121.
    """
    cur = pd.Timestamp(FORWARD_CLOCK_START)
    elapsed = 0
    eligible = 0
    for _ in range(50):
        year_end = pd.Timestamp(year=cur.year + 1, month=1, day=1)
        span = int((year_end - cur) / pd.Timedelta(days=1))
        if span >= YEAR_MIN_DAYS:
            eligible += 1
            if eligible >= YEARS_NEEDED:
                return elapsed + YEAR_MIN_DAYS
        elapsed += span
        cur = year_end
    raise RuntimeError("years gate is unreachable at this YEAR_MIN_DAYS")


def years_assessable_on() -> dt.date:
    first = pd.Timestamp(FORWARD_CLOCK_START)
    return (first + pd.Timedelta(days=years_assessable_forward_day() - 1)).date()


def _year_gate(rows: list[dict]) -> tuple[bool | None, dict]:
    """>= 2 positive calendar years with >= 60 forward days each."""
    by_year: dict[int, list[float]] = {}
    for r in rows:
        by_year.setdefault(int(r["day"][:4]), []).append(r["net_ret"])
    stats = {y: {"days": len(v),
                 "net": float(np.prod([1 + x for x in v]) - 1.0)}
             for y, v in sorted(by_year.items())}
    eligible = {y: s for y, s in stats.items() if s["days"] >= YEAR_MIN_DAYS}
    if len(eligible) < YEARS_NEEDED:
        return None, stats
    return sum(1 for s in eligible.values() if s["net"] > 0) >= YEARS_NEEDED, stats


def _gate(value, test) -> bool | None:
    if value is None:
        return None
    return bool(test(float(value)))


def _gross_turnover_per_year(rows: list[dict], fills: list[dict],
                             e0: float) -> float:
    """Reported, never gated (the B4 kill this study refuses to reuse)."""
    if not rows or not fills:
        return 0.0
    years = len(rows) / 365.0
    eq = [r["equity"] for r in rows]
    avg_equity = float(np.mean(eq)) if eq else e0
    if years <= 0 or avg_equity <= 0:
        return 0.0
    traded = sum(f["notional"] for f in fills)
    return float(traded / avg_equity / years)


def _median_adv(fills: list[dict]) -> float:
    advs = [f["adv20"] for f in fills if f.get("adv20")]
    return float(np.median(advs)) if advs else 0.0


def _decide(*, powered: bool, gates: dict) -> tuple[str, str]:
    failed = sorted(k for k, v in gates.items() if v is False)
    unknown = sorted(k for k, v in gates.items() if v is None)
    if not powered:
        return ("UNDERPOWERED",
                "stopping rule: <90 forward days or a cell <20 round trips")
    if failed:
        return "KILLED", "failed gate(s): " + ", ".join(failed)
    if unknown:
        return ("UNDERPOWERED",
                "gate(s) not yet assessable: " + ", ".join(unknown))
    return "PASS", "every gate passed"


def _immediate_kill(cells: dict) -> dict:
    """GROSS/ALLIN immediate-kill inputs, evaluated ONCE at power.

    For each cell: GROSS_i = mean gross trade return (bps of position
    notional) over completed round trips (both symbols/sides pooled,
    open excluded); ALLIN_i = mean all-in cost in bps over the SAME
    round trips. Kill iff max(GROSS_i - ALLIN_i) < 0. Never called
    before power (never on thin pre-power data).
    """
    per_cell = {}
    for cell in CELLS:
        trades = cells[cell]["out"]["base"]["trades"]
        gross = [t["gross_bps"] for t in trades]
        allin = [t["allin_bps"] for t in trades]
        mean_g = float(np.mean(gross)) if gross else 0.0
        mean_a = float(np.mean(allin)) if allin else 0.0
        per_cell[_cell_key(cell)] = {
            "gross_bps": mean_g, "allin_bps": mean_a,
            "net_bps": mean_g - mean_a, "n_round_trips": len(trades)}
    best = max(v["net_bps"] for v in per_cell.values())
    return {"per_cell": per_cell, "max_net_bps": best,
            "triggered": bool(best < 0)}


def evaluate_frames(frames_by_symbol: dict[str, dict[str, pd.DataFrame]],
                    *, as_of: str | None = None) -> dict:
    """Full gate evaluation. Returns the verdict document (not yet written)."""
    prep = {s: _prep(f) for s, f in frames_by_symbol.items()}
    base_set, dropped = _run_cell_set(frames_by_symbol, adverse=False)
    adverse_set, dropped_2x = _run_cell_set(frames_by_symbol, adverse=True)
    assert dropped == dropped_2x  # one shared clock at both cost levels
    dropped_set = set(dropped)
    days = [d for d in study_days(prep) if str(d.date()) not in dropped_set]
    forward_days = len(days)
    cells: dict[tuple[float, int], dict] = {}
    for cell in CELLS:
        out = {"base": base_set[cell], "adverse": adverse_set[cell]}
        rows = out["base"]["rows"]
        net = np.array([r["net_ret"] for r in rows], dtype=float) if rows \
            else np.zeros(0)
        net2 = np.array([r["net_ret"] for r in out["adverse"]["rows"]],
                        dtype=float) if out["adverse"]["rows"] else np.zeros(0)
        cells[cell] = {"out": out, "rows": rows, "net": net, "net2": net2,
                       "round_trips": int(out["base"]["round_trips"])}
    powered_days = forward_days >= MIN_FORWARD_DAYS
    powered_rt = all(c["round_trips"] >= MIN_ROUND_TRIPS
                     for c in cells.values())
    powered = bool(powered_days and powered_rt)

    sharpes_1x = {cell: ST.sharpe(c["net"], PERIODS)
                  if len(c["net"]) >= 2 else 0.0
                  for cell, c in cells.items()}
    eligible = {cell for cell in CELLS
                if cells[cell]["round_trips"] >= MIN_ROUND_TRIPS}
    selected = _select_cell(sharpes_1x, eligible or set(CELLS))
    sel = cells[selected]
    rows, net, net2 = sel["rows"], sel["net"], sel["net2"]

    # Immediate-kill: exactly ONCE at the first powered run, before gates
    # 1-10, never before power. A kill here is a verdict (written once).
    kill_doc: dict | None = None
    if powered:
        kill_doc = _immediate_kill(cells)
    if kill_doc is not None and kill_doc["triggered"]:
        years_from = years_assessable_forward_day()
        return {
            "hypothesis": "V-reg-forward",
            **_bindings(),
            "as_of_utc": as_of or dt.datetime.now(dt.UTC).isoformat(),
            "status": "KILLED",
            "status_reason": (
                "immediate-kill: max_over_cells(GROSS_i - ALLIN_i) = "
                f"{kill_doc['max_net_bps']:.2f} bps < 0 (prereg stopping "
                "rule; gates 1-10 not evaluated)"),
            "forward_days": forward_days,
            "forward_days_remaining": max(
                0, MIN_FORWARD_DAYS - forward_days),
            "per_cell": {_cell_key(cell): {
                "R": cell[0], "H": cell[1],
                "round_trips": cells[cell]["round_trips"],
                "round_trips_remaining": max(
                    0, MIN_ROUND_TRIPS - cells[cell]["round_trips"]),
                "eligible": cell in eligible,
                "mean_hold_days": cells[cell]["out"]["base"][
                    "mean_hold_days"],
            } for cell in CELLS},
            "powered": powered,
            "years_assessable_from_forward_day": years_from,
            "years_assessable_from": str(years_assessable_on()),
            "forward_days_to_first_possible_pass": max(
                0, years_from - forward_days),
            "regime_absent_cells": [],
            "immediate_kill": kill_doc,
            "selection": {"selected": None,
                          "rule": ("no selection: immediate-kill fired "
                                   "before gates 1-10")},
            "gates": {k: None for k in (
                "sharpe", "sharpe_2x", "dsr", "pbo", "plateau",
                "drawdown", "years", "median_participation",
                "max_participation", "bootstrap", "newey_west_t")},
            "failed_gates": [],
            "unassessable_gates": "not evaluated (immediate-kill)",
            "imputation_refused_days": dropped,
            "days": [r["day"] for r in rows],
        }

    stats: dict[str, float] = {}
    if len(net) >= 2:
        stats["sharpe"] = ST.sharpe(net, periods=PERIODS)
        stats["sharpe_1x"] = stats["sharpe"]
        stats["max_dd"] = ST.max_drawdown(net)
        stats["mean_daily"] = float(net.mean())
        stats["final_equity"] = float(rows[-1]["equity"])
        stats["total_net"] = float(rows[-1]["equity"] / E0 - 1.0)
        stats["nw_t_lag30"] = ST.newey_west_tstat(net, max_lag=NW_LAG)
        lo, hi = ST.stationary_bootstrap_ci(
            list(net), np.mean, mean_block=BOOTSTRAP_BLOCK_D,
            rounds=BOOTSTRAP_ROUNDS, seed=7,
            lower_q=GATE_BOOTSTRAP_LOWER_Q)
        stats["bootstrap_lower"], stats["bootstrap_upper"] = lo, hi
    if len(net2) >= 2:
        stats["sharpe_2x"] = ST.sharpe(net2, periods=PERIODS)
    parts = _participation_stats(sel["out"]["base"]["fills"])
    years_ok, year_stats = _year_gate(rows)
    turnover = _gross_turnover_per_year(rows, sel["out"]["base"]["fills"], E0)
    capacity = (ST.capacity_estimate(
        median_adv=_median_adv(sel["out"]["base"]["fills"]),
        max_participation=PARTICIPATION_CAP,
        gross_turnover_per_year=turnover)
        if turnover > 0 and sel["out"]["base"]["fills"] else None)

    # DSR at N = 6: the 6 V-REG forward cell Sharpes (own mechanism
    # family, selected cell included). No external Sharpe enters.
    vreg_sharpes = [sharpes_1x[c] for c in CELLS]
    hold = sel["out"]["base"]["mean_hold_days"] or None
    if len(net) >= 2:
        dsr_doc = _dsr_with_n(list(net), vreg_sharpes, N_DSR,
                              hold_days=hold)
        dsr_sens = {
            "n12": _dsr_with_n(list(net), vreg_sharpes, 12,
                               hold_days=hold)["dsr"],
            "n25": _dsr_with_n(list(net), vreg_sharpes, 25,
                               hold_days=hold)["dsr"],
            "note": "report-only sensitivities, never gated",
        }
    else:
        dsr_doc = {"dsr": None, "n": forward_days, "n_eff": None,
                   "n_trials": N_DSR, "n_for_q": N_DSR}
        dsr_sens = {"n12": None, "n25": None,
                    "note": "report-only sensitivities, never gated"}

    # PBO + plateau are COMPUTED at power (fail-closed on refusal); before
    # power they are not-yet-assessable, like the years gate. Uncomputable
    # at assessment time refuses loudly -- never silently nulled.
    if powered:
        pbo_doc = _pbo_bespoke(
            {cell: [float(x) for x in cells[cell]["net"]] for cell in CELLS})
        plateau_doc = _plateau_detail(sharpes_1x)
        pbo_value: float | None = pbo_doc["pbo"]
        plateau_value: float | None = plateau_doc["value"]
    else:
        pbo_doc = {"pbo": None, "n_splits": 70,
                   "note": "assessed at power only"}
        plateau_doc = {"value": None,
                       "note": "assessed at power only"}
        pbo_value, plateau_value = None, None

    gates = {
        "sharpe": _gate(stats.get("sharpe"), lambda v: v >= GATE_SHARPE),
        "sharpe_2x": _gate(stats.get("sharpe_2x"),
                           lambda v: v > GATE_SHARPE_2X),
        "dsr": _gate(dsr_doc.get("dsr"), lambda v: v >= GATE_DSR),
        "pbo": _gate(pbo_value, lambda v: v <= GATE_PBO),
        "plateau": _gate(plateau_value, lambda v: v >= GATE_PLATEAU),
        "drawdown": _gate(stats.get("max_dd"), lambda v: v <= GATE_DD),
        "years": years_ok,
        "median_participation": _gate(
            parts["median"], lambda v: v <= GATE_MEDIAN_PARTICIPATION),
        "max_participation": _gate(
            parts["max"], lambda v: v <= GATE_MAX_PARTICIPATION),
        "bootstrap": _gate(
            stats.get("bootstrap_lower"), lambda v: v > 0.0)
        if len(net) >= 2 else None,
        "newey_west_t": _gate(stats.get("nw_t_lag30"),
                              lambda v: v >= GATE_NW_T),
    }
    status, reason = _decide(powered=powered, gates=gates)
    failed = sorted(k for k, v in gates.items() if v is False)
    unknown = sorted(k for k, v in gates.items() if v is None)
    years_from = years_assessable_forward_day()
    return {
        "hypothesis": "V-reg-forward",
        **_bindings(),
        "as_of_utc": as_of or dt.datetime.now(dt.UTC).isoformat(),
        "status": status,
        "status_reason": reason,
        "forward_days": forward_days,
        "forward_days_remaining": max(0, MIN_FORWARD_DAYS - forward_days),
        "per_cell": {_cell_key(cell): {
            "R": cell[0], "H": cell[1],
            "round_trips": cells[cell]["round_trips"],
            "round_trips_remaining": max(
                0, MIN_ROUND_TRIPS - cells[cell]["round_trips"]),
            "sharpe_1x": sharpes_1x[cell],
            "eligible": cell in eligible,
            "mean_hold_days": cells[cell]["out"]["base"]["mean_hold_days"],
        } for cell in CELLS},
        "powered": powered,
        "years_assessable_from_forward_day": years_from,
        "years_assessable_from": str(years_assessable_on()),
        "forward_days_to_first_possible_pass": max(0, years_from - forward_days),
        "regime_absent_cells": sorted(
            _cell_key(cell) for cell in CELLS
            if forward_days >= REGIME_MILESTONE_DAYS
            and cells[cell]["round_trips"] < MIN_ROUND_TRIPS),
        "regime_note": ("cells <20 RTs at 180+ days are labeled "
                        "regime-absent (report-only); regime absence is "
                        "never converted into a KILL"),
        "immediate_kill": kill_doc,
        "selection": {"selected": _cell_key(selected),
                      "rule": ("largest 1x net Sharpe among eligible "
                               "(>=20 RT) cells; exact ties to "
                               "lexicographically smallest (R, H)")},
        "mean_hold_days": sel["out"]["base"]["mean_hold_days"],
        "gates": gates,
        "failed_gates": failed,
        "unassessable_gates": unknown,
        "stats": stats,
        "years": year_stats,
        "participation": parts,
        "dsr_detail": dsr_doc,
        "dsr_sensitivities": dsr_sens,
        "trial_sharpes": {(_cell_key(c)): sharpes_1x[c] for c in CELLS},
        "trial_sharpes_n": N_DSR,
        "pbo_detail": pbo_doc,
        "plateau_detail": plateau_doc,
        "fees_per_round_trip_bps": FEES_PER_ROUND_TRIP_BPS,
        "grid": {"R": list(R_VALUES), "H": list(H_VALUES)},
        "capital_capacity": capacity,
        "gross_turnover_per_year_descriptive": turnover,
        "diagnostics": _diagnostics(sel["out"]["base"]["trades"]),
        "imputation_refused_days": dropped,
        "net_daily": [float(x) for x in net],
        "days": [r["day"] for r in rows],
    }


def _diagnostics(trades: list[dict]) -> dict:
    """Ungated report-only splits: per-side and per-symbol expectancies.

    Both sides are pooled in every statistic; per-side counts and
    expectancies are reported but never gated (no side selection).
    Per-symbol P&L and each-symbol-alone expectancy likewise.
    """
    by_side: dict[str, dict] = {}
    for side in ("LONG", "SHORT"):
        legs = [t for t in trades if t["side"] == side]
        by_side[side] = {
            "n": len(legs),
            "mean_net_bps": (float(np.mean([t["net_bps"] for t in legs]))
                             if legs else 0.0)}
    by_symbol: dict[str, dict] = {}
    for symbol in UNIVERSE:
        legs = [t for t in trades if t["symbol"] == symbol]
        by_symbol[symbol] = {
            "n": len(legs),
            "mean_net_bps": (float(np.mean([t["net_bps"] for t in legs]))
                             if legs else 0.0)}
    return {"per_side": by_side, "per_symbol": by_symbol,
            "note": "diagnostics only; never gated"}

# -- status / run / verify / forward_command -----------------------------------
def _blocking_gate(doc: dict) -> str:
    if doc["forward_days"] < MIN_FORWARD_DAYS:
        return "forward_days"
    short = [k for k, c in doc["per_cell"].items()
             if c["round_trips"] < MIN_ROUND_TRIPS]
    if short:
        return "round_trips:" + ",".join(short)
    return "years_assessability"


def status_doc(root: Path) -> dict:
    """Coverage + powering counters only. No return statistic is computed,
    reported or written here -- run does that, once."""
    frames, manifest = load_frames(root)
    prep = {s: _prep(f) for s, f in frames.items()}
    base_set, dropped = _run_cell_set(frames, adverse=False)
    dropped_set = set(dropped)
    days = [d for d in study_days(prep) if str(d.date()) not in dropped_set]
    forward_days = len(days)
    per_cell = {}
    for cell in CELLS:
        r, h = cell
        out = base_set[cell]
        per_cell[_cell_key(cell)] = {
            "R": r, "H": h,
            "round_trips": int(out["round_trips"]),
            "round_trips_required": MIN_ROUND_TRIPS,
            "round_trips_remaining": max(
                0, MIN_ROUND_TRIPS - int(out["round_trips"])),
        }
    powered = bool(forward_days >= MIN_FORWARD_DAYS and all(
        c["round_trips"] >= MIN_ROUND_TRIPS for c in per_cell.values()))
    years_from = years_assessable_forward_day()
    doc = {
        **_bindings(),
        "forward_clock_start": FORWARD_CLOCK_START,
        "coverage": coverage(frames),
        "data_manifest": manifest,
        "forward_days": forward_days,
        "forward_days_required": MIN_FORWARD_DAYS,
        "forward_days_remaining": max(0, MIN_FORWARD_DAYS - forward_days),
        "per_cell": per_cell,
        "powered": powered,
        "years_assessable_from_forward_day": years_from,
        "years_assessable_from": str(years_assessable_on()),
        "forward_days_to_first_possible_pass": max(0, years_from - forward_days),
        "regime_absent_cells": sorted(
            k for k, c in per_cell.items()
            if forward_days >= REGIME_MILESTONE_DAYS
            and c["round_trips"] < MIN_ROUND_TRIPS),
        "imputation_refused_days": dropped,
        "note": ("coverage and powering counters only; no return "
                 "statistic is computed, reported or written here"),
    }
    doc["blocking_gate"] = _blocking_gate(doc)
    return doc


def _verdict_path() -> Path:
    return VERDICT_DIR / VERDICT_NAME


def _read_stored_verdict() -> dict | None:
    dest = _verdict_path()
    if not dest.exists():
        return None
    try:
        doc = json.loads(dest.read_text())
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def run(root: Path, *, force: bool = False) -> dict:
    """Fire the one-shot verdict. Refuses while UNDERPOWERED (unless
    --force, which writes an UNDERPOWERED document, never a verdict) and
    refuses to overwrite a verdict that has already fired."""
    frames, manifest = load_frames(root)
    pre = status_doc(root)
    if not pre["powered"] and not force:
        raise SystemExit(
            f"V-REG is UNDERPOWERED: {pre['forward_days']} of 90 forward "
            f"days, per-cell RTs "
            f"{ {k: c['round_trips'] for k, c in pre['per_cell'].items()} } "
            f"of 20 each. A PASS is impossible before forward day "
            f"{pre['years_assessable_from_forward_day']} "
            f"({pre['years_assessable_from']}, the years gate). The one "
            f"look does not fire early (prereg stopping rule).")
    dest = _verdict_path()
    prior = _read_stored_verdict()
    if (prior is not None and dest.exists()
            and prior.get("status") != "UNDERPOWERED"):
        raise SystemExit(
            f"{dest} already holds a {prior.get('status')} verdict; the "
            f"study gets one look. A second look requires a new prereg.")
    verdict = evaluate_frames(frames)
    verdict["coverage"] = pre["coverage"]
    verdict["data_manifest"] = manifest
    if force and verdict["status"] != "UNDERPOWERED":
        # --force only ever writes an UNDERPOWERED document; anything else
        # through this path would be a second-look smuggle.
        raise SystemExit(
            f"refusing --force: computed status is {verdict['status']}, "
            f"not UNDERPOWERED")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(verdict, indent=1, sort_keys=True,
                             default=str))
    os.replace(tmp, dest)
    return verdict


def _diff_docs(a, b, path: str = "") -> list[str]:
    """Recursive diff paths between a recomputed and a stored document."""
    diffs: list[str] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b), key=repr):
            sub = f"{path}.{key}" if path else str(key)
            if key not in a:
                diffs.append(f"{sub}: missing in recomputed")
            elif key not in b:
                diffs.append(f"{sub}: missing in stored")
            else:
                diffs.extend(_diff_docs(a[key], b[key], sub))
        return diffs
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: len {len(a)} != {len(b)}"]
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            diffs.extend(_diff_docs(x, y, f"{path}[{i}]"))
        return diffs
    if isinstance(a, float) and isinstance(b, float):
        if not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-15):
            diffs.append(f"{path}: {a!r} != {b!r}")
        return diffs
    if a != b:
        diffs.append(f"{path}: {a!r} != {b!r}")
    return diffs


def verify(root: Path) -> dict:
    """Recompute every number from checksummed inputs; diff vs the stored
    verdict. Never writes. Refuses while UNDERPOWERED (no peeking path)."""
    frames, manifest = load_frames(root)
    pre = status_doc(root)
    if not pre["powered"]:
        raise SystemExit(
            f"verify refuses while UNDERPOWERED "
            f"({pre['forward_days']} of 90 forward days). Recomputation "
            f"before the stopping rule would be an early look.")
    recomputed = evaluate_frames(frames)
    recomputed["coverage"] = pre["coverage"]
    recomputed["data_manifest"] = manifest
    stored = _read_stored_verdict()
    if stored is None:
        return {"state": "RECOMPUTED-ONLY",
                **_bindings(),
                "note": ("no stored verdict to compare; recomputed "
                         "document returned, nothing written"),
                "recomputed": recomputed}
    stored_cmp = {k: v for k, v in stored.items() if k != "as_of_utc"}
    recomp_cmp = {k: v for k, v in recomputed.items() if k != "as_of_utc"}
    # The stored document went through JSON (int keys become strings);
    # normalize the recomputation the same way before comparing.
    recomp_cmp = json.loads(json.dumps(recomp_cmp, default=str))
    diffs = _diff_docs(recomp_cmp, stored_cmp)
    return {"state": "MATCH" if not diffs else "MISMATCH",
            **_bindings(),
            "diffs": diffs[:50],
            "n_diffs": len(diffs),
            "note": ("stored verdict vs recomputation from checksummed "
                     "inputs; nothing written")}


def forward_command(root: Path) -> dict:
    """One command for the frozen study: the verdict, or what is missing."""
    prior = _read_stored_verdict()
    if prior is not None and prior.get("status") != "UNDERPOWERED":
        return {"state": "VERDICT", "verdict": prior,
                "note": "already fired; never recomputed or overwritten"}
    doc = status_doc(root)
    if doc["powered"]:
        verdict = run(root)
        return {"state": "VERDICT", "verdict": verdict}
    return {"state": "INSUFFICIENT FORWARD DATA",
            **_bindings(),
            "forward_clock_start": FORWARD_CLOCK_START,
            "forward_days": doc["forward_days"],
            "forward_days_required": MIN_FORWARD_DAYS,
            "forward_days_remaining": doc["forward_days_remaining"],
            "per_cell": doc["per_cell"],
            "blocking_gate": doc["blocking_gate"],
            "regime_absent_cells": doc["regime_absent_cells"],
            "earliest_evaluable_on": str(
                forward_clock_start().date() + pd.Timedelta(days=89)),
            "pass_possible_on": doc["years_assessable_from"],
            "years_assessable_from_forward_day":
                doc["years_assessable_from_forward_day"],
            "coverage": doc["coverage"],
            "note": ("the 90-day look is kill-or-underpowered only; a PASS "
                     "first becomes possible on forward day 121 (the years "
                     "gate)")}


def main(argv: list[str] | None = None) -> int:
    from cryptobot import netguard  # opt-in DNS-sinkhole fallback
    netguard.install_from_env()
    ap = argparse.ArgumentParser(prog="forward_vreg")
    ap.add_argument("cmd", choices=("fetch", "status", "run", "verify"))
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--manifest-out", default=str(TRACKED_MANIFEST))
    ap.add_argument("--force", action="store_true",
                    help="run even while UNDERPOWERED (writes an "
                         "UNDERPOWERED document, never a verdict)")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if args.cmd == "fetch":
        manifest = fetch(root, VisionClient(),
                         manifest_out=Path(args.manifest_out))
        print(f"fetched {len(manifest['files'])} files, "
              f"checksums verified")
        return 0
    if args.cmd == "status":
        doc = status_doc(root)
        print(json.dumps(doc, indent=1, sort_keys=True, default=str))
        rt = ", ".join(f"{k} {c['round_trips']}/20"
                       for k, c in doc["per_cell"].items())
        print(f"{doc['forward_days']}/90 days, {rt} "
              f"-> blocking: {doc['blocking_gate']}")
        return 0
    if args.cmd == "run":
        doc = run(root, force=args.force)
        print(json.dumps(doc, indent=1, sort_keys=True, default=str))
        return 0
    if args.cmd == "verify":
        doc = verify(root)
        print(json.dumps(doc, indent=1, sort_keys=True, default=str))
        return 0 if doc["state"] != "MISMATCH" else 1
    raise AssertionError("unreachable")  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
