"""Live stream GUI player — a thin OpenCV window over :class:`StreamSession`.

OpenCV's ``highgui`` creates and pumps its own native window via ``imshow`` /
``waitKey`` from a plain Python process — including on macOS — so, unlike
libVLC, we own the window without an embedded native drawable or an external
app. The tradeoff: ``cv2.VideoCapture`` decodes *video frames only*, so this
backend has no audio.

All stream and viewport logic lives in :class:`StreamSession`; this class only
adds the window, the ``waitKey`` loop, and the keyboard bindings, so the same
controls are reused by the (headless) HTTP API. ``cv2`` is imported lazily so
importing this module never requires OpenCV; tests inject a fake ``cv2``.
"""

from __future__ import annotations

import logging
import time

from streamcatcher.config import Projection
from streamcatcher.player.profiles import CameraProfile
from streamcatcher.player.reconnect import ReconnectPolicy, backoff_delays
from streamcatcher.player.session import (
    SnapshotError,
    StreamOpenError,
    StreamSession,
    _load_cv2,
)

__all__ = ["OpenCvPlayer", "SnapshotError", "StreamOpenError"]

log = logging.getLogger("streamcatcher.player.opencv")

_WINDOW_TITLE = "Streamcatcher"

# waitKey timeout in milliseconds. 1ms yields to the highgui event loop each
# frame while keeping the window responsive.
_WAITKEY_MS = 1

# 'p' (photo) saves the current view. It's a single global key so it works the
# same in flat and 360 modes — 'p' is deliberately outside the W/A/S/D + '+'/'-'
# look-around bindings, which reserve 's' for tilt-down.
_SNAPSHOT_KEYS = (ord("p"), ord("P"))


class OpenCvPlayer:
    """Play a live RTMP/RTSP stream in an OpenCV window (video only).

    With ``projection=Projection.EQUIRECT`` the stream is treated as a 360
    equirectangular panorama and reprojected to a flat viewport the user can
    look around with ``W``/``A``/``S``/``D`` (tilt/pan) and ``+``/``-`` (zoom).
    ``Projection.FLAT`` (the default) shows frames unchanged.
    """

    def __init__(
        self,
        url: str,
        projection: Projection = Projection.FLAT,
        profile: CameraProfile | None = None,
        reconnect: ReconnectPolicy | None = None,
    ) -> None:
        self._session = StreamSession(url, projection, profile)
        self._policy = reconnect or ReconnectPolicy()
        self._window_open = False
        self._last_frame = None  # most recently rendered frame, for the 'p' snapshot

    def play(self) -> None:
        """Open the stream and show frames until the window closes or 'q' is hit."""
        cv2 = _load_cv2()
        self._session.open()
        if self._session.is_360:
            log.info("360 viewport enabled. Look around: W/A/S/D, zoom: +/-, quit: q.")
        log.info("Press 'p' to save a snapshot.")

        cv2.namedWindow(_WINDOW_TITLE, cv2.WINDOW_NORMAL)
        self._window_open = True
        try:
            while True:
                frame = self._session.read_frame()
                if frame is None:
                    if not self._policy.enabled:
                        log.info("Stream ended or dropped.")
                        break
                    if not self._reconnect(cv2):
                        break  # the user quit while we were reconnecting
                    continue  # reconnected — resume reading frames
                self._last_frame = self._session.render(frame)
                cv2.imshow(_WINDOW_TITLE, self._last_frame)
                key = cv2.waitKey(_WAITKEY_MS) & 0xFF
                if key == ord("q"):
                    break
                self._dispatch_key(key)
                if cv2.getWindowProperty(_WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                    break  # the user closed the window
        except KeyboardInterrupt:
            log.info("Interrupted — closing the stream.")
        finally:
            self.stop()

    def _reconnect(self, cv2) -> bool:
        """Retry a dropped stream with exponential backoff.

        Returns ``True`` once the stream is back, or ``False`` if the user quit
        (``q`` or closed the window) while we were down. Ctrl-C propagates to
        :meth:`play`'s handler. The stream URL is never logged.
        """
        log.info("Connection lost — reconnecting…")
        for delay in backoff_delays(self._policy):
            log.info("Retrying in %.0fs…", delay)
            if self._wait_or_quit(cv2, delay):
                return False
            if self._session.reconnect():
                log.info("Reconnected.")
                return True
        return False  # pragma: no cover - backoff_delays never ends

    def _wait_or_quit(self, cv2, delay: float) -> bool:
        """Wait ``delay`` seconds, staying responsive; ``True`` if the user quit."""
        if self._quit_requested(cv2):
            return True
        time.sleep(delay)
        return self._quit_requested(cv2)

    def _quit_requested(self, cv2) -> bool:
        """Whether the user pressed 'q' or closed the window (pumps the GUI)."""
        if (cv2.waitKey(_WAITKEY_MS) & 0xFF) == ord("q"):
            return True
        return cv2.getWindowProperty(_WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1

    def _dispatch_key(self, key: int) -> None:
        """Route a key press: 'p' snapshots (any mode); W/A/S/D/+/- look around (360)."""
        if key in _SNAPSHOT_KEYS:
            self._save_snapshot()
            return
        if not self._session.is_360:
            return
        session = self._session
        actions = {
            ord("a"): session.pan_left,
            ord("A"): session.pan_left,
            ord("d"): session.pan_right,
            ord("D"): session.pan_right,
            ord("w"): session.tilt_up,
            ord("W"): session.tilt_up,
            ord("s"): session.tilt_down,
            ord("S"): session.tilt_down,
            ord("+"): session.zoom_in,
            ord("="): session.zoom_in,
            ord("-"): session.zoom_out,
            ord("_"): session.zoom_out,
        }
        action = actions.get(key)
        if action is not None:
            action()

    def stop(self) -> None:
        """Release the capture and destroy the window."""
        self._session.close()
        if self._window_open:
            _load_cv2().destroyWindow(_WINDOW_TITLE)
            self._window_open = False
        log.info("Live player: stopped.")

    def _save_snapshot(self) -> None:
        """Write the frame currently on screen to a timestamped file (the 'p' key)."""
        if self._last_frame is None:
            return  # nothing shown yet
        path = f"streamcatcher-snapshot-{time.strftime('%Y%m%d-%H%M%S')}.jpg"
        try:
            self._session.write_snapshot(self._last_frame, path)
        except SnapshotError as exc:
            log.warning("Snapshot failed: %s", exc)
            return
        log.info("Snapshot saved to %s", path)

    def snapshot(self, path: str) -> None:
        """Capture a single frame from the stream and save it to ``path`` (no window).

        Opens the stream if it isn't already, grabs one rendered frame — applying
        the configured projection/profile, so the still matches what the window
        shows — writes it, then leaves the capture as it found it. Raises
        :class:`StreamOpenError` if the stream won't open or
        :class:`SnapshotError` if no frame arrives or the file can't be written.
        """
        opened_here = not self._session.is_open()
        if opened_here:
            self._session.open()
        try:
            self._session.snapshot(path)
            log.info("Snapshot saved to %s", path)
        finally:
            if opened_here:
                self._session.close()

    def is_playing(self) -> bool:
        """Whether a stream capture is currently open."""
        return self._session.is_open()
