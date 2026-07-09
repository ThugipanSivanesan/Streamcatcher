"""Tests for the camera profile registry and aspect-ratio auto-detect.

Pure data + lookup logic — no OpenCV, no window, no network.
"""

import pytest

from streamcatcher.config import Projection
from streamcatcher.player.profiles import (
    PRESETS,
    CameraProfile,
    available_profiles,
    get_profile,
    profile_for_frame,
)


def test_presets_cover_every_projection():
    projections = {p.projection for p in PRESETS.values()}
    assert projections == set(Projection)  # flat, equirect, equirect-180, fisheye


def test_named_360_cameras_are_equirect():
    for name in ("generic-360", "insta360-pro", "ricoh-theta"):
        assert get_profile(name).projection is Projection.EQUIRECT


def test_generic_fisheye_carries_a_lens_fov():
    profile = get_profile("generic-fisheye")
    assert profile.projection is Projection.FISHEYE
    assert profile.fisheye_fov_deg == 180.0


def test_get_profile_unknown_name_lists_valid_options():
    with pytest.raises(ValueError) as excinfo:
        get_profile("nope")
    message = str(excinfo.value)
    assert "nope" in message
    for name in available_profiles():
        assert name in message  # the error guides the user to a valid name


def test_profile_is_immutable():
    # Frozen dataclasses raise FrozenInstanceError, a subclass of AttributeError.
    with pytest.raises(AttributeError):
        get_profile("flat").name = "changed"


def test_profile_defaults_have_no_offsets():
    profile = CameraProfile("x", Projection.EQUIRECT)
    assert (profile.yaw_offset_deg, profile.pitch_offset_deg, profile.roll_offset_deg) == (
        0.0,
        0.0,
        0.0,
    )


def test_profile_for_frame_detects_2to1_as_equirect():
    profile = profile_for_frame(3840, 1920)  # classic 2:1 panorama
    assert profile.projection is Projection.EQUIRECT


def test_profile_for_frame_tolerates_near_2to1():
    assert profile_for_frame(3840, 1900).projection is Projection.EQUIRECT


def test_profile_for_frame_treats_16to9_as_flat():
    assert profile_for_frame(1920, 1080).projection is Projection.FLAT


def test_profile_for_frame_handles_zero_height():
    assert profile_for_frame(1920, 0).projection is Projection.FLAT  # no divide-by-zero
