"""Record a live stream to disk, with two selectable backends.

:class:`OpenCvRecorder` tees the frames the player already decodes into a
``cv2.VideoWriter``. It needs no extra dependency, but re-encodes the video and
carries **no audio** — the OpenCV capture path decodes video only (see
:mod:`streamcatcher.player.opencv_player`).

:class:`FfmpegRecorder` spawns ``ffmpeg -c copy`` on its own connection to the
stream, copying the original elementary streams to disk losslessly and **with
audio**. It needs the ``ffmpeg`` binary on ``PATH``.

Both satisfy the :class:`Recorder` protocol so the player brackets either one the
same way: :meth:`~Recorder.start` when the first frame arrives, :meth:`write`
per new frame (a no-op for ffmpeg, which pulls the stream itself), and
:meth:`stop` on the way out. ``cv2`` is imported lazily via
:func:`streamcatcher.player.session._load_cv2`, so importing this module never
requires OpenCV.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Protocol, runtime_checkable

from streamcatcher.config import RecordMode, Settings
from streamcatcher.player.session import _load_cv2

log = logging.getLogger("streamcatcher.player.recorder")

# Input schemes that take the RTSP-over-TCP transport hint for ffmpeg.
_RTSP_SCHEMES = ("rtsp://",)

# How long to wait for ffmpeg to finalize the container after asking it to stop,
# before escalating to terminate()/kill(). mp4 needs a clean exit to write its
# moov atom, so we give it real time.
_FFMPEG_STOP_TIMEOUT = 10.0


class RecordError(RuntimeError):
    """Raised when a recording can't be started, written, or finalized."""


class FfmpegNotFoundError(RecordError):
    """Raised when ffmpeg-mode recording is requested but the binary is missing."""


@runtime_checkable
class Recorder(Protocol):
    """Write a live stream to a file. Backends differ; the lifecycle is shared."""

    def start(self, sample_frame, fps: float | None) -> None:
        """Open the output. ``sample_frame`` supplies width/height; ``fps`` may be None."""
        ...

    def write(self, frame) -> None:
        """Append one frame (opencv), or a no-op (ffmpeg copies the stream itself)."""
        ...

    def stop(self) -> None:
        """Finalize and close the output. Safe to call more than once."""
        ...

    def is_recording(self) -> bool:
        """Whether the output is currently open."""
        ...

    @property
    def output(self) -> str:
        """The target path (for logging)."""
        ...


class OpenCvRecorder:
    """Record decoded frames with ``cv2.VideoWriter`` — video only, re-encoded.

    Writes the **raw** decoded frame it is handed, not any reprojected viewport,
    so a 360 recording keeps the whole equirectangular panorama rather than
    following the operator's look-around. If the frame size changes mid-stream
    (e.g. the source returns at a new resolution after a reconnect), the writer
    silently drops mismatched frames, so this rolls to a fresh numbered segment
    (``name.mp4`` → ``name-002.mp4`` → …) instead of losing footage.
    """

    def __init__(self, path: str, *, fps_fallback: float = 25.0, fourcc: str = "mp4v") -> None:
        self._base_path = path
        self._fps_fallback = float(fps_fallback)
        self._fourcc = fourcc
        self._writer = None
        self._cv2 = None
        self._size: tuple[int, int] | None = None  # (width, height) of the open segment
        self._fps: float = self._fps_fallback
        self._segment = 0  # 0 → base path; 1, 2, … → -002, -003 suffixes

    @property
    def output(self) -> str:
        return self._base_path

    def is_recording(self) -> bool:
        return self._writer is not None

    def start(self, sample_frame, fps: float | None) -> None:
        self._cv2 = _load_cv2()
        self._fps = fps if fps and fps > 0 else self._fps_fallback
        self._open_segment(sample_frame)

    def write(self, frame) -> None:
        if self._writer is None:
            return
        height, width = frame.shape[:2]
        if (width, height) != self._size:
            # Resolution changed (typically after a reconnect); a VideoWriter is
            # fixed-size, so start a new segment rather than drop the frames.
            log.info(
                "Stream resolution changed to %dx%d — starting a new recording segment.",
                width,
                height,
            )
            self._open_segment(frame)
        self._writer.write(frame)

    def stop(self) -> None:
        if self._writer is not None:
            self._writer.release()
            self._writer = None
            log.info("Recording finalized: %s", self._current_path)

    # -- internals ------------------------------------------------------------

    def _next_path(self) -> str:
        """Path for the next segment: the base first, then ``-002``, ``-003``, …."""
        self._segment += 1
        if self._segment == 1:
            return self._base_path
        root, ext = os.path.splitext(self._base_path)
        return f"{root}-{self._segment:03d}{ext}"

    def _open_segment(self, frame) -> None:
        cv2 = self._cv2 or _load_cv2()
        if self._writer is not None:
            self._writer.release()
        height, width = frame.shape[:2]
        path = self._next_path()
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*self._fourcc)
        writer = cv2.VideoWriter(path, fourcc, float(self._fps), (width, height))
        if not writer.isOpened():
            raise RecordError(
                f"Could not open a video writer for {path!r}. Check the path, the "
                f"file extension, and that the {self._fourcc!r} codec is available."
            )
        self._writer = writer
        self._size = (width, height)
        self._current_path = path
        log.info("Recording to %s (%dx%d @ %.3g fps).", path, width, height, self._fps)


class FfmpegRecorder:
    """Record the original stream with ``ffmpeg -c copy`` — lossless, keeps audio.

    Runs a subprocess that opens its own connection to ``url`` and copies the
    stream to disk without re-encoding, so both video and audio are preserved.
    :meth:`write` is a no-op — ffmpeg pulls the stream itself. Because a partially
    written mp4 has no moov atom and won't play, :meth:`stop` asks ffmpeg to quit
    gracefully (``q`` on stdin) and waits before escalating.
    """

    def __init__(self, path: str, url: str) -> None:
        self._path = path
        self._url = url  # secret: embeds credentials, so it is never logged
        self._proc: subprocess.Popen | None = None

    @property
    def output(self) -> str:
        return self._path

    def is_recording(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, sample_frame, fps: float | None) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise FfmpegNotFoundError(
                "ffmpeg-mode recording needs the 'ffmpeg' binary on your PATH, but "
                "it wasn't found. Install it (e.g. 'brew install ffmpeg' or "
                "'apt install ffmpeg'), or use '--record-mode opencv' instead."
            )
        directory = os.path.dirname(self._path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
        if self._url.lower().startswith(_RTSP_SCHEMES):
            command += ["-rtsp_transport", "tcp"]
        command += ["-i", self._url, "-c", "copy", self._path]
        try:
            # stdin is a pipe so stop() can send 'q'; output is discarded to keep
            # the pipe from filling and blocking ffmpeg.
            self._proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise RecordError(f"Could not start ffmpeg: {exc}") from exc
        log.info("Recording to %s (ffmpeg -c copy).", self._path)

    def write(self, frame) -> None:
        # ffmpeg copies the stream on its own connection; nothing to push here.
        return

    def stop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        self._proc = None
        if proc.poll() is not None:
            log.info("Recording finalized: %s", self._path)
            return
        # Ask ffmpeg to quit cleanly so it finalizes the container, then escalate.
        try:
            if proc.stdin is not None:
                proc.stdin.write(b"q")
                proc.stdin.flush()
                proc.stdin.close()
        except (OSError, ValueError):
            proc.terminate()
        try:
            proc.wait(timeout=_FFMPEG_STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            log.warning("ffmpeg did not stop in time — terminating.")
            proc.terminate()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
        log.info("Recording finalized: %s", self._path)


def build_recorder(mode: RecordMode, path: str, settings: Settings, url: str) -> Recorder:
    """Build the recorder for ``mode`` writing to ``path``."""
    if mode is RecordMode.FFMPEG:
        return FfmpegRecorder(path, url)
    return OpenCvRecorder(
        path,
        fps_fallback=settings.record_fps,
        fourcc=settings.record_fourcc,
    )
