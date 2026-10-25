"""C2-FWD forward paper recorder (prereg: research/prereg/C2-forward.md).

Public REST only: no keys, no orders. Recording is allowed at or after
00:05 UTC. Repeated invocations are idempotent; missed days are booked only
when their point-in-time universe snapshots are available. `health` reports
coverage only. Scoring is a separate, explicit command.
"""
from __future__ import annotations

import argparse
import datetime as dt
import errno
import fcntl
import hashlib
import json
import math
import os
import statistics
import sys
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptobot.research import c_family, quant  # noqa: E402

BASE = "https://fapi.binance.com"
UNIVERSE_SIZE = 30
HISTORY_DAYS = c_family.MIN_HISTORY_DAYS
MIN_LISTING_DAYS = 35
REPORTS = Path(__file__).resolve().parents[1] / "reports/hypotheses"
LOOKS = (365, 730, 1095)
OBF_BOUNDS = (2.973, 2.102, 1.717)
BOOTSTRAP_ROUNDS = 50_000
VM_TARGET_BPS, VM_CAP, VM_WINDOW, VM_WARMUP = 150.0, 2.0, 120, 20
BOOKING_CUTOFF = dt.time(0, 5, tzinfo=dt.UTC)
MAX_UNIVERSE_SNAPSHOT_AGE = dt.timedelta(hours=8)
MAX_EXCHANGE_INFO_CLOCK_SKEW = dt.timedelta(minutes=15)
_FUNDING_INTERVAL_MS = 8 * 60 * 60 * 1000


class RefusedToBook(RuntimeError):
    """The available public data is insufficient for an honest daily row."""


class LedgerError(RuntimeError):
    """The forward ledger is malformed, discontinuous, or inconsistent."""


class Fetcher(Protocol):
    def universe_snapshot(self, day: str, *, observed_at: dt.datetime,
                          include_volume: bool) -> dict: ...
    def quote_volume_30d(self, symbol: str, end_day: str) -> float: ...
    def mark_closes(self, symbol: str, start: str, end: str) -> dict[str, float]: ...
    def funding_events(self, symbol: str, start_day: str,
                       end_day: str) -> list[tuple[int, float]]: ...


def _ms(day: str) -> int:
    return int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.UTC).timestamp() * 1000)


def _day(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.UTC).strftime("%Y-%m-%d")


def _shift(day: str, n: int) -> str:
    return (dt.date.fromisoformat(day) + dt.timedelta(days=n)).isoformat()


def _parse_utc(value: str) -> dt.datetime:
    if not isinstance(value, str):
        raise RefusedToBook("invalid snapshot timestamp")
    try:
        stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise RefusedToBook("invalid snapshot timestamp") from exc
    if stamp.tzinfo is None:
        raise RefusedToBook("snapshot timestamp has no timezone")
    return stamp.astimezone(dt.UTC)


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(float(value))


class RestFetcher:
    """Binance USD-M public endpoints (no credentials)."""

    def __init__(self, *, now: Callable[[], dt.datetime] | None = None,
                 now_ms: Callable[[], int] | None = None) -> None:
        if now is not None:
            self._now = now
        elif now_ms is not None:
            self._now = lambda: dt.datetime.fromtimestamp(now_ms() / 1000, dt.UTC)
        else:
            self._now = lambda: dt.datetime.now(dt.UTC)
        self._funding_intervals: dict[str, int] | None = None
        self._exchange_server_time_ms: int | None = None

    def _data_time_ms(self) -> int:
        if self._exchange_server_time_ms is not None:
            return self._exchange_server_time_ms
        now = self._now()
        if now.tzinfo is None:
            raise RefusedToBook("candle clock must be timezone-aware")
        return int(now.astimezone(dt.UTC).timestamp() * 1000)

    def _get(self, path: str, **params) -> object:
        url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "cryptobot-c2-fwd"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())

    def universe_snapshot(self, day: str, *, observed_at: dt.datetime,
                          include_volume: bool) -> dict:
        self._exchange_server_time_ms = None
        info = self._get("/fapi/v1/exchangeInfo")
        required_info = ("timezone", "serverTime", "rateLimits", "exchangeFilters", "symbols")
        if (not isinstance(info, dict)
                or any(key not in info for key in required_info)
                or not isinstance(info.get("timezone"), str)
                or not isinstance(info.get("serverTime"), int)
                or not isinstance(info.get("rateLimits"), list)
                or not isinstance(info.get("exchangeFilters"), list)):
            raise RefusedToBook("exchangeInfo snapshot is empty or partial")
        server_time = dt.datetime.fromtimestamp(info["serverTime"] / 1000, dt.UTC)
        if observed_at.tzinfo is None:
            raise RefusedToBook("exchangeInfo observation clock must be timezone-aware")
        local_observed = observed_at.astimezone(dt.UTC)
        if abs(server_time - local_observed) > MAX_EXCHANGE_INFO_CLOCK_SKEW:
            raise RefusedToBook("exchangeInfo server time is stale")
        if server_time.date().isoformat() != day or server_time.timetz() < BOOKING_CUTOFF:
            raise RefusedToBook("exchangeInfo server time is outside the UTC booking day")
        self._exchange_server_time_ms = info["serverTime"]
        if not isinstance(info, dict) or not isinstance(info.get("symbols"), list) \
                or not info["symbols"]:
            raise RefusedToBook("exchangeInfo snapshot is empty or partial")
        symbols: dict[str, dict] = {}
        for item in info["symbols"]:
            if not isinstance(item, dict) or any(
                    key not in item for key in ("contractType", "quoteAsset", "symbol", "status")):
                raise RefusedToBook("exchangeInfo contains a partial symbol row")
            if item.get("contractType") != "PERPETUAL" or item.get("quoteAsset") != "USDT":
                continue
            sym = item.get("symbol")
            if not isinstance(sym, str) or not sym or sym in symbols:
                raise RefusedToBook("exchangeInfo contains an invalid or duplicate symbol")
            onboard_ms = item.get("onboardDate")
            if not isinstance(onboard_ms, (int, float)) or onboard_ms <= 0:
                raise RefusedToBook("exchangeInfo listing date is missing")
            onboard = _day(int(onboard_ms))
            symbols[sym] = {"status": item.get("status"), "onboard_date": onboard}
        if not symbols:
            raise RefusedToBook("exchangeInfo has no USD-M perpetual symbols")
        if include_volume:
            raise RefusedToBook(
                "volume ranking must be finalized from the saved pre-close snapshot")
        return {"day": day, "observed_at_utc": server_time.isoformat(),
                "source": "exchangeInfo", "symbols": symbols,
                "quote_volume_30d": {}, "volume_observed_at_utc": None}

    def quote_volume_30d(self, symbol: str, end_day: str) -> float:
        start = _shift(end_day, -29)
        rows = self._get("/fapi/v1/klines", symbol=symbol, interval="1d",
                         startTime=_ms(start), endTime=_ms(end_day) + 86_399_999,
                         limit=30)
        if not isinstance(rows, list) or len(rows) != 30:
            raise RefusedToBook(f"incomplete 30-day volume window for {symbol}")
        expected = [_shift(start, i) for i in range(30)]
        got: list[str] = []
        volumes: list[float] = []
        now_ms = self._data_time_ms()
        for row in rows:
            try:
                opened, closed, quote = int(row[0]), int(row[6]), float(row[7])
            except (IndexError, TypeError, ValueError) as exc:
                raise RefusedToBook(f"malformed 30-day volume window for {symbol}") from exc
            if opened % 86_400_000 or closed != opened + 86_399_999:
                raise RefusedToBook(f"malformed UTC volume candle for {symbol}")
            if closed > now_ms or not math.isfinite(quote) or quote < 0:
                raise RefusedToBook(f"stale or invalid volume candle for {symbol}")
            got.append(_day(opened))
            volumes.append(quote)
        if got != expected:
            raise RefusedToBook(f"incomplete 30-day volume window for {symbol}")
        total = math.fsum(volumes)
        if not math.isfinite(total):
            raise RefusedToBook(f"invalid 30-day quote volume for {symbol}")
        return total

    def mark_closes(self, symbol: str, start: str, end: str) -> dict[str, float]:
        rows = self._get("/fapi/v1/markPriceKlines", symbol=symbol, interval="1d",
                         startTime=_ms(start), endTime=_ms(end) + 86_399_999,
                         limit=1500)
        if not isinstance(rows, list):
            raise RefusedToBook(f"malformed mark-candle response for {symbol}")
        now_ms = self._data_time_ms()
        out: dict[str, float] = {}
        for row in rows:
            try:
                opened, closed, price = int(row[0]), int(row[6]), float(row[4])
            except (IndexError, TypeError, ValueError) as exc:
                raise RefusedToBook(f"malformed mark candle for {symbol}") from exc
            if opened % 86_400_000 or closed != opened + 86_399_999:
                raise RefusedToBook(f"malformed UTC mark candle for {symbol}")
            if closed > now_ms:
                continue
            day = _day(opened)
            if day in out or not math.isfinite(price) or price <= 0:
                raise RefusedToBook(f"duplicate or invalid mark candle for {symbol}")
            if start <= day <= end:
                out[day] = price
        return out

    def _funding_interval_hours(self, symbol: str) -> int:
        if self._funding_intervals is None:
            rows = self._get("/fapi/v1/fundingInfo")
            if not isinstance(rows, list):
                raise RefusedToBook("funding interval metadata is malformed")
            intervals: dict[str, int] = {}
            for row in rows:
                try:
                    row_symbol = row["symbol"]
                    hours = int(row["fundingIntervalHours"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise RefusedToBook("funding interval metadata is malformed") from exc
                if (not isinstance(row_symbol, str) or not row_symbol
                        or row_symbol in intervals or hours <= 0 or 24 % hours):
                    raise RefusedToBook("funding interval metadata is invalid")
                intervals[row_symbol] = hours
            self._funding_intervals = intervals
        return self._funding_intervals.get(symbol, 8)

    def funding_events(self, symbol: str, start_day: str,
                       end_day: str) -> list[tuple[int, float]]:
        start_ms, end_ms = _ms(start_day), _ms(end_day)
        rows = self._get("/fapi/v1/fundingRate", symbol=symbol,
                         startTime=start_ms + 1, endTime=end_ms, limit=1000)
        if not isinstance(rows, list):
            raise RefusedToBook(f"funding response is malformed for {symbol}")
        events: list[tuple[int, float]] = []
        for row in rows:
            try:
                stamp, rate = int(row["fundingTime"]), float(row["fundingRate"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RefusedToBook(f"malformed funding event for {symbol}") from exc
            if start_ms < stamp <= end_ms:
                if not math.isfinite(rate):
                    raise RefusedToBook(f"invalid funding event for {symbol}")
                events.append((stamp, rate))
        events.sort()
        times = [stamp for stamp, _ in events]
        interval_ms = self._funding_interval_hours(symbol) * 60 * 60 * 1000
        required = list(range(start_ms + interval_ms, end_ms + 1, interval_ms))
        if len(times) != len(set(times)) or set(times) != set(required):
            raise RefusedToBook(f"funding coverage incomplete for {symbol}")
        return events

    def funding(self, symbol: str, start: str, end: str) -> dict[str, float]:
        """Compatibility view of the complete public funding events by UTC day."""
        events = self.funding_events(symbol, start, _shift(end, 1))
        out: dict[str, float] = {}
        for stamp, rate in events:
            day = _day(stamp)
            out[day] = out.get(day, 0.0) + rate
        return out


def _snapshot_path(root: Path, day: str) -> Path:
    return root / "universe" / f"{day}.json"


def _close_snapshot_path(root: Path, day: str) -> Path:
    return root / "universe" / f"{day}.close.json"


def _validate_snapshot(snapshot: dict, day: str, *, close: bool = False) -> dict:
    if not isinstance(snapshot, dict) or snapshot.get("day") != day:
        raise RefusedToBook(f"point-in-time snapshot missing for {day}")
    if snapshot.get("source") != "carried-forward-ledger":
        observed = _parse_utc(snapshot.get("observed_at_utc"))
        expected = _shift(day, 1) if close else day
        if observed.date().isoformat() != expected or observed.timetz() < BOOKING_CUTOFF:
            moment = "after its UTC close" if close else "before its UTC close"
            raise RefusedToBook(f"snapshot for {day} was not observed {moment}")
    symbols = snapshot.get("symbols")
    volumes = snapshot.get("quote_volume_30d", {})
    if not isinstance(symbols, dict) or not symbols or not isinstance(volumes, dict):
        raise RefusedToBook(f"point-in-time snapshot for {day} is incomplete")
    for sym, meta in symbols.items():
        if not isinstance(sym, str) or not isinstance(meta, dict) \
                or not isinstance(meta.get("status"), str):
            raise RefusedToBook(f"point-in-time snapshot for {day} is malformed")
        onboard = meta.get("onboard_date")
        if onboard is not None:
            try:
                dt.date.fromisoformat(onboard)
            except (TypeError, ValueError) as exc:
                raise RefusedToBook(f"listing date is malformed for {sym}") from exc
    for sym, value in volumes.items():
        if sym not in symbols or not _finite(value) or value < 0:
            raise RefusedToBook(f"invalid volume snapshot for {sym}")
    volume_observed = snapshot.get("volume_observed_at_utc")
    if volume_observed is not None:
        stamp = _parse_utc(volume_observed)
        if stamp.date().isoformat() != _shift(day, 1) or stamp.timetz() < BOOKING_CUTOFF:
            raise RefusedToBook(f"volume snapshot for {day} was not finalized after close")
    return snapshot


def _atomic_replace(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                    dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
        _fsync_dir(path.parent)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _atomic_json_replace(path: Path, value: dict) -> None:
    _atomic_replace(path, (json.dumps(value, indent=1, sort_keys=True) + "\n").encode())


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _save_selection_snapshot(root: Path, snapshot: dict) -> dict:
    day = snapshot.get("day")
    snapshot = _validate_snapshot(snapshot, day)
    path = _snapshot_path(root, day)
    prior = _load_snapshot(root, day)
    if prior is not None:
        old_stamp = _parse_utc(prior["observed_at_utc"])
        new_stamp = _parse_utc(snapshot["observed_at_utc"])
        if new_stamp <= old_stamp:
            return prior
        # Preserve already-finalized volume data when refreshing today's
        # membership snapshot during another scheduled run.
        if prior.get("volume_observed_at_utc"):
            snapshot["quote_volume_30d"] = prior["quote_volume_30d"]
            snapshot["volume_observed_at_utc"] = prior["volume_observed_at_utc"]
    _atomic_json_replace(path, snapshot)
    return snapshot


def _load_snapshot(root: Path, day: str) -> dict | None:
    path = _snapshot_path(root, day)
    if not path.exists():
        return None
    try:
        return _validate_snapshot(json.loads(path.read_text()), day)
    except (OSError, json.JSONDecodeError) as exc:
        raise RefusedToBook(f"stored snapshot for {day} is unreadable") from exc


def _save_close_snapshot(root: Path, day: str, symbols: dict,
                         observed_at: dt.datetime) -> dict:
    snapshot = {"day": day, "observed_at_utc": observed_at.astimezone(dt.UTC).isoformat(),
                "source": "post-close-status", "symbols": symbols,
                "quote_volume_30d": {}}
    snapshot = _validate_snapshot(snapshot, day, close=True)
    path = _close_snapshot_path(root, day)
    if not path.exists():
        _atomic_json_replace(path, snapshot)
    return _load_close_snapshot(root, day) or snapshot


def _load_close_snapshot(root: Path, day: str) -> dict | None:
    path = _close_snapshot_path(root, day)
    if not path.exists():
        return None
    try:
        return _validate_snapshot(json.loads(path.read_text()), day, close=True)
    except (OSError, json.JSONDecodeError) as exc:
        raise RefusedToBook(f"stored close snapshot for {day} is unreadable") from exc


def _finalize_volume_snapshot(fetcher: Fetcher, root: Path, day: str,
                              observed_at: dt.datetime) -> dict:
    observed_at = observed_at.astimezone(dt.UTC)
    if observed_at.date().isoformat() != _shift(day, 1) \
            or observed_at.timetz() < BOOKING_CUTOFF:
        raise RefusedToBook(f"volume history for {day} was not finalized at booking time")
    snapshot = _load_snapshot(root, day)
    if snapshot is None:
        raise RefusedToBook(f"pre-close membership snapshot unavailable for {day}")
    _require_fresh_selection(snapshot, day, observed_at)
    if snapshot.get("volume_observed_at_utc"):
        return snapshot
    volumes: dict[str, float] = {}
    asof = dt.date.fromisoformat(day)
    for sym, meta in sorted(snapshot["symbols"].items()):
        if meta["status"] != "TRADING":
            continue
        onboard = meta.get("onboard_date")
        if onboard is None:
            raise RefusedToBook(f"listing age unavailable for {sym}")
        if (asof - dt.date.fromisoformat(onboard)).days < MIN_LISTING_DAYS:
            continue
        value = fetcher.quote_volume_30d(sym, day)
        if not _finite(value) or value < 0:
            raise RefusedToBook(f"invalid 30-day quote volume for {sym}")
        volumes[sym] = float(value)
    if len(volumes) < UNIVERSE_SIZE:
        raise RefusedToBook("fewer than 30 listing-age-eligible volume histories")
    snapshot["quote_volume_30d"] = volumes
    snapshot["volume_observed_at_utc"] = observed_at.astimezone(dt.UTC).isoformat()
    snapshot["source"] = "exchangeInfo+completed-volume"
    snapshot = _validate_snapshot(snapshot, day)
    _atomic_json_replace(_snapshot_path(root, day), snapshot)
    return snapshot


def _universe(snapshot: dict, day: str) -> list[str]:
    snapshot = _validate_snapshot(snapshot, day)
    if not snapshot.get("volume_observed_at_utc"):
        raise RefusedToBook(f"completed 30-day volume snapshot unavailable for {day}")
    rows: list[tuple[float, str]] = []
    asof = dt.date.fromisoformat(day)
    symbols = snapshot["symbols"]
    volumes = snapshot["quote_volume_30d"]
    for sym, meta in sorted(symbols.items()):
        if meta["status"] != "TRADING":
            continue
        onboard = meta.get("onboard_date")
        if onboard is None:
            raise RefusedToBook(f"listing age unavailable for {sym}")
        age = (asof - dt.date.fromisoformat(onboard)).days
        if age < MIN_LISTING_DAYS:
            continue
        if sym not in volumes or not _finite(volumes[sym]) or volumes[sym] < 0:
            raise RefusedToBook(f"unreadable 30-day volume for {sym}")
        rows.append((float(volumes[sym]), sym))
    rows.sort(key=lambda x: (x[0], x[1]), reverse=True)
    chosen = [sym for _, sym in rows[:UNIVERSE_SIZE]]
    if len(chosen) != UNIVERSE_SIZE:
        raise RefusedToBook("fewer than 30 listing-age-eligible symbols")
    return chosen


def _eligible_at(closes: dict[str, dict[str, float]], days: list[str], t: int) -> list[str]:
    """Signal eligibility uses only complete candles through decision close t."""
    if t < HISTORY_DAYS or t >= len(days):
        return []
    needed = days[t - HISTORY_DAYS:t + 1]
    return sorted(sym for sym, series in closes.items()
                  if all(day in series and _finite(series[day]) and series[day] > 0
                         for day in needed))


def _fallback_snapshot(day: str, universe: list[str]) -> dict:
    """Carry the already-frozen weekly membership; never infer delisting."""
    return {"day": day, "source": "carried-forward-ledger",
            "symbols": {s: {"status": "TRADING", "onboard_date": None}
                        for s in universe}, "quote_volume_30d": {}}


def _funding_events(fetcher: Fetcher, symbol: str, start_day: str,
                    end_day: str) -> list[tuple[int, float]]:
    method = getattr(fetcher, "funding_events", None)
    if not callable(method):
        raise RefusedToBook(f"funding coverage unavailable for {symbol}")
    events = method(symbol, start_day, end_day)
    if not isinstance(events, list) or not events:
        raise RefusedToBook(f"funding coverage incomplete for {symbol}")
    normalized = []
    for stamp, rate in events:
        if not isinstance(stamp, int) or not _finite(rate):
            raise RefusedToBook(f"invalid funding event for {symbol}")
        normalized.append((stamp, float(rate)))
    start_ms, end_ms = _ms(start_day), _ms(end_day)
    required = (start_ms + _FUNDING_INTERVAL_MS,
                start_ms + 2 * _FUNDING_INTERVAL_MS, end_ms)
    times = [stamp for stamp, _ in normalized]
    if len(times) != len(set(times)) or not set(required).issubset(times) \
            or any(not start_ms < stamp <= end_ms for stamp in times):
        raise RefusedToBook(f"funding coverage incomplete for {symbol}")
    return normalized


def book_day(fetcher: Fetcher, state: dict, t_day: str, *,
             snapshot: dict, next_snapshot: dict | None) -> dict:
    """Decide at close t_day using only then-known data; earn close-to-close."""
    snapshot = _validate_snapshot(snapshot, t_day)
    nxt = _shift(t_day, 1)
    if next_snapshot is not None:
        next_snapshot = _validate_snapshot(next_snapshot, nxt, close=True)

    previous_universe = list(state.get("universe", []))
    previous_held = dict(state.get("held", {}))
    if c_family._is_monday(t_day) or not previous_universe:
        universe = _universe(snapshot, t_day)
    else:
        universe = previous_universe
    statuses = snapshot["symbols"]
    retired = sorted(s for s in universe if s not in statuses)
    inactive = sorted(s for s in universe if s in statuses
                      and statuses[s].get("status") != "TRADING")
    if inactive:
        raise RefusedToBook(f"non-trading symbols require manual data-gap handling: {inactive}")
    active_universe = [s for s in universe if s in statuses]

    # Preserve weekly membership while removing only symbols absent from a
    # complete exchangeInfo snapshot. A non-TRADING status is not a delisting.
    symbols = sorted(set(active_universe) | set(previous_held))
    start = _shift(t_day, -HISTORY_DAYS)
    closes = {s: fetcher.mark_closes(s, start, nxt) for s in symbols
              if s not in retired}
    days = [_shift(start, k) for k in range(HISTORY_DAYS + 2)]
    t = days.index(t_day)

    for sym in active_universe:
        series = closes.get(sym, {})
        history_days = days[t - HISTORY_DAYS:t + 1]
        if any(day not in series or not _finite(series[day]) or series[day] <= 0
               for day in history_days):
            raise RefusedToBook(f"stale or partial candle history for {sym}")
    eligible = [s for s in _eligible_at(closes, days, t) if s in active_universe]
    if len(eligible) != len(active_universe):
        raise RefusedToBook("stale or partial signal candles")

    # Any symbol dropped from this week's active universe is closed at t_day.
    held = {s: w for s, w in previous_held.items() if s in eligible}
    target = held
    if c_family._is_monday(t_day) or not held:
        target = c_family.signal_xsmom(closes, {}, days, t, eligible)
    if not target:
        raise RefusedToBook("signal produced no tradeable portfolio")

    retired_targets: list[str] = []
    gross = 0.0
    funding_total = 0.0
    funding_counts: dict[str, int] = {}
    for sym, weight in target.items():
        if sym not in closes or t_day not in closes[sym]:
            raise RefusedToBook(f"missing decision close for {sym}")
        if nxt not in closes[sym]:
            status_next = next_snapshot["symbols"].get(sym) if next_snapshot else None
            if status_next is not None:
                if status_next.get("status") != "TRADING":
                    raise RefusedToBook(f"halted symbol {sym} is not a confirmed delisting")
                raise RefusedToBook(f"stale or partial next candle for {sym}")
            if next_snapshot is None or sym not in statuses:
                raise RefusedToBook(f"unconfirmed missing candle for {sym}")
            # A complete later exchangeInfo snapshot omits this previously
            # trading symbol: mark the final available close, then retire it.
            retired_targets.append(sym)
            continue
        gross += weight * (closes[sym][nxt] / closes[sym][t_day] - 1.0) * 1e4
        events = _funding_events(fetcher, sym, nxt, _shift(nxt, 1))
        funding_total += weight * math.fsum(rate for _, rate in events) * 1e4
        funding_counts[sym] = len(events)

    turnover = math.fsum(abs(target.get(s, 0.0) - previous_held.get(s, 0.0))
                         for s in set(target) | set(previous_held))
    retired_exit_turnover = math.fsum(abs(target[s]) for s in retired_targets)
    turnover += retired_exit_turnover
    held_after = {s: w for s, w in target.items() if s not in retired_targets}
    state["universe"] = active_universe
    state["held"] = held_after
    cost = turnover * c_family.COST_BPS_PER_SIDE
    return {"day": nxt, "decided_at_close": t_day, "weights": target,
            "held_after": held_after, "universe": active_universe,
            "retired_symbols": sorted(set(retired) | set(retired_targets)),
            "retired_exit_mark_day": t_day if retired_targets else None,
            "retired_exit_turnover": retired_exit_turnover,
            "turnover": turnover, "funding_event_counts": funding_counts,
            "gross_bps": gross - funding_total,
            "gross_bps_semantics": "price return net of funding, before fees",
            "net_bps": gross - funding_total - cost,
            "adverse_bps": gross - funding_total - 2 * cost}


def _locked(root: Path):
    """Non-blocking advisory process lock; descriptor lifetime owns the lock."""
    class Lock:
        def __enter__(self):
            root.mkdir(parents=True, exist_ok=True)
            self.fd = os.open(root / ".record.lock", os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                os.close(self.fd)
                if exc.errno in (errno.EACCES, errno.EAGAIN):
                    raise RefusedToBook("another recorder writer holds the lock") from exc
                raise
            return self

        def __exit__(self, *_exc):
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)

    return Lock()


def _rows(root: Path, *, repair_torn_tail: bool = False) -> list[dict]:
    ledger = root / "ledger.jsonl"
    if not ledger.exists():
        return []
    raw = ledger.read_bytes()
    if raw and not raw.endswith(b"\n"):
        split = raw.rfind(b"\n") + 1
        tail = raw[split:]
        try:
            recovered = json.loads(tail)
            if not isinstance(recovered, dict):
                raise ValueError("not an object")
            # The complete JSON payload survived; only its line terminator did not.
            if repair_torn_tail:
                _atomic_replace(ledger, raw + b"\n")
                raw += b"\n"
            else:
                raise LedgerError("ledger ends with an unterminated row")
        except (json.JSONDecodeError, ValueError) as exc:
            if not repair_torn_tail:
                raise LedgerError("ledger has a torn final row") from exc
            torn = root / "ledger.torn"
            old = torn.read_bytes() if torn.exists() else b""
            _atomic_replace(torn, old + tail)
            _atomic_replace(ledger, raw[:split])
            raw = raw[:split]
    rows: list[dict] = []
    for line_no, line in enumerate(raw.splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LedgerError(f"malformed ledger row {line_no}") from exc
        if not isinstance(row, dict):
            raise LedgerError(f"ledger row {line_no} is not an object")
        rows.append(row)
    return rows


def _ledger_issues(rows: list[dict]) -> tuple[list[str], int, list[str]]:
    days: list[str] = []
    duplicates = 0
    issues: list[str] = []
    seen: set[str] = set()
    for i, row in enumerate(rows):
        day = row.get("day")
        try:
            parsed = dt.date.fromisoformat(day)
            if parsed.isoformat() != day:
                raise ValueError
        except (TypeError, ValueError):
            issues.append(f"invalid date at row {i + 1}")
            continue
        if day in seen:
            duplicates += 1
        seen.add(day)
        days.append(day)
        for key in ("net_bps", "adverse_bps", "gross_bps", "turnover"):
            if not _finite(row.get(key)):
                issues.append(f"invalid {key} at row {i + 1}")
        if _finite(row.get("turnover")) and row["turnover"] < 0:
            issues.append(f"negative turnover at row {i + 1}")
        if row.get("decided_at_close") is not None and \
                row["decided_at_close"] != _shift(day, -1):
            issues.append(f"close timestamp mismatch at row {i + 1}")
    gaps = []
    for a, b in zip(days, days[1:], strict=False):
        if b != _shift(a, 1):
            gaps.append(b)
            issues.append(f"days {a} and {b} are not consecutive")
    return gaps, duplicates, issues


def _validate_ledger(rows: list[dict]) -> None:
    gaps, duplicates, issues = _ledger_issues(rows)
    if gaps or duplicates or issues:
        raise LedgerError("ledger rows are not consecutive and valid")


def _state_from_row(row: dict) -> dict:
    return {"last_booked": row["day"], "universe": list(row.get("universe", [])),
            "held": dict(row.get("held_after", row.get("weights", {})))}


def _write_ledger(rows: list[dict], path: Path) -> None:
    content = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode()
    _atomic_replace(path, content)


def _save_state(path: Path, state: dict) -> None:
    _atomic_json_replace(path, state)


def _fallback_membership(day: str, state: dict) -> dict:
    return _fallback_snapshot(day, list(state.get("universe", [])))


def _require_fresh_selection(snapshot: dict, day: str,
                             observed_by: dt.datetime | None = None) -> dict:
    if snapshot.get("source") == "carried-forward-ledger":
        return snapshot
    observed = _parse_utc(snapshot.get("observed_at_utc"))
    if observed_by is not None and observed > observed_by.astimezone(dt.UTC):
        raise RefusedToBook(f"future point-in-time universe snapshot for {day}")
    close_at = dt.datetime.combine(dt.date.fromisoformat(_shift(day, 1)),
                                   dt.time.min, tzinfo=dt.UTC)
    if close_at - observed > MAX_UNIVERSE_SNAPSHOT_AGE:
        raise RefusedToBook(f"stale point-in-time universe snapshot for {day}")
    return snapshot


def _snapshot_for_booking(root: Path, day: str, state: dict,
                          observed_by: dt.datetime) -> dict:
    saved = _load_snapshot(root, day)
    if saved is not None:
        return _require_fresh_selection(saved, day, observed_by)
    if c_family._is_monday(day) or not state.get("universe"):
        raise RefusedToBook(f"point-in-time universe snapshot unavailable for {day}")
    # Weekly membership is frozen from the prior recorded row. Missing future
    # candles still fail closed unless a complete next-day snapshot confirms exit.
    return _fallback_membership(day, state)


def record(root: Path, fetcher: Fetcher, today: str, *,
           now: dt.datetime | None = None) -> int:
    """Book available close-to-close rows; exactly-once under process crashes."""
    now = now or dt.datetime.now(dt.UTC)
    if now.tzinfo is None:
        raise RefusedToBook("recording clock must be timezone-aware")
    now = now.astimezone(dt.UTC)
    if now.timetz() < BOOKING_CUTOFF:
        raise RefusedToBook("booking is not allowed before 00:05 UTC")
    if today != now.date().isoformat():
        raise RefusedToBook("booking date does not match the UTC clock")

    root.mkdir(parents=True, exist_ok=True)
    state_path, ledger = root / "state.json", root / "ledger.jsonl"
    last_full = _shift(today, -1)
    with _locked(root):
        had_ledger = ledger.exists()
        rows = _rows(root, repair_torn_tail=True)
        _validate_ledger(rows)
        if state_path.exists():
            try:
                stored_state = json.loads(state_path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                raise LedgerError("state file is unreadable") from exc
            if not isinstance(stored_state, dict):
                raise LedgerError("state file is malformed")
        else:
            stored_state = {}

        # Capture today's membership while the day is still open. It is the
        # only snapshot eligible to determine today's close-time universe.
        current_snapshot = fetcher.universe_snapshot(
            today, observed_at=now, include_volume=False)
        current_snapshot = _save_selection_snapshot(root, current_snapshot)
        current_observed = _parse_utc(current_snapshot["observed_at_utc"])
        if abs(current_observed - now) > MAX_EXCHANGE_INFO_CLOCK_SKEW:
            raise RefusedToBook("exchangeInfo snapshot time is stale")
        if current_observed > now:
            now = current_observed
        # This post-close observation is used only to distinguish a confirmed
        # retirement from a missing candle, never to choose today's signal set.
        _save_close_snapshot(root, last_full, current_snapshot["symbols"],
                             current_observed)

        if rows:
            state = _state_from_row(rows[-1])
            old_state_day = stored_state.get("last_booked")
            if old_state_day and old_state_day > state["last_booked"]:
                raise LedgerError("state is ahead of the complete ledger")
        elif stored_state:
            if stored_state.get("bootstrap_anchor"):
                state = stored_state
            elif had_ledger and (root / "ledger.torn").exists():
                # A torn first append was discarded; state is the last complete
                # checkpoint and the missing day is safely retried.
                state = stored_state
            else:
                raise LedgerError("state exists without a recoverable ledger")
        else:
            # Begin from today's observed membership; yesterday's snapshot may
            # predate this recorder and cannot safely seed the first decision.
            state = {"last_booked": today, "universe": [], "held": {},
                     "bootstrap_anchor": True}
            _save_state(state_path, state)
            return 0

        t_day = state.get("last_booked") or _shift(last_full, -1)
        if t_day == last_full and (c_family._is_monday(t_day)
                                   or not state.get("universe")):
            _finalize_volume_snapshot(fetcher, root, t_day, now)
        if t_day <= last_full and c_family._is_monday(last_full):
            _finalize_volume_snapshot(fetcher, root, last_full, now)
        appended = 0
        while t_day < last_full:
            snapshot = _snapshot_for_booking(root, t_day, state, now)
            if c_family._is_monday(t_day) or not state.get("universe"):
                if not snapshot.get("volume_observed_at_utc"):
                    snapshot = _finalize_volume_snapshot(fetcher, root, t_day, now)
            next_snapshot = _load_close_snapshot(root, _shift(t_day, 1))
            row = book_day(fetcher, state, t_day, snapshot=snapshot,
                           next_snapshot=next_snapshot)
            new_rows = [*rows, row]
            _validate_ledger(new_rows)
            _write_ledger(new_rows, ledger)
            rows = new_rows
            state = _state_from_row(row)
            _save_state(state_path, state)
            t_day = row["day"]
            appended += 1
        return appended


def _rows_health(root: Path) -> tuple[list[dict], str | None]:
    try:
        return _rows(root), None
    except (OSError, LedgerError) as exc:
        return [], str(exc)


def health(root: Path) -> dict:
    rows, read_error = _rows_health(root)
    days = [r.get("day", "") for r in rows]
    gaps, duplicates, issues = _ledger_issues(rows)
    corrupt = read_error is not None or bool(issues)
    count = len(rows)
    due = [i + 1 for i, n in enumerate(LOOKS)
           if count == n and not (REPORTS / f"C2-forward-look{i + 1}.json").exists()]
    missed = [i + 1 for i, n in enumerate(LOOKS)
              if count > n and not (REPORTS / f"C2-forward-look{i + 1}.json").exists()]
    if corrupt:
        due, missed = [], []
    return {"scored_days": count, "first": days[0] if days else None,
            "last": days[-1] if days else None, "gaps": gaps,
            "duplicates": duplicates, "corrupt": corrupt,
            "ledger_error": read_error, "looks_due": due,
            "missed_looks": missed,
            "next_look_at_days": next((n for n in LOOKS if count < n), None)}


def vol_managed(results: list[c_family.DayResult]) -> list[c_family.DayResult]:
    """Amendment-1 C2-VM return series, including separate adverse costs."""
    out: list[c_family.DayResult] = []
    lev_prev = 1.0
    history: list[float] = []
    for t, row in enumerate(results):
        lev = quant.vol_target_leverage(history[max(0, t - VM_WINDOW):],
                                        VM_TARGET_BPS, VM_CAP) \
            if t >= VM_WARMUP else 1.0
        turnover_cost = abs(lev - lev_prev) * c_family.COST_BPS_PER_SIDE
        net = row.gross_bps * lev - row.turnover * lev * c_family.COST_BPS_PER_SIDE \
            - turnover_cost
        adverse = row.gross_bps * lev \
            - row.turnover * lev * c_family.COST_BPS_PER_SIDE * 2.0 \
            - turnover_cost * 2.0
        out.append(c_family.DayResult(row.day, net, adverse,
                                      row.gross_bps * lev,
                                      row.turnover * lev + abs(lev - lev_prev)))
        history.append(net)
        lev_prev = lev
    return out


def _score_stats(results: list[c_family.DayResult]) -> dict:
    return c_family.score(results, rounds=BOOTSTRAP_ROUNDS)


def _ledger_sha256(rows: list[dict]) -> str:
    canonical = "\n".join(json.dumps(row, sort_keys=True) for row in rows).encode()
    return hashlib.sha256(canonical).hexdigest()


def _score_decision(stats: dict, look: int) -> tuple[float | None, str]:
    p_value = stats.get("p_value")
    mean_adverse = stats.get("mean_adverse_bps")
    if (not isinstance(p_value, (int, float)) or isinstance(p_value, bool)
            or not math.isfinite(p_value) or not 0 < p_value <= 1
            or not isinstance(mean_adverse, (int, float))
            or isinstance(mean_adverse, bool) or not math.isfinite(mean_adverse)):
        raise LedgerError("bootstrap returned invalid scoring statistics")
    p_value = float(p_value)
    mean_adverse = float(mean_adverse)
    z = statistics.NormalDist().inv_cdf(1 - p_value) if p_value < 1 else None
    crossed = z is not None and z >= OBF_BOUNDS[look - 1] and mean_adverse > 0
    final = look == len(LOOKS)
    return z, "FORWARD-PASS" if crossed else ("KILLED" if final else "CONTINUE")


def _prior_look(out_dir: Path, look: int, rows: list[dict]) -> dict:
    path = out_dir / f"C2-forward-look{look}.json"
    if not path.exists():
        raise RuntimeError(f"look {look} has not been scored")
    try:
        report = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"prior look {look} report is corrupt") from exc
    if not isinstance(report, dict) or report.get("verdict") not in \
            {"CONTINUE", "FORWARD-PASS", "KILLED"}:
        raise RuntimeError(f"prior look {look} report is invalid")
    expected_days = LOOKS[look - 1]
    if (type(report.get("look")) is not int or report["look"] != look
            or type(report.get("days")) is not int
            or report["days"] != expected_days
            or report.get("ledger_sha256") != _ledger_sha256(rows[:expected_days])
            or report.get("bootstrap_rounds") != BOOTSTRAP_ROUNDS
            or report.get("bootstrap_seed") != 7
            or report.get("bound") != OBF_BOUNDS[look - 1]):
        raise RuntimeError(f"prior look {look} report does not match its scored ledger")
    prefix = rows[:expected_days]
    results = [c_family.DayResult(r["day"], float(r["net_bps"]),
                                  float(r["adverse_bps"]), float(r["gross_bps"]),
                                  float(r["turnover"])) for r in prefix]
    stats = _score_stats(results)
    expected_z, expected_verdict = _score_decision(stats, look)
    if (report.get("verdict") != expected_verdict
            or report.get("z") != expected_z
            or report.get("p_value") != stats["p_value"]
            or report.get("mean_adverse_bps") != stats["mean_adverse_bps"]):
        raise RuntimeError(f"prior look {look} report is inconsistent with its ledger")
    return report


def _atomic_create_json(path: Path, doc: dict) -> None:
    """Publish a complete report once; a crash cannot leave a partial target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                     dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write((json.dumps(doc, indent=1, sort_keys=True) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp_name, path)
        _fsync_dir(path.parent)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def score_look(root: Path, out_dir: Path, look: int) -> dict:
    """Run exactly one preregistered look, in order, at its exact row count."""
    if not 1 <= look <= len(LOOKS):
        raise ValueError(f"look must be 1..{len(LOOKS)}")
    out = out_dir / f"C2-forward-look{look}.json"
    if out.exists():
        raise FileExistsError(f"{out.name} exists (each look runs exactly once)")
    rows = _rows(root)
    _validate_ledger(rows)
    previous = [_prior_look(out_dir, k, rows) for k in range(1, look)]
    if any(r["verdict"] in {"FORWARD-PASS", "KILLED"} for r in previous):
        raise RuntimeError("the forward test already stopped")
    if any((out_dir / f"C2-forward-look{k}.json").exists()
           for k in range(look + 1, len(LOOKS) + 1)):
        raise RuntimeError("later look exists before this look")
    required = LOOKS[look - 1]
    if len(rows) != required:
        raise RuntimeError(f"look {look} requires exactly {required} rows; found {len(rows)}")
    results = [c_family.DayResult(r["day"], float(r["net_bps"]),
                                  float(r["adverse_bps"]), float(r["gross_bps"]),
                                  float(r["turnover"])) for r in rows]
    stats = _score_stats(results)
    z, verdict = _score_decision(stats, look)

    secondary: dict = {"status": "NOT-TESTED", "bound": OBF_BOUNDS[look - 1]}
    if verdict == "FORWARD-PASS":
        vm_stats = _score_stats(vol_managed(results))
        vm_p = vm_stats["p_value"]
        if not _finite(vm_p) or not 0 < vm_p <= 1:
            raise LedgerError("C2-VM bootstrap returned an invalid p-value")
        vm_z = statistics.NormalDist().inv_cdf(1 - vm_p) if vm_p < 1 else None
        vm_pass = vm_z is not None and vm_z >= OBF_BOUNDS[look - 1] \
            and vm_stats["mean_adverse_bps"] > 0
        secondary = {"status": "PASS" if vm_pass else "NOT-PASS",
                     "bound": OBF_BOUNDS[look - 1], "z": vm_z,
                     "p_value": vm_p,
                     "mean_adverse_bps": vm_stats["mean_adverse_bps"],
                     "bootstrap_rounds": BOOTSTRAP_ROUNDS}

    doc = {"hypothesis": "C2-XSMOM-forward", "look": look,
           "days": len(rows), "prereg": ["research/prereg/C2-forward.md",
                                           "research/prereg/C2-forward-amendment-1.md"],
           "z": z, "bound": OBF_BOUNDS[look - 1], "verdict": verdict,
           "bootstrap_rounds": BOOTSTRAP_ROUNDS,
           "bootstrap_seed": 7, "ledger_sha256": _ledger_sha256(rows),
           **stats, "secondary_C2_VM_test": secondary}
    _atomic_create_json(out, doc)
    return doc


def today_utc(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.UTC)
    if now.tzinfo is None:
        raise ValueError("UTC clock must be timezone-aware")
    now = now.astimezone(dt.UTC)
    if now.timetz() < BOOKING_CUTOFF:
        return _shift(now.date().isoformat(), -1)
    return now.date().isoformat()


def main(argv: list[str] | None = None, *, fetcher: Fetcher | None = None,
         now: dt.datetime | None = None) -> int:
    from cryptobot import netguard  # opt-in DNS-sinkhole fallback (CRYPTOBOT_DOH=1)

    netguard.install_from_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("record", "health", "score"))
    ap.add_argument("--root", default="data/forward_c2")
    ap.add_argument("--look", type=int, help="score: look number 1..3")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if args.cmd == "health":
        print(json.dumps(health(root), indent=1))
        return 0
    if args.cmd == "score":
        doc = score_look(root, REPORTS, args.look or 0)
        print(json.dumps(doc, indent=1))
        return 0
    now = now or dt.datetime.now(dt.UTC)
    if now.tzinfo is None or now.astimezone(dt.UTC).timetz() < BOOKING_CUTOFF:
        raise RefusedToBook("booking is not allowed before 00:05 UTC")
    today = now.astimezone(dt.UTC).date().isoformat()
    print(f"forward_c2: appended {record(root, fetcher or RestFetcher(), today, now=now)} day(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
