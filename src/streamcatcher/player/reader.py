"""Background frame reader that keeps a :class:`StreamSession`'s latest frame.

Moving the blocking ``cap.read()`` off the caller's thread is what keeps the GUI
responsive: a slow or stalled read (network jitter, packet loss, waiting for the
next keyframe) can no longer freeze the window or the look-around controls. Only
the *freshest* frame is kept — stale frames are dropped — so a live view stays
close to real time instead of drifting further behind whenever rendering can't
keep up with the stream.

The reader is deliberately unrated: the blocking ``read`` paces the loop to the
stream's own frame rate, so it neither busy-spins nor lags behind. ``cv2`` is
never imported here; all decoding goes through the injected session, so tests can
drive it with a fake.
"""

from __future__ import annotations

import threading

from streamcatcher.player.session import StreamSession


class FrameReader:
    """Own a session's blocking reads on a daemon thread, caching the latest frame.

    :meth:`start` primes one frame synchronously — so the first render already
    has something to show — then hands the remaining reads to a background
    thread. :meth:`latest` returns the newest raw frame (or ``None`` before the
    first arrives), and :meth:`ended` reports once the stream stops producing
    frames, so the caller can reconnect or exit. The cached frame is guarded by a
    lock; the session itself must not be read from another thread while a reader
    owns it (stop the reader before reconnecting or closing).
    """

    def __init__(self, session: StreamSession) -> None:
        self._session = session
        self._lock = threading.Lock()
        self._latest = None  # newest raw frame, or None until the first arrives
        self._ended = False  # the stream has stopped producing frames
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Prime one frame synchronously, then read the rest in the background."""
        self._read_once()  # so the first render isn't waiting on the thread
        self._thread = threading.Thread(target=self._loop, name="gui-frame-reader", daemon=True)
        self._thread.start()

    def latest(self):
        """The newest raw frame, or ``None`` if none has arrived yet."""
        with self._lock:
            return self._latest

    def ended(self) -> bool:
        """Whether the stream has stopped producing frames."""
        with self._lock:
            return self._ended

    def stop(self) -> None:
        """Signal the reader to stop and join it (idempotent, bounded wait)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # -- internals ------------------------------------------------------------

    def _read_once(self) -> bool:
        """Read one raw frame into the cache; ``False`` once the stream has ended."""
        try:
            frame = self._session.read_frame()
        except Exception:  # a read after the capture is torn down — treat as ended
            frame = None
        if frame is None:
            with self._lock:
                self._ended = True
            return False
        with self._lock:
            self._latest = frame
        return True

    def _loop(self) -> None:
        """Refresh the cached frame until stopped or the stream ends."""
        while not self._stop.is_set():
            if not self._read_once():
                return  # stream ended — keep the last good frame and stop reading
