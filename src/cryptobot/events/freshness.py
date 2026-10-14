"""Real source freshness: persisted verification + background refresh (W4-24H).

BEFORE: FixtureAdapter.load() stamped fetched_utc=now with zero HTTP
verification, so every reload/restart renewed "fresh" coverage for free.
AFTER: a local load only restores the cache (status "cached"); coverage
resolves to "fresh" solely from a persisted verified_utc that is still
inside CACHE_TTL. Only refresh_once() — an HTTP GET of the official
calendar whose page still contains every cached schedule date — may move
verified_utc forward. Local reading is never a successful fetch.

Outage behavior: a failed refresh keeps serving the cache, records the
error + consecutive failures, and leaves verified_utc untouched. Once
verified_utc + CACHE_TTL elapses with no successful refresh, coverage
reads stale/expired and the gate fails closed. Schedule diffs found on
the page are recorded as drift CANDIDATES and never auto-applied.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .sources import COVERAGE_TTL
from .store import EventStore, coverage_status
from .timezones import parse_iso_utc
from .types import SourceCoverage

CACHE_TTL = timedelta(days=7)
REFRESH_INTERVAL_S = 6 * 3600
HTTP_TIMEOUT_S = 20
USER_AGENT = "cryptobot-events-refresh/1 (paper-research calendar check)"

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")
_MONTH_NO = {name: num + 1 for num, name in enumerate(MONTHS)}

_FOMC_SECTION = re.compile(r"####\s+(\d{4})\s+FOMC Meetings")
_FOMC_HTML_SECTION = re.compile(r"(\d{4})\s+FOMC Meetings")
_FOMC_MONTH_BLOCK = re.compile(
    r"\*\*(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\*\*\s*\n+\s*(\d{1,2})-(\d{1,2})")
# Real Fed layout (verified live 2026-10-14): month + day-range divs.
# Decision day = range end; trailing "*" (projection meetings) tolerated.
_FOMC_HTML_BLOCK = re.compile(
    r"fomc-meeting__month[^>]*><strong>("
    r"January|February|March|April|May|June|July|August|September|"
    r"October|November|December)</strong>.*?fomc-meeting__date[^>]*>"
    r"(\d{1,2})-(\d{1,2})\*?", re.DOTALL)
_FOMC_STATEMENT = re.compile(r"monetary(\d{4})(\d{2})(\d{2})")
_LONG_DATE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(\d{1,2}),\s+(20\d{2})")
# Real BLS release-list layout (verified live 2026-10-14): abbreviated
# months with a dot, except May (no dot); observed Sep. (not Sept.).
_ABBR_NO = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
            "Jul": 7, "Aug": 8, "Sep": 9, "Sept": 9, "Oct": 10, "Nov": 11,
            "Dec": 12}
_RELEASE_LIST_ROW = re.compile(
    r"<td>(Jan\.|Feb\.|Mar\.|Apr\.|May|Jun\.|Jul\.|Aug\.|Sept?\.|Oct\.|"
    r"Nov\.|Dec\.)\s+(\d{1,2}),\s+(20\d{2})</td>\s*"
    r"<td>(\d{2}:\d{2}\s+[AP]M)</td>")


def _release_list_dates(body_text: str) -> set[date]:
    """Dates from BLS release-list table rows (date cell + time cell)."""
    found: set[date] = set()
    for month, day, year, _clock in _RELEASE_LIST_ROW.findall(body_text):
        found.add(date(int(year), _ABBR_NO[month.rstrip(".")], int(day)))
    return found

STATE_FORMAT = "cryptobot-source-state/1"


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    url: str = ""


def default_http_get(url: str, timeout_s: float = HTTP_TIMEOUT_S,
                     ) -> HttpResponse:
    """GET with an explicit UA and timeout. Raises on transport failure."""
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout_s) as reply:
        return HttpResponse(status=reply.status, body=reply.read(), url=url)


def parse_fomc_decision_dates(body_text: str) -> set[date]:
    """Decision dates from a Fed FOMC calendar page body.

    Union of (a) statement-link dates (monetaryYYYYMMDD: released
    meetings) and (b) month-block second days (all listed meetings,
    including scheduled-not-released). Raises when the page marker is
    absent or no dates are found.
    """
    if "FOMC Meetings" not in body_text:
        raise ValueError("Fed page marker 'FOMC Meetings' absent")
    found: set[date] = set()
    for year, month, day in _FOMC_STATEMENT.findall(body_text):
        found.add(date(int(year), int(month), int(day)))
    sections = list(_FOMC_SECTION.finditer(body_text))
    if not sections:
        sections = list(_FOMC_HTML_SECTION.finditer(body_text))
    bounds = [m.start() for m in sections] + [len(body_text)]
    years = [int(m.group(1)) for m in sections]

    def year_at(pos: int) -> int | None:
        return next((y for y, start, end in
                     zip(years, bounds, bounds[1:])
                     if start <= pos < end), None)

    for block in _FOMC_MONTH_BLOCK.finditer(body_text):
        year = year_at(block.start())
        if year is None:
            continue
        found.add(date(year, _MONTH_NO[block.group(1)],
                       int(block.group(3))))
    for block in _FOMC_HTML_BLOCK.finditer(body_text):
        year = year_at(block.start())
        if year is None:
            continue
        try:
            found.add(date(year, _MONTH_NO[block.group(1)],
                           int(block.group(3))))
        except ValueError:
            continue  # month-boundary ranges: statement links cover them.
    if not found:
        raise ValueError("no FOMC decision dates parsed")
    return found


def parse_cpi_release_dates(body_text: str) -> set[date]:
    """Release dates from a BLS CPI schedule page body.

    Union of the release-list table (real layout, verified live
    2026-10-14) and long-form dates (canned-page compatibility).
    Raises when the CPI marker is absent or no dates are found.
    """
    if "Consumer Price Index" not in body_text:
        raise ValueError("BLS page marker 'Consumer Price Index' absent")
    found = {date(int(year), _MONTH_NO[month], int(day))
             for month, day, year in _LONG_DATE.findall(body_text)}
    found |= _release_list_dates(body_text)
    if not found:
        raise ValueError("no CPI release dates parsed")
    return found


def parse_employment_dates(body_text: str) -> set[date]:
    """Release dates from a BLS Employment Situation schedule page body.

    Same release-list layout as CPI (verified live 2026-10-14), plus
    long-form union for robustness. Raises when the marker is absent
    or no dates are found.
    """
    if "Employment Situation" not in body_text:
        raise ValueError("BLS page marker 'Employment Situation' absent")
    found = {date(int(year), _MONTH_NO[month], int(day))
             for month, day, year in _LONG_DATE.findall(body_text)}
    found |= _release_list_dates(body_text)
    if not found:
        raise ValueError("no Employment Situation dates parsed")
    return found


@dataclass
class SourceState:
    source: str
    verified_utc: datetime | None = None
    last_attempt_utc: datetime | None = None
    payload_hash: str = ""
    consecutive_failures: int = 0
    last_error: str = ""
    drift_missing: tuple[str, ...] = ()
    drift_extra: tuple[str, ...] = ()
    drift_recorded_utc: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        def iso(moment: datetime | None) -> str | None:
            return moment.isoformat() if moment else None

        return {"source": self.source, "verified_utc": iso(self.verified_utc),
                "last_attempt_utc": iso(self.last_attempt_utc),
                "payload_hash": self.payload_hash,
                "consecutive_failures": self.consecutive_failures,
                "last_error": self.last_error,
                "drift_missing": list(self.drift_missing),
                "drift_extra": list(self.drift_extra),
                "drift_recorded_utc": iso(self.drift_recorded_utc)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceState:
        def moment(key: str) -> datetime | None:
            return parse_iso_utc(data[key]) if data.get(key) else None

        return cls(
            source=data["source"], verified_utc=moment("verified_utc"),
            last_attempt_utc=moment("last_attempt_utc"),
            payload_hash=data.get("payload_hash", ""),
            consecutive_failures=int(data.get("consecutive_failures", 0)),
            last_error=data.get("last_error", ""),
            drift_missing=tuple(data.get("drift_missing", ())),
            drift_extra=tuple(data.get("drift_extra", ())),
            drift_recorded_utc=moment("drift_recorded_utc"))


class SourceStateStore:
    """Persisted per-source verification state (survives restart)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._states: dict[str, SourceState] = {}

    def load(self) -> SourceStateStore:
        if not self.path.exists():
            return self
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ValueError(
                f"source state {self.path} is corrupt: {exc}") from exc
        if data.get("format") != STATE_FORMAT:
            raise ValueError(
                f"unsupported source-state format: {data.get('format')!r}")
        for item in data.get("states", []):
            state = SourceState.from_dict(item)
            self._states[state.source] = state
        return self

    def save(self) -> None:
        payload = {"format": STATE_FORMAT,
                   "states": [s.to_dict() for s in sorted(
                       self._states.values(), key=lambda s: s.source)]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent),
                                   prefix=".source-state-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, indent=2, sort_keys=True))
            os.replace(tmp, self.path)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def get(self, source: str) -> SourceState:
        return self._states.get(source, SourceState(source=source))

    def put(self, state: SourceState) -> None:
        self._states[state.source] = state

    def sources(self) -> list[str]:
        return sorted(self._states)


@dataclass(frozen=True)
class RefreshResult:
    source: str
    ok: bool
    verified_utc: datetime | None
    http_status: int | None
    error: str = ""
    missing: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()
    payload_hash: str = ""


_PARSERS: dict[str, Callable[[str], set[date]]] = {
    "fomc": parse_fomc_decision_dates,
    "cpi": parse_cpi_release_dates,
    "employment": parse_employment_dates,
}


def _cached_dates(store: EventStore, source: str) -> set[date]:
    kinds = {"fomc": ("decision",), "cpi": ("release",),
             "employment": ("release",)}.get(source, ())
    return {e.scheduled_utc.date() for e in store.by_source(source)
            if not kinds or e.kind in kinds}


class FreshnessTracker:
    """Resolve coverage from persisted verification; refresh over HTTP."""

    def __init__(self, state_path: str | Path, adapters: list[Any],
                 cache_ttl: timedelta = CACHE_TTL) -> None:
        self.states = SourceStateStore(state_path).load()
        self.adapters = list(adapters)
        self.cache_ttl = cache_ttl
        self.lock = threading.Lock()
        self._stop: threading.Event | None = None
        self._thread: threading.Thread | None = None

    def verified_within_ttl(self, source: str, now_utc: datetime) -> bool:
        verified = self.states.get(source).verified_utc
        return (verified is not None
                and verified <= now_utc <= verified + self.cache_ttl)

    def local_load(self, store: EventStore, now_utc: datetime,
                   ) -> dict[str, str]:
        """Restore caches from local fixtures WITHOUT verifying.

        Events load normally; coverage resolves to "fresh" only when the
        persisted verified_utc is inside TTL, otherwise "unverified".
        Returns the resolved per-source state.
        """
        if now_utc.tzinfo is None:
            raise ValueError("now_utc must be timezone-aware")
        resolved: dict[str, str] = {}
        with self.lock:
            for adapter in self.adapters:
                snapshot = adapter.load(now_utc)
                for event in snapshot.events:
                    store.upsert(event)
                if snapshot.status in ("outage", "not-implemented"):
                    coverage = snapshot.coverage()
                    store.set_coverage(coverage)
                    resolved[snapshot.source] = coverage.status
                    continue
                state = self.states.get(snapshot.source)
                if state.verified_utc is not None:
                    # Verified before: fresh inside TTL, stale past it
                    # (the time check in coverage_status reports stale).
                    coverage = SourceCoverage(
                        source=snapshot.source,
                        source_url=snapshot.source_url,
                        horizon_end_utc=snapshot.horizon_end_utc,
                        fetched_utc=snapshot.fetched_utc,
                        expires_utc=state.verified_utc + self.cache_ttl,
                        status="fresh", verified_utc=state.verified_utc)
                else:
                    coverage = snapshot.coverage()
                store.set_coverage(coverage)
                resolved[snapshot.source] = coverage_status(
                    coverage, now_utc)
        return resolved

    def refresh_once(self, store: EventStore,
                     http_get: Callable[..., HttpResponse],
                     now_utc: datetime) -> dict[str, RefreshResult]:
        """Verify each cache against its official calendar over HTTP.

        Success (HTTP 200 + marker + all cached dates present) moves
        verified_utc to now and persists state. Anything else keeps the
        cache, records the failure, and persists that too.
        """
        if now_utc.tzinfo is None:
            raise ValueError("now_utc must be timezone-aware")
        results: dict[str, RefreshResult] = {}
        with self.lock:
            for adapter in self.adapters:
                source = adapter.source_id
                parser = _PARSERS.get(source)
                if parser is None:
                    results[source] = RefreshResult(
                        source=source, ok=False, verified_utc=None,
                        http_status=None,
                        error=f"{source}: no official-page parser")
                    continue
                state = self.states.get(source)
                state.last_attempt_utc = now_utc
                try:
                    reply = http_get(adapter.source_url)
                    body_text = reply.body.decode("utf-8", errors="replace")
                    if reply.status != 200:
                        raise ValueError(f"HTTP {reply.status}")
                    page_dates = parser(body_text)
                except Exception as exc:  # transport/parse failure: outage
                    state.consecutive_failures += 1
                    state.last_error = f"{type(exc).__name__}: {exc}"
                    self.states.put(state)
                    prior = store.coverage(source)
                    coverage = SourceCoverage(
                        source=source, source_url=adapter.source_url,
                        horizon_end_utc=(prior.horizon_end_utc
                                         if prior else None),
                        fetched_utc=now_utc,
                        expires_utc=now_utc + COVERAGE_TTL,
                        status="outage",
                        last_error=state.last_error,
                        verified_utc=state.verified_utc)
                    store.set_coverage(coverage)
                    results[source] = RefreshResult(
                        source=source, ok=False,
                        verified_utc=state.verified_utc,
                        http_status=None, error=state.last_error)
                    continue
                # REL-W3: drift is judged on UPCOMING cached dates only.
                # Official pages scroll past releases off (BLS shows ~12
                # upcoming); treating scrolled-off past dates as drift
                # would outage every refresh a week after each release.
                # Past dates already happened and cannot drift.
                today = now_utc.date()
                cached = {day for day in _cached_dates(store, source)
                          if day >= today}
                # NOTE: an empty upcoming set (elapsed horizon) yields
                # empty drift and stays "verified" here; coverage_status
                # reports "expired-horizon" separately -> no-entry.
                years = {day.year for day in cached}
                in_scope = {day for day in page_dates
                            if day.year in years and day >= today}
                missing = sorted(day.isoformat() for day in cached - in_scope)
                extra = sorted(day.isoformat() for day in in_scope - cached)
                payload_hash = hashlib.sha256(reply.body).hexdigest()[:16]
                state.payload_hash = payload_hash
                state.drift_missing = tuple(missing)
                state.drift_extra = tuple(extra)
                state.drift_recorded_utc = now_utc
                if missing:
                    state.consecutive_failures += 1
                    state.last_error = (
                        f"schedule drift: {len(missing)} cached date(s) "
                        f"absent from official page")
                    self.states.put(state)
                    coverage = SourceCoverage(
                        source=source, source_url=adapter.source_url,
                        horizon_end_utc=(store.coverage(source).horizon_end_utc
                                         if store.coverage(source) else None),
                        fetched_utc=now_utc,
                        expires_utc=now_utc + COVERAGE_TTL,
                        status="outage", last_error=state.last_error,
                        verified_utc=state.verified_utc)
                    store.set_coverage(coverage)
                    results[source] = RefreshResult(
                        source=source, ok=False,
                        verified_utc=state.verified_utc,
                        http_status=reply.status, error=state.last_error,
                        missing=tuple(missing), extra=tuple(extra),
                        payload_hash=payload_hash)
                    continue
                state.verified_utc = now_utc
                state.consecutive_failures = 0
                state.last_error = ""
                self.states.put(state)
                horizon = (store.coverage(source).horizon_end_utc
                           if store.coverage(source) else None)
                store.set_coverage(SourceCoverage(
                    source=source, source_url=adapter.source_url,
                    horizon_end_utc=horizon, fetched_utc=now_utc,
                    expires_utc=now_utc + self.cache_ttl, status="fresh",
                    verified_utc=now_utc))
                results[source] = RefreshResult(
                    source=source, ok=True, verified_utc=now_utc,
                    http_status=reply.status, extra=tuple(extra),
                    payload_hash=payload_hash)
            self.states.save()
        return results

    def start(self, store: EventStore,
              http_get: Callable[..., HttpResponse],
              interval_s: float = REFRESH_INTERVAL_S,
              now_utc: Callable[[], datetime] | None = None,
              on_result: Callable[[dict[str, RefreshResult]], None] | None
              = None) -> None:
        """Run refresh_once() on a daemon thread until stop()."""
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("refresher already running")
        clock = now_utc or (lambda: datetime.now(timezone.utc))
        stop = threading.Event()
        self._stop = stop

        def loop() -> None:
            while not stop.wait(interval_s):
                try:
                    results = self.refresh_once(store, http_get, clock())
                except Exception:
                    continue
                if on_result is not None:
                    try:
                        on_result(results)
                    except Exception:
                        continue

        self._thread = threading.Thread(target=loop, daemon=True,
                                        name="events-refresh")
        self._thread.start()

    def stop(self, timeout_s: float = 10.0) -> None:
        if self._stop is not None:
            self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout_s)
