"""Unit tests for the recording backends.

``OpenCvRecorder`` is exercised through the fake ``cv2`` (tests/conftest.py);
``FfmpegRecorder`` is exercised with a fake ``subprocess.Popen`` and a patched
``shutil.which`` so no real ffmpeg process is ever launched.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from streamcatcher.config import RecordMode, Settings
from streamcatcher.player.recorder import (
    FfmpegNotFoundError,
    FfmpegRecorder,
    OpenCvRecorder,
    Recorder,
    RecordError,
    build_recorder,
)


def _frame(width: int = 16, height: int = 8):
    return np.zeros((height, width, 3), dtype=np.uint8)


# --- OpenCvRecorder --------------------------------------------------------


def test_opencv_recorder_satisfies_protocol():
    assert isinstance(OpenCvRecorder("out.mp4"), Recorder)


def test_opencv_recorder_opens_writer_with_frame_size_and_fps(fake_cv2):
    rec = OpenCvRecorder("out.mp4", fps_fallback=25.0, fourcc="mp4v")
    rec.start(_frame(320, 240), fps=30.0)

    writer = fake_cv2.last_video_writer
    assert writer is not None
    assert writer.path == "out.mp4"
    assert writer.size == (320, 240)  # (width, height)
    assert writer.fps == 30.0
    assert writer.fourcc == "mp4v"
    assert rec.is_recording() is True


def test_opencv_recorder_falls_back_to_default_fps_when_unknown(fake_cv2):
    rec = OpenCvRecorder("out.mp4", fps_fallback=25.0)
    rec.start(_frame(), fps=None)  # stream reported no fps

    assert fake_cv2.last_video_writer.fps == 25.0


def test_opencv_recorder_writes_and_finalizes(fake_cv2):
    rec = OpenCvRecorder("out.mp4")
    rec.start(_frame(), fps=25.0)
    rec.write(_frame())
    rec.write(_frame())

    writer = fake_cv2.last_video_writer
    assert writer.frames_written == 2
    rec.stop()
    assert writer.release_calls == 1
    assert rec.is_recording() is False


def test_opencv_recorder_stop_is_idempotent(fake_cv2):
    rec = OpenCvRecorder("out.mp4")
    rec.start(_frame(), fps=25.0)
    rec.stop()
    rec.stop()  # must not raise or double-release

    assert fake_cv2.last_video_writer.release_calls == 1


def test_opencv_recorder_write_before_start_is_noop(fake_cv2):
    rec = OpenCvRecorder("out.mp4")
    rec.write(_frame())  # nothing opened yet

    assert fake_cv2.video_writers == []


def test_opencv_recorder_raises_when_writer_wont_open(fake_cv2):
    fake_cv2.videowriter_ok = False
    rec = OpenCvRecorder("out.mp4")
    with pytest.raises(RecordError):
        rec.start(_frame(), fps=25.0)


def test_opencv_recorder_rolls_to_new_segment_on_resolution_change(fake_cv2):
    rec = OpenCvRecorder("out.mp4")
    rec.start(_frame(320, 240), fps=25.0)
    rec.write(_frame(320, 240))
    rec.write(_frame(640, 480))  # resolution changed → new segment

    assert len(fake_cv2.video_writers) == 2
    assert fake_cv2.video_writers[0].path == "out.mp4"
    assert fake_cv2.video_writers[1].path == "out-002.mp4"
    assert fake_cv2.video_writers[0].release_calls == 1  # first segment finalized
    assert fake_cv2.video_writers[1].size == (640, 480)


def test_opencv_recorder_creates_parent_directory(fake_cv2, tmp_path):
    target = tmp_path / "nested" / "out.mp4"
    rec = OpenCvRecorder(str(target))
    rec.start(_frame(), fps=25.0)

    assert (tmp_path / "nested").is_dir()


# --- FfmpegRecorder --------------------------------------------------------


class _FakeProc:
    """A stand-in for subprocess.Popen recording how it was stopped."""

    def __init__(self, running: bool = True) -> None:
        self._running = running
        self.returncode = None if running else 0
        self.stdin = _FakeStdin()
        self.terminated = False
        self.killed = False
        self.wait_calls = 0

    def poll(self):
        return None if self._running else self.returncode

    def wait(self, timeout=None):
        self.wait_calls += 1
        self._running = False
        self.returncode = 0
        return 0

    def terminate(self):
        self.terminated = True
        self._running = False

    def kill(self):
        self.killed = True
        self._running = False

    def die(self, returncode: int = 1) -> None:
        """Simulate ffmpeg exiting on its own, without being asked to stop."""
        self._running = False
        self.returncode = returncode


class _FakeStdin:
    def __init__(self) -> None:
        self.written = b""
        self.closed = False

    def write(self, data):
        self.written += data

    def flush(self):
        pass

    def close(self):
        self.closed = True


@pytest.fixture
def fake_ffmpeg(monkeypatch):
    """Patch shutil.which and subprocess.Popen so no real ffmpeg is launched."""
    import streamcatcher.player.recorder as mod

    procs: list[_FakeProc] = []
    captured: dict = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        proc = _FakeProc()
        procs.append(proc)
        return proc

    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(mod.subprocess, "Popen", fake_popen)
    return {"procs": procs, "captured": captured}


def test_ffmpeg_recorder_satisfies_protocol():
    assert isinstance(FfmpegRecorder("out.mp4", "rtsp://cam/stream"), Recorder)


def test_ffmpeg_recorder_builds_copy_command(fake_ffmpeg):
    rec = FfmpegRecorder("out.mp4", "rtsp://cam/stream")
    rec.start(None, fps=None)

    command = fake_ffmpeg["captured"]["command"]
    assert command[0] == "/usr/bin/ffmpeg"
    assert "-i" in command and "rtsp://cam/stream" in command
    assert command[command.index("-i") + 1] == "rtsp://cam/stream"
    # lossless copy of both streams
    assert command[command.index("-c") + 1] == "copy"
    assert command[-1] == "out.mp4"
    # RTSP-over-TCP hint for an rtsp source
    assert "-rtsp_transport" in command
    assert rec.is_recording() is True


def test_ffmpeg_recorder_omits_rtsp_transport_for_rtmp(fake_ffmpeg):
    rec = FfmpegRecorder("out.mp4", "rtmp://cam/stream")
    rec.start(None, fps=None)

    assert "-rtsp_transport" not in fake_ffmpeg["captured"]["command"]


def test_ffmpeg_recorder_write_is_noop(fake_ffmpeg):
    rec = FfmpegRecorder("out.mp4", "rtsp://cam/stream")
    rec.start(None, fps=None)
    rec.write(_frame())  # ffmpeg pulls the stream itself; must be a no-op

    assert fake_ffmpeg["procs"][0].stdin.written == b""  # no frame data pushed


def test_ffmpeg_recorder_stops_gracefully(fake_ffmpeg):
    rec = FfmpegRecorder("out.mp4", "rtsp://cam/stream")
    rec.start(None, fps=None)
    rec.stop()

    proc = fake_ffmpeg["procs"][0]
    assert proc.stdin.written == b"q"  # asked ffmpeg to quit cleanly (finalize mp4)
    assert proc.wait_calls >= 1
    assert proc.killed is False  # graceful, not force-killed
    assert rec.is_recording() is False


def test_ffmpeg_recorder_stop_is_idempotent(fake_ffmpeg):
    rec = FfmpegRecorder("out.mp4", "rtsp://cam/stream")
    rec.start(None, fps=None)
    rec.stop()
    rec.stop()  # must not raise


def test_ffmpeg_recorder_raises_when_binary_missing(monkeypatch):
    import streamcatcher.player.recorder as mod

    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    rec = FfmpegRecorder("out.mp4", "rtsp://cam/stream")
    with pytest.raises(FfmpegNotFoundError):
        rec.start(None, fps=None)


def test_ffmpeg_recorder_does_not_expose_url_in_output_property(fake_ffmpeg):
    rec = FfmpegRecorder("out.mp4", "rtsp://user:secret@cam/stream")
    assert "secret" not in rec.output


# --- build_recorder --------------------------------------------------------


# --- FfmpegRecorder: a subprocess that dies on its own ----------------------
#
# ffmpeg holds its own connection, so it can fail (bad codec for the container,
# its own auth failure) while playback looks perfectly healthy. It used to do so
# silently: stderr went to DEVNULL and nothing polled the process, so the user
# recorded nothing and stop() still logged "Recording finalized".


def test_ffmpeg_recorder_captures_stderr_instead_of_discarding_it(fake_ffmpeg):
    import subprocess

    rec = FfmpegRecorder("out.mp4", "rtsp://cam/stream")
    rec.start(None, fps=None)

    stderr = fake_ffmpeg["captured"]["kwargs"]["stderr"]
    assert stderr is not subprocess.DEVNULL  # discarding it is what lost the reason
    assert hasattr(stderr, "fileno")  # a real file ffmpeg can be pointed at


def test_ffmpeg_recorder_write_raises_once_the_process_has_died(fake_ffmpeg):
    rec = FfmpegRecorder("out.mp4", "rtsp://cam/stream")
    rec.start(None, fps=None)
    rec.write(_frame())  # still running — no complaint

    fake_ffmpeg["procs"][0].die(returncode=1)

    with pytest.raises(RecordError) as excinfo:
        rec.write(_frame())
    assert "1" in str(excinfo.value)  # surfaces the exit code
    assert "out.mp4" in str(excinfo.value)


def test_ffmpeg_recorder_write_quotes_ffmpeg_stderr_in_the_error(fake_ffmpeg):
    rec = FfmpegRecorder("out.mp4", "rtsp://cam/stream")
    rec.start(None, fps=None)
    # Whatever ffmpeg printed before dying is the only clue to *why*.
    fake_ffmpeg["captured"]["kwargs"]["stderr"].write(b"Invalid data found when processing input")
    fake_ffmpeg["procs"][0].die(returncode=1)

    with pytest.raises(RecordError) as excinfo:
        rec.write(_frame())
    assert "Invalid data found when processing input" in str(excinfo.value)


def test_ffmpeg_recorder_reports_a_dead_process_only_once(fake_ffmpeg):
    rec = FfmpegRecorder("out.mp4", "rtsp://cam/stream")
    rec.start(None, fps=None)
    fake_ffmpeg["procs"][0].die(returncode=1)

    with pytest.raises(RecordError):
        rec.write(_frame())
    # The player drops the recorder after the first RecordError, but a second
    # write must not raise again (nor a stop() re-report it) — see below.
    rec.write(_frame())
    assert rec.is_recording() is False


def test_ffmpeg_recorder_stop_does_not_claim_success_after_a_crash(fake_ffmpeg, caplog):
    rec = FfmpegRecorder("out.mp4", "rtsp://cam/stream")
    rec.start(None, fps=None)
    fake_ffmpeg["captured"]["kwargs"]["stderr"].write(b"Could not write header")
    fake_ffmpeg["procs"][0].die(returncode=1)

    with caplog.at_level(logging.ERROR):
        rec.stop()

    assert "Recording finalized" not in caplog.text  # the old, false reassurance
    assert "Could not write header" in caplog.text


def test_ffmpeg_recorder_stop_still_reports_success_on_a_clean_exit(fake_ffmpeg, caplog):
    rec = FfmpegRecorder("out.mp4", "rtsp://cam/stream")
    rec.start(None, fps=None)
    fake_ffmpeg["procs"][0].die(returncode=0)  # exited cleanly, e.g. source ended

    with caplog.at_level(logging.INFO):
        rec.stop()

    assert "Recording finalized" in caplog.text


def test_build_recorder_selects_opencv():
    settings = Settings(record_fps=15.0, record_fourcc="XVID")
    rec = build_recorder(RecordMode.OPENCV, "out.mp4", settings, "rtsp://cam/stream")
    assert isinstance(rec, OpenCvRecorder)


def test_build_recorder_selects_ffmpeg():
    rec = build_recorder(RecordMode.FFMPEG, "out.mp4", Settings(), "rtsp://cam/stream")
    assert isinstance(rec, FfmpegRecorder)
