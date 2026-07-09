"""Multi-session store for the HTTP control API.

:class:`SessionManager` owns a set of live :class:`~streamcatcher.player.session.StreamSession`
objects keyed by opaque id, each wrapped in a :class:`ManagedSession` that adds a
per-session lock and a last-access timestamp.

``StreamSession`` is synchronous and not thread-safe (``look()`` mutates the
viewport while ``render()`` reads it, and ``cap.read()`` blocks). Every access to
a session therefore goes through its :class:`ManagedSession`, which serialises
reads and look-mutations under one lock. Frames are read **on demand** — there is
no always-on reader thread — and the API's route handlers run in Starlette's
thread pool, so a blocking read never stalls the event loop. The only background
task is the idle reaper (driven by the app), which calls :meth:`SessionManager.reap`.
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
    """A :class:`StreamSession` plus a lock and a last-access timestamp."""

    def __init__(self, session_id: str, session: StreamSession) -> None:
        self.id = session_id
        self._session = session
        self._lock = threading.Lock()
        self.last_access = time.monotonic()

    def touch(self) -> None:
        self.last_access = time.monotonic()

    # All of the following serialise access to the underlying session.

    def grab_view(self):
        """Read and render the next viewport frame; ``None`` when the stream ends."""
        with self._lock:
            return self._session.grab_view()

    def grab_raw(self):
        """Read the next raw (pre-reprojection) frame; ``None`` when it ends."""
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
        with self._lock:
            self._session.close()


class SessionManager:
    """A thread-safe registry of live sessions with a concurrency cap."""

    def __init__(self, *, max_sessions: int, idle_timeout: int) -> None:
        self._sessions: dict[str, ManagedSession] = {}
        self._lock = threading.Lock()
        self._max_sessions = max_sessions
        self._idle_timeout = idle_timeout

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
        managed = ManagedSession(session_id, session)
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
