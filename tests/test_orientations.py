"""Tests for the four-orientation (front/right/back/left) split.

The reprojection math is verified in pure NumPy (no OpenCV) by checking where
each view's centre pixel samples the source panorama; the wiring through the
session and player uses the fake ``cv2`` (tests/conftest.py).
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from streamcatcher.config import Backend, Settings
from streamcatcher.player.factory import get_player
from streamcatcher.player.orientations import (
    ORIENTATIONS,
    OrientationError,
    split_equirect,
)
from streamcatcher.player.reprojection import EquirectView
from streamcatcher.player.session import StreamSession


def _frame(width: int = 200, height: int = 100):
    return np.zeros((height, width, 3), dtype=np.uint8)


# --- orientation geometry (pure NumPy) -------------------------------------


def test_orientations_are_the_four_cardinals_in_order():
    assert list(ORIENTATIONS.keys()) == ["front", "right", "back", "left"]
    assert ORIENTATIONS == {"front": 0.0, "right": 90.0, "back": 180.0, "left": -90.0}


def test_each_view_centre_samples_the_expected_heading():
    # For a 90° HFOV view at yaw Y, the centre ray points at longitude Y, which
    # maps to column (Y/360 + 0.5) * width in the equirect source. This pins that
    # front/right/back/left actually aim where their names say.
    size = 101  # odd so there is an exact centre pixel
    src_w, src_h = 360, 180
    expected_fraction = {"front": 0.5, "right": 0.75, "back": 1.0, "left": 0.25}
    centre = size // 2
    for name, yaw in ORIENTATIONS.items():
        view = EquirectView(
            out_width=size, out_height=size, hfov_deg=90.0, yaw_deg=yaw, pitch_deg=0.0
        )
        map_x, map_y = view.build_maps(src_w, src_h)
        assert map_x[centre, centre] / src_w == pytest.approx(expected_fraction[name], abs=1e-3)
        # Pitch 0 → the centre row samples the equator, half-way down the frame.
        assert map_y[centre, centre] / src_h == pytest.approx(0.5, abs=1e-3)


# --- split_equirect --------------------------------------------------------


def test_split_equirect_returns_four_named_views(fake_cv2):
    views = split_equirect(_frame(), fake_cv2, size=64)

    assert list(views.keys()) == ["front", "right", "back", "left"]
    assert fake_cv2.remap_calls == 4  # one reprojection per view


def test_split_equirect_raises_on_no_frame(fake_cv2):
    with pytest.raises(OrientationError):
        split_equirect(None, fake_cv2)


# --- StreamSession ---------------------------------------------------------


def test_session_split_orientations_reads_and_splits(fake_cv2):
    session = StreamSession("rtsp://cam/stream")
    session.open()
    views = session.split_orientations(size=64)

    assert set(views) == {"front", "right", "back", "left"}


def test_session_split_orientations_raises_without_a_frame(fake_cv2):
    fake_cv2.frames = 0  # the stream never yields a frame
    session = StreamSession("rtsp://cam/stream")
    session.open()
    with pytest.raises(OrientationError):
        session.split_orientations(size=64)


def test_session_write_orientations_writes_named_files(fake_cv2, tmp_path):
    session = StreamSession("rtsp://cam/stream")
    session.open()
    views = session.split_orientations(size=64)
    paths = session.write_orientations(views, str(tmp_path))

    assert set(paths) == {"front", "right", "back", "left"}
    assert fake_cv2.imwrite_calls == 4
    names = sorted(os.path.basename(path) for path, _ in fake_cv2.written)
    assert names == ["back.jpg", "front.jpg", "left.jpg", "right.jpg"]


def test_session_write_orientations_raises_on_write_failure(fake_cv2, tmp_path):
    fake_cv2.imwrite_ok = False
    session = StreamSession("rtsp://cam/stream")
    session.open()
    views = session.split_orientations(size=64)
    with pytest.raises(OrientationError):
        session.write_orientations(views, str(tmp_path))


# --- OpenCvPlayer ----------------------------------------------------------


def test_opencv_player_save_orientations_writes_four_files(fake_cv2, tmp_path):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    player = OpenCvPlayer("rtsp://cam/stream", orientation_size=64)
    player.save_orientations(str(tmp_path))

    assert fake_cv2.imwrite_calls == 4
    assert fake_cv2.last_capture.release_calls == 1  # opened just for the split, then released
    assert player.is_playing() is False
    assert fake_cv2.imshow_calls == 0  # no window


def test_opencv_player_save_orientations_works_headless(fake_cv2, tmp_path):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    # No window is opened, so it must work on a headless OpenCV build.
    fake_cv2.gui_available = False
    OpenCvPlayer("rtsp://cam/stream", orientation_size=64).save_orientations(str(tmp_path))

    assert fake_cv2.imwrite_calls == 4
    assert fake_cv2.named_windows == []


def test_opencv_player_save_orientations_raises_when_stream_unopenable(fake_cv2, tmp_path):
    from streamcatcher.player.opencv_player import OpenCvPlayer, StreamOpenError

    fake_cv2.open_ok = False
    with pytest.raises(StreamOpenError):
        OpenCvPlayer("rtsp://cam/stream").save_orientations(str(tmp_path))
    assert fake_cv2.imwrite_calls == 0


def test_opencv_player_save_orientations_does_not_log_the_url(fake_cv2, tmp_path, caplog):
    import logging

    from streamcatcher.player.opencv_player import OpenCvPlayer

    with caplog.at_level(logging.INFO):
        OpenCvPlayer("rtsp://user:changeme@cam/stream", orientation_size=64).save_orientations(
            str(tmp_path)
        )
    assert "changeme" not in caplog.text


# --- factory + stub --------------------------------------------------------


def test_factory_passes_orientation_settings_to_player(fake_cv2):
    from streamcatcher.player.opencv_player import OpenCvPlayer

    settings = Settings(
        stream_url="rtsp://cam/stream",
        backend=Backend.OPENCV,
        orientation_size=512,
        orientation_hfov_deg=100.0,
    )
    player = get_player(settings)
    assert isinstance(player, OpenCvPlayer)
    assert player._orientation_size == 512
    assert player._orientation_hfov_deg == 100.0


def test_stub_player_save_orientations_records_the_request():
    from streamcatcher.player.stub_player import StubPlayer

    player = StubPlayer("rtsp://cam/stream")
    player.save_orientations("out_dir")
    assert player.last_orientations == "out_dir"
