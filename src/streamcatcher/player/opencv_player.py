"""Live stream player built on OpenCV (video-only).

OpenCV's ``highgui`` creates and pumps its own native window via ``imshow`` /
``waitKey`` from a plain Python process — including on macOS — so, unlike
libVLC, we own the window without an embedded native drawable or an external
app. The tradeoff: ``cv2.VideoCapture`` decodes *video frames only*, so this
backend has no audio.

``cv2`` is imported lazily inside :meth:`OpenCvPlayer.play` so importing this
module (and running the whole test suite) never requires OpenCV to be installed;
tests inject a fake ``cv2`` instead.
"""

from __future__ import annotations

import logging
import os

from streamcatcher.config import Projection
from streamcatcher.player.reprojection import (
    PITCH_STEP,
    YAW_STEP,
    ZOOM_STEP,
    EquirectView,
)

log = logging.getLogger("streamcatcher.player.opencv")

_WINDOW_TITLE = "Streamcatcher"

# waitKey timeout in milliseconds. 1ms yields to the highgui event loop each
# frame while keeping the window responsive.
_WAITKEY_MS = 1

# Force RTSP over TCP: the default UDP transport drops/truncates high-resolution
# frames. Seeded into the env FFmpeg reads when OpenCV opens the capture.
_FFMPEG_CAPTURE_OPTIONS = "rtsp_transport;tcp"


class StreamOpenError(RuntimeError):
    """Raised when OpenCV cannot open the stream URL."""


def _load_cv2():
    """Import and return the ``cv2`` module, lazily.

    Kept out of module scope so importing this module never requires OpenCV.
    """
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - exercised via the fake in tests
        raise StreamOpenError(
            "OpenCV (cv2) is not installed. Install it with 'pip install opencv-python'."
        ) from exc
    return cv2


class OpenCvPlayer:
    """Play a live RTMP/RTSP stream in an OpenCV window (video only).

    With ``projection=Projection.EQUIRECT`` the stream is treated as a 360
    equirectangular panorama: each frame is reprojected to a flat viewport the
    user can look around with ``W``/``A``/``S``/``D`` (tilt/pan) and ``+``/``-``
    (zoom). ``Projection.FLAT`` (the default) shows frames unchanged.
    """

    def __init__(self, url: str, projection: Projection = Projection.FLAT) -> None:
        self._url = url  # secret: embeds credentials, so it is never logged
        self._cap = None
        self._window_open = False
        self._view = EquirectView() if projection is Projection.EQUIRECT else None
        self._maps = None  # cached (map_x, map_y); rebuilt when the view moves

    def play(self) -> None:
        """Open the stream and show frames until the window closes or 'q' is hit."""
        cv2 = _load_cv2()
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", _FFMPEG_CAPTURE_OPTIONS)

        if self._view is not None:
            log.info(
                "Opening live stream with OpenCV (360 viewport). "
                "Look around: W/A/S/D, zoom: +/-, quit: q."
            )
        else:
            log.info("Opening live stream with OpenCV.")
        self._cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        if not self._cap.isOpened():
            self._cap = None
            raise StreamOpenError(
                "Could not open the stream. Check the URL, network, and credentials."
            )

        cv2.namedWindow(_WINDOW_TITLE, cv2.WINDOW_NORMAL)
        self._window_open = True
        try:
            while True:
                ok, frame = self._cap.read()
                if not ok:
                    # Stream ended or dropped. Robust reconnect/backoff is Slice 3.
                    log.info("Stream ended or dropped.")
                    break
                cv2.imshow(_WINDOW_TITLE, self._render(cv2, frame))
                key = cv2.waitKey(_WAITKEY_MS) & 0xFF
                if key == ord("q"):
                    break
                if self._view is not None and self._handle_nav(key):
                    self._maps = None  # view moved — rebuild maps on the next frame
                if cv2.getWindowProperty(_WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                    break  # the user closed the window
        except KeyboardInterrupt:
            log.info("Interrupted — closing the stream.")
        finally:
            self.stop()

    def _render(self, cv2, frame):
        """Reproject ``frame`` to the current viewport in 360 mode, else pass through."""
        if self._view is None:
            return frame
        if self._maps is None:
            height, width = frame.shape[:2]
            self._maps = self._view.build_maps(width, height)
        map_x, map_y = self._maps
        return cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR)

    def _handle_nav(self, key: int) -> bool:
        """Apply a look-around key to the viewport. Returns True if the view moved."""
        view = self._view
        if key in (ord("a"), ord("A")):
            view.pan(-YAW_STEP)
        elif key in (ord("d"), ord("D")):
            view.pan(YAW_STEP)
        elif key in (ord("w"), ord("W")):
            view.tilt(PITCH_STEP)
        elif key in (ord("s"), ord("S")):
            view.tilt(-PITCH_STEP)
        elif key in (ord("+"), ord("=")):
            view.zoom(-ZOOM_STEP)  # narrower FOV = zoom in
        elif key in (ord("-"), ord("_")):
            view.zoom(ZOOM_STEP)
        else:
            return False
        return True

    def stop(self) -> None:
        """Release the capture and destroy the window."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        if self._window_open:
            _load_cv2().destroyWindow(_WINDOW_TITLE)
            self._window_open = False
        log.info("Live player: stopped.")

    def snapshot(self, path: str) -> None:
        """Not supported yet — snapshots arrive with a later slice."""
        raise NotImplementedError("Snapshots aren't supported yet; they arrive in a later slice.")

    def is_playing(self) -> bool:
        """Whether a stream capture is currently open."""
        return self._cap is not None and self._cap.isOpened()
