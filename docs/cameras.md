# 360° & cameras

Panoramic cameras don't produce a flat, ready-to-watch image — they produce a
warped one (an equirectangular strip or a circular fisheye) that has to be
**reprojected** into a normal perspective view before it's watchable. Streamcatcher
does that reprojection on the fly and lets you steer a virtual pinhole camera
around the sphere.

## Projections

Pick one with `--projection`/`-p`, or let a [profile](#camera-profiles) set it.

| Projection | Source geometry | Coverage | Use it for |
|---|---|---|---|
| `flat` | Ordinary rectilinear video | — | Normal 2D cameras (default) |
| `equirect` | Equirectangular panorama (2:1) | 360° × 180° | Fully stitched 360 cameras |
| `equirect-180` | Equirectangular hemisphere | 180° × 180° | Front-facing 180 cameras |
| `fisheye` | Raw circular fisheye lens | up to the lens FOV | A single uncorrected lens |

In any non-flat mode the window (or the API) shows a **flat viewport** you look
around with `W`/`A`/`S`/`D` (aim) and `+`/`-` (zoom). Past the source's coverage —
e.g. behind an `equirect-180` hemisphere — you see a black border.

!!! info "Equirectangular ≠ raw fisheye"
    A stitched 360 camera (e.g. an Insta360 Pro streaming over RTSP) already
    outputs an **equirectangular** panorama — the "warped" look is inherent
    equirect distortion, not raw per-lens fisheye, so it needs `equirect`, not
    `fisheye`, and no lens calibration. Use `fisheye` only for a single,
    uncorrected circular lens.

## Camera profiles

A **profile** bundles a projection with the camera's mounting offsets (yaw / pitch
/ roll) and, for fisheye, the lens field of view — so you name the camera instead
of remembering geometry flags:

```console
streamcatcher play rtsp://cam/live -b opencv --profile ricoh-theta
```

A `--profile` overrides `--projection`. Built-in presets:

| Profile | Projection | Notes |
|---|---|---|
| `flat` | `flat` | Plain 2D — the identity profile |
| `generic-360` | `equirect` | Any stitched 360 panorama |
| `generic-180` | `equirect-180` | Any front-facing 180 hemisphere |
| `generic-fisheye` | `fisheye` | A single 180° fisheye lens |
| `insta360-pro` | `equirect` | Insta360 Pro (stitched output) |
| `ricoh-theta` | `equirect` | Ricoh Theta series |

List them from the CLI help, or from Python:

```python
from streamcatcher.player.profiles import available_profiles
print(available_profiles())
```

## How the reprojection works

The reprojection is **pure NumPy** — it builds `cv2.remap` lookup tables and hands
them to OpenCV, but the geometry itself uses no OpenCV, no GPU, and no live
stream, which keeps it deterministic and unit-testable.

- **Equirectangular → pinhole:** a virtual pinhole camera's rays are mapped onto
  the sphere (`longitude = atan2(x, z)`, `latitude = atan2(y, ·)`), then back to
  pixel coordinates in the panorama. Coverage narrower than 360°/180° maps to a
  black border.
- **Fisheye → pinhole:** an equidistant lens model (`r = (θ / (fov/2)) · R`), pure
  NumPy again. Rays beyond the lens FOV are masked to black. This deliberately
  avoids `cv2.fisheye`, which needs per-camera calibration coefficients we don't
  have.

Mounting offsets from the profile are folded into the ray generation (roll → pitch
→ yaw), so a camera that isn't level still produces a level viewport. Zero offsets
are a numeric identity, so a plain 360 stream is byte-for-byte unaffected.

If you don't know a camera's geometry, Streamcatcher can guess from the frame
aspect ratio: a 2:1 frame is treated as `generic-360`, anything else as `flat`
(see [`profile_for_frame`](reference.md)).
