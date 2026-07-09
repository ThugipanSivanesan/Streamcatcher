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
    """Play a live RTMP/RTSP stream in an OpenCV window (video only)."""

    def __init__(self, url: str) -> None:
        self._url = url  # secret: embeds credentials, so it is never logged
        self._cap = None
        self._window_open = False

    def play(self) -> None:
        """Open the stream and show frames until the window closes or 'q' is hit."""
        cv2 = _load_cv2()
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", _FFMPEG_CAPTURE_OPTIONS)

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
                cv2.imshow(_WINDOW_TITLE, frame)
                if (cv2.waitKey(_WAITKEY_MS) & 0xFF) == ord("q"):
                    break
                if cv2.getWindowProperty(_WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                    break  # the user closed the window
        except KeyboardInterrupt:
            log.info("Interrupted — closing the stream.")
        finally:
            self.stop()

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
