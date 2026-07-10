"""Multi-session store for the HTTP control API.

:class:`SessionManager` owns a set of live :class:`~streamcatcher.player.session.StreamSession`
objects keyed by opaque id, each wrapped in a :class:`ManagedSession` that adds a
per-session lock and a last-access timestamp.

``StreamSession`` is synchronous and not thread-safe (``look()`` mutates the
viewport while ``render()`` reads it, and ``cap.read()`` blocks). Every access to
a session therefore goes through its :class:`ManagedSession`, which serialises
reads and look-mutations under one lock. By default frames are read **on demand**,
and the API's route handlers run in Starlette's thread pool, so a blocking read
never stalls the event loop. Optionally (``reader_fps > 0``) each session runs a
background reader thread that keeps the latest frame cached, so request handlers
return the cached frame instead of blocking on a read — see :class:`ManagedSession`.
The other background task is the idle reaper (driven by the app), which calls
:meth:`SessionManager.reap`.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid

from streamcatcher.config import Projection, Settings
from streamcatcher.logging_setup import install_secret_redaction
from streamcatcher.player.profiles import get_profile
from streamcatcher.player.session import StreamSession, ViewState

log = logging.getLogger("streamcatcher.api.sessions")

# The discrete look actions exposed as `POST /session/{id}/look/{action}`; each
# maps to a same-named method on StreamSession.
DISCRETE_LOOKS = frozenset({"pan_left", "pan_right", "tilt_up", "tilt_down", "zoom_in", "zoom_out"})


class SessionNotFoundError(KeyError):
    """Raised when a session id is unknown (maps to HTTP 404)."""


class SessionLimitError(RuntimeError):
    """Raised when the concurrent-session cap is reached (maps to HTTP 429)."""


class ManagedSession:
    """A :class:`StreamSession` plus a lock and a last-access timestamp.

    When ``reader_fps`` is positive a background daemon thread owns the blocking
    ``cap.read()`` and keeps the latest raw frame cached, so request handlers
    return the cached frame instead of blocking on a read. The cache is primed
    synchronously at construction; after the stream drops it holds the last good
    frame (which *is* the latest frame) until reconnect or close. With
    ``reader_fps == 0`` (the default) frames are read on demand under the lock,
    exactly as before.
    """

    def __init__(self, session_id: str, session: StreamSession, *, reader_fps: int = 0) -> None:
        self.id = session_id
        self._session = session
        self._lock = threading.Lock()  # serialises access to the StreamSession
        self.last_access = time.monotonic()
        # Optional background reader. ``_frame_lock`` guards only the cached-frame
        # handoff and is never held while acquiring ``_lock`` (no lock-order cycle).
        self._reader_fps = reader_fps
        self._frame_lock = threading.Lock()
        self._latest_raw = None  # most recent raw frame, or None if none yet
        self._ended = False  # the stream has stopped producing frames
        self._stop = threading.Event()
        self._reader: threading.Thread | None = None
        if reader_fps > 0:
            self._read_once()  # prime so the first request already has a frame
            if not self._ended:
                self._reader = threading.Thread(
                    target=self._reader_loop, name=f"reader-{session_id}", daemon=True
                )
                self._reader.start()

    def touch(self) -> None:
        self.last_access = time.monotonic()

    # --- background reader ----------------------------------------------------

    def _read_once(self) -> bool:
        """Read one raw frame into the cache; ``False`` once the stream has ended."""
        with self._lock:
            raw = self._session.read_frame()
        if raw is None:
            with self._frame_lock:
                self._ended = True
            return False
        with self._frame_lock:
            self._latest_raw = raw
        return True

    def _reader_loop(self) -> None:
        """Refresh the cached frame until stopped or the stream ends."""
        delay = 1.0 / self._reader_fps
        while not self._stop.is_set():
            if not self._read_once():
                break  # stream ended — keep the last good frame and stop reading
            self._stop.wait(delay)

    def _cached_raw(self):
        with self._frame_lock:
            return self._latest_raw

    # --- request-facing access (serialised) ----------------------------------

    def grab_view(self):
        """The current viewport frame (rendered); ``None`` when no frame is available."""
        if self._reader_fps:
            raw = self._cached_raw()
            if raw is None:
                return None
            with self._lock:
                return self._session.render(raw)
        with self._lock:
            return self._session.grab_view()

    def grab_raw(self):
        """The current raw (pre-reprojection) frame; ``None`` when unavailable."""
        if self._reader_fps:
            return self._cached_raw()
        with self._lock:
            return self._session.read_frame()

    def look(self, pan: float, tilt: float, zoom: float) -> None:
        with self._lock:
            self._session.look(pan=pan, tilt=tilt, zoom=zoom)

    def apply_discrete(self, action: str) -> None:
        """Apply a named discrete look step (see :data:`DISCRETE_LOOKS`)."""
        if action not in DISCRETE_LOOKS:
            raise ValueError(f"Unknown look action {action!r}.")
        method = getattr(self._session, action)
        with self._lock:
            method()

    def state(self) -> ViewState:
        with self._lock:
            return self._session.state()

    def close(self) -> None:
        self._stop.set()
        if self._reader is not None:
            self._reader.join(timeout=2.0)
        with self._lock:
            self._session.close()


class SessionManager:
    """A thread-safe registry of live sessions with a concurrency cap."""

    def __init__(self, *, max_sessions: int, idle_timeout: int, reader_fps: int = 0) -> None:
        self._sessions: dict[str, ManagedSession] = {}
        self._lock = threading.Lock()
        self._max_sessions = max_sessions
        self._idle_timeout = idle_timeout
        self._reader_fps = reader_fps  # >0 gives each session a background reader

    def create(self, url: str, projection: Projection, profile_name: str | None) -> ManagedSession:
        """Open a new session for ``url`` and register it.

        Raises ``ValueError`` for an unknown profile, :class:`SessionLimitError`
        when the cap is reached, or ``StreamOpenError`` if the stream won't open.
        """
        # Resolve the profile first so a bad name fails before we open anything.
        profile = get_profile(profile_name) if profile_name else None
        # Seed log redaction with the URL's embedded credentials so they can't
        # leak through any log line this session produces.
        install_secret_redaction(Settings(stream_url=url).secret_values())

        with self._lock:
            if len(self._sessions) >= self._max_sessions:
                raise SessionLimitError(
                    f"Session limit reached ({self._max_sessions}); close a session first."
                )

        # Open outside the manager lock: a blocking open must not stall lookups
        # of other, already-live sessions.
        session = StreamSession(url, projection=projection, profile=profile)
        session.open()  # raises StreamOpenError on failure
        session_id = uuid.uuid4().hex
        managed = ManagedSession(session_id, session, reader_fps=self._reader_fps)
        with self._lock:
            self._sessions[session_id] = managed
        log.info("Opened session %s.", session_id)
        return managed

    def get(self, session_id: str) -> ManagedSession:
        with self._lock:
            managed = self._sessions.get(session_id)
        if managed is None:
            raise SessionNotFoundError(session_id)
        managed.touch()
        return managed

    def delete(self, session_id: str) -> None:
        with self._lock:
            managed = self._sessions.pop(session_id, None)
        if managed is None:
            raise SessionNotFoundError(session_id)
        managed.close()
        log.info("Closed session %s.", session_id)

    def list_ids(self) -> list[str]:
        with self._lock:
            return list(self._sessions)

    def reap(self) -> int:
        """Close and drop sessions idle longer than the timeout; return the count."""
        now = time.monotonic()
        with self._lock:
            expired = [
                sid for sid, m in self._sessions.items() if now - m.last_access > self._idle_timeout
            ]
            managed = [self._sessions.pop(sid) for sid in expired]
        for m in managed:
            m.close()
            log.info("Reaped idle session %s.", m.id)
        return len(managed)

    def close_all(self) -> None:
        """Close every session (used on server shutdown)."""
        with self._lock:
            managed = list(self._sessions.values())
            self._sessions.clear()
        for m in managed:
            m.close()
