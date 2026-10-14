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
