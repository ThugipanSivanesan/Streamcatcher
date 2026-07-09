import logging

import pytest

from streamcatcher.config import Backend, Projection, Settings
from streamcatcher.player.base import Player
from streamcatcher.player.factory import get_player
from streamcatcher.player.reconnect import ReconnectPolicy
from streamcatcher.player.reprojection import PITCH_STEP, YAW_STEP, ZOOM_STEP
from streamcatcher.player.stub_player import StubPlayer

# The ``fake_cv2`` fixture lives in tests/conftest.py.

# Auto-reconnect is on by default, so a finite fake stream would retry forever.
# Frame-display tests that just want the scripted frames shown once opt out with
# this policy; the reconnect behaviour has its own tests further down.
_NO_RETRY = ReconnectPolicy(enabled=False)


def test_factory_returns_stub_by_default():
    settings = Settings(stream_url="rtsp://cam.local/stream")
    assert isinstance(get_player(settings), StubPlayer)


def test_factory_requires_a_url(monkeypatch):
    monkeypatch.delenv("STREAMCATCHER_STREAM_URL", raising=False)
    with pytest.raises(ValueError):
        get_player(Settings())


def test_stub_satisfies_player_protocol():
    assert isinstance(StubPlayer("rtsp://cam/stream"), Player)


def test_stub_player_lifecycle():
    player = StubPlayer("rtsp://cam/stream")
    assert player.is_playing() is False

    player.play()
    assert player.is_playing() is True

    player.snapshot("shot.png")
    assert player.last_snapshot == "shot.png"

    player.stop()
    assert player.is_playing() is False


def test_stub_player_does_not_log_the_url(caplog):
    with caplog.at_level(logging.INFO):
        StubPlayer("rtsp://user:changeme@cam.local/stream").play()
    assert "changeme" not in caplog.text


# --- Live OpenCV backend ---------------------------------------------------
#
# The live player opens the stream with OpenCV and shows frames in a window it
# owns. The ``fake_cv2`` fixture (tests/conftest.py) injects a fake ``cv2`` whose
# capture yields scripted frames and whose window calls are spies, so these tests
# never touch a real decoder, window, or network and stay offline/headless.


def test_factory_returns_opencv_player_for_opencv_backend():
    from streamcatcher.player.opencv_player import OpenCvPlayer

    settings = Settings(stream_url="rtsp://cam/stream", backend=Backend.OPENCV)
    assert isinstance(get_player(settings), OpenCvPlayer)


def test_opencv_player_satisfies_player_protocol():
    from streamcatcher.player.opencv_player import OpenCvPlayer

    assert isinstance(OpenCvPlayer("rtsp://cam/stream"), Player)


def test_opencv_player_play_opens_stream_and_shows_frames(fake_cv2):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    OpenCvPlayer("rtsp://user:pass@cam/stream", reconnect=_NO_RETRY).play()

    cap = fake_cv2.last_capture
    assert cap is not None
    assert cap.url == "rtsp://user:pass@cam/stream"
    assert fake_cv2.imshow_calls == fake_cv2.frames  # every frame was shown
    assert cap.release_calls == 1  # capture released on the way out
    assert fake_cv2.destroyed_windows == ["Streamcatcher"]  # window torn down


def test_opencv_player_play_quits_on_q_key(fake_cv2):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    fake_cv2.keys = [ord("q")]
    OpenCvPlayer("rtsp://cam/stream").play()

    assert fake_cv2.imshow_calls == 1  # stopped after the first frame


def test_opencv_player_play_stops_when_window_closed(fake_cv2):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    fake_cv2.window_visible = 0  # user closed the window
    OpenCvPlayer("rtsp://cam/stream").play()

    assert fake_cv2.imshow_calls == 1
    assert fake_cv2.last_capture.release_calls == 1


def test_opencv_player_play_raises_when_stream_unopenable(fake_cv2):
    from streamcatcher.player.opencv_player import OpenCvPlayer, StreamOpenError

    fake_cv2.open_ok = False
    with pytest.raises(StreamOpenError):
        OpenCvPlayer("rtsp://cam/stream").play()


def test_opencv_player_is_playing_reflects_capture(fake_cv2):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    player = OpenCvPlayer("rtsp://cam/stream")
    assert player.is_playing() is False  # nothing opened yet

    player._session.open()
    assert player.is_playing() is True

    player._session.close()  # simulate the stream closing
    assert player.is_playing() is False


def test_opencv_player_snapshot_not_supported_yet():
    from streamcatcher.player.opencv_player import OpenCvPlayer

    with pytest.raises(NotImplementedError):
        OpenCvPlayer("rtsp://cam/stream").snapshot("shot.png")


def test_opencv_player_does_not_log_the_url(fake_cv2, caplog):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    with caplog.at_level(logging.INFO):
        OpenCvPlayer("rtsp://user:changeme@cam.local/stream", reconnect=_NO_RETRY).play()
    assert "changeme" not in caplog.text


# --- 360 equirectangular viewport ------------------------------------------


def test_factory_passes_projection_to_opencv_player():
    from streamcatcher.player.opencv_player import OpenCvPlayer

    settings = Settings(
        stream_url="rtsp://cam/stream",
        backend=Backend.OPENCV,
        projection=Projection.EQUIRECT,
    )
    player = get_player(settings)
    assert isinstance(player, OpenCvPlayer)
    assert player._session.is_360  # 360 viewport enabled


def test_factory_resolves_named_profile():
    from streamcatcher.player.opencv_player import OpenCvPlayer

    settings = Settings(
        stream_url="rtsp://cam/stream", backend=Backend.OPENCV, profile="generic-fisheye"
    )
    player = get_player(settings)
    assert isinstance(player, OpenCvPlayer)
    assert player._session.state().projection == "fisheye"  # profile drove the view


def test_factory_rejects_unknown_profile():
    settings = Settings(stream_url="rtsp://cam/stream", backend=Backend.OPENCV, profile="bogus")
    with pytest.raises(ValueError):
        get_player(settings)


def test_opencv_player_flat_does_not_reproject(fake_cv2):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    OpenCvPlayer("rtsp://cam/stream", reconnect=_NO_RETRY).play()  # default projection = flat

    assert fake_cv2.remap_calls == 0
    assert fake_cv2.imshow_calls == fake_cv2.frames


def test_opencv_player_360_reprojects_each_frame(fake_cv2):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    OpenCvPlayer("rtsp://cam/stream", projection=Projection.EQUIRECT, reconnect=_NO_RETRY).play()

    assert fake_cv2.remap_calls == fake_cv2.frames  # every frame reprojected
    assert fake_cv2.imshow_calls == fake_cv2.frames


def test_opencv_player_360_pans_on_key(fake_cv2):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    fake_cv2.keys = [ord("d")]  # look right once, then no more keys
    player = OpenCvPlayer("rtsp://cam/stream", projection=Projection.EQUIRECT, reconnect=_NO_RETRY)
    player.play()

    assert player._session.state().yaw_deg == YAW_STEP  # the viewport panned right


def test_opencv_player_360_tilts_and_zooms_on_keys(fake_cv2):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    # One key per frame (default 3 frames): tilt up, tilt up, zoom in.
    fake_cv2.keys = [ord("w"), ord("w"), ord("+")]
    player = OpenCvPlayer("rtsp://cam/stream", projection=Projection.EQUIRECT, reconnect=_NO_RETRY)
    player.play()

    state = player._session.state()
    assert state.pitch_deg == 2 * PITCH_STEP  # tilted up twice
    assert state.hfov_deg == 100.0 - ZOOM_STEP  # zoomed in once


# --- auto-reconnect with backoff -------------------------------------------
#
# Reconnect retries forever, so a finite fake stream only stops on a quit
# signal. ``no_sleep`` makes the backoff waits instant; tests terminate either
# by "closing the window" after enough captures or by scripting a 'q' key.

_FAST_RETRY = ReconnectPolicy(base_delay=1.0, factor=2.0, max_delay=5.0)


@pytest.fixture
def no_sleep(monkeypatch):
    """Make backoff waits instant so retry-forever tests run fast."""
    import streamcatcher.player.opencv_player as mod

    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)


def test_opencv_player_reconnects_and_resumes_after_a_drop(fake_cv2, no_sleep):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    fake_cv2.frames = 1  # one frame per capture, then a "drop"
    fake_cv2.close_window_after_captures = 1  # quit once the reconnect capture opens

    OpenCvPlayer("rtsp://cam/stream", reconnect=_FAST_RETRY).play()

    assert len(fake_cv2.captures) == 2  # original + one reconnect
    assert fake_cv2.imshow_calls == 2  # a frame shown from each capture
    assert fake_cv2.captures[0].release_calls == 1  # dropped capture released


def test_opencv_player_retries_through_failed_opens_then_reconnects(fake_cv2, no_sleep):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    fake_cv2.frames = 1
    # open #1 works, the next two reconnects fail, the fourth succeeds.
    fake_cv2.open_results = [True, False, False, True]
    fake_cv2.close_window_after_captures = 3  # quit once the 4th capture opens

    OpenCvPlayer("rtsp://cam/stream", reconnect=_FAST_RETRY).play()

    assert len(fake_cv2.captures) == 4  # one good + two failed + one good
    assert fake_cv2.imshow_calls == 2  # frames from the two working captures


def test_opencv_player_quits_during_backoff_without_reconnecting(fake_cv2, no_sleep):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    fake_cv2.frames = 1
    # First waitKey (frame loop) is a no-op key; the second (during the backoff
    # wait) is 'q', so the user quits before any reconnect is attempted.
    fake_cv2.keys = [ord("x"), ord("q")]

    OpenCvPlayer("rtsp://cam/stream", reconnect=_FAST_RETRY).play()

    assert len(fake_cv2.captures) == 1  # no reconnect capture was opened
    assert fake_cv2.imshow_calls == 1


def test_opencv_player_no_reconnect_exits_on_drop(fake_cv2, caplog):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    fake_cv2.frames = 1
    with caplog.at_level(logging.INFO):
        OpenCvPlayer("rtsp://cam/stream", reconnect=ReconnectPolicy(enabled=False)).play()

    assert len(fake_cv2.captures) == 1  # gave up on the first drop
    assert fake_cv2.imshow_calls == 1
    assert "Stream ended or dropped." in caplog.text


def test_opencv_player_reconnect_does_not_log_the_url(fake_cv2, no_sleep, caplog):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    fake_cv2.frames = 1
    fake_cv2.close_window_after_captures = 1
    with caplog.at_level(logging.INFO):
        OpenCvPlayer("rtsp://user:changeme@cam.local/stream", reconnect=_FAST_RETRY).play()

    assert "changeme" not in caplog.text
    assert "Reconnected." in caplog.text  # the reconnect path actually ran


def test_factory_builds_reconnect_policy_from_settings(fake_cv2):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    settings = Settings(
        stream_url="rtsp://cam/stream",
        backend=Backend.OPENCV,
        reconnect_enabled=False,
        reconnect_base_delay=2.5,
        reconnect_backoff_factor=3.0,
        reconnect_max_delay=45.0,
    )
    player = get_player(settings)
    assert isinstance(player, OpenCvPlayer)
    assert player._policy == ReconnectPolicy(
        enabled=False, base_delay=2.5, factor=3.0, max_delay=45.0
    )
