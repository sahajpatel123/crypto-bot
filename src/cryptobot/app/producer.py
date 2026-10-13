"""Bounded feed producer + async REST runner (W3-30MIN §4).

The control loop must never block on the feed, REST, or reconnect work.
:class:`BoundedProducer` moves a blocking event iterator onto a daemon
thread behind a bounded queue (drop-oldest + loud counter); the control
thread polls with a tick timeout. :class:`AsyncCall` runs one blocking
REST callable off-thread with non-blocking result polling.

Single-owner rule: the producer/worker threads touch ONLY their own
queue/counters. Account, order, risk, and ledger state stay owned by the
Session control thread — enforced by construction (no callbacks into
Session from these threads).
"""
from __future__ import annotations

import os
import queue
import threading
import time
from typing import Any, Callable, Iterator

__all__ = ["TIMEOUT", "AsyncCall", "BoundedProducer",
           "deadline_remaining_s"]


class _Timeout:
    """Sentinel type: poll() returned with no queued item (tick wake)."""

    _inst: "_Timeout | None" = None

    def __new__(cls) -> "_Timeout":
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self) -> str:  # pragma: no cover - debugging aid.
        return "TIMEOUT"


#: Returned by BoundedProducer.poll on tick-timeout. Queued idle
#: heartbeats (None) are real items and arrive as None, so a timeout
#: wake is never confused with a heartbeat wake.
TIMEOUT = _Timeout()


def deadline_remaining_s(default: float | None = None) -> float | None:
    """Seconds left on the inherited run_budget deadline (W3-30MIN §4).

    Reads CRYPTOBOT_DEADLINE_MONO (monotonic seconds, set by
    tools/run_budget.py). Returns ``default`` when no deadline is
    inherited. Never negative.
    """
    raw = os.environ.get("CRYPTOBOT_DEADLINE_MONO")
    if raw is None:
        return default
    try:
        return max(0.0, float(raw) - time.monotonic())
    except ValueError:
        return default


class BoundedProducer:
    """Threaded, bounded, drop-oldest event queue over a blocking iterator.

    Idle heartbeats (None) are queued as wakes like any event: every
    iterator yield gets exactly one control wake, in order. Terminal
    iterator failures are captured and re-raised to the control thread
    via :meth:`raise_if_failed` (never swallowed in the thread).
    """

    def __init__(self, event_iter: Iterator[Any], *, maxsize: int = 1000,
                 name: str = "feed") -> None:
        if maxsize <= 0:
            raise ValueError("maxsize must be > 0")
        self._iter = event_iter
        self._queue: queue.Queue = queue.Queue()
        self._maxsize = maxsize
        self._dropped = 0
        self._finished = threading.Event()
        self._error: BaseException | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._pump, name=name,
                                        daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        try:
            for event in self._iter:
                if self._stop.is_set():
                    return
                # Boxed: a queued None heartbeat must survive the trip
                # as an item, distinct from a poll timeout.
                self._queue.put_nowait((event,))
                while self._queue.qsize() > self._maxsize:
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        break
                    self._dropped += 1
        except BaseException as exc:  # noqa: BLE001 - ferried to control.
            self._error = exc
        finally:
            self._finished.set()

    def poll(self, timeout: float) -> Any:
        """Next queued item, or TIMEOUT when the tick elapses with none."""
        try:
            (event,) = self._queue.get(timeout=timeout)
            return event
        except queue.Empty:
            return TIMEOUT

    def raise_if_failed(self) -> None:
        """Re-raise a terminal producer failure on the control thread."""
        if self._error is not None:
            raise self._error

    @property
    def dropped(self) -> int:
        """Events dropped by the bound (loud overflow counter)."""
        return self._dropped

    @property
    def finished(self) -> bool:
        """True once the iterator is exhausted or failed."""
        return self._finished.is_set()

    @property
    def qsize(self) -> int:
        return self._queue.qsize()

    def close(self, timeout: float = 0.25) -> None:
        """Signal the pump to exit; wait at most one tick for it.

        A producer blocked on a stuck feed must never delay loop
        shutdown (operator-stop responsiveness): the pump is a daemon
        thread holding only its own queue, so an unreaped pump exits
        on its own at the next yield boundary with nothing stranded.
        """
        self._stop.set()
        self._thread.join(timeout=timeout)


class AsyncCall:
    """One blocking callable off the control thread; poll for the result.

    Exactly one background thread per call; :meth:`poll` never blocks.
    """

    def __init__(self, fn: Callable[[], Any], *, name: str = "rest") -> None:
        self._result: list[Any] = []
        self._error: BaseException | None = None
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(fn,),
                                        name=name, daemon=True)
        self._thread.start()

    def _run(self, fn: Callable[[], Any]) -> None:
        try:
            self._result.append(fn())
        except BaseException as exc:  # noqa: BLE001 - ferried to control.
            self._error = exc
        finally:
            self._done.set()

    def poll(self) -> tuple[bool, Any]:
        """(done, result-or-exception). Never blocks, never raises."""
        if not self._done.is_set():
            return False, None
        if self._error is not None:
            return True, self._error
        return True, self._result[0] if self._result else None

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until done (shutdown drain only). Returns done flag."""
        return self._done.wait(timeout)
