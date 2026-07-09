"""Unit tests for the pure-NumPy equirectangular reprojection math.

These exercise :class:`EquirectView` directly — no OpenCV, no window, no
network — so the geometry is pinned deterministically.
"""

import numpy as np
import pytest

from streamcatcher.player.reprojection import (
    PITCH_STEP,
    YAW_STEP,
    ZOOM_STEP,
    EquirectView,
    FisheyeView,
)

# Odd dimensions so an exact center pixel exists at index (H//2, W//2).
_SRC_W, _SRC_H = 3840, 1920


def _center(view):
    map_x, map_y = view.build_maps(_SRC_W, _SRC_H)
    r, c = view.out_height // 2, view.out_width // 2
    return float(map_x[r, c]), float(map_y[r, c])


def test_maps_have_output_shape():
    view = EquirectView(out_width=640, out_height=480)
    map_x, map_y = view.build_maps(_SRC_W, _SRC_H)
    assert map_x.shape == (480, 640)
    assert map_y.shape == (480, 640)
    assert map_x.dtype == np.float32
    assert map_y.dtype == np.float32


def test_forward_view_samples_source_center():
    # Looking straight ahead (yaw=pitch=0), the center pixel maps to the
    # middle of the equirectangular frame.
    x, y = _center(EquirectView(out_width=101, out_height=101))
    assert x == np.float32(_SRC_W / 2)
    assert y == np.float32(_SRC_H / 2)


def test_yaw_ninety_shifts_a_quarter_width():
    # Panning 90 deg right moves the sampled column a quarter of the way
    # around the panorama.
    x, _ = _center(EquirectView(out_width=101, out_height=101, yaw_deg=90.0))
    assert x == np.float32(0.75 * _SRC_W)


def test_positive_pitch_looks_up():
    # Positive pitch raises the view: the sampled row moves above the equator.
    _, y = _center(EquirectView(out_width=101, out_height=101, pitch_deg=30.0))
    assert y < _SRC_H / 2


def test_pan_wraps_into_signed_range():
    view = EquirectView(yaw_deg=170.0)
    view.pan(YAW_STEP * 4)  # 170 + 20 -> 190 -> wraps to -170
    assert view.yaw_deg == -170.0


def test_tilt_clamps_at_the_pole():
    view = EquirectView(pitch_deg=88.0)
    for _ in range(10):
        view.tilt(PITCH_STEP)
    assert view.pitch_deg == 89.0


def test_zoom_clamps_field_of_view():
    view = EquirectView(hfov_deg=100.0)
    for _ in range(100):
        view.zoom(-ZOOM_STEP)
    assert view.hfov_deg == 30.0
    for _ in range(100):
        view.zoom(ZOOM_STEP)
    assert view.hfov_deg == 120.0


# --- equirect-180 (front-only hemisphere) ----------------------------------


def test_equirect180_forward_still_samples_center():
    view = EquirectView(out_width=101, out_height=101, h_coverage_deg=180.0)
    x, y = _center(view)
    assert x == np.float32(_SRC_W / 2)
    assert y == np.float32(_SRC_H / 2)


def test_equirect180_has_double_horizontal_sensitivity():
    # A 180-wide frame packs the same panorama into half the longitude, so a
    # 45 deg pan reaches the quarter-width that a full 360 needs 90 deg for.
    view180 = EquirectView(out_width=101, out_height=101, h_coverage_deg=180.0, yaw_deg=45.0)
    x180, _ = _center(view180)
    x360, _ = _center(EquirectView(out_width=101, out_height=101, yaw_deg=45.0))
    assert x180 == np.float32(0.75 * _SRC_W)
    assert x360 == np.float32(0.625 * _SRC_W)  # (45/360)+0.5


# --- fisheye (single equidistant lens) -------------------------------------

# A square source keeps the fisheye circle radius equal on both axes.
_FISH = 200


def _fish_center(view):
    map_x, map_y = view.build_maps(_FISH, _FISH)
    r, c = view.out_height // 2, view.out_width // 2
    return float(map_x[r, c]), float(map_y[r, c])


def test_fisheye_forward_samples_image_center():
    x, y = _fish_center(FisheyeView(out_width=101, out_height=101, fov_deg=180.0))
    assert x == np.float32(_FISH / 2)
    assert y == np.float32(_FISH / 2)


def test_fisheye_90deg_pan_reaches_circle_edge():
    # With a 180 deg lens, looking 90 deg sideways lands on the circle rim:
    # the sampled column reaches the image edge, on the equator (mid row).
    x, y = _fish_center(FisheyeView(out_width=101, out_height=101, fov_deg=180.0, yaw_deg=90.0))
    assert x == pytest.approx(_FISH, abs=1e-3)  # right rim
    assert y == pytest.approx(_FISH / 2, abs=1e-3)


def test_fisheye_beyond_fov_is_masked_off_frame():
    # Looking backwards is outside a 180 deg lens — those pixels map off-frame
    # (negative) so cv2.remap renders them as the black border.
    x, y = _fish_center(FisheyeView(out_width=101, out_height=101, fov_deg=180.0, yaw_deg=180.0))
    assert x < 0
    assert y < 0


def test_fisheye_maps_are_float32_with_output_shape():
    map_x, map_y = FisheyeView(out_width=64, out_height=48).build_maps(_FISH, _FISH)
    assert map_x.shape == (48, 64)
    assert map_x.dtype == np.float32 and map_y.dtype == np.float32


# --- mounting orientation offsets ------------------------------------------


def test_yaw_offset_folds_into_the_pan():
    # A fixed 90 deg yaw offset with no interactive pan samples the same column
    # as a 90 deg interactive pan with no offset.
    x_offset, _ = _center(EquirectView(out_width=101, out_height=101, yaw_offset_deg=90.0))
    x_pan, _ = _center(EquirectView(out_width=101, out_height=101, yaw_deg=90.0))
    assert x_offset == x_pan == np.float32(0.75 * _SRC_W)


def test_roll_offset_flips_up_and_down():
    # Roll the mount 180 deg and a pixel that looked up now looks down: the row
    # it samples crosses to the other side of the equator.
    w = h = 101
    top_row, mid_col = 0, w // 2
    up = EquirectView(out_width=w, out_height=h).build_maps(_SRC_W, _SRC_H)[1][top_row, mid_col]
    rolled = EquirectView(out_width=w, out_height=h, roll_offset_deg=180.0).build_maps(
        _SRC_W, _SRC_H
    )[1][top_row, mid_col]
    assert up < _SRC_H / 2  # top pixel looks above the equator
    assert rolled > _SRC_H / 2  # after a 180 roll it looks below


def test_zero_roll_offset_keeps_equirect_numerics_identical():
    # The refactor must not perturb the original full-360 maps.
    plain = EquirectView(out_width=64, out_height=48, yaw_deg=30.0, pitch_deg=10.0)
    mx, my = plain.build_maps(_SRC_W, _SRC_H)
    explicit = EquirectView(
        out_width=64,
        out_height=48,
        yaw_deg=30.0,
        pitch_deg=10.0,
        roll_offset_deg=0.0,
        yaw_offset_deg=0.0,
        pitch_offset_deg=0.0,
    )
    ex, ey = explicit.build_maps(_SRC_W, _SRC_H)
    assert np.array_equal(mx, ex) and np.array_equal(my, ey)
