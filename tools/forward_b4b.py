#!/usr/bin/env python3
"""B4b forward basis/carry recorder + evaluator.

Prereg: ``research/prereg/B4b-forward-basis.md`` (FROZEN before any forward
read). Every rule, cost term, gate and stopping condition in this file is
transcribed from that document; if the two ever disagree, the prereg wins
and this file is the bug.

Forward window only: files dated strictly after 2026-10-17 (daily) and
months strictly after 2026-10 (monthly). The recorder refuses to run if it
cannot form a purely-forward input set, and it never falls back to holdout
or dev bytes.

Data source: the Binance Vision CDN only (``data.binance.vision``). The
public REST host ``fapi.binance.com`` answers HTTP 451 from this network,
and a REST pull would not be forward-only anyway.

Usage
-----
    python tools/forward_b4b.py fetch    [--root data/forward_b4b]
    python tools/forward_b4b.py status   [--root data/forward_b4b]
    python tools/forward_b4b.py evaluate [--root data/forward_b4b]
    python tools/forward_b4b.py all

``fetch`` downloads and checksum-verifies the forward files, writing a
manifest of sha256 digests. ``status`` reports coverage and how many
forward days and round trips are still missing before the study is powered
(no return statistics: that would be a look). ``evaluate`` computes the B4b
series point-in-time and fires the one look; it refuses while UNDERPOWERED
and refuses to overwrite a verdict that has already fired.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
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

# -- frozen constants (research/prereg/B4b-forward-basis.md) ------------------
VISION = "https://data.binance.vision"
S3LIST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"

CUTOFF_DAY = dt.date(2026, 10, 17)      # forward iff strictly after
CUTOFF_MONTH = "2026-10"                # forward iff strictly after
FORWARD_CLOCK_START = "2026-11-01"      # first day with forward-only funding
UNIVERSE = ("BTCUSDT", "ETHUSDT")

RT_BPS = 53.0                # hurdle identity only (B4's 53 bps); see below
SPOT_TAKER_BPS = 15.0
SPOT_SPREAD_BPS = 1.0
PERP_TAKER_BPS = 7.5
PERP_SPREAD_BPS = 1.0
# The 1 bp/fill slip floor is REMOVED and replaced by per-fill impact.
FILL_BPS = {"spot": SPOT_TAKER_BPS + SPOT_SPREAD_BPS,
            "perp": PERP_TAKER_BPS + PERP_SPREAD_BPS}

K_HURDLE = 1.5
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
MIN_ROUND_TRIPS = 20

GATE_SHARPE = 0.70
GATE_SHARPE_2X = 0.30
GATE_DSR = 0.80
GATE_PBO = 0.30
GATE_DD = 0.35
GATE_MEDIAN_PARTICIPATION = 0.01
GATE_MAX_PARTICIPATION = 0.05
GATE_NW_T = 2.0
GATE_BOOTSTRAP_LOWER_Q = 0.20
YEARS_NEEDED = 2
YEAR_MIN_DAYS = 60
# Gates that are null for structural reasons and cannot block a pass.
#
# "pbo": CSCV needs a cross-section of competing trials on one timeline;
#   a single preregistered cell has no IS/OOS ranking to invert.
# "plateau": plateau_fraction walks Hamming-1 neighbours of the winning
#   cell in a parameter grid; a single frozen forward cell has no grid,
#   so there are no neighbours to walk.
# Every other null gate -- notably "years" -- blocks a PASS.
STRUCTURAL_NULL_GATES = frozenset({"pbo", "plateau"})

B4_DEV_ARTIFACT = ROOT / "research/autopilot_b/dev/B4.json"
VERDICT_DIR = ROOT / "reports/hypotheses"
VERDICT_NAME = "B4b-forward.json"
DEFAULT_ROOT = ROOT / "data/forward_b4b"

DAY_RE = re.compile(r"-(\d{4}-\d{2}-\d{2})\.zip$")
MONTH_RE = re.compile(r"-(\d{4}-\d{2})\.zip$")


class InputBeforeForwardWindow(RuntimeError):
    """An input file or row predates the forward window. Never tolerated."""


# -- forward-window rules (pure) ---------------------------------------------
def file_window(name: str) -> tuple[str, str]:
    """('day'|'month', stamp) for a Vision file name; raises if undated."""
    day = DAY_RE.search(name)
    if day:
        return "day", day.group(1)
    month = MONTH_RE.search(name)
    if month:
        return "month", month.group(1)
    raise ValueError(f"no YYYY-MM[-DD] date in {name!r}")


def is_forward_file(name: str) -> bool:
    """The prereg's file rule: daily > 2026-10-17, monthly > 2026-10."""
    kind, stamp = file_window(name)
    if kind == "day":
        return stamp > CUTOFF_DAY.isoformat()
    return stamp > CUTOFF_MONTH


def forward_clock_start() -> pd.Timestamp:
    return pd.Timestamp(FORWARD_CLOCK_START, tz="UTC")


def hurdle_apr(k: float = K_HURDLE, rt_bps: float = RT_BPS) -> float:
    """Entry hurdle carried from C1: k * RT * 365 / 7."""
    return k * (rt_bps / 1e4) * 365.0 / 7.0


def median_hurdle_rate(k: float = K_HURDLE, rt_bps: float = RT_BPS) -> float:
    """The trailing median 8h rate the hurdle implies."""
    return hurdle_apr(k, rt_bps) / (3.0 * 365.0)


# -- fetching (Vision CDN, polite, checksum-verified) -------------------------
class VisionClient:
    """Rate-limited, retrying, checksum-verifying Vision fetcher."""

    def __init__(self, *, delay: float = 0.30, timeout: float = 60.0,
                 retries: int = 4) -> None:
        self.delay = float(delay)
        self.timeout = float(timeout)
        self.retries = int(retries)
        self._last = 0.0
        self.requests = 0

    def _polite(self) -> None:
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        self.requests += 1

    def get(self, url: str) -> bytes:
        last: Exception | None = None
        for attempt in range(self.retries):
            self._polite()
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "cryptobot-b4b-forward/1"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return r.read()
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code in (403, 404):
                    raise
            except Exception as exc:  # noqa: BLE001 — retried with backoff
                last = exc
            time.sleep(min(2.0 ** attempt, 8.0))
        raise RuntimeError(f"GET failed: {url}: {last}")

    def list_keys(self, prefix: str) -> list[dict]:
        out: list[dict] = []
        token: str | None = None
        while True:
            q = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
            if token:
                q["continuation-token"] = token
            root = ET.fromstring(self.get(S3LIST + "?" + urllib.parse.urlencode(q)))
            for c in root.findall(f"{S3_NS}Contents"):
                key = c.findtext(f"{S3_NS}Key") or ""
                if key:
                    out.append({"key": key,
                                "size": int(c.findtext(f"{S3_NS}Size") or 0)})
            if (root.findtext(f"{S3_NS}IsTruncated") or "").lower() != "true":
                return out
            token = root.findtext(f"{S3_NS}NextContinuationToken")
            if not token:
                return out

    def download_verified(self, key: str, dest: Path) -> dict:
        """Download ``key`` and verify its sibling .CHECKSUM (sha256).

        The published digest is fetched and compared on *every* call,
        including when the file is already on disk. A resumed path that
        trusted local bytes would let a corrupted, truncated or replaced
        file pass as verified while the caller printed "checksums
        verified" -- exactly the assurance the prereg relies on.
        """
        url = f"{VISION}/{urllib.parse.quote(key, safe='/')}"
        want = self.get(url + ".CHECKSUM").decode().split()[0]
        if dest.exists():
            local = _sha256_file(dest)
            if local == want:
                return {"key": key, "path": str(dest), "resumed": True,
                        "sha256": local, "verified": True}
            # Local copy is not the published artifact: re-fetch it.
            dest.unlink()
        blob = self.get(url)
        got = hashlib.sha256(blob).hexdigest()
        if got != want:
            raise RuntimeError(
                f"checksum mismatch for {key}: want={want[:16]} got={got[:16]}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(blob)
        os.replace(tmp, dest)
        return {"key": key, "path": str(dest), "sha256": got,
                "bytes": len(blob), "resumed": False, "verified": True}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def wanted_prefixes(symbol: str) -> dict[str, list[str]]:
    return {
        "spot": [f"data/spot/daily/klines/{symbol}/1h/"],
        "perp": [f"data/futures/um/daily/klines/{symbol}/1h/"],
        "funding": [f"data/futures/um/monthly/fundingRate/{symbol}/"],
    }


def local_path(root: Path, dataset: str, symbol: str, name: str) -> Path:
    return root / dataset / symbol / name


def plan_files(vision: VisionClient, *, symbols=UNIVERSE) -> list[dict]:
    """Every forward-dated Vision file for the three needed datasets."""
    jobs: list[dict] = []
    for symbol in symbols:
        for dataset, prefixes in wanted_prefixes(symbol).items():
            for prefix in prefixes:
                for item in vision.list_keys(prefix):
                    name = item["key"].rsplit("/", 1)[-1]
                    if not name.endswith(".zip"):
                        continue          # .CHECKSUM siblings
                    try:
                        ok = is_forward_file(name)
                    except ValueError:
                        continue          # undated junk object
                    if not ok:
                        continue          # pre-window: never fetched
                    jobs.append({"dataset": dataset, "symbol": symbol,
                                 "name": name, "key": item["key"],
                                 "size": item["size"]})
    return sorted(jobs, key=lambda j: (j["dataset"], j["symbol"], j["name"]))


def fetch(root: Path, vision: VisionClient, *,
          symbols=UNIVERSE) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    jobs = plan_files(vision, symbols=symbols)
    records = []
    for job in jobs:
        dest = local_path(root, job["dataset"], job["symbol"], job["name"])
        rec = vision.download_verified(job["key"], dest)
        rec.update({"dataset": job["dataset"], "symbol": job["symbol"],
                    "name": job["name"]})
        records.append(rec)
    manifest = {
        "format": "cryptobot-b4b-forward-manifest/1",
        "generated_utc": dt.datetime.now(dt.UTC).isoformat(),
        "prereg": "research/prereg/B4b-forward-basis.md",
        "source": VISION,
        "cutoff_day": CUTOFF_DAY.isoformat(),
        "cutoff_month": CUTOFF_MONTH,
        "forward_clock_start": FORWARD_CLOCK_START,
        "files": records,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return manifest


# -- loading (forward-window enforced) ---------------------------------------
def _series_ms(idx: pd.Series) -> pd.Series:
    """Epoch milliseconds from a tz-aware datetime Series (any unit)."""
    naive = pd.to_datetime(idx, utc=True).dt.tz_localize(None)
    return naive.astype("datetime64[ms]").astype("int64")


def _read_kline_zip(path: Path) -> pd.DataFrame:
    """Vision 1h kline zip -> (open_ms, open, close, quote_volume).

    Vision's own format drifts: UM klines carry a header row and millisecond
    timestamps while spot klines carry no header and microsecond timestamps
    (observed on the 2026-10-23 files). ``lake.read_klines_zip`` already
    infers both, so it is reused rather than re-derived here.
    """
    df = read_klines_zip(path)
    return pd.DataFrame({
        "open_ms": _series_ms(df["open_time"]),
        "open": df["open"].astype(float),
        "close": df["close"].astype(float),
        "quote_volume": df["quote_volume"].astype(float),
    })


def _read_funding_zip(path: Path) -> pd.DataFrame:
    """Vision monthly fundingRate zip -> (calc_ms, rate)."""
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
    """The half-open ``[start, end)`` of a Vision file's own date stamp.

    A daily file may only carry rows inside its own UTC day; a monthly file
    only rows inside its own month. A forward-only study cannot rely on the
    file *name* alone: a holdout-dated file renamed to a forward date would
    otherwise smuggle pre-window rows past the filename rule.
    """
    kind, stamp = file_window(name)
    start = pd.Timestamp(stamp, tz="UTC")
    if kind == "day":
        return start, start + pd.Timedelta(days=1)
    return start, start + pd.offsets.MonthBegin(1)


def _assert_rows_in_file_window(df: pd.DataFrame, stamp_col: str,
                                name: str) -> None:
    """Every row must fall inside its own file's date window.

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


def assert_forward_files(names: list[str]) -> None:
    bad = [n for n in names if not _safe_forward(n)]
    if bad:
        raise InputBeforeForwardWindow(
            "refusing to run: pre-window input(s) requested: "
            + ", ".join(sorted(bad)[:10]))


def _safe_forward(name: str) -> bool:
    try:
        return is_forward_file(name)
    except ValueError:
        return False


def load_frames(root: Path) -> dict[str, dict[str, pd.DataFrame]]:
    """Build per-symbol {spot, perp, funding} forward-only frames."""
    out: dict[str, dict[str, pd.DataFrame]] = {}
    for symbol in UNIVERSE:
        frames: dict[str, pd.DataFrame] = {}
        for dataset in ("spot", "perp", "funding"):
            folder = root / dataset / symbol
            zips = sorted(folder.glob("*.zip")) if folder.exists() else []
            names = [p.name for p in zips]
            assert_forward_files(names)
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
        out[symbol] = frames
    return out


def coverage(frames: dict[str, dict[str, pd.DataFrame]]) -> dict:
    """Per-dataset first/last forward day actually present."""
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


# -- the B4b book ------------------------------------------------------------
@dataclass
class B4bConfig:
    e0: float = E0
    k: float = K_HURDLE
    drift_band: float = DRIFT_BAND
    rt_bps: float = RT_BPS
    adverse_mult: float = 1.0
    adv_window: int = ADV_WINDOW
    participation_cap: float = PARTICIPATION_CAP
    qty_step: float = QTY_STEP
    min_notional: float = MIN_NOTIONAL


DEFAULT_CONFIG = B4bConfig()


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
    cfg: B4bConfig
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
    """(sigma_d, ADV20) from bars strictly before ``boundary``.

    ``bars`` is 1h with UTC ``time`` index, ``close`` and ``quote_volume``.
    A forward-only study means these windows can only ever be filled with
    forward bars; there is no fallback to a constant.
    """
    past = bars[bars.index < boundary]
    if past.empty:
        return 0.0, 0.0
    day_close = past["close"].resample("1D").last().dropna()
    day_qv = past["quote_volume"].resample("1D").sum(min_count=1).dropna()
    day_close = day_close.tail(window + 1)
    day_qv = day_qv.tail(window)
    # ADV20 is a 20-day median, so 20 forward days of bars must exist first;
    # there is no shorter-window substitute (the prereg allows no fallback).
    if len(day_qv) < window or len(day_close) < 2:
        return 0.0, 0.0
    rets = np.log(day_close.astype(float)).diff().dropna()
    sigma = float(rets.std(ddof=1)) if len(rets) >= 2 else 0.0
    adv = float(day_qv.median())
    return (sigma if sigma > 0 else 0.0), (adv if adv > 0 else 0.0)


def _prep(frames: dict[str, pd.DataFrame]) -> dict:
    """Index the 1h klines by time and the funding settlements by time."""
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
    """00:00 UTC boundaries covered by the perp bars (the study clock)."""
    if perp.empty:
        return []
    days = pd.date_range(perp.index.min().floor("D"),
                         perp.index.max().floor("D"), freq="D")
    return [d for d in days if d >= forward_clock_start()]


def _day_has_inputs(prep: dict, day: pd.Timestamp) -> bool:
    """A forward day needs every input: both venues' bars and a settlement.

    The prereg defines a forward day as one where *every* input used to mark
    it comes from a forward-dated file. Bars alone are not a day: without a
    funding settlement there is no carry to measure, so counting it would
    overstate the forward clock. Funding alone is not a day either: the mark
    for ``day`` is the last close at or before it, so both venues must have
    bars inside the preceding forward day. Without that check, dropping days
    of bars left the day counted and marked off a stale price, which lifted
    Sharpe 6.957 -> 7.566 on the review sample with no new data at all.
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


def _trailing_funding(funding: pd.Series, boundary: pd.Timestamp,
                      n: int = TRAIL_SETTLEMENTS) -> float | None:
    past = funding[funding.index < boundary]
    if len(past) < n:
        return None
    return float(np.median(past.tail(n).to_numpy(dtype=float)))


def simulate(frames_by_symbol: dict[str, dict[str, pd.DataFrame]],
             cfg: B4bConfig | None = None) -> dict:
    """Run the frozen B4b book point-in-time. Returns ledger + audit trail."""
    cfg = cfg or DEFAULT_CONFIG
    prep = {s: _prep(f) for s, f in frames_by_symbol.items()}
    hurdle = hurdle_apr(cfg.k, cfg.rt_bps)
    book = Book(cash=cfg.e0, cfg=cfg)
    days: list[pd.Timestamp] = []
    for s in UNIVERSE:
        if "perp" in prep.get(s, {}):
            days = sorted(set(days) | set(decision_days(prep[s]["perp"])))
    days = [d for d in days if _day_has_inputs(prep, d)]
    rows: list[dict] = []
    prev_equity = cfg.e0
    for day in days:
        # 1) accrue P&L and funding over (day-1d, day]
        for symbol, pos in list(book.positions.items()):
            p = prep[symbol]
            s_now = _price_at(p["spot"], day)
            p_now = _price_at(p["perp"], day)
            # Only the perp is a derivative whose variation margin settles
            # into cash. The spot leg is a held asset: its P&L is already
            # the mark (qty_spot * price) added to equity below, so accruing
            # a spot delta into cash as well counted the spot leg twice and
            # left the "delta-neutral" book long 1x spot for the whole hold
            # (equity = E0 + q*(s_t - s_entry) + funding - costs).
            book.cash += pos.qty_perp * (p_now - pos.price_perp)
            window = p["funding"][(p["funding"].index > day - pd.Timedelta(days=1))
                                  & (p["funding"].index <= day)]
            if len(window) and p_now > 0:
                book.cash += float(window.sum()) * (-pos.qty_perp) * p_now
                book.funding_income += float(window.sum()) * (-pos.qty_perp) * p_now
            pos.price_spot, pos.price_perp = s_now, p_now
        equity = book.cash + sum(pos.qty_spot * _price_at(prep[s]["spot"], day)
                                 for s, pos in book.positions.items())
        # 2) per-symbol decision at `day`
        for symbol in UNIVERSE:
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
            below = apr < 0.5 * hurdle
            pos.exit_streak = pos.exit_streak + 1 if below else 0
            do_exit = (median < 0) or (held >= MIN_HOLD_DAYS
                                       and pos.exit_streak >= EXIT_STREAK)
            if do_exit:
                s_px = _fill_bar_price(p["spot"], day)
                p_px = _fill_bar_price(p["perp"], day)
                # The perp is closed by a trade at p_px, so its variation
                # margin runs to that price; otherwise the gap between the
                # last daily mark and the exit fill is never booked and the
                # two legs stop cancelling on the exit day.
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
            # Rebalances execute where entry and exit execute: the open of
            # the next 1h bar after the decision (prereg, execution rule).
            # Using the prior close here priced the hedge on a bar the
            # decision was not allowed to trade.
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


def run_both_costs(frames_by_symbol: dict[str, dict[str, pd.DataFrame]],
                   cfg: B4bConfig | None = None) -> dict:
    cfg = cfg or DEFAULT_CONFIG
    base = simulate(frames_by_symbol, cfg)
    adverse_cfg = B4bConfig(**{**cfg.__dict__, "adverse_mult": 2.0})
    adverse = simulate(frames_by_symbol, adverse_cfg)
    return {"base": base, "adverse": adverse}


# -- gates ------------------------------------------------------------------
def trial_sharpes() -> list[float]:
    """The 9 B4 dev cell Sharpes (DSR trial vector, not a forward result)."""
    doc = json.loads(B4_DEV_ARTIFACT.read_text())
    sharpes = sorted(float(v) for v in doc["cell_sharpes"].values())
    if len(sharpes) != 9:
        raise RuntimeError(
            f"expected the 9 frozen B4 dev cells, found {len(sharpes)}")
    return sharpes


def _participation_stats(fills: list[dict]) -> dict:
    parts = [f["participation"] for f in fills if f["participation"] > 0]
    if not parts:
        return {"n": 0, "median": None, "max": None}
    return {"n": len(parts), "median": float(np.median(parts)),
            "max": float(max(parts))}


def years_assessable_forward_day() -> int:
    """Forward days needed before gate 6 (>= 2 positive years) exists.

    The clock starts mid-calendar-year, so the first year supplies only the
    days between ``FORWARD_CLOCK_START`` and 31 Dec, while every eligible
    year needs ``YEAR_MIN_DAYS`` forward days inside it. Under the
    2026-11-01 clock: 2026 supplies 61 forward days (so it is eligible once
    60 accrue), and 2027 reaches 60 forward days on 2027-03-01, which is
    forward day 61 + 60 = 121.

    Consequences, stated before any forward read: a 90-day look cannot PASS
    -- at 90 days the only determinate outcome is KILLED -- and a PASS first
    becomes possible on forward day 121. ``YEAR_MIN_DAYS`` stays at 60
    because raising it to 180 would make the gate permanently unassessable
    (2026 can never supply 180 forward days under the 14-day cut above).
    """
    cur = pd.Timestamp(FORWARD_CLOCK_START)
    elapsed = 0
    eligible = 0
    for _ in range(50):                      # bounded: a year is <= 366 days
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
    """First forward-clock date on which gate 6 can be assessed."""
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


def evaluate_frames(frames_by_symbol: dict[str, dict[str, pd.DataFrame]],
                    *, cfg: B4bConfig | None = None,
                    extra_trials: list[float] | None = None,
                    as_of: str | None = None) -> dict:
    """Full gate evaluation. Returns the verdict document (not yet written)."""
    cfg = cfg or DEFAULT_CONFIG
    out = run_both_costs(frames_by_symbol, cfg)
    base, adverse = out["base"], out["adverse"]
    rows = base["rows"]
    net = np.array([r["net_ret"] for r in rows], dtype=float) if rows else \
        np.zeros(0)
    net2 = np.array([r["net_ret"] for r in adverse["rows"]], dtype=float) \
        if adverse["rows"] else np.zeros(0)
    forward_days = int(len(rows))
    round_trips = int(base["round_trips"])
    powered_days = forward_days >= MIN_FORWARD_DAYS
    powered_rt = round_trips >= MIN_ROUND_TRIPS

    stats: dict[str, float] = {}
    if len(net) >= 2:
        stats["sharpe"] = ST.sharpe(net, periods=PERIODS)
        stats["sharpe_1x"] = stats["sharpe"]
        stats["max_dd"] = ST.max_drawdown(net)
        stats["mean_daily"] = float(net.mean())
        stats["final_equity"] = float(rows[-1]["equity"])
        stats["total_net"] = float(rows[-1]["equity"] / cfg.e0 - 1.0)
        stats["nw_t_lag30"] = ST.newey_west_tstat(net, max_lag=NW_LAG)
        lo, hi = ST.stationary_bootstrap_ci(
            list(net), np.mean, mean_block=BOOTSTRAP_BLOCK_D,
            rounds=BOOTSTRAP_ROUNDS, seed=7,
            lower_q=GATE_BOOTSTRAP_LOWER_Q)
        stats["bootstrap_lower"], stats["bootstrap_upper"] = lo, hi
    if len(net2) >= 2:
        stats["sharpe_2x"] = ST.sharpe(net2, periods=PERIODS)
    parts = _participation_stats(base["fills"])
    years_ok, year_stats = _year_gate(rows)
    turnover = _gross_turnover_per_year(rows, base["fills"], cfg.e0)
    capacity = (ST.capacity_estimate(median_adv=_median_adv(base["fills"]),
                                     max_participation=PARTICIPATION_CAP,
                                     gross_turnover_per_year=turnover)
                if turnover > 0 and base["fills"] else None)
    trials = list(extra_trials or []) + trial_sharpes()
    hold = base["mean_hold_days"] or None
    dsr_doc = (ST.dsr_detail(list(net),
                             trials + [stats.get("sharpe", 0.0)],
                             hold_days=hold)
               if len(net) >= 2 else {
                   "dsr": None, "n": forward_days, "n_eff": None,
                   "n_trials": len(trials) + 1})
    gates = {
        "sharpe": _gate(stats.get("sharpe"), GATE_SHARPE,
                        lambda v: v >= GATE_SHARPE),
        "sharpe_2x": _gate(stats.get("sharpe_2x"), GATE_SHARPE_2X,
                           lambda v: v > GATE_SHARPE_2X),
        "dsr": _gate(dsr_doc.get("dsr"), GATE_DSR, lambda v: v >= GATE_DSR),
        "pbo": None,   # single preregistered cell: see prereg, DSR carries it
        "plateau": None,   # no parameter grid to walk: see prereg
        "drawdown": _gate(stats.get("max_dd"), GATE_DD, lambda v: v <= GATE_DD),
        "years": years_ok,
        "median_participation": _gate(parts["median"],
                                      GATE_MEDIAN_PARTICIPATION,
                                      lambda v: v <= GATE_MEDIAN_PARTICIPATION),
        "max_participation": _gate(parts["max"], GATE_MAX_PARTICIPATION,
                                   lambda v: v <= GATE_MAX_PARTICIPATION),
        "bootstrap": _gate(
            stats.get("bootstrap_lower"), 0.0, lambda v: v > 0.0)
        if len(net) >= 2 else None,
        "newey_west_t": _gate(stats.get("nw_t_lag30"), GATE_NW_T,
                              lambda v: v >= GATE_NW_T),
    }
    failed = sorted(k for k, v in gates.items() if v is False)
    unknown = sorted(k for k, v in gates.items() if v is None)
    # A null gate that is null BY STRUCTURE is not a blocker: PBO has no
    # cross-section of trials and plateau has no parameter grid in a single
    # preregistered cell, so the selection penalty is carried by DSR at
    # N = 10 instead (prereg). "years" is NOT structural: it blocks.
    structural_null = [k for k in unknown if k in STRUCTURAL_NULL_GATES]
    blocking_unknown = [k for k in unknown if k not in STRUCTURAL_NULL_GATES]
    if not (powered_days and powered_rt):
        # The stopping rule comes first: before the study is powered, gate
        # values are snapshots, not a verdict. Nothing fires early.
        status = "UNDERPOWERED"
        reason = "stopping rule: <90 forward days or <20 round trips"
    elif failed:
        status = "KILLED"
        reason = "failed gate(s): " + ", ".join(failed)
    elif blocking_unknown:
        # e.g. the >=2-positive-years gate before two calendar years exist
        status = "UNDERPOWERED"
        reason = ("gate(s) not yet assessable: " + ", ".join(blocking_unknown))
    else:
        status = "PASS"
        reason = "every gate passed"
    years_from = years_assessable_forward_day()
    return {
        "hypothesis": "B4b-forward-basis",
        "prereg": "research/prereg/B4b-forward-basis.md",
        "as_of_utc": as_of or dt.datetime.now(dt.UTC).isoformat(),
        "status": status,
        "status_reason": reason,
        "forward_days": forward_days,
        "forward_days_remaining": max(0, MIN_FORWARD_DAYS - forward_days),
        "round_trips": round_trips,
        "round_trips_remaining": max(0, MIN_ROUND_TRIPS - round_trips),
        "powered": bool(powered_days and powered_rt),
        # The years gate is inherited from B4 and is not structural, so a
        # PASS is impossible before it can be assessed. Stated in the
        # prereg; reported here so a 90-day look cannot be misread.
        "years_assessable_from_forward_day": years_from,
        "years_assessable_from": str(years_assessable_on()),
        "forward_days_to_first_possible_pass": max(0, years_from - forward_days),
        "mean_hold_days": base["mean_hold_days"],
        "gates": gates,
        "failed_gates": failed,
        "unassessable_gates": blocking_unknown,
        "structural_null_gates": structural_null,
        "stats": stats,
        "years": year_stats,
        "participation": parts,
        "dsr_detail": dsr_doc,
        "trial_sharpes_n": len(trials) + 1,
        "fees_per_round_trip_bps": 2 * (SPOT_TAKER_BPS + SPOT_SPREAD_BPS)
        + 2 * (PERP_TAKER_BPS + PERP_SPREAD_BPS),
        "hurdle_apr": hurdle_apr(cfg.k, cfg.rt_bps),
        "hurdle_median_rate": median_hurdle_rate(cfg.k, cfg.rt_bps),
        "capital_capacity": capacity,
        "gross_turnover_per_year_descriptive": turnover,
        "net_daily": [float(x) for x in net],
        "days": [r["day"] for r in rows],
    }


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


def _gate(value, threshold: float, test) -> bool | None:
    if value is None:
        return None
    return bool(test(float(value)))


# -- commands ---------------------------------------------------------------
def status_doc(root: Path) -> dict:
    frames = load_frames(root)
    cov = coverage(frames)
    sim = simulate(frames)
    rows, rt = sim["rows"], sim["round_trips"]
    years_from = years_assessable_forward_day()
    return {
        "prereg": "research/prereg/B4b-forward-basis.md",
        "forward_clock_start": FORWARD_CLOCK_START,
        "coverage": cov,
        "forward_days": len(rows),
        "forward_days_required": MIN_FORWARD_DAYS,
        "forward_days_remaining": max(0, MIN_FORWARD_DAYS - len(rows)),
        "round_trips": rt,
        "round_trips_required": MIN_ROUND_TRIPS,
        "round_trips_remaining": max(0, MIN_ROUND_TRIPS - rt),
        "powered": bool(len(rows) >= MIN_FORWARD_DAYS
                        and rt >= MIN_ROUND_TRIPS),
        "years_assessable_from_forward_day": years_from,
        "years_assessable_from": str(years_assessable_on()),
        "forward_days_to_first_possible_pass": max(0, years_from - len(rows)),
        # The book is run point-in-time to get the powering counters (a
        # round trip cannot be counted without it). No return statistic is
        # computed, reported or written here -- ``evaluate`` does that, once.
        "note": ("coverage and powering counters only; the book is run for "
                 "the round-trip count but no return statistic is reported"),
    }


def evaluate(root: Path, *, force: bool = False,
             out_dir: Path = VERDICT_DIR) -> dict:
    doc = status_doc(root)
    if not doc["powered"] and not force:
        raise SystemExit(
            f"B4b is UNDERPOWERED: {doc['forward_days']} of "
            f"{MIN_FORWARD_DAYS} forward days, {doc['round_trips']} of "
            f"{MIN_ROUND_TRIPS} round trips. "
            f"{doc['forward_days_remaining']} forward day(s) and "
            f"{doc['round_trips_remaining']} round trip(s) still to go. "
            f"A PASS is impossible before forward day "
            f"{doc['years_assessable_from_forward_day']} "
            f"({doc['years_assessable_from']}, the years gate). "
            "The one look does not fire early (prereg stopping rule).")
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / VERDICT_NAME
    if dest.exists():
        prior = json.loads(dest.read_text())
        if prior.get("status") != "UNDERPOWERED":
            raise SystemExit(
                f"{dest} already holds a {prior.get('status')} verdict; the "
                "study gets one look (prereg stopping rule)")
    frames = load_frames(root)
    verdict = evaluate_frames(frames)
    verdict["coverage"] = doc["coverage"]
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(verdict, indent=1) + "\n")
    tmp.replace(dest)
    return verdict


def main(argv=None) -> int:
    from cryptobot import netguard  # opt-in DNS-sinkhole fallback (CRYPTOBOT_DOH=1)

    netguard.install_from_env()
    ap = argparse.ArgumentParser(
        prog="forward_b4b",
        description="B4b forward basis recorder/evaluator (Vision CDN only)")
    ap.add_argument("cmd", choices=("fetch", "status", "evaluate", "all"))
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--force", action="store_true",
                    help="evaluate even while UNDERPOWERED (manual override; "
                         "writes an UNDERPOWERED verdict, never a pass)")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if args.cmd in ("fetch", "all"):
        vision = VisionClient()
        manifest = fetch(root, vision)
        print(f"forward_b4b: fetched {len(manifest['files'])} forward file(s) "
              f"into {root} ({vision.requests} request(s), checksums verified)")
    if args.cmd in ("status", "all"):
        doc = status_doc(root)
        print(json.dumps(doc, indent=1))
        print(f"forward_b4b: {doc['forward_days']}/{MIN_FORWARD_DAYS} forward "
              f"days, {doc['round_trips']}/{MIN_ROUND_TRIPS} round trips -> "
              f"{doc['forward_days_remaining']} day(s) and "
              f"{doc['round_trips_remaining']} round trip(s) remaining")
    if args.cmd == "evaluate":
        verdict = evaluate(root, force=args.force)
        print(json.dumps(verdict, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
