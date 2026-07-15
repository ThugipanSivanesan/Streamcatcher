"""Headless stream control core, shared by the GUI player and the HTTP API.

:class:`StreamSession` owns the OpenCV capture and the optional 360 viewport and
exposes *programmatic* controls — open, read a frame, render the current
viewport, look around (pan/tilt/zoom), inspect state, close — with **no window
and no keyboard loop**. The GUI player (:class:`~streamcatcher.player.opencv_player.OpenCvPlayer`)
and, later, the FastAPI server both drive the same session, so the controls live
in exactly one place.

``cv2`` is imported lazily inside :meth:`StreamSession.open`, so importing this
module never requires OpenCV; tests inject a fake ``cv2``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from streamcatcher.config import Projection
from streamcatcher.player.reprojection import (
    PITCH_STEP,
    YAW_STEP,
    ZOOM_STEP,
    EquirectView,
    _SphericalView,
)

log = logging.getLogger("streamcatcher.player.session")

# Low-latency FFmpeg capture options, seeded into the env FFmpeg reads when
# OpenCV opens the capture (pairs are ``key;value`` delimited by ``|``):
#   rtsp_transport;tcp  force RTSP over TCP — the default UDP transport
#                       drops/truncates high-resolution frames.
#   fflags;nobuffer     skip the demuxer's input buffer, so a frame reaches us
#                       as soon as it is demuxed instead of queuing — this keeps
#                       a live view close to real time.
_FFMPEG_CAPTURE_OPTIONS = "rtsp_transport;tcp|fflags;nobuffer"

# A just-opened stream's decoder can return a few empty reads before the first
# real frame arrives, so a one-shot snapshot retries this many times before it
# gives up.
_SNAPSHOT_READ_ATTEMPTS = 30


class StreamOpenError(RuntimeError):
    """Raised when OpenCV cannot open the stream URL."""


class SnapshotError(RuntimeError):
    """Raised when a snapshot frame can't be captured or written to disk."""


def _build_view(projection: Projection) -> _SphericalView | None:
    """Build the reprojection view for a projection, or ``None`` for flat video."""
    if projection is Projection.EQUIRECT:
        return EquirectView()
    return None  # Projection.FLAT — no reprojection


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


@dataclass(frozen=True)
class ViewState:
    """A snapshot of the viewport orientation (``None`` fields when not 360)."""

    projection: str
    yaw_deg: float | None = None
    pitch_deg: float | None = None
    hfov_deg: float | None = None


class StreamSession:
    """Own a live capture and an optional 360 viewport, with no window."""

    def __init__(
        self,
        url: str,
        projection: Projection = Projection.FLAT,
    ) -> None:
        self._url = url  # secret: embeds credentials, so it is never logged
        self._projection = Projection(projection)
        self._cap = None
        self._cv2 = None
        self._view = _build_view(self._projection)
        self._maps = None  # cached (map_x, map_y); rebuilt when the view moves

    @property
    def has_viewport(self) -> bool:
        """Whether this session reprojects a look-around viewport (equirect)."""
        return self._view is not None

    # Back-compat alias: the equirect viewport was originally called "360".
    # Kept for existing callers/tests.
    is_360 = has_viewport

    # -- lifecycle ------------------------------------------------------------

    def open(self) -> None:
        """Open the stream capture with low-latency options. Raises on failure."""
        cv2 = _load_cv2()
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", _FFMPEG_CAPTURE_OPTIONS)
        log.info("Opening live stream with OpenCV.")
        cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            cap.release()
            raise StreamOpenError(
                "Could not open the stream. Check the URL, network, and credentials."
            )
        # Keep only the freshest frame buffered so a slow render loop can't fall
        # progressively behind real time. Best-effort: honored by some backends,
        # ignored by others (FFmpeg leans on ``fflags;nobuffer`` above instead).
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._cv2 = cv2
        self._cap = cap

    def close(self) -> None:
        """Release the capture. Safe to call more than once."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        log.info("Stream session closed.")

    def reconnect(self) -> bool:
        """Tear down and re-open the capture, keeping the viewport orientation.

        Returns ``True`` on success, or ``False`` if the stream still can't be
        opened (so the caller can back off and retry). The viewport ``_view``
        (yaw/pitch/hfov) is left untouched, so a look-around orientation
        survives a reconnect; cached remap tables are dropped in case the
        stream returns at a different resolution.
        """
        self.close()
        self._maps = None
        try:
            self.open()
        except StreamOpenError:
            return False
        return True

    def is_open(self) -> bool:
        """Whether a stream capture is currently open."""
        return self._cap is not None and self._cap.isOpened()

    # -- frames ---------------------------------------------------------------

    def read_frame(self):
        """Read the next raw frame; returns the frame, or ``None`` when it ends."""
        if self._cap is None:
            raise RuntimeError("Session is not open.")
        ok, frame = self._cap.read()
        return frame if ok else None

    def render(self, frame):
        """Return the viewport for ``frame`` — reprojected in 360, else unchanged."""
        if self._view is None:
            return frame
        if self._maps is None:
            height, width = frame.shape[:2]
            self._maps = self._view.build_maps(width, height)
        map_x, map_y = self._maps
        return self._cv2.remap(frame, map_x, map_y, self._cv2.INTER_LINEAR)

    def grab_view(self):
        """Read and render the next viewport frame; ``None`` when the stream ends."""
        frame = self.read_frame()
        return None if frame is None else self.render(frame)

    # -- look controls --------------------------------------------------------

    def look(self, pan: float = 0.0, tilt: float = 0.0, zoom: float = 0.0) -> None:
        """Apply pan/tilt/zoom degree deltas to the viewport (a no-op when flat).

        ``zoom`` is a horizontal-FOV delta: negative narrows the view (zooms in).
        """
        if self._view is None or not (pan or tilt or zoom):
            return
        if pan:
            self._view.pan(pan)
        if tilt:
            self._view.tilt(tilt)
        if zoom:
            self._view.zoom(zoom)
        self._maps = None  # view moved — rebuild maps on the next render

    def pan_left(self) -> None:
        self.look(pan=-YAW_STEP)

    def pan_right(self) -> None:
        self.look(pan=YAW_STEP)

    def tilt_up(self) -> None:
        self.look(tilt=PITCH_STEP)

    def tilt_down(self) -> None:
        self.look(tilt=-PITCH_STEP)

    def zoom_in(self) -> None:
        self.look(zoom=-ZOOM_STEP)

    def zoom_out(self) -> None:
        self.look(zoom=ZOOM_STEP)

    def state(self) -> ViewState:
        """Current projection and (in 360) the viewport orientation."""
        if self._view is None:
            return ViewState(projection=self._projection.value)
        return ViewState(
            projection=self._projection.value,
            yaw_deg=self._view.yaw_deg,
            pitch_deg=self._view.pitch_deg,
            hfov_deg=self._view.hfov_deg,
        )

    # -- snapshots ------------------------------------------------------------

    def snapshot(self, path: str) -> None:
        """Grab the current viewport and save it to ``path`` as an image file.

        The saved image is the reprojected look-around viewport in 360 modes
        (what the viewer sees), or the raw frame when flat. Reads until a frame
        arrives — a just-opened decoder can return empty first — then writes it,
        raising :class:`SnapshotError` if no frame comes or the file can't be
        written.
        """
        frame = None
        for _ in range(_SNAPSHOT_READ_ATTEMPTS):
            frame = self.grab_view()
            if frame is not None:
                break
        if frame is None:
            raise SnapshotError("No frame to snapshot; the stream may have ended.")
        self.write_snapshot(frame, path)

    def write_snapshot(self, frame, path: str) -> None:
        """Write an already-rendered ``frame`` to ``path`` as an image file.

        Creates the parent directory if needed. Raises :class:`SnapshotError`
        when OpenCV can't encode/write the file (e.g. an unknown extension or an
        unwritable location).
        """
        cv2 = self._cv2 or _load_cv2()
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        if not cv2.imwrite(path, frame):
            raise SnapshotError(f"Could not write the snapshot to {path!r}.")
