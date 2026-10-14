"""Binance USD-M private user-stream reader (Worker 2, release).

Owns the user-data-stream socket loop with an INJECTED transport: gap
watchdog, listenKey lifecycle (via the engine), and reconnect+heal
(engine.stream_reconnected() looks up every journaled non-terminal
order, so a dropped socket can never lose a TRADE event silently).

Steppable by design: poll_once() advances one step so offline tests
drive exact gap/reconnect/heal scripts with a fake clock. Production
wiring (real socket factory, thread supervision) is manager/CLI scope.

Gap model: this stream has no server heartbeat, so silence is normal
idleness and NEVER triggers a reconnect. Gaps surface as socket death,
listenKeyExpiry, or process restart — every one of which heals via
engine.stream_reconnected() (REST lookup of every journaled
non-terminal order) before any new exposure.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Protocol


class StreamSocket(Protocol):
    """Minimal socket surface the reader needs (injectable)."""

    def recv(self, timeout_s: float) -> dict[str, Any] | None:
        """Next envelope, or None on timeout (raises on socket death)."""
        ...

    def close(self) -> None:
        ...


class UserStreamReader:
    """Read private stream envelopes into the engine, healing gaps."""

    def __init__(
        self,
        engine: Any,
        socket_factory: Callable[[str], StreamSocket],
        *,
        keepalive_s: float = 1500.0,
        initial_backoff_s: float = 1.0,
        max_backoff_s: float = 60.0,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._engine = engine
        self._factory = socket_factory
        self._keepalive_s = float(keepalive_s)
        self._initial_backoff_s = float(initial_backoff_s)
        self._max_backoff_s = float(max_backoff_s)
        self._now = now
        self._sleep = sleep
        self._socket: StreamSocket | None = None
        self._last_keepalive_at: float | None = None
        self._backoff_until: float = 0.0
        self._backoff_s = float(initial_backoff_s)

    # -- connection ------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._socket is not None

    def _drop(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

    def _ensure_connected(self) -> bool:
        """Open key + dial + heal; False only inside backoff (no throw)."""
        if self._socket is not None:
            return True
        now = self._now()
        if now < self._backoff_until:
            return False
        try:
            key = self._engine.listen_key
            if key is None:
                key = self._engine.open_listen_key()
            self._socket = self._factory(key)
            # Fresh connect AND reconnect both heal: journaled
            # non-terminal orders reconcile before any new exposure.
            self._engine.stream_reconnected()
        except Exception:
            self._drop()
            self._backoff_until = now + self._backoff_s
            self._backoff_s = min(self._backoff_s * 2.0,
                                  self._max_backoff_s)
            return False
        self._backoff_s = self._initial_backoff_s
        self._last_keepalive_at = self._now()
        return True

    # -- stepping ----------------------------------------------------------
    def poll_once(self, timeout_s: float = 1.0) -> str:
        """Advance one step. Returns event|keepalive|healed|idle|backoff."""
        was_down = self._socket is None
        if not self._ensure_connected():
            return "backoff"
        assert self._socket is not None
        try:
            envelope = self._socket.recv(timeout_s)
        except Exception:
            self._drop()
            healed = self._ensure_connected()
            return "healed" if healed else "backoff"
        if was_down:
            # Fresh connect (or backoff recovery) always heals first;
            # any envelope arriving on this step still dispatches below.
            if envelope is None:
                return "healed"
        now = self._now()
        if envelope is None:
            # Silence is idleness, never a gap signal (no heartbeat).
            assert self._last_keepalive_at is not None
            if now - self._last_keepalive_at >= self._keepalive_s:
                try:
                    self._engine.keepalive_listen_key()
                except Exception:
                    self._drop()
                    healed = self._ensure_connected()
                    return "healed" if healed else "backoff"
                self._last_keepalive_at = now
                return "keepalive"
            return "idle"
        self._engine.note_user_event(envelope)
        if envelope.get("e") == "listenKeyExpired" \
                or self._engine.listen_key is None:
            # Venue closed the socket with the key; redial next step.
            self._drop()
        return "event"

    def run_until(self, deadline: float,
                  timeout_s: float = 1.0) -> dict[str, int]:
        """Loop poll_once until the (fake-clock) deadline; count actions."""
        counts: dict[str, int] = {}
        while self._now() < deadline:
            action = self.poll_once(timeout_s)
            counts[action] = counts.get(action, 0) + 1
            if action == "backoff":
                self._sleep(0)
        return counts

    def close(self) -> None:
        self._drop()


# -- live-run wiring seam (Checkpoint-B) -------------------------------------
_STREAM_METHODS = ("listen_key", "open_listen_key", "keepalive_listen_key",
                   "stream_reconnected", "note_user_event", "set_exit_only")


class UserStreamAttachment:
    """Supervised private-stream wiring for the live run path.

    Owns one UserStreamReader plus the gap→halt coupling: while the
    stream is down (connecting, socket dead, backoff) entries are
    halted via the engine's existing exit-only flag — the same halt
    mechanism Session uses (funding-mismatch, health, filters) — so
    exits keep working and no new exposure opens blind. The first
    heal releases the halt. Last-writer-wins, matching Session's own
    exit-only use (Session re-asserts its halt reasons on its ticks).

    Manager wiring (cli.py owns Session construction; call after the
    Session exists, before run_live)::

        stream = attach_user_stream(session, engine, ws_factory)
        try:
            session.run_live(...)
        finally:
            stream.close()

    close() stops the pump and the socket; exit-only state is left
    as-is (re-attach re-heals). Gap/heal transitions checkpoint to
    the run store best-effort (never break the pump).
    """

    def __init__(
        self,
        session: Any,
        engine: Any,
        socket_factory: Callable[[str], StreamSocket],
        *,
        start_thread: bool = True,
        poll_timeout_s: float = 1.0,
        idle_sleep_s: float = 0.5,
        keepalive_s: float = 1500.0,
        initial_backoff_s: float = 1.0,
        max_backoff_s: float = 60.0,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        missing = [name for name in _STREAM_METHODS
                   if not hasattr(engine, name)
                   or (name != "listen_key"
                       and not callable(getattr(engine, name)))]
        if missing:
            raise TypeError(
                "attach_user_stream needs a live engine with a private "
                f"user stream; missing: {', '.join(missing)}")
        if not callable(socket_factory):
            raise TypeError("ws_factory must be callable")
        self._session = session
        self._engine = engine
        self._reader = UserStreamReader(
            engine, socket_factory, keepalive_s=keepalive_s,
            initial_backoff_s=initial_backoff_s,
            max_backoff_s=max_backoff_s, now=now, sleep=sleep)
        self._poll_timeout_s = float(poll_timeout_s)
        self._idle_sleep_s = float(idle_sleep_s)
        self._sleep = sleep
        self._halted = False
        self._closed = False
        self._errors = 0
        self._thread: threading.Thread | None = None
        # Halt-until-first-heal: no new exposure before the stream
        # proves itself and reconciles.
        self._engage_halt("user-stream-gap:connecting")
        if start_thread:
            self._thread = threading.Thread(
                target=self._pump, name="user-stream",
                daemon=True)
            self._thread.start()

    @property
    def reader(self) -> UserStreamReader:
        return self._reader

    @property
    def halted(self) -> bool:
        """True while OUR gap halt is engaged (not Session's own)."""
        return self._halted

    @property
    def errors(self) -> int:
        return self._errors

    def _checkpoint(self, kind: str, payload: dict[str, Any]) -> None:
        try:
            store = getattr(self._session, "store", None)
            run_id = getattr(self._session, "run_id", "")
            if store is None or not run_id:
                return
            store.checkpoint(run_id, kind, payload)
        except Exception:
            pass

    def _engage_halt(self, reason: str) -> None:
        self._engine.set_exit_only(True, reason)
        self._halted = True
        self._checkpoint("user-stream-gap", {"reason": reason})

    def _release_halt(self, reason: str) -> None:
        self._engine.set_exit_only(False, reason)
        self._halted = False
        self._checkpoint("user-stream-healed", {"reason": reason})

    def poll_once(self) -> str:
        """One supervised step: pump the reader, couple the halt."""
        if self._closed:
            raise RuntimeError("attachment is closed")
        action = self._reader.poll_once(self._poll_timeout_s)
        # _ensure_connected heals before reporting connected, so any
        # connected step means reconciled-this-step or steady-holding.
        if not self._reader.connected:
            if not self._halted:
                self._engage_halt("user-stream-gap")
        elif self._halted:
            self._release_halt("user-stream-healed")
        return action

    def _pump(self) -> None:
        while not self._closed:
            try:
                action = self.poll_once()
            except Exception:
                self._errors += 1
                action = "backoff"
            if self._closed:
                break
            if action in ("idle", "backoff", "keepalive"):
                self._sleep(self._idle_sleep_s)

    def close(self) -> None:
        self._closed = True
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)
        self._reader.close()


def attach_user_stream(
    session: Any,
    engine: Any,
    ws_factory: Callable[[str], StreamSocket],
    **kwargs: Any,
) -> UserStreamAttachment:
    """Attach the private user stream to a live run (Checkpoint-B).

    See UserStreamAttachment for the manager wiring call. Extra
    kwargs pass through (start_thread, poll_timeout_s, idle_sleep_s,
    keepalive_s, backoffs, now, sleep).
    """
    return UserStreamAttachment(session, engine, ws_factory, **kwargs)
