"""Tests for the background :class:`FrameReader`.

These drive the reader directly with the ``fake_cv2`` fixture (tests/conftest.py)
so a real thread runs, but against a scripted, instant fake capture — no network,
no decoder, no window.
"""

from streamcatcher.player.reader import FrameReader
from streamcatcher.player.session import StreamSession

URL = "rtsp://cam/stream"


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
