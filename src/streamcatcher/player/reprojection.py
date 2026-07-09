"""Equirectangular → perspective reprojection for 360 streams.

An Insta360-style camera streams an *equirectangular* frame: a 2:1 panorama of
the whole sphere. Viewed raw, that panorama looks warped ("fisheye"). This
module aims a virtual pinhole camera — an ordinary flat window — at the sphere,
so the viewer sees an undistorted slice and can pan/tilt/zoom around it.

The lookup tables are built with NumPy only (no OpenCV), so the math is pure,
deterministic, and unit-testable without a decoder or a display. The player
feeds the returned ``map_x``/``map_y`` to ``cv2.remap`` to warp each frame.

Coordinate convention (right-handed camera space): ``+X`` right, ``+Y`` up,
``+Z`` forward. ``yaw`` pans left/right about ``+Y``; ``pitch`` tilts up/down;
positive pitch looks up. ``hfov`` is the horizontal field of view — smaller is
more zoomed in.
"""

from __future__ import annotations

import numpy as np

# Navigation steps, in degrees, applied per key press by the player.
YAW_STEP = 5.0
PITCH_STEP = 5.0
ZOOM_STEP = 5.0

_MIN_HFOV = 30.0  # most zoomed in
_MAX_HFOV = 120.0  # widest view before edges distort badly
_MAX_PITCH = 89.0  # stop short of the poles to avoid the singularity


class EquirectView:
    """A virtual pinhole camera aimed into an equirectangular panorama."""

    def __init__(
        self,
        out_width: int = 1280,
        out_height: int = 720,
        hfov_deg: float = 100.0,
        yaw_deg: float = 0.0,
        pitch_deg: float = 0.0,
    ) -> None:
        self.out_width = int(out_width)
        self.out_height = int(out_height)
        self.hfov_deg = float(hfov_deg)
        self.yaw_deg = float(yaw_deg)
        self.pitch_deg = float(pitch_deg)

    # -- navigation -----------------------------------------------------------

    def pan(self, delta_deg: float) -> None:
        """Rotate the view left/right, wrapping into ``[-180, 180)``."""
        self.yaw_deg = (self.yaw_deg + delta_deg + 180.0) % 360.0 - 180.0

    def tilt(self, delta_deg: float) -> None:
        """Rotate the view up/down, clamped short of the poles."""
        self.pitch_deg = float(np.clip(self.pitch_deg + delta_deg, -_MAX_PITCH, _MAX_PITCH))

    def zoom(self, delta_hfov_deg: float) -> None:
        """Widen/narrow the field of view (negative = zoom in), clamped."""
        self.hfov_deg = float(np.clip(self.hfov_deg + delta_hfov_deg, _MIN_HFOV, _MAX_HFOV))

    # -- map building ---------------------------------------------------------

    def build_maps(self, src_width: int, src_height: int) -> tuple[np.ndarray, np.ndarray]:
        """Build the ``cv2.remap`` tables sampling the ``src`` equirect frame.

        Returns ``(map_x, map_y)`` float32 arrays of shape ``(out_height,
        out_width)`` giving, for each output pixel, the source column/row to
        sample from the equirectangular frame.
        """
        w, h = self.out_width, self.out_height
        cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
        focal = (w / 2.0) / np.tan(np.radians(self.hfov_deg) / 2.0)

        u = np.arange(w, dtype=np.float64) - cx
        v = np.arange(h, dtype=np.float64) - cy
        uu, vv = np.meshgrid(u, v)  # (h, w)

        # Camera-space rays: +X right, +Y up (image v grows downward), +Z forward.
        x = uu
        y = -vv
        z = np.full_like(uu, focal)

        pitch = np.radians(self.pitch_deg)
        yaw = np.radians(self.yaw_deg)
        cp, sp = np.cos(pitch), np.sin(pitch)
        cyaw, syaw = np.cos(yaw), np.sin(yaw)

        # Tilt about +X (positive pitch looks up), then pan about +Y.
        y1 = y * cp + z * sp
        z1 = -y * sp + z * cp
        x2 = x * cyaw + z1 * syaw
        z2 = -x * syaw + z1 * cyaw
        y2 = y1

        lon = np.arctan2(x2, z2)  # [-pi, pi]; 0 = forward
        lat = np.arctan2(y2, np.sqrt(x2 * x2 + z2 * z2))  # [-pi/2, pi/2]

        map_x = (lon / (2.0 * np.pi) + 0.5) * src_width
        map_y = (0.5 - lat / np.pi) * src_height
        return map_x.astype(np.float32), map_y.astype(np.float32)
