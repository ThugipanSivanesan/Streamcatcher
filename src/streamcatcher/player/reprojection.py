"""Reprojection of 360 equirectangular streams to a flat, look-around viewport.

A 360 camera streams an *equirectangular* frame — a 2:1 panorama of the whole
sphere. Viewed raw it looks warped. This module aims a virtual pinhole camera —
an ordinary flat window — at the source, so the viewer sees an undistorted slice
and can pan/tilt/zoom around it.

The lookup tables are built with NumPy only (no OpenCV), so the math is pure,
deterministic, and unit-testable without a decoder or a display. The player
feeds the returned ``map_x``/``map_y`` to ``cv2.remap`` to warp each frame.

:class:`EquirectView` is the virtual camera: it samples a full ``360×180``
equirectangular panorama for whatever slice the current yaw/pitch/hfov select.

Coordinate convention (right-handed camera space): ``+X`` right, ``+Y`` up,
``+Z`` forward. ``yaw`` pans left/right about ``+Y``; ``pitch`` tilts up/down
(positive looks up); ``roll`` rotates about ``+Z`` (used only as a fixed mounting
offset). ``hfov`` is the horizontal field of view — smaller is more zoomed in.
The ``*_offset_deg`` values are fixed mounting rotations added on top of the
interactive yaw/pitch, so a camera mounted rotated still reads level.
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


class _SphericalView:
    """A virtual pinhole camera that can look around a spherical source.

    Subclasses implement :meth:`_rays_to_source`, mapping the camera-space rays
    this base builds onto their particular source geometry.
    """

    def __init__(
        self,
        out_width: int = 1280,
        out_height: int = 720,
        hfov_deg: float = 100.0,
        yaw_deg: float = 0.0,
        pitch_deg: float = 0.0,
        yaw_offset_deg: float = 0.0,
        pitch_offset_deg: float = 0.0,
        roll_offset_deg: float = 0.0,
    ) -> None:
        self.out_width = int(out_width)
        self.out_height = int(out_height)
        self.hfov_deg = float(hfov_deg)
        self.yaw_deg = float(yaw_deg)
        self.pitch_deg = float(pitch_deg)
        # Fixed mounting offsets, folded into every ray build (not interactive).
        self.yaw_offset_deg = float(yaw_offset_deg)
        self.pitch_offset_deg = float(pitch_offset_deg)
        self.roll_offset_deg = float(roll_offset_deg)

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

    def _camera_rays(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Direction rays for every output pixel, after roll/pitch/yaw.

        Returns ``(x, y, z)`` arrays of shape ``(out_height, out_width)`` in the
        source's camera space, with all fixed offsets and the interactive
        yaw/pitch already applied.
        """
        w, h = self.out_width, self.out_height
        cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
        focal = (w / 2.0) / np.tan(np.radians(self.hfov_deg) / 2.0)

        u = np.arange(w, dtype=np.float64) - cx
        v = np.arange(h, dtype=np.float64) - cy
        uu, vv = np.meshgrid(u, v)  # (h, w)

        # Base rays: +X right, +Y up (image v grows downward), +Z forward.
        x0 = uu
        y0 = -vv
        z0 = np.full_like(uu, focal)

        roll = np.radians(self.roll_offset_deg)
        pitch = np.radians(self.pitch_deg + self.pitch_offset_deg)
        yaw = np.radians(self.yaw_deg + self.yaw_offset_deg)
        cr, sr = np.cos(roll), np.sin(roll)
        cp, sp = np.cos(pitch), np.sin(pitch)
        cyaw, syaw = np.cos(yaw), np.sin(yaw)

        # Roll about +Z, then tilt about +X (positive pitch looks up), then pan
        # about +Y. Roll is identity when its offset is 0, so a plain view keeps
        # the original equirect numerics exactly.
        xr = x0 * cr - y0 * sr
        yr = x0 * sr + y0 * cr
        y1 = yr * cp + z0 * sp
        z1 = -yr * sp + z0 * cp
        x2 = xr * cyaw + z1 * syaw
        z2 = -xr * syaw + z1 * cyaw
        y2 = y1
        return x2, y2, z2

    def build_maps(self, src_width: int, src_height: int) -> tuple[np.ndarray, np.ndarray]:
        """Build the ``cv2.remap`` tables sampling the ``src`` frame.

        Returns ``(map_x, map_y)`` float32 arrays of shape ``(out_height,
        out_width)`` giving, for each output pixel, the source column/row to
        sample. Pixels that fall outside the source map to negative coordinates
        so ``cv2.remap``'s constant border renders them black.
        """
        x, y, z = self._camera_rays()
        map_x, map_y = self._rays_to_source(x, y, z, src_width, src_height)
        return map_x.astype(np.float32), map_y.astype(np.float32)

    def _rays_to_source(
        self, x: np.ndarray, y: np.ndarray, z: np.ndarray, src_width: int, src_height: int
    ) -> tuple[np.ndarray, np.ndarray]:  # pragma: no cover - abstract
        raise NotImplementedError


class EquirectView(_SphericalView):
    """A virtual pinhole camera aimed into a full ``360×180`` equirectangular panorama.

    Longitude spans the full ``360`` across the frame width and latitude the full
    ``180`` across its height, so every camera ray lands somewhere on the frame.
    """

    def _rays_to_source(self, x, y, z, src_width, src_height):
        lon = np.arctan2(x, z)  # [-pi, pi]; 0 = forward
        lat = np.arctan2(y, np.sqrt(x * x + z * z))  # [-pi/2, pi/2]
        map_x = (lon / (2.0 * np.pi) + 0.5) * src_width
        map_y = (0.5 - lat / np.pi) * src_height
        return map_x, map_y
