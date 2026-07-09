"""Camera profiles — named bundles of geometry for common 360/fisheye cameras.

A :class:`CameraProfile` says how to interpret a stream: its projection (flat,
equirectangular, front-only equirect-180, or raw fisheye), any fixed mounting
orientation offsets, and — for fisheye — the lens field of view. The player and
the HTTP API pick a profile by name (``--profile ricoh-theta``) or fall back to
:func:`profile_for_frame`, which infers one from the frame's aspect ratio.

Profiles are deliberately camera-*agnostic*: the equirect reprojection is the
same regardless of make, so presets differ only in projection and orientation.
New cameras are added as data here, without touching the reprojection math.
"""

from __future__ import annotations

from dataclasses import dataclass

from streamcatcher.config import Projection


@dataclass(frozen=True)
class CameraProfile:
    """How to interpret a given camera's stream geometry.

    ``*_offset_deg`` are fixed rotations applied on top of the interactive
    look-around, so a camera mounted rotated (e.g. upside down) still reads
    level. ``fisheye_fov_deg`` is the lens field of view, used only when
    ``projection`` is :attr:`Projection.FISHEYE`.
    """

    name: str
    projection: Projection
    yaw_offset_deg: float = 0.0
    pitch_offset_deg: float = 0.0
    roll_offset_deg: float = 0.0
    fisheye_fov_deg: float = 180.0


# Aspect-ratio auto-detect: equirectangular panoramas are 2:1 (width:height).
_EQUIRECT_ASPECT = 2.0
_ASPECT_TOLERANCE = 0.05


PRESETS: dict[str, CameraProfile] = {
    "flat": CameraProfile("flat", Projection.FLAT),
    # Full-sphere equirectangular cameras. These differ only by mounting; the
    # reprojection is identical, so the offsets are the only camera-specific bit.
    "generic-360": CameraProfile("generic-360", Projection.EQUIRECT),
    "insta360-pro": CameraProfile("insta360-pro", Projection.EQUIRECT),
    "ricoh-theta": CameraProfile("ricoh-theta", Projection.EQUIRECT),
    # Front-only 180x180 hemisphere.
    "generic-180": CameraProfile("generic-180", Projection.EQUIRECT_180),
    # Single raw fisheye lens (undistorted with the equidistant model).
    "generic-fisheye": CameraProfile("generic-fisheye", Projection.FISHEYE, fisheye_fov_deg=180.0),
}


def available_profiles() -> list[str]:
    """The names of every registered preset, for help text and error messages."""
    return list(PRESETS)


def get_profile(name: str) -> CameraProfile:
    """Look up a preset by name. Raises ``ValueError`` listing the valid names."""
    try:
        return PRESETS[name]
    except KeyError:
        valid = ", ".join(available_profiles())
        raise ValueError(f"Unknown camera profile {name!r}. Available profiles: {valid}.") from None


def profile_for_frame(width: int, height: int) -> CameraProfile:
    """Infer a profile from a frame's dimensions.

    A 2:1 frame is an equirectangular 360 panorama; anything else is treated as
    ordinary flat video. Only the unambiguous 2:1 case is auto-detected — raw
    fisheye and equirect-180 need an explicit ``--profile``.
    """
    if height > 0 and abs(width / height - _EQUIRECT_ASPECT) <= _ASPECT_TOLERANCE:
        return PRESETS["generic-360"]
    return PRESETS["flat"]
