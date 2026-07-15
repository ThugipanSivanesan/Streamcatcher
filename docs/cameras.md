# 360° & cameras

Panoramic cameras don't produce a flat, ready-to-watch image — they produce a
warped one (an equirectangular strip) that has to be **reprojected** into a
normal perspective view before it's watchable. Streamcatcher does that
reprojection on the fly and lets you steer a virtual pinhole camera around the
sphere.

## Projections

Pick one with `--projection`/`-p`:

| Projection | Source geometry | Coverage | Use it for |
|---|---|---|---|
| `flat` | Ordinary rectilinear video | — | Normal 2D cameras (default) |
| `equirect` | Equirectangular panorama (2:1) | 360° × 180° | Fully stitched 360 cameras |

In `equirect` mode the window (or the API) shows a **flat viewport** you look
around with `W`/`A`/`S`/`D` (aim) and `+`/`-` (zoom).

!!! info "Equirectangular ≠ raw fisheye"
    A stitched 360 camera (e.g. an Insta360 Pro streaming over RTSP) already
    outputs an **equirectangular** panorama — the "warped" look is inherent
    equirect distortion, not raw per-lens fisheye, so it needs `equirect` and no
    lens calibration. Raw single-lens fisheye sources are not supported.

## How the reprojection works

The reprojection is **pure NumPy** — it builds `cv2.remap` lookup tables and hands
them to OpenCV, but the geometry itself uses no OpenCV, no GPU, and no live
stream, which keeps it deterministic and unit-testable.

- **Equirectangular → pinhole:** a virtual pinhole camera's rays are mapped onto
  the sphere (`longitude = atan2(x, z)`, `latitude = atan2(y, ·)`), then back to
  pixel coordinates in the full 360° × 180° panorama.

The view supports fixed mounting offsets (roll → pitch → yaw), folded into the ray
generation so a camera that isn't level still produces a level viewport. Zero
offsets are a numeric identity, so a plain 360 stream is byte-for-byte unaffected.
