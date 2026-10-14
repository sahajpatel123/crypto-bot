"""Entry-blocking event gate for Session (Worker 4, EV-001).

Paper hypothesis (frozen, directive section 6): block entries from 15
minutes before a designated event until 15 minutes after it. Press
conferences are separate events covering their verified end (or the
fixture's explicit conservative duration) plus the post buffer.
REL-W3 admission cutoff: entries stop earlier, at window_start minus
max-hold minus the orderly-exit budget, so an admitted position's full
hold and exit fit before the window (pre-buffer absorbs abnormal exits).

The gate answers ONE question: may Session admit a new entry right now?
It never touches exits: there is deliberately no exit-blocking API, so
event restrictions cannot suppress protective exits. Session consults
``check()`` in ``_maybe_admit`` before risk evaluation and maps a blocked
decision to rejection reason ``event:<cause>`` (stage "event" in
rejections.jsonl).

Fail-closed coverage: when any REQUIRED source is unknown, outage,
stale, unverified, or past its horizon, check() blocks with an explicit
``event:stale-source:<source>:<state>`` reason. A source outage or an
incomplete horizon can never silently mean "no events".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .store import EventStore, coverage_status
from .types import Event

PRE_BUFFER_S = 900
POST_BUFFER_S = 900
PRESS_DURATION_S = 3600  # fallback when a press event lacks press_end_utc
RESUME_COOLDOWN_S = 0
MAX_HOLD_S = 300  # REL-W3: longest position hold the cutoff fits
EXIT_BUDGET_S = 120  # REL-W3: orderly-exit budget after max hold
REQUIRED_SOURCES = ("fomc", "cpi")
OPTIONAL_SOURCES = ("employment", "bea-pce", "bea-gdp",
                    "exchange-notices")


@dataclass(frozen=True)
class GateConfig:
    pre_buffer_s: int = PRE_BUFFER_S
    post_buffer_s: int = POST_BUFFER_S
    press_duration_s: int = PRESS_DURATION_S
    resume_cooldown_s: int = RESUME_COOLDOWN_S
    max_hold_s: int = MAX_HOLD_S
    exit_budget_s: int = EXIT_BUDGET_S
    required_sources: tuple[str, ...] = REQUIRED_SOURCES
    optional_sources: tuple[str, ...] = OPTIONAL_SOURCES

    def __post_init__(self) -> None:
        for name in ("pre_buffer_s", "post_buffer_s", "press_duration_s",
                     "resume_cooldown_s", "max_hold_s", "exit_budget_s"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        object.__setattr__(self, "required_sources",
                           tuple(self.required_sources))
        object.__setattr__(self, "optional_sources",
                           tuple(self.optional_sources))


@dataclass(frozen=True)
class GateDecision:
    blocked: bool
    reason: str
    event_ids: tuple[str, ...] = ()
    window_end_utc: datetime | None = None
    coverage: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_ids", tuple(self.event_ids))
        if self.window_end_utc is not None and self.window_end_utc.tzinfo is None:
            raise ValueError("window_end_utc must be timezone-aware")


@dataclass(frozen=True)
class UpcomingEvent:
    event: Event
    window_start_utc: datetime
    window_end_utc: datetime
    action: str  # "prepare-flat": cancel unfilled entries, aim flat


class EventGate:
    def __init__(self, store: EventStore,
                 config: GateConfig | None = None) -> None:
        self.store = store
        self.config = config or GateConfig()

    def window(self, event: Event) -> tuple[datetime, datetime]:
        """(block_start, block_end) for one event, buffers included.

        Decision/release events: scheduled +/- buffers. Press conferences:
        scheduled - pre-buffer through press-end + post-buffer, where
        press-end is the verified fixture value or the configured
        conservative duration assumption.
        """
        start = event.scheduled_utc - timedelta(
            seconds=self.config.pre_buffer_s)
        anchor = event.scheduled_utc
        if event.kind == "press-conference":
            anchor = event.press_end_utc or (
                event.scheduled_utc + timedelta(
                    seconds=self.config.press_duration_s))
        end = anchor + timedelta(seconds=self.config.post_buffer_s)
        end += timedelta(seconds=self.config.resume_cooldown_s)
        return start, end

    def admission_cutoff(self, event: Event) -> datetime:
        """Latest instant a new entry may be admitted before this window.

        REL-W3: cutoff = window_start - max_hold - exit_budget, so a
        position opened at the cutoff is flat by window start under
        normal closes; the pre-buffer then absorbs abnormal exits.
        """
        start, _ = self.window(event)
        return start - timedelta(seconds=self.config.max_hold_s
                                 + self.config.exit_budget_s)

    def coverage_report(self, now_utc: datetime) -> dict[str, str]:
        report: dict[str, str] = {}
        for source in (self.config.required_sources
                       + self.config.optional_sources):
            report[source] = coverage_status(
                self.store.coverage(source), now_utc)
        return report

    def check(self, now_utc: datetime) -> GateDecision:
        if now_utc.tzinfo is None:
            raise ValueError("now_utc must be timezone-aware")
        coverage = self.coverage_report(now_utc)
        for source in self.config.required_sources:
            state = coverage[source]
            if state != "fresh":
                return GateDecision(
                    blocked=True,
                    reason=f"event:stale-source:{source}:{state}",
                    coverage=coverage)
        hits: list[tuple[str, Event, datetime, datetime]] = []
        for event in self.store.all():
            if event.status == "cancelled":
                continue
            start, end = self.window(event)
            # REL-W3: entries stop at the admission cutoff (hold + exit
            # fit before the window), not at window start.
            if self.admission_cutoff(event) <= now_utc <= end:
                if now_utc < event.scheduled_utc:
                    label = "pre-window"
                elif (event.kind == "press-conference"
                      and now_utc >= event.scheduled_utc):
                    label = "press-window"
                elif now_utc <= event.scheduled_utc + timedelta(
                        seconds=self.config.post_buffer_s):
                    label = "in-window"
                else:
                    label = "post-window"
                hits.append((label, event, start, end))
        if not hits:
            return GateDecision(blocked=False, reason="event:clear",
                                coverage=coverage)
        # Deterministic priority: press/in-window first, then pre, then post;
        # ties broken by earliest window start, then event_id.
        order = {"press-window": 0, "in-window": 1, "pre-window": 2,
                 "post-window": 3}
        hits.sort(key=lambda h: (order[h[0]], h[2], h[1].event_id))
        label, event, _, end = hits[0]
        return GateDecision(
            blocked=True,
            reason=f"event:{label}:{event.event_id}",
            event_ids=tuple(h[1].event_id for h in hits),
            window_end_utc=max(h[3] for h in hits),
            coverage=coverage)

    def active(self, now_utc: datetime) -> list[Event]:
        """Events whose block window contains now (any label)."""
        if now_utc.tzinfo is None:
            raise ValueError("now_utc must be timezone-aware")
        out = []
        for event in self.store.all():
            if event.status == "cancelled":
                continue
            start, end = self.window(event)
            if start <= now_utc <= end:
                out.append(event)
        return out

    def upcoming(self, now_utc: datetime,
                 horizon_s: int) -> list[UpcomingEvent]:
        """Events whose window opens within horizon_s (for aim-flat prep).

        Session uses this BEFORE the window: cancel unfilled entries and
        aim to be flat by window start. Protection stays on until closure
        is confirmed; this query never mutates positions itself.
        """
        if now_utc.tzinfo is None:
            raise ValueError("now_utc must be timezone-aware")
        if horizon_s < 0:
            raise ValueError("horizon_s must be >= 0")
        horizon_end = now_utc + timedelta(seconds=horizon_s)
        out: list[UpcomingEvent] = []
        for event in self.store.all():
            if event.status == "cancelled":
                continue
            start, end = self.window(event)
            if now_utc < start <= horizon_end:
                out.append(UpcomingEvent(
                    event=event, window_start_utc=start,
                    window_end_utc=end, action="prepare-flat"))
        out.sort(key=lambda u: (u.window_start_utc, u.event.event_id))
        return out
