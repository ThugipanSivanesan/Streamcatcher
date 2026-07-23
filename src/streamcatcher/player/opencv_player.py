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
from streamcatcher.player.reader import FrameReader
from streamcatcher.player.reconnect import ReconnectPolicy, backoff_delays
from streamcatcher.player.recorder import Recorder, RecordError
from streamcatcher.player.session import (
    SnapshotError,
    StreamOpenError,
    StreamSession,
    _load_cv2,
)

__all__ = ["OpenCvPlayer", "SnapshotError", "StreamOpenError"]

log = logging.getLogger("streamcatcher.player.opencv")

_WINDOW_TITLE = "Streamcatcher"

# Shown when highgui is missing — i.e. opencv-python-headless is installed. That
# build ships cv2 but no window backend, so the first ``namedWindow``/``imshow``
# raises ``cv2.error`` ("rebuild the library with … support"). We translate it
# into this actionable message instead of leaking the cryptic OpenCV error.
_GUI_HELP = (
    "The live viewer needs the desktop build of OpenCV, but this looks like "
    "opencv-python-headless, which has no window support. Install the desktop "
    "build with 'pip install opencv-python' to open a window, or use the "
    "headless features instead: 'streamcatcher serve' (HTTP API) and "
    "'streamcatcher play --snapshot' both work without a GUI."
)

# waitKey timeout in milliseconds. 1ms yields to the highgui event loop each
# frame while keeping the window responsive.
_WAITKEY_MS = 1

# 'p' (photo) saves the current view. It's a single global key so it works the
# same in flat and 360 modes — 'p' is deliberately outside the W/A/S/D + '+'/'-'
# look-around bindings, which reserve 's' for tilt-down.
_SNAPSHOT_KEYS = (ord("p"), ord("P"))

# Drag-to-look sensitivity, in degrees of view rotation per pixel dragged.
# Applied to both axes; the reprojection wraps yaw and clamps pitch.
_MOUSE_SENSITIVITY = 0.2


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
        reconnect: ReconnectPolicy | None = None,
        recorder: Recorder | None = None,
        record_duration: float | None = None,
    ) -> None:
        self._session = StreamSession(url, projection)
        self._policy = reconnect or ReconnectPolicy()
        self._recorder = recorder  # None unless --record was requested
        self._recording = False  # the recorder has been started (lazily, on frame 1)
        # Optional recording length cap (seconds). The deadline is a monotonic
        # timestamp set when recording actually starts (the first frame), so the
        # limit measures recorded time, not time spent waiting for a frame.
        self._record_duration = record_duration
        self._record_deadline: float | None = None
        self._window_open = False
        self._last_frame = None  # most recently rendered frame, for the 'p' snapshot
        self._last_raw = None  # raw frame behind _last_frame, to skip re-rendering it
        self._view_dirty = False  # the viewport moved — re-render even on the same frame
        self._dragging = False  # left button held for drag-to-look (360 modes)
        self._last_mouse = (0, 0)  # last cursor position while dragging

    def play(self) -> None:
        """Open the stream and show frames until the window closes or 'q' is hit."""
        cv2 = _load_cv2()
        # Create the window before touching the network so a headless OpenCV
        # build fails fast with a clear message instead of connecting first and
        # then dying on the cryptic highgui ``cv2.error``.
        try:
            cv2.namedWindow(_WINDOW_TITLE, cv2.WINDOW_NORMAL)
        except cv2.error as exc:
            raise StreamOpenError(_GUI_HELP) from exc
        cv2.setMouseCallback(_WINDOW_TITLE, self._on_mouse)
        self._window_open = True
        reader = None
        try:
            self._session.open()
            if self._session.is_360:
                log.info(
                    "360 viewport enabled. Look around: W/A/S/D or drag the mouse, "
                    "zoom: +/-, quit: q."
                )
            log.info("Press 'p' to save a snapshot.")
            # A background thread owns the blocking reads so decode jitter can't
            # freeze the window or the look-around keys; the loop below renders
            # the freshest frame at its own cadence and stays responsive.
            reader = FrameReader(self._session)
            reader.start()
            while True:
                raw = reader.latest()
                if raw is not None:
                    new_frame = raw is not self._last_raw
                    # Re-render only when there's a new frame or the viewport moved,
                    # so an idle view doesn't re-run the (costly) 360 remap each tick.
                    if new_frame or self._view_dirty:
                        self._last_frame = self._session.render(raw)
                        cv2.imshow(_WINDOW_TITLE, self._last_frame)
                        self._view_dirty = False
                    if new_frame:
                        # Record the raw frame (the full panorama in 360), not the
                        # rendered viewport, so a recording doesn't follow the look.
                        self._record(raw)
                        self._last_raw = raw
                if self._record_duration_reached():
                    log.info("Reached the recording duration limit — stopping.")
                    break
                key = cv2.waitKey(_WAITKEY_MS) & 0xFF
                if key == ord("q"):
                    break
                self._dispatch_key(key)
                if cv2.getWindowProperty(_WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                    break  # the user closed the window
                if reader.ended():
                    reader.stop()
                    if not self._policy.enabled:
                        log.info("Stream ended or dropped.")
                        break
                    if not self._reconnect(cv2):
                        break  # the user quit while we were reconnecting
                    reader = FrameReader(self._session)  # fresh capture, fresh reader
                    reader.start()
        except KeyboardInterrupt:
            log.info("Interrupted — closing the stream.")
        finally:
            if reader is not None:
                reader.stop()
            self._stop_recording()
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
            self._view_dirty = True  # orientation changed — force a re-render

    def _on_mouse(self, event: int, x: int, y: int, flags: int, param=None) -> None:
        """Drag with the left button held to look around (360 modes only).

        Uses the grab-the-scene convention: dragging right looks left and
        dragging down looks up, as if pulling the panorama under the cursor.
        Pixel deltas are scaled to degrees by :data:`_MOUSE_SENSITIVITY` and
        handed to the session, which wraps yaw and clamps pitch.
        """
        if not self._session.is_360:
            return
        cv2 = _load_cv2()
        if event == cv2.EVENT_LBUTTONDOWN:
            self._dragging = True
            self._last_mouse = (x, y)
        elif event == cv2.EVENT_LBUTTONUP:
            self._dragging = False
        elif event == cv2.EVENT_MOUSEMOVE and self._dragging:
            last_x, last_y = self._last_mouse
            self._last_mouse = (x, y)
            self._session.look(
                pan=-(x - last_x) * _MOUSE_SENSITIVITY,
                tilt=(y - last_y) * _MOUSE_SENSITIVITY,
            )
            self._view_dirty = True  # orientation changed — force a re-render

    def stop(self) -> None:
        """Release the capture and destroy the window."""
        self._session.close()
        if self._window_open:
            _load_cv2().destroyWindow(_WINDOW_TITLE)
            self._window_open = False
        log.info("Live player: stopped.")

    def _record(self, raw) -> None:
        """Feed one raw frame to the recorder, starting it lazily on the first frame.

        Recording is best-effort: if the writer can't be opened or a write fails,
        log a warning and drop the recorder so playback keeps going.
        """
        if self._recorder is None:
            return
        try:
            if not self._recording:
                self._recorder.start(raw, self._session.capture_fps())
                self._recording = True
                if self._record_duration is not None:
                    self._record_deadline = time.monotonic() + self._record_duration
                    log.info("Recording for up to %.0fs.", self._record_duration)
            self._recorder.write(raw)
        except RecordError as exc:
            log.warning("Recording stopped: %s", exc)
            self._stop_recording()
            self._recorder = None

    def _record_duration_reached(self) -> bool:
        """Whether recording has run for its configured ``--duration`` limit.

        Always ``False`` until recording starts and when no duration was set, so
        this is a no-op for open-ended recordings and for plain playback.
        """
        return self._record_deadline is not None and time.monotonic() >= self._record_deadline

    def _stop_recording(self) -> None:
        """Finalize the recording, if any (safe to call more than once)."""
        if self._recorder is None:
            return
        try:
            self._recorder.stop()
        except Exception as exc:  # finalizing must never crash the shutdown path
            log.warning("Could not finalize the recording cleanly: %s", exc)
        finally:
            self._recording = False

    def _save_snapshot(self) -> None:
        """Write the frame currently on screen to a timestamped file (the 'p' key)."""
        if self._last_frame is None:
            return  # nothing shown yet
        filename = f"streamcatcher-snapshot-{time.strftime('%Y%m%d-%H%M%S')}.jpg"
        try:
            self._session.write_snapshot(self._last_frame, filename)
        except SnapshotError as exc:
            log.warning("Snapshot failed: %s", exc)
            return
        log.info("Snapshot saved to %s", filename)

    def snapshot(self, path: str) -> None:
        """Capture a single frame from the stream and save it to ``path`` (no window).

        Opens the stream if it isn't already, grabs one rendered frame — applying
        the configured projection, so the still matches what the window
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
