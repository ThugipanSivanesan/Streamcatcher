"""Tests for the headless :class:`StreamSession` control core.

These drive the session directly — no window, no keyboard loop. The ``fake_cv2``
fixture (tests/conftest.py) injects a fake ``cv2`` so nothing touches a real
decoder or network.
"""

import logging

import pytest

from streamcatcher.config import Projection
from streamcatcher.player.reprojection import PITCH_STEP, YAW_STEP, ZOOM_STEP
from streamcatcher.player.session import StreamOpenError, StreamSession, ViewState


def test_streamsession_is_exported_from_package():
    import streamcatcher

    assert streamcatcher.StreamSession is StreamSession


def test_open_read_and_close_lifecycle(fake_cv2):
    session = StreamSession("rtsp://user:pass@cam/stream")
    assert session.is_open() is False

    session.open()
    assert session.is_open() is True
    assert fake_cv2.last_capture.url == "rtsp://user:pass@cam/stream"

    frames = [session.read_frame() for _ in range(fake_cv2.frames)]
    assert all(f is not None for f in frames)  # scripted frames delivered
    assert session.read_frame() is None  # stream ended

    session.close()
    assert session.is_open() is False
    assert fake_cv2.last_capture.release_calls == 1


def test_close_is_idempotent(fake_cv2):
    session = StreamSession("rtsp://cam/stream")
    session.open()
    session.close()
    session.close()  # should not raise
    assert fake_cv2.last_capture.release_calls == 1


def test_open_raises_when_stream_unopenable(fake_cv2):
    fake_cv2.open_ok = False
    with pytest.raises(StreamOpenError):
        StreamSession("rtsp://cam/stream").open()


def test_read_frame_before_open_raises(fake_cv2):
    with pytest.raises(RuntimeError):
        StreamSession("rtsp://cam/stream").read_frame()


def test_flat_session_render_passes_frame_through(fake_cv2):
    session = StreamSession("rtsp://cam/stream")  # projection=flat
    session.open()
    frame = session.read_frame()
    assert session.render(frame) is frame  # unchanged
    assert fake_cv2.remap_calls == 0


def test_360_session_render_reprojects(fake_cv2):
    session = StreamSession("rtsp://cam/stream", projection=Projection.EQUIRECT)
    session.open()
    session.render(session.read_frame())
    assert fake_cv2.remap_calls == 1


def test_grab_view_reads_and_renders(fake_cv2):
    session = StreamSession("rtsp://cam/stream", projection=Projection.EQUIRECT)
    session.open()
    for _ in range(fake_cv2.frames):
        assert session.grab_view() is not None
    assert session.grab_view() is None  # stream ended
    assert fake_cv2.remap_calls == fake_cv2.frames


def test_look_controls_update_state():
    session = StreamSession("rtsp://cam/stream", projection=Projection.EQUIRECT)

    session.pan_right()
    session.pan_right()
    session.pan_left()
    session.tilt_up()
    session.tilt_down()
    session.tilt_down()
    session.zoom_in()
    session.zoom_out()
    session.zoom_in()

    state = session.state()
    assert isinstance(state, ViewState)
    assert state.projection == "equirect"
    assert state.yaw_deg == YAW_STEP  # +2 -1 steps
    assert state.pitch_deg == -PITCH_STEP  # +1 -2 steps
    assert state.hfov_deg == 100.0 - ZOOM_STEP  # net zoomed in once (in, out, in)


def test_look_accepts_combined_deltas():
    session = StreamSession("rtsp://cam/stream", projection=Projection.EQUIRECT)
    session.look(pan=20.0, tilt=-10.0, zoom=15.0)
    state = session.state()
    assert state.yaw_deg == 20.0
    assert state.pitch_deg == -10.0
    assert state.hfov_deg == 100.0 + 15.0


def test_flat_session_look_is_a_noop():
    session = StreamSession("rtsp://cam/stream")  # flat
    session.pan_right()
    session.zoom_in()
    state = session.state()
    assert state.projection == "flat"
    assert state.yaw_deg is None  # no viewport in flat mode


def test_session_does_not_log_the_url(fake_cv2, caplog):
    with caplog.at_level(logging.INFO):
        StreamSession("rtsp://user:secretpass@cam.local/stream").open()
    assert "secretpass" not in caplog.text
