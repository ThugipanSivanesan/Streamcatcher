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

from streamcatcher.config import Projection
from streamcatcher.player.session import StreamOpenError, StreamSession, _load_cv2

__all__ = ["OpenCvPlayer", "StreamOpenError"]

log = logging.getLogger("streamcatcher.player.opencv")

_WINDOW_TITLE = "Streamcatcher"

# waitKey timeout in milliseconds. 1ms yields to the highgui event loop each
# frame while keeping the window responsive.
_WAITKEY_MS = 1


class OpenCvPlayer:
    """Play a live RTMP/RTSP stream in an OpenCV window (video only).

    With ``projection=Projection.EQUIRECT`` the stream is treated as a 360
    equirectangular panorama and reprojected to a flat viewport the user can
    look around with ``W``/``A``/``S``/``D`` (tilt/pan) and ``+``/``-`` (zoom).
    ``Projection.FLAT`` (the default) shows frames unchanged.
    """

    def __init__(self, url: str, projection: Projection = Projection.FLAT) -> None:
        self._session = StreamSession(url, projection)
        self._window_open = False

    def play(self) -> None:
        """Open the stream and show frames until the window closes or 'q' is hit."""
        cv2 = _load_cv2()
        self._session.open()
        if self._session.is_360:
            log.info("360 viewport enabled. Look around: W/A/S/D, zoom: +/-, quit: q.")

        cv2.namedWindow(_WINDOW_TITLE, cv2.WINDOW_NORMAL)
        self._window_open = True
        try:
            while True:
                frame = self._session.read_frame()
                if frame is None:
                    # Stream ended or dropped. Robust reconnect/backoff is a later slice.
                    log.info("Stream ended or dropped.")
                    break
                cv2.imshow(_WINDOW_TITLE, self._session.render(frame))
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

    def _dispatch_key(self, key: int) -> None:
        """Route a look-around key press to the session (no-op unless 360)."""
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

    def snapshot(self, path: str) -> None:
        """Not supported yet — snapshots arrive with a later slice."""
        raise NotImplementedError("Snapshots aren't supported yet; they arrive in a later slice.")

    def is_playing(self) -> bool:
        """Whether a stream capture is currently open."""
        return self._session.is_open()
