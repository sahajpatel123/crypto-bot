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

Thread-ownership model (R1): in threaded mode the pump thread owns
ONLY the socket (recv/close) and the bounded handoff queue — it never
touches the Session, ledger, SQLite, or adapter state. The owner
thread (the run loop, via drain_owner() every tick) performs every
engine call and every checkpoint. Overflow, apply failures, and
excessive lag halt new entries without discarding evidence.
"""
from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol


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


# -- live-run wiring seam (Checkpoint-B, thread-owned per R1) -----------------
_STREAM_METHODS = ("listen_key", "open_listen_key", "keepalive_listen_key",
                   "stream_reconnected", "note_user_event", "set_exit_only")

_GAP_REASON = "user-stream-gap"
_OVERFLOW_REASON = "user-stream-overflow"
_LAG_REASON = "user-stream-lag"
_APPLY_REASON = "user-stream-apply"
_PUMP_REASON = "user-stream-pump"
_MIRROR_REASON = "user-stream"
_PARK_RING = 100


class UserStreamAttachment:
    """Supervised private-stream wiring for the live run path.

    Owns the gap→halt coupling plus, in threaded mode, a socket-only
    pump and the bounded supervised handoff to the owner:

    - The pump thread owns ONLY the socket (recv/close) and the
      handoff queue. It never touches the Session, ledger, SQLite,
      or adapter state (R1).
    - The OWNER thread (the run loop, via drain_owner() every tick)
      performs every engine call: connect, heal, envelope
      application, keepalive, reconnect. Single-threaded stepping
      via poll_once() keeps identical semantics with the caller as
      owner.
    - Halt reasons are attachment-owned and thread-safe; the owner
      mirrors them to the engine's reason-keyed exit-only under one
      coarse "user-stream" reason (R3: heals never clear Session's
      own halts). Queue overflow, apply failures, and excessive lag
      halt new entries WITHOUT discarding evidence (parked items +
      durable checkpoints).

    Manager wiring (cli.py owns Session construction; call after the
    Session exists, before run_live)::

        stream = attach_user_stream(session, engine, ws_factory)
        try:
            session.run_live(...)  # ticks call stream.drain_owner()
        finally:
            stream.close()

    close() stops the pump and the socket and lifts the stream's own
    halts (an operator act; evidence stays in the store).
    Gap/heal/overflow/apply/lag transitions checkpoint to the run
    store best-effort, always on the owner thread.
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
        queue_maxsize: int = 1000,
        lag_halt_s: float = 30.0,
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
        if int(queue_maxsize) < 1:
            raise ValueError("queue_maxsize must be >= 1")
        self._session = session
        self._engine = engine
        self._factory = socket_factory
        self._keepalive_s = float(keepalive_s)
        self._reader = UserStreamReader(
            engine, socket_factory, keepalive_s=keepalive_s,
            initial_backoff_s=initial_backoff_s,
            max_backoff_s=max_backoff_s, now=now, sleep=sleep)
        self._poll_timeout_s = float(poll_timeout_s)
        self._idle_sleep_s = float(idle_sleep_s)
        self._sleep = sleep
        self._now = now
        self._threaded = bool(start_thread)
        # Thread-safe attachment state (the ONLY thing the pump
        # touches besides its socket and these guarded cells).
        self._state_lock = threading.Lock()
        self._halt_reasons: set[str] = set()
        self._errors = 0
        self._fatal: str | None = None
        self._overflow_latch = False
        # Bounded handoff (R1): pump -> owner queue, owner -> pump
        # socket box (maxsize 1; full means pump hasn't taken yet).
        self._queue: queue.Queue = queue.Queue(maxsize=int(queue_maxsize))
        self._sock_box: queue.Queue = queue.Queue(maxsize=1)
        self._live_socket: StreamSocket | None = None  # owner-side ref.
        self._last_keepalive_at: float | None = None
        self._backoff_until: float = 0.0
        self._backoff_s = float(initial_backoff_s)
        self._initial_backoff_s = float(initial_backoff_s)
        self._max_backoff_s = float(max_backoff_s)
        self._lag_halt_s = float(lag_halt_s)
        self._parked: list[dict[str, Any]] = []  # owner-only ring.
        self._mirrored: bool | None = None
        self._closed = False
        self._thread: threading.Thread | None = None
        # Halt-until-first-heal: no new exposure before the stream
        # proves itself and reconciles.
        self._engage_halt(_GAP_REASON, "user-stream-gap",
                          {"phase": "connecting"})
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
        """True while ANY of OUR halt reasons is engaged."""
        with self._state_lock:
            return bool(self._halt_reasons)

    def halt_reasons(self) -> tuple[str, ...]:
        """Held stream halt reasons, sorted (R1/R3 evidence)."""
        with self._state_lock:
            return tuple(sorted(self._halt_reasons))

    @property
    def errors(self) -> int:
        with self._state_lock:
            return self._errors

    @property
    def fatal_error(self) -> str | None:
        """Pump-thread fatal text, if the pump died unexpectedly."""
        with self._state_lock:
            return self._fatal

    def pending_failures(self) -> list[dict[str, Any]]:
        """Parked apply-failures (evidence ring, oldest first)."""
        with self._state_lock:
            return list(self._parked)

    def acknowledge_failures(self) -> int:
        """Clear parked failures (owner act); releases the apply halt.

        Durable checkpoints stay in the store; only the live halt and
        the ring clear. Returns the acknowledged count.
        """
        if self._closed:
            raise RuntimeError("attachment is closed")
        with self._state_lock:
            count = len(self._parked)
            self._parked = []
        if _APPLY_REASON in self.halt_reasons():
            self._release_halt(_APPLY_REASON, "user-stream-apply-acked",
                               {"acknowledged": count})
        return count

    def _checkpoint(self, kind: str, payload: dict[str, Any]) -> None:
        try:
            store = getattr(self._session, "store", None)
            run_id = getattr(self._session, "run_id", "")
            if store is None or not run_id:
                return
            store.checkpoint(run_id, kind, payload)
        except Exception:
            pass

    # -- halt reasons: flag from any thread, mirror on owner -----------
    def _flag_halt(self, reason: str) -> None:
        """Engage one reason WITHOUT engine/store contact (any thread)."""
        with self._state_lock:
            self._halt_reasons.add(reason)

    def _engage_halt(self, reason: str, checkpoint_kind: str,
                     payload: dict[str, Any]) -> None:
        """Engage one reason + mirror + checkpoint (OWNER ONLY)."""
        with self._state_lock:
            fresh = reason not in self._halt_reasons
            self._halt_reasons.add(reason)
        self._mirror_halts()
        if fresh:
            self._checkpoint(checkpoint_kind,
                             {"reason": reason, **payload})

    def _release_halt(self, reason: str, checkpoint_kind: str,
                      payload: dict[str, Any]) -> None:
        """Release one reason + mirror + checkpoint (OWNER ONLY)."""
        with self._state_lock:
            held = reason in self._halt_reasons
            self._halt_reasons.discard(reason)
        self._mirror_halts()
        if held:
            self._checkpoint(checkpoint_kind,
                             {"reason": reason, **payload})

    def _mirror_halts(self) -> None:
        """Mirror attachment halts to engine exit-only (OWNER ONLY).

        One coarse engine reason; Session's own reasons survive every
        stream transition (R3). Called only on change (no journal
        spam): polled state, not per-tick writes.
        """
        halted = self.halted
        if halted == self._mirrored:
            return
        self._mirrored = halted
        self._engine.set_exit_only(halted, _MIRROR_REASON)

    # -- single-thread stepping (caller is the owner) ------------------
    def poll_once(self) -> str:
        """One supervised step: pump the reader, couple the halt."""
        if self._closed:
            raise RuntimeError("attachment is closed")
        if self._threaded:
            raise RuntimeError(
                "threaded attachment: drive the owner via drain_owner()")
        action = self._reader.poll_once(self._poll_timeout_s)
        # _ensure_connected heals before reporting connected, so any
        # connected step means reconciled-this-step or steady-holding.
        if not self._reader.connected:
            if _GAP_REASON not in self.halt_reasons():
                self._engage_halt(_GAP_REASON, "user-stream-gap",
                                  {"phase": action})
        elif _GAP_REASON in self.halt_reasons():
            self._release_halt(_GAP_REASON, "user-stream-healed",
                               {"phase": action})
        return action

    # -- threaded pump: socket + queue ONLY (R1) ------------------------
    def _pump(self) -> None:
        """Socket-only pump (R1): recv, enqueue, report death.

        Touches NOTHING but its socket, the handoff queue/socket box,
        and the guarded flag cells. All engine/session/store contact
        happens on the owner thread via drain_owner().
        """
        try:
            while not self._closed:
                try:
                    sock = self._sock_box.get(timeout=0.2)
                except queue.Empty:
                    continue
                if self._closed:
                    try:
                        sock.close()
                    except Exception:
                        pass
                    return
                try:
                    while not self._closed:
                        try:
                            envelope = sock.recv(self._poll_timeout_s)
                        except Exception as exc:
                            with self._state_lock:
                                self._errors += 1
                            self._put_blocking(
                                ("dead", str(exc), self._now()))
                            break
                        if envelope is None:
                            continue
                        self._put_blocking(
                            ("envelope", envelope, self._now()))
                finally:
                    try:
                        sock.close()
                    except Exception:
                        pass
        except Exception as exc:  # supervision: loud death, no spin.
            with self._state_lock:
                self._errors += 1
                self._fatal = f"{type(exc).__name__}: {exc}"
            self._flag_halt(_PUMP_REASON)

    def _put_blocking(self, item: tuple) -> None:
        """Enqueue without EVER discarding (R1 backpressure).

        A full queue blocks (evidence is never dropped); the block
        latches the overflow halt until the owner drains empty.
        """
        while not self._closed:
            try:
                self._queue.put(item, timeout=0.2)
                return
            except queue.Full:
                with self._state_lock:
                    self._overflow_latch = True

    # -- owner drain (every run-loop tick) -------------------------------
    def drain_owner(self) -> str:
        """Apply handoff input on the OWNER thread. Never raises for
        venue/transport conditions (they halt + checkpoint instead);
        raises only when closed or on programmer error."""
        if self._closed:
            return "closed"
        if not self._threaded:
            return self.poll_once()
        if self._thread is not None and not self._thread.is_alive():
            self._engage_halt(_PUMP_REASON, "user-stream-pump-dead",
                              {"fatal": self.fatal_error or "unknown"})
        status = "idle"
        if self._owner_connect():
            status = "healed"
        elif self._live_socket is None:
            status = "backoff"
        oldest: float | None = None
        for _ in range(self._queue.maxsize + 1):
            try:
                kind, payload, stamp = self._queue.get_nowait()
            except queue.Empty:
                break
            if oldest is None or stamp < oldest:
                oldest = stamp
            if kind == "envelope":
                status = "event"
                self._apply_envelope(payload)
            else:
                self._on_socket_dead(payload)
        self._owner_keepalive()
        self._owner_backlog(oldest)
        self._mirror_halts()
        return status

    def _owner_connect(self) -> bool:
        """Dial + heal on the owner; hand the socket to the pump."""
        if self._live_socket is not None:
            return False
        now = self._now()
        if now < self._backoff_until:
            return False
        try:
            key = self._engine.listen_key
            if key is None:
                key = self._engine.open_listen_key()
            sock = self._factory(key)
            self._engine.stream_reconnected()
        except Exception as exc:
            with self._state_lock:
                self._errors += 1
            self._backoff_until = now + self._backoff_s
            self._backoff_s = min(self._backoff_s * 2.0,
                                  self._max_backoff_s)
            self._checkpoint("user-stream-connect-failed",
                             {"error": f"{type(exc).__name__}: {exc}"})
            return False
        try:
            self._sock_box.put_nowait(sock)
        except queue.Full:
            try:
                sock.close()
            except Exception:
                pass
            return False
        self._backoff_s = self._initial_backoff_s
        self._last_keepalive_at = self._now()
        self._live_socket = sock
        self._release_halt(_GAP_REASON, "user-stream-healed",
                           {"phase": "owner-connect"})
        return True

    def _apply_envelope(self, envelope: dict[str, Any]) -> None:
        """Apply one envelope on the owner; park failures (R1)."""
        try:
            self._engine.note_user_event(envelope)
        except Exception as exc:
            with self._state_lock:
                self._parked.append({
                    "envelope": envelope,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                del self._parked[:-_PARK_RING]
            self._engage_halt(_APPLY_REASON, "user-stream-apply-failed",
                              {"error": f"{type(exc).__name__}: {exc}"})
            return
        if envelope.get("e") == "listenKeyExpired" \
                or self._engine.listen_key is None:
            # Venue closed the socket with the key; redial. Gap
            # engages NOW (coverage uncertain until reheal), the
            # pump's dead report just confirms.
            self._redial("listenKeyExpired")

    def _on_socket_dead(self, error: str) -> None:
        self._live_socket = None
        self._engage_halt(_GAP_REASON, "user-stream-gap",
                          {"phase": "socket-dead", "error": error})

    def _redial(self, why: str) -> None:
        sock, self._live_socket = self._live_socket, None
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
        self._engage_halt(_GAP_REASON, "user-stream-gap",
                          {"phase": "redial", "why": why})

    def _owner_keepalive(self) -> None:
        if self._live_socket is None or self._last_keepalive_at is None:
            return
        if self._now() - self._last_keepalive_at < self._keepalive_s:
            return
        try:
            self._engine.keepalive_listen_key()
        except Exception:
            self._redial("keepalive-failed")
            return
        self._last_keepalive_at = self._now()

    def _owner_backlog(self, oldest: float | None) -> None:
        """Overflow + lag accounting from the live queue (R1)."""
        with self._queue.mutex:
            remaining = len(self._queue.queue)
            oldest_pending = (self._queue.queue[0][2]
                              if self._queue.queue else None)
        with self._state_lock:
            overflow = self._overflow_latch
            if remaining == 0:
                self._overflow_latch = False
        if overflow and remaining == 0:
            self._release_halt(_OVERFLOW_REASON,
                               "user-stream-overflow-drained", {})
        elif overflow:
            self._engage_halt(_OVERFLOW_REASON, "user-stream-overflow",
                              {"queued": remaining})
        stamp = oldest_pending if oldest_pending is not None else oldest
        if remaining == 0:
            if _LAG_REASON in self.halt_reasons():
                self._release_halt(_LAG_REASON, "user-stream-caught-up",
                                   {})
        elif stamp is not None and self._now() - stamp > self._lag_halt_s:
            self._engage_halt(_LAG_REASON, "user-stream-lag",
                              {"lag_s": self._now() - stamp,
                               "queued": remaining})
        elif _LAG_REASON in self.halt_reasons():
            self._release_halt(_LAG_REASON, "user-stream-caught-up", {})

    def close(self) -> None:
        """Stop the pump + socket (OWNER ONLY); lift stream halts."""
        self._closed = True
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)
        try:
            while True:
                try:
                    sock = self._sock_box.get_nowait()
                except queue.Empty:
                    break
                try:
                    sock.close()
                except Exception:
                    pass
        finally:
            self._reader.close()
        if thread is threading.current_thread():
            return  # never mirror from the pump thread itself.
        with self._state_lock:
            reasons = sorted(self._halt_reasons)
            self._halt_reasons.clear()
        self._mirror_halts()
        if reasons:
            self._checkpoint("user-stream-closed", {"was": reasons})


def attach_user_stream(
    session: Any,
    engine: Any,
    ws_factory: Callable[[str], StreamSocket],
    **kwargs: Any,
) -> UserStreamAttachment:
    """Attach the private user stream to a live run (Checkpoint-B).

    Threaded (default): the pump owns the socket ONLY (R1); the run
    loop must call attachment.drain_owner() every tick — Session
    does this in run_live once attached here. Single-threaded
    (start_thread=False): drive via poll_once() stepping.

    Extra kwargs pass through (start_thread, poll_timeout_s,
    idle_sleep_s, keepalive_s, backoffs, queue_maxsize, lag_halt_s,
    now, sleep). Registers the attachment on the session so
    admission can consult stream halts.
    """
    attachment = UserStreamAttachment(session, engine, ws_factory,
                                      **kwargs)
    try:
        session._user_stream_attachment = attachment
    except AttributeError:
        pass
    return attachment
