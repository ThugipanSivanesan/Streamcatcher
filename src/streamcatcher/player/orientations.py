"""Split a 360 equirectangular frame into four cardinal views.

A single equirectangular frame holds the whole sphere. This module aims the same
virtual pinhole camera used for the interactive viewport
(:class:`~streamcatcher.player.reprojection.EquirectView`) at four fixed
headings — **front, right, back, left** — and returns one flat, undistorted
image per heading. With the default 90° horizontal field of view the four views
tile the full 360° horizon edge-to-edge with no overlap and no gap, so together
they are a complete flat "unwrap" of the panorama's horizontal band.

The map building is NumPy-only (via ``EquirectView``); ``cv2`` is only used for
the final ``remap`` and is passed in, so this module never imports OpenCV.
"""

from __future__ import annotations

from streamcatcher.player.reprojection import EquirectView

# Heading (yaw, in degrees) for each named view, in a stable order. 90°-FOV
# views at these yaws tile the horizon: front | right | back | left.
ORIENTATIONS: dict[str, float] = {
    "front": 0.0,
    "right": 90.0,
    "back": 180.0,
    "left": -90.0,
}

# Defaults chosen so the four square views tile the full horizon: a 90° HFOV on a
# square output also gives a 90° vertical FOV, covering ±45° of pitch.
DEFAULT_HFOV_DEG = 90.0
DEFAULT_SIZE = 1024


class OrientationError(RuntimeError):
    """Raised when the four-orientation split can't be produced or written."""


def split_equirect(
    frame,
    cv2,
    *,
    size: int = DEFAULT_SIZE,
    hfov_deg: float = DEFAULT_HFOV_DEG,
    pitch_deg: float = 0.0,
) -> dict:
    """Reproject an equirectangular ``frame`` into four cardinal pinhole views.

    Returns an ordered mapping ``{"front", "right", "back", "left"} -> image``,
    each a ``size``×``size`` rectilinear view with horizontal FOV ``hfov_deg``,
    aimed at yaw 0/90/180/-90 and the given ``pitch_deg``. The frame is treated
    as a full 360°×180° equirectangular panorama regardless of how it was
    captured.
    """
    if frame is None:
        raise OrientationError("No frame to split.")
    src_height, src_width = frame.shape[:2]
    views: dict = {}
    for name, yaw in ORIENTATIONS.items():
        view = EquirectView(
            out_width=size,
            out_height=size,
            hfov_deg=hfov_deg,
            yaw_deg=yaw,
            pitch_deg=pitch_deg,
        )
        map_x, map_y = view.build_maps(src_width, src_height)
        views[name] = cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR)
    return views
