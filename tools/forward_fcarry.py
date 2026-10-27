#!/usr/bin/env python3
"""F-CARRY forward funding/basis carry evaluator (six cells, one look).

Prereg: ``research/prereg/F-carry-forward.md`` (FROZEN before any forward
read, freeze commit cc630e1). Every rule, cost term, gate and stopping
condition in this file is transcribed from that document; if the two ever
disagree, the prereg wins and this file is the bug.

Forward window only: files dated strictly after 2026-10-17 (daily) and
months strictly after 2026-10 (monthly). The October monthly funding file
is holdout-dated and is never decoded -- not for warm-up, ADV20, sigma
seeding, or anything else. Every file is checksum-verified against its
manifest record (built from the published .CHECKSUM at fetch) on EVERY run,
including resumed files; unknown or tampered files are refused, never used.

Data source: the Binance Vision CDN only (``data.binance.vision``).

Usage
-----
    python tools/forward_fcarry.py fetch    [--root data/forward_fcarry]
    python tools/forward_fcarry.py status   [--root data/forward_fcarry]
    python tools/forward_fcarry.py run      [--root data/forward_fcarry] [--force]
    python tools/forward_fcarry.py verify   [--root data/forward_fcarry]

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
# Acklam): the missing-B4b DSR rule needs q(N) at a different N than the
# vector it averages over, so the ratio must use the identical
# approximation. Verified equal to dsr_detail on standard inputs by test.

# -- frozen constants (research/prereg/F-carry-forward.md) --------------------
VISION = "https://data.binance.vision"
S3LIST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"

CUTOFF_DAY = dt.date(2026, 10, 17)      # forward iff strictly after
CUTOFF_MONTH = "2026-10"                # forward iff strictly after
FORWARD_CLOCK_START = "2026-11-01"      # first day with forward-only funding
UNIVERSE = ("BTCUSDT", "ETHUSDT")

RT_BPS = 53.0                # hurdle identity only (B4's 53 bps)
SPOT_TAKER_BPS = 15.0
SPOT_SPREAD_BPS = 1.0
PERP_TAKER_BPS = 7.5
PERP_SPREAD_BPS = 1.0
FILL_BPS = {"spot": SPOT_TAKER_BPS + SPOT_SPREAD_BPS,
            "perp": PERP_TAKER_BPS + PERP_SPREAD_BPS}

K_VALUES = (1.0, 1.25)
UNIVERSE_SPLITS = {"BTC": ("BTCUSDT",), "ETH": ("ETHUSDT",),
                   "BOTH": ("BTCUSDT", "ETHUSDT")}
# Lexicographic cell order per prereg (NOT ASCII: 'BOTH' < 'BTC' in ASCII).
UNIVERSE_RANK = {"BTC": 0, "ETH": 1, "BOTH": 2}
CELLS: tuple[tuple[float, str], ...] = tuple(
    (k, u) for k in K_VALUES for u in ("BTC", "ETH", "BOTH"))

DRIFT_BAND = 0.05
TRAIL_SETTLEMENTS = 21       # 7 days of 8h settlements
MIN_HOLD_DAYS = 7
EXIT_STREAK = 3
ADV_WINDOW = 20
PARTICIPATION_CAP = 0.01     # Q_leg <= 1% of ADV20
MIN_NOTIONAL = 6.0
QTY_STEP = 0.001

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
N_DSR = 16                   # 9 B4 DEV + 1 B4b forward + 6 F-CARRY
PBO_PARTITIONS = 8
PBO_MIN_DAYS = 8             # below this the bespoke PBO refuses (fail-closed)

B4_DEV_ARTIFACT = ROOT / "research/autopilot_b/dev/B4.json"
B4B_VERDICT_DEFAULT = ROOT / "reports/hypotheses/B4b-forward.json"
PREREG_PATH = "research/prereg/F-carry-forward.md"
VERDICT_DIR = ROOT / "reports/hypotheses"
VERDICT_NAME = "F-carry-forward.json"
DEFAULT_ROOT = ROOT / "data/forward_fcarry"
TRACKED_MANIFEST = ROOT / "research/forward_fcarry_data_manifest.json"

DAY_RE = re.compile(r"-(\d{4}-\d{2}-\d{2})\.zip$")
MONTH_RE = re.compile(r"-(\d{4}-\d{2})\.zip$")


class InputBeforeForwardWindow(RuntimeError):
    """An input file or row predates the forward window. Never tolerated."""


class ChecksumRefusal(RuntimeError):
    """A data file failed checksum/pinning verification. Never tolerated."""


# -- clock / hurdle -----------------------------------------------------------
def forward_clock_start() -> pd.Timestamp:
    return pd.Timestamp(FORWARD_CLOCK_START, tz="UTC")


def hurdle_apr(k: float, rt_bps: float = RT_BPS) -> float:
    return k * (rt_bps / 1e4) * 365.0 / 7.0


def median_hurdle_rate(k: float, rt_bps: float = RT_BPS) -> float:
    return hurdle_apr(k, rt_bps) / 3.0 / 365.0


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
        "k_values": list(K_VALUES),
        "universe_splits": {u: list(s)
                            for u, s in UNIVERSE_SPLITS.items()},
        "drift_band": DRIFT_BAND, "rt_bps": RT_BPS,
        "trail_settlements": TRAIL_SETTLEMENTS,
        "min_hold_days": MIN_HOLD_DAYS, "exit_streak": EXIT_STREAK,
        "adv_window": ADV_WINDOW,
        "participation_cap": PARTICIPATION_CAP,
        "min_notional": MIN_NOTIONAL, "qty_step": QTY_STEP, "e0": E0,
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


# -- Vision fetch (same mechanics as forward_b4b) ------------------------------
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
                url, headers={"User-Agent": "cryptobot-fcarry-forward/1"})
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
    return {"spot": f"data/spot/daily/klines/{symbol}/1h/",
            "perp": f"data/futures/um/daily/klines/{symbol}/1h/",
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
    manifest = {"format": "cryptobot-fcarry-forward-manifest/1",
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
    """Build per-symbol {spot, perp, funding} forward-only frames.

    Every zip is checksum-verified against the manifest before it is
    decoded; returns (frames, data_manifest) for output binding.
    """
    root = Path(root)
    records = _manifest_records(root)
    manifest_files: list[dict] = []
    out: dict[str, dict[str, pd.DataFrame]] = {}
    for symbol in UNIVERSE:
        frames: dict[str, pd.DataFrame] = {}
        for dataset in ("spot", "perp", "funding"):
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
        for dataset in ("spot", "perp", "funding"):
            df = f.get(dataset)
            col = {"spot": "open_ms", "perp": "open_ms",
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


# -- the F-CARRY book (per cell) ------------------------------------------------
@dataclass
class FcarryConfig:
    e0: float = E0
    k: float = 1.0
    drift_band: float = DRIFT_BAND
    rt_bps: float = RT_BPS
    adverse_mult: float = 1.0
    adv_window: int = ADV_WINDOW
    participation_cap: float = PARTICIPATION_CAP
    qty_step: float = QTY_STEP
    min_notional: float = MIN_NOTIONAL


@dataclass
class Position:
    qty_spot: float
    qty_perp: float          # signed; short perp is negative
    entry: pd.Timestamp
    entry_day: int
    price_spot: float        # last mark used for P&L accrual
    price_perp: float
    exit_streak: int = 0


@dataclass
class Book:
    cash: float
    cfg: FcarryConfig
    positions: dict[str, Position] = field(default_factory=dict)
    fills: list[dict] = field(default_factory=list)
    round_trips: int = 0
    hold_days: list[float] = field(default_factory=list)
    funding_income: float = 0.0
    fees_paid: float = 0.0

    def cost_of(self, notional: float, venue: str, *, sigma: float,
                adv: float) -> tuple[float, float]:
        """(cash cost, participation) for one fill of ``notional``."""
        if adv <= 0 or notional <= 0:
            return 0.0, 0.0
        m = self.cfg.adverse_mult
        fee = notional * FILL_BPS[venue] / 1e4 * m
        participation = notional / adv
        impact = notional * 0.5 * sigma * math.sqrt(participation) * m
        return fee + impact, participation

    def fill(self, *, day: str, symbol: str, venue: str, notional: float,
             price: float, sigma: float, adv: float) -> tuple[float, float]:
        cost, part = self.cost_of(notional, venue, sigma=sigma, adv=adv)
        self.cash -= cost
        self.fees_paid += cost
        self.fills.append({"day": day, "symbol": symbol, "venue": venue,
                           "notional": notional, "participation": part,
                           "cost": cost, "sigma_d": sigma, "adv20": adv,
                           "price": price})
        return cost, part


def _step_floor(x: float, step: float) -> float:
    if step <= 0:
        return x
    return math.floor(x / step) * step


def _qty(notional: float, price: float) -> float:
    if price <= 0:
        return 0.0
    return notional / price


def _trailing_stats(bars: pd.DataFrame, boundary: pd.Timestamp, *,
                    window: int = ADV_WINDOW) -> tuple[float, float]:
    """(sigma_d, ADV20) from bars strictly before ``boundary`` (no fallback)."""
    past = bars[bars.index < boundary]
    if past.empty:
        return 0.0, 0.0
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


def _prep(frames: dict[str, pd.DataFrame]) -> dict:
    out = {}
    for venue in ("spot", "perp"):
        df = frames.get(venue)
        if df is None or df.empty:
            out[venue] = pd.DataFrame(columns=["open", "close",
                                               "quote_volume"])
            continue
        d = df.copy()
        d.index = pd.to_datetime(d["open_ms"], unit="ms", utc=True)
        out[venue] = d[["open", "close", "quote_volume"]].sort_index()
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


def _fill_bar_price(bars: pd.DataFrame, boundary: pd.Timestamp) -> float:
    """Open of the first bar at/after ``boundary`` (else last close)."""
    at_or_after = bars[bars.index >= boundary]
    if not at_or_after.empty:
        return float(at_or_after["open"].iloc[0])
    return _price_at(bars, boundary)


def decision_days(perp: pd.DataFrame) -> list[pd.Timestamp]:
    if perp.empty:
        return []
    days = pd.date_range(perp.index.min().floor("D"),
                         perp.index.max().floor("D"), freq="D")
    return [d for d in days if d >= forward_clock_start()]


def _day_has_inputs(prep: dict, day: pd.Timestamp) -> bool:
    """A forward day needs every input: both venues' bars and a settlement.

    Bars alone are not a day (no carry to measure); funding alone is not a
    day (the mark needs both venues' bars inside the preceding forward day).
    Counting a day without its marks scores it off a stale price.
    """
    syms = [s for s, p in prep.items() if not p["perp"].empty]
    if not syms:
        return False
    lo, hi = day - pd.Timedelta(days=1), day
    ok = 0
    for s in syms:
        p = prep[s]
        if p["spot"].empty or p["perp"].empty:
            continue
        has_bars = all(
            len(bars[(bars.index >= lo) & (bars.index < hi)]) > 0
            for bars in (p["spot"], p["perp"]))
        has_funding = (not p["funding"].empty and len(
            p["funding"][(p["funding"].index > lo)
                          & (p["funding"].index <= hi)]) > 0)
        if has_bars and has_funding:
            ok += 1
    return ok == len(syms)


def study_days(prep: dict) -> list[pd.Timestamp]:
    """The shared study clock over the full universe (all cells agree)."""
    days: list[pd.Timestamp] = []
    for s in UNIVERSE:
        if "perp" in prep.get(s, {}):
            days = sorted(set(days) | set(decision_days(prep[s]["perp"])))
    return [d for d in days if _day_has_inputs(prep, d)]


def _trailing_funding(funding: pd.Series, boundary: pd.Timestamp,
                      n: int = TRAIL_SETTLEMENTS) -> float | None:
    past = funding[funding.index < boundary]
    if len(past) < n:
        return None
    return float(np.median(past.tail(n).to_numpy(dtype=float)))


def exit_decision(*, held_days: float, median_rate: float, apr: float,
                  streak: int = 0, k: float = 1.0,
                  rt_bps: float = RT_BPS) -> tuple[bool, int]:
    """C1/B4b exit hysteresis, as one testable predicate (k-parameterized)."""
    below = apr < 0.5 * hurdle_apr(k, rt_bps)
    new_streak = streak + 1 if below else 0
    exit_now = bool(median_rate < 0.0) or (
        held_days >= MIN_HOLD_DAYS and new_streak >= EXIT_STREAK)
    return exit_now, new_streak


def simulate(frames_by_symbol: dict[str, dict[str, pd.DataFrame]],
             cfg: FcarryConfig,
             symbols: tuple[str, ...]) -> dict:
    """Run one frozen F-CARRY cell book point-in-time (ledger + audit)."""
    prep = {s: _prep(f) for s, f in frames_by_symbol.items()}
    hurdle = hurdle_apr(cfg.k, cfg.rt_bps)
    book = Book(cash=cfg.e0, cfg=cfg)
    days = study_days(prep)
    rows: list[dict] = []
    prev_equity = cfg.e0
    for day in days:
        # 1) accrue P&L and funding over (day-1d, day]
        for symbol, pos in list(book.positions.items()):
            p = prep[symbol]
            s_now = _price_at(p["spot"], day)
            p_now = _price_at(p["perp"], day)
            # Only the perp settles variation margin into cash. The spot
            # leg is a held asset: its P&L is the mark added to equity
            # below, so accruing a spot delta into cash as well would
            # count the spot leg twice.
            book.cash += pos.qty_perp * (p_now - pos.price_perp)
            window = p["funding"][(p["funding"].index > day - pd.Timedelta(days=1))
                                  & (p["funding"].index <= day)]
            if len(window) and p_now > 0:
                book.cash += float(window.sum()) * (-pos.qty_perp) * p_now
                book.funding_income += float(window.sum()) * (-pos.qty_perp) * p_now
            pos.price_spot, pos.price_perp = s_now, p_now
        equity = book.cash + sum(pos.qty_spot * _price_at(prep[s]["spot"], day)
                                 for s, pos in book.positions.items())
        # 2) per-symbol decision at `day` (this cell's universe only)
        for symbol in symbols:
            p = prep.get(symbol)
            if not p or p["perp"].empty:
                continue
            sigma_s, adv_s = _trailing_stats(p["spot"], day)
            sigma_p, adv_p = _trailing_stats(p["perp"], day)
            median = _trailing_funding(p["funding"], day)
            apr = None if median is None else median * 3.0 * 365.0
            pos = book.positions.get(symbol)
            sizing_ok = (sigma_s > 0 and adv_s > 0 and sigma_p > 0 and adv_p > 0)
            if pos is None:
                if median is None or not sizing_ok:
                    continue
                if not (apr > hurdle and median > 0):
                    continue
                notional_spot = min(0.5 * equity, cfg.participation_cap * adv_s)
                notional_perp = min(0.5 * equity, cfg.participation_cap * adv_p)
                leg = min(notional_spot, notional_perp)
                if leg < cfg.min_notional:
                    continue
                qs = _step_floor(_qty(leg, _fill_bar_price(p["spot"], day)),
                                 cfg.qty_step)
                qp = _step_floor(_qty(leg, _fill_bar_price(p["perp"], day)),
                                 cfg.qty_step)
                if qs <= 0 or qp <= 0:
                    continue
                qs_px = _fill_bar_price(p["spot"], day)
                qp_px = _fill_bar_price(p["perp"], day)
                book.fill(day=str(day.date()), symbol=symbol, venue="spot",
                          notional=qs * qs_px, price=qs_px, sigma=sigma_s,
                          adv=adv_s)
                book.fill(day=str(day.date()), symbol=symbol, venue="perp",
                          notional=qp * qp_px, price=qp_px, sigma=sigma_p,
                          adv=adv_p)
                book.cash -= qs * qs_px
                book.positions[symbol] = Position(
                    qty_spot=qs, qty_perp=-qp, entry=day,
                    entry_day=len(days), price_spot=qs_px, price_perp=qp_px)
                continue
            if median is None:
                continue
            held = (day - pos.entry) / pd.Timedelta(days=1)
            do_exit, pos.exit_streak = exit_decision(
                held_days=held, median_rate=median, apr=apr,
                streak=pos.exit_streak, k=cfg.k, rt_bps=cfg.rt_bps)
            if do_exit:
                s_px = _fill_bar_price(p["spot"], day)
                p_px = _fill_bar_price(p["perp"], day)
                book.cash += pos.qty_perp * (p_px - pos.price_perp)
                book.fill(day=str(day.date()), symbol=symbol, venue="spot",
                          notional=abs(pos.qty_spot) * s_px, price=s_px,
                          sigma=sigma_s, adv=adv_s)
                book.fill(day=str(day.date()), symbol=symbol, venue="perp",
                          notional=abs(pos.qty_perp) * p_px, price=p_px,
                          sigma=sigma_p, adv=adv_p)
                book.cash += pos.qty_spot * s_px
                book.positions.pop(symbol)
                book.round_trips += 1
                book.hold_days.append(float(held))
                continue
            if not (sigma_s > 0 and sigma_p > 0 and adv_s > 0 and adv_p > 0):
                continue
            s_px = _fill_bar_price(p["spot"], day)
            p_px = _fill_bar_price(p["perp"], day)
            drift = abs(pos.qty_spot * s_px - abs(pos.qty_perp) * p_px)
            if equity > 0 and drift / equity > cfg.drift_band:
                target_spot = pos.qty_spot * s_px
                target_perp = min(target_spot, cfg.participation_cap * adv_p)
                delta = abs(pos.qty_perp) - _qty(target_perp, p_px)
                if abs(delta) * p_px >= cfg.min_notional:
                    book.cash += pos.qty_perp * (p_px - pos.price_perp)
                    book.fill(day=str(day.date()), symbol=symbol, venue="perp",
                              notional=abs(delta) * p_px, price=p_px,
                              sigma=sigma_p, adv=adv_p)
                    pos.qty_perp = -_qty(target_perp, p_px)
                    pos.price_perp = p_px
        equity = book.cash + sum(pos.qty_spot * _price_at(prep[s]["spot"], day)
                                 for s, pos in book.positions.items())
        rows.append({"day": str(day.date()),
                     "equity": equity,
                     "net_ret": (equity / prev_equity - 1.0)
                     if prev_equity > 0 else 0.0,
                     "open_positions": sorted(book.positions),
                     "fills": len([f for f in book.fills
                                   if f["day"] == str(day.date())])})
        prev_equity = equity
    return {"rows": rows, "fills": book.fills, "book": book,
            "round_trips": book.round_trips,
            "funding_income": book.funding_income,
            "fees_paid": book.fees_paid,
            "mean_hold_days": (float(np.mean(book.hold_days))
                               if book.hold_days else 0.0)}


def run_cell_both_costs(frames_by_symbol: dict[str, dict[str, pd.DataFrame]],
                        k: float, symbols: tuple[str, ...]) -> dict:
    cfg = FcarryConfig(k=k)
    base = simulate(frames_by_symbol, cfg, symbols)
    adverse_cfg = FcarryConfig(**{**cfg.__dict__, "adverse_mult": 2.0})
    adverse = simulate(frames_by_symbol, adverse_cfg, symbols)
    return {"base": base, "adverse": adverse}

# -- gates ---------------------------------------------------------------------
def _cell_key(cell: tuple[float, str]) -> str:
    return f"k={cell[0]:g}/{cell[1]}"


def _read_b4_dev_sharpes() -> list[float]:
    """The 9 B4 dev cell Sharpes (DSR trial vector, not a forward result)."""
    doc = json.loads(B4_DEV_ARTIFACT.read_text())
    sharpes = sorted(float(v) for v in doc["cell_sharpes"].values())
    if len(sharpes) != 9:
        raise RuntimeError(
            f"expected the 9 frozen B4 dev cells, found {len(sharpes)}")
    return sharpes


def _read_b4b_forward_sharpe(path: Path | None) -> float | None:
    """B4b's scored forward Sharpe, or None under the missing-B4b rule.

    A number counts only from a SCORED B4b verdict (PASS or KILLED): a
    B4b that is still UNDERPOWERED has no scored Sharpe even if a snapshot
    number sits in its document.
    """
    path = Path(path) if path else B4B_VERDICT_DEFAULT
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if doc.get("status") not in ("PASS", "KILLED"):
        return None
    value = (doc.get("stats") or {}).get("sharpe")
    if value is None or not math.isfinite(float(value)):
        return None
    return float(value)


def _qterm(k: int) -> float:
    """The Bailey-Lopez de Prado trial-count term (same _phi_inv as DSR)."""
    gamma = 0.5772156649
    return ((1 - gamma) * _phi_inv(1 - 1 / k)
            + gamma * _phi_inv(1 - 1 / (k * math.e)))


def _dsr_with_n(selected_returns: list[float], vector_for_v: list[float],
                n_for_q: int, *, hold_days: float | None) -> dict:
    """DSR with V averaged over ``vector_for_v`` and q() at ``n_for_q``.

    Identical to slow_stats.dsr_detail when n_for_q == len(vector); the
    missing-B4b rule (V over 15, q at 16) and the N sensitivities need the
    decoupled form. Equality with dsr_detail on standard inputs is pinned
    by test, so this cannot silently diverge.
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


def _pbo_bespoke(cell_returns: dict[tuple[float, str], list[float]]) -> dict:
    """Bespoke Gate-4 PBO, implemented VERBATIM from the prereg.

    CSCV over the 6 cells on the full calendar-day series of mean net daily
    return. 8 consecutive partitions with numpy.array_split semantics
    (sizes differ by at most one day; remainder days go to the earliest
    partitions). All 70 ways to choose 4 partitions in-sample; the
    highest in-sample daily Sharpe is selected (exact ties broken by
    lexicographically smallest (k, universe), BTC < ETH < BOTH).
    lambda = other cells with strictly lower OOS Sharpe, divided by 5.
    The selected cell takes the lowest rank within its OOS tie group;
    tied cells do not count as lower-scoring competitors; an all-tied
    OOS set has lambda = 0. PBO = fraction of splits with lambda < 0.5.
    Deterministic (no seed). Substituting slow_stats.pbo_cscv is
    FORBIDDEN (opposite lambda scale, different block edges).

    Returns {pbo, lambdas, best_keys, n_splits, edges}; the gate consumes
    ["pbo"]. Refuses (fail-closed) on short/ragged/non-finite input.
    """
    keys = sorted(cell_returns, key=lambda c: (c[0], UNIVERSE_RANK[c[1]]))
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
    best_keys: list[tuple[float, str]] = []
    for combo in itertools.combinations(range(PBO_PARTITIONS),
                                        PBO_PARTITIONS // 2):
        in_set = set(combo)
        is_idx = [i for b in combo for i in blocks[b]]
        oos_idx = [i for b in range(PBO_PARTITIONS) if b not in in_set
                   for i in blocks[b]]
        is_sr = [ST.sharpe([series[c][i] for i in is_idx], PERIODS)
                 for c in range(len(keys))]
        order = sorted(range(len(keys)),
                       key=lambda c: (-is_sr[c], keys[c][0],
                                      UNIVERSE_RANK[keys[c][1]]))
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


def _plateau_detail(cell_sharpes: dict[tuple[float, str], float]) -> dict:
    """plateau_fraction over the 2x3 grid, fail-closed on a bad shape.

    Cells are inserted in (k, universe-rank) order so the best-cell
    tie-break matches the selection rule (lexicographically smallest).
    """
    ordered = {c: cell_sharpes[c] for c in sorted(
        cell_sharpes, key=lambda c: (c[0], UNIVERSE_RANK[c[1]]))}
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


def _select_cell(cell_sharpes: dict[tuple[float, str], float],
                 eligible: set[tuple[float, str]]) -> tuple[float, str]:
    """Largest 1x Sharpe among eligible cells; ties to lexicographically
    smallest (k, universe), BTC < ETH < BOTH. Non-finite never wins."""
    def key(cell: tuple[float, str]) -> tuple[float, float, int]:
        sr = cell_sharpes.get(cell, float("-inf"))
        sr = sr if math.isfinite(sr) else float("-inf")
        return (-sr, cell[0], UNIVERSE_RANK[cell[1]])
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


def evaluate_frames(frames_by_symbol: dict[str, dict[str, pd.DataFrame]],
                    *, b4b_verdict: Path | None = None,
                    as_of: str | None = None) -> dict:
    """Full gate evaluation. Returns the verdict document (not yet written)."""
    prep = {s: _prep(f) for s, f in frames_by_symbol.items()}
    days = study_days(prep)
    forward_days = len(days)
    cells: dict[tuple[float, str], dict] = {}
    for cell in CELLS:
        k, u = cell
        out = run_cell_both_costs(frames_by_symbol, k, UNIVERSE_SPLITS[u])
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

    # DSR at N = 16: 9 B4 DEV + B4b forward + 6 F-CARRY (selected incl.).
    fcarry_sharpes = [sharpes_1x[c] for c in CELLS]
    b4b_sharpe = _read_b4b_forward_sharpe(b4b_verdict)
    hold = sel["out"]["base"]["mean_hold_days"] or None
    if len(net) >= 2:
        if b4b_sharpe is None:
            vec15 = _read_b4_dev_sharpes() + fcarry_sharpes
            dsr_doc = _dsr_with_n(list(net), vec15, N_DSR, hold_days=hold)
            missing_b4b = True
        else:
            vec16 = _read_b4_dev_sharpes() + [b4b_sharpe] + fcarry_sharpes
            dsr_doc = _dsr_with_n(list(net), vec16, N_DSR, hold_days=hold)
            missing_b4b = False
        sens_base = _read_b4_dev_sharpes() + fcarry_sharpes
        dsr_sens = {
            "n15": _dsr_with_n(list(net), sens_base, 15, hold_days=hold)["dsr"],
            "n25": _dsr_with_n(list(net), sens_base, 25, hold_days=hold)["dsr"],
            "min_imputed_n16": ST.dsr_detail(
                list(net), sens_base + [min(sens_base)],
                hold_days=hold)["dsr"],
            "note": "report-only sensitivities, never gated",
        }
    else:
        dsr_doc = {"dsr": None, "n": forward_days, "n_eff": None,
                   "n_trials": N_DSR, "n_for_q": N_DSR}
        dsr_sens = {"n15": None, "n25": None, "min_imputed_n16": None,
                    "note": "report-only sensitivities, never gated"}
        missing_b4b = b4b_sharpe is None

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
        "hypothesis": "F-carry-forward",
        **_bindings(),
        "as_of_utc": as_of or dt.datetime.now(dt.UTC).isoformat(),
        "status": status,
        "status_reason": reason,
        "forward_days": forward_days,
        "forward_days_remaining": max(0, MIN_FORWARD_DAYS - forward_days),
        "per_cell": {_cell_key(cell): {
            "k": cell[0], "universe": cell[1],
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
        "selection": {"selected": _cell_key(selected),
                      "rule": ("largest 1x net Sharpe among eligible "
                               "(>=20 RT) cells; exact ties to "
                               "lexicographically smallest (k, universe), "
                               "BTC < ETH < BOTH")},
        "mean_hold_days": sel["out"]["base"]["mean_hold_days"],
        "gates": gates,
        "failed_gates": failed,
        "unassessable_gates": unknown,
        "stats": stats,
        "years": year_stats,
        "participation": parts,
        "dsr_detail": dsr_doc,
        "dsr_sensitivities": dsr_sens,
        "trial_sharpes_n": N_DSR,
        "b4b_forward_sharpe": b4b_sharpe,
        "missing_b4b_rule_applied": missing_b4b,
        "pbo_detail": pbo_doc,
        "plateau_detail": plateau_doc,
        "fees_per_round_trip_bps": 2 * (SPOT_TAKER_BPS + SPOT_SPREAD_BPS)
        + 2 * (PERP_TAKER_BPS + PERP_SPREAD_BPS),
        "hurdles": {str(k): {
            "hurdle_apr": hurdle_apr(k),
            "hurdle_median_rate": median_hurdle_rate(k)} for k in K_VALUES},
        "capital_capacity": capacity,
        "gross_turnover_per_year_descriptive": turnover,
        "net_daily": [float(x) for x in net],
        "days": [r["day"] for r in rows],
    }

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
    days = study_days(prep)
    forward_days = len(days)
    per_cell = {}
    for cell in CELLS:
        k, u = cell
        out = simulate(frames, FcarryConfig(k=k), UNIVERSE_SPLITS[u])
        per_cell[_cell_key(cell)] = {
            "k": k, "universe": u,
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


def run(root: Path, *, force: bool = False,
        b4b_verdict: Path | None = None) -> dict:
    """Fire the one-shot verdict. Refuses while UNDERPOWERED (unless
    --force, which writes an UNDERPOWERED document, never a verdict) and
    refuses to overwrite a verdict that has already fired."""
    frames, manifest = load_frames(root)
    pre = status_doc(root)
    if not pre["powered"] and not force:
        raise SystemExit(
            f"F-CARRY is UNDERPOWERED: {pre['forward_days']} of 90 forward "
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
    verdict = evaluate_frames(frames, b4b_verdict=b4b_verdict)
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


def verify(root: Path, *, b4b_verdict: Path | None = None) -> dict:
    """Recompute every number from checksummed inputs; diff vs the stored
    verdict. Never writes. Refuses while UNDERPOWERED (no peeking path)."""
    frames, manifest = load_frames(root)
    pre = status_doc(root)
    if not pre["powered"]:
        raise SystemExit(
            f"verify refuses while UNDERPOWERED "
            f"({pre['forward_days']} of 90 forward days). Recomputation "
            f"before the stopping rule would be an early look.")
    recomputed = evaluate_frames(frames, b4b_verdict=b4b_verdict)
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


def forward_command(root: Path, *,
                    b4b_verdict: Path | None = None) -> dict:
    """One command for the frozen study: the verdict, or what is missing."""
    prior = _read_stored_verdict()
    if prior is not None and prior.get("status") != "UNDERPOWERED":
        return {"state": "VERDICT", "verdict": prior,
                "note": "already fired; never recomputed or overwritten"}
    doc = status_doc(root)
    if doc["powered"]:
        verdict = run(root, b4b_verdict=b4b_verdict)
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
    ap = argparse.ArgumentParser(prog="forward_fcarry")
    ap.add_argument("cmd", choices=("fetch", "status", "run", "verify"))
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--manifest-out", default=str(TRACKED_MANIFEST))
    ap.add_argument("--force", action="store_true",
                    help="run even while UNDERPOWERED (writes an "
                         "UNDERPOWERED document, never a verdict)")
    ap.add_argument("--b4b-verdict", default=str(B4B_VERDICT_DEFAULT),
                    help="B4b verdict JSON supplying the forward Sharpe "
                         "for the N=16 trial vector (missing/unscored "
                         "applies the frozen missing-B4b rule)")
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
        doc = run(root, force=args.force,
                  b4b_verdict=Path(args.b4b_verdict))
        print(json.dumps(doc, indent=1, sort_keys=True, default=str))
        return 0
    if args.cmd == "verify":
        doc = verify(root, b4b_verdict=Path(args.b4b_verdict))
        print(json.dumps(doc, indent=1, sort_keys=True, default=str))
        return 0 if doc["state"] != "MISMATCH" else 1
    raise AssertionError("unreachable")  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
