import logging

import pytest

from streamcatcher.config import Backend, Projection, Settings
from streamcatcher.player.base import Player
from streamcatcher.player.factory import get_player
from streamcatcher.player.reprojection import PITCH_STEP, YAW_STEP, ZOOM_STEP
from streamcatcher.player.stub_player import StubPlayer

# The ``fake_cv2`` fixture lives in tests/conftest.py.


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
        StubPlayer("rtsp://user:secretpass@cam.local/stream").play()
    assert "secretpass" not in caplog.text


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

    OpenCvPlayer("rtsp://user:pass@cam/stream").play()

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
        OpenCvPlayer("rtsp://user:secretpass@cam.local/stream").play()
    assert "secretpass" not in caplog.text


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

    OpenCvPlayer("rtsp://cam/stream").play()  # default projection = flat

    assert fake_cv2.remap_calls == 0
    assert fake_cv2.imshow_calls == fake_cv2.frames


def test_opencv_player_360_reprojects_each_frame(fake_cv2):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    OpenCvPlayer("rtsp://cam/stream", projection=Projection.EQUIRECT).play()

    assert fake_cv2.remap_calls == fake_cv2.frames  # every frame reprojected
    assert fake_cv2.imshow_calls == fake_cv2.frames


def test_opencv_player_360_pans_on_key(fake_cv2):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    fake_cv2.keys = [ord("d")]  # look right once, then no more keys
    player = OpenCvPlayer("rtsp://cam/stream", projection=Projection.EQUIRECT)
    player.play()

    assert player._session.state().yaw_deg == YAW_STEP  # the viewport panned right


def test_opencv_player_360_tilts_and_zooms_on_keys(fake_cv2):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    # One key per frame (default 3 frames): tilt up, tilt up, zoom in.
    fake_cv2.keys = [ord("w"), ord("w"), ord("+")]
    player = OpenCvPlayer("rtsp://cam/stream", projection=Projection.EQUIRECT)
    player.play()

    state = player._session.state()
    assert state.pitch_deg == 2 * PITCH_STEP  # tilted up twice
    assert state.hfov_deg == 100.0 - ZOOM_STEP  # zoomed in once
