"""Tests for the background :class:`FrameReader`.

These drive the reader directly with the ``fake_cv2`` fixture (tests/conftest.py)
so a real thread runs, but against a scripted, instant fake capture — no network,
no decoder, no window.
"""

import threading

import numpy as np

import streamcatcher.player.reader as reader_module
from streamcatcher.player.reader import FrameReader
from streamcatcher.player.session import StreamSession

URL = "rtsp://cam/stream"


class _StuckSession:
    """A session whose reads block forever after the first — a stalled stream.

    This is the scenario the reader exists for, and the one where releasing the
    capture under the thread is unsafe.
    """

    def __init__(self, release: threading.Event) -> None:
        self._release = release
        self.reads = 0

    def read_frame(self):
        self.reads += 1
        if self.reads == 1:
            return np.zeros((8, 16, 3), dtype=np.uint8)  # prime start() and return
        self._release.wait(10.0)  # blocked, exactly like a stalled cap.read()
        return None


def _open_session(fake_cv2) -> StreamSession:
    session = StreamSession(URL)
    session.open()
    return session


def test_reader_primes_a_frame_before_the_thread_runs(fake_cv2):
    fake_cv2.frames = 1_000_000  # endless, so the stream can't end before we assert
    reader = FrameReader(_open_session(fake_cv2))
    reader.start()
    try:
        assert reader.latest() is not None  # primed synchronously by start()
        assert reader.ended() is False
    finally:
        reader.stop()


def test_reader_marks_ended_and_keeps_the_last_frame(fake_cv2):
    fake_cv2.frames = 3
    reader = FrameReader(_open_session(fake_cv2))
    reader.start()
    reader._thread.join(timeout=2.0)  # the finite fake stream drains and self-stops
    try:
        assert reader.ended() is True
        assert reader.latest() is not None  # last good frame retained after the end
    finally:
        reader.stop()


def test_reader_ends_when_no_frame_ever_arrives(fake_cv2):
    fake_cv2.frames = 0  # the stream opens but yields nothing
    reader = FrameReader(_open_session(fake_cv2))
    reader.start()  # the primed read gets nothing
    try:
        assert reader.ended() is True
        assert reader.latest() is None
    finally:
        reader.stop()


def test_reader_stop_joins_the_thread(fake_cv2):
    fake_cv2.frames = 1_000_000  # effectively endless, so the reader keeps running
    reader = FrameReader(_open_session(fake_cv2))
    reader.start()
    assert reader._thread is not None and reader._thread.is_alive()

    reader.stop()

    assert reader._thread is None  # stop() joined and cleared the thread
    reader.stop()  # idempotent — safe to call again


def test_stop_reports_success_so_the_caller_may_release_the_capture(fake_cv2):
    fake_cv2.frames = 1_000_000
    reader = FrameReader(_open_session(fake_cv2))
    reader.start()

    assert reader.stop() is True  # thread exited; the capture is safe to release
    assert reader.stop() is True  # still true once already stopped


def test_stop_reports_failure_when_the_thread_stays_in_a_blocking_read(monkeypatch):
    # Keep the test fast; the real budget is _STOP_TIMEOUT seconds.
    monkeypatch.setattr(reader_module, "_STOP_TIMEOUT", 0.3)
    monkeypatch.setattr(reader_module, "_JOIN_SLICE", 0.05)
    release = threading.Event()
    reader = FrameReader(_StuckSession(release))
    reader.start()
    try:
        # The thread is parked inside read_frame(), so stop() must not claim
        # success — releasing the capture here is what could crash the process.
        assert reader.stop() is False
        assert reader._thread is not None  # still tracked, still running
    finally:
        release.set()
        reader._thread.join(timeout=5.0)
