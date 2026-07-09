"""Reprojection of 360/fisheye streams to a flat, look-around viewport.

A 360 camera streams either an *equirectangular* frame (a 2:1 panorama of the
whole sphere) or a raw *fisheye* circle. Viewed raw, both look warped. This
module aims a virtual pinhole camera — an ordinary flat window — at the source,
so the viewer sees an undistorted slice and can pan/tilt/zoom around it.

The lookup tables are built with NumPy only (no OpenCV), so the math is pure,
deterministic, and unit-testable without a decoder or a display. The player
feeds the returned ``map_x``/``map_y`` to ``cv2.remap`` to warp each frame.

Two source geometries share one virtual camera:

* :class:`EquirectView` samples an equirectangular panorama. Its ``h_coverage_deg``
  /``v_coverage_deg`` describe how much of the sphere the frame spans — ``360×180``
  for a full 360, ``180×180`` for a front-only "equirect-180" hemisphere.
* :class:`FisheyeView` samples a single raw fisheye lens using the *equidistant*
  projection (``r = f·θ``). We use a generic equidistant model rather than a
  calibrated ``cv2.fisheye`` undistort because we have no per-camera distortion
  coefficients; the lens field of view (``fov_deg``) is the only parameter.

Coordinate convention (right-handed camera space): ``+X`` right, ``+Y`` up,
``+Z`` forward. ``yaw`` pans left/right about ``+Y``; ``pitch`` tilts up/down
(positive looks up); ``roll`` rotates about ``+Z`` (used only as a fixed mounting
offset). ``hfov`` is the horizontal field of view — smaller is more zoomed in.
Per-profile ``*_offset_deg`` values are fixed rotations added on top of the
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
    this base builds onto their particular source geometry (equirect, fisheye).
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
    """A virtual pinhole camera aimed into an equirectangular panorama.

    ``h_coverage_deg``/``v_coverage_deg`` give the sphere span the frame covers:
    ``360×180`` for a full 360 panorama, ``180×180`` for a front-only hemisphere
    ("equirect-180"). Rays outside that span map off the frame and render black.
    """

    def __init__(
        self,
        *args,
        h_coverage_deg: float = 360.0,
        v_coverage_deg: float = 180.0,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.h_coverage_deg = float(h_coverage_deg)
        self.v_coverage_deg = float(v_coverage_deg)

    def _rays_to_source(self, x, y, z, src_width, src_height):
        lon = np.arctan2(x, z)  # [-pi, pi]; 0 = forward
        lat = np.arctan2(y, np.sqrt(x * x + z * z))  # [-pi/2, pi/2]
        map_x = (lon / np.radians(self.h_coverage_deg) + 0.5) * src_width
        map_y = (0.5 - lat / np.radians(self.v_coverage_deg)) * src_height
        return map_x, map_y


class FisheyeView(_SphericalView):
    """A virtual pinhole camera aimed into a single equidistant fisheye lens.

    The source is a circular fisheye whose optical axis is ``+Z``. A ray at angle
    ``θ`` from that axis lands at radius ``r = (θ / (fov/2))·R`` from the image
    centre (equidistant model), where ``R`` is the fisheye circle radius. Rays
    beyond the lens's field of view render black.
    """

    def __init__(self, *args, fov_deg: float = 180.0, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fov_deg = float(fov_deg)

    def _rays_to_source(self, x, y, z, src_width, src_height):
        norm = np.sqrt(x * x + y * y + z * z)
        theta = np.arccos(np.clip(z / norm, -1.0, 1.0))  # angle from the +Z axis
        phi = np.arctan2(y, x)
        radius = 0.5 * min(src_width, src_height)  # fisheye circle radius, px
        r = (theta / np.radians(self.fov_deg / 2.0)) * radius
        cx, cy = src_width / 2.0, src_height / 2.0
        map_x = cx + r * np.cos(phi)
        map_y = cy - r * np.sin(phi)  # image row grows downward; ray +Y is up
        # Anything past the lens's own field of view isn't captured — send it
        # off-frame so it renders as the constant border rather than smearing.
        outside = theta > np.radians(self.fov_deg / 2.0)
        map_x = np.where(outside, -1.0, map_x)
        map_y = np.where(outside, -1.0, map_y)
        return map_x, map_y
