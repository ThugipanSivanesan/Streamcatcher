# CLI usage

Streamcatcher has two commands: [`play`](#play) (view or snapshot a stream) and
[`serve`](http-api.md) (run the HTTP control API).

## `play`

```console
streamcatcher play URL [OPTIONS]
```

`URL` is an `rtsp://…` or `rtmp://…` stream address. It may embed credentials
(`rtsp://user:pass@host/…`); those are wrapped in a secret and never printed to
logs (see [Security](security.md)).

```console
# View a plain 2D stream in a window
streamcatcher play rtsp://camera.local:554/stream1 -b opencv

# View a 360° equirectangular camera with a look-around viewport
streamcatcher play rtsp://camera.local/live/live -b opencv -p equirect

# Use a named camera profile (sets projection + mounting offsets)
streamcatcher play rtsp://camera.local/live -b opencv --profile ricoh-theta

# Capture a single frame and exit — no window
streamcatcher play rtsp://camera.local/live -b opencv --snapshot shot.jpg
```

### In the viewer window

| Key | Action |
|---|---|
| `W` / `A` / `S` / `D` | Tilt up / pan left / tilt down / pan right *(360 modes only)* |
| `+` / `-` | Zoom in / out *(360 modes only)* |
| `p` | Save a snapshot |
| `q` | Quit |

Closing the window also quits.

### Options

| Flag | Values | Env var |
|---|---|---|
| `--backend` / `-b` | `opencv` (live window), `stub` (offline, default) | `STREAMCATCHER_BACKEND` |
| `--projection` / `-p` | `flat` (default), `equirect`, `equirect-180`, `fisheye` | `STREAMCATCHER_PROJECTION` |
| `--profile` | `flat`, `generic-360`, `generic-180`, `generic-fisheye`, `insta360-pro`, `ricoh-theta` | `STREAMCATCHER_PROFILE` |
| `--snapshot` | `PATH` — save one frame there and exit (no window) | — |
| `--reconnect` / `--no-reconnect` | auto-reconnect on drop (default on) | `STREAMCATCHER_RECONNECT_ENABLED` |

Every flag has an environment-variable default (prefix `STREAMCATCHER_`); passing
the flag overrides the env var. A named `--profile` overrides `--projection`.

### Backends

- **`stub`** (default) — a no-op player that logs what it would do and touches no
  window, decoder, or network. It's the offline-first default so the package and
  the test suite run anywhere. It does nothing useful against a real camera.
- **`opencv`** — the live player. Opens the stream with OpenCV, forces RTSP over
  TCP to reduce dropped packets, and shows frames in a window it owns.

Pass `-b opencv` (or set `STREAMCATCHER_BACKEND=opencv`) for real playback.

## Projections

`flat` shows frames unchanged. The other three treat the frame as 360°/wide
geometry and reproject it into a flat, steerable viewport:

- `equirect` — a full 360°×180° equirectangular panorama.
- `equirect-180` — a front-only 180°×180° hemisphere.
- `fisheye` — a single raw fisheye lens.

See [360° & cameras](cameras.md) for how these work and which to pick.

## Snapshots

Two ways to grab a still:

- **Live:** press `p` in the viewer. The current view (the reprojected viewport in
  360 modes, the raw frame when flat) is written to a timestamped
  `streamcatcher-snapshot-YYYYMMDD-HHMMSS.jpg` in the current directory.
- **One-shot:** `--snapshot PATH` opens the stream, grabs one rendered frame,
  writes it to `PATH`, and exits without ever opening a window. It respects
  `--projection` / `--profile`, so the still matches what the window would show.

```console
streamcatcher play rtsp://cam/live -b opencv -p equirect --snapshot view.jpg
```

## Auto-reconnect

When a live stream drops, the OpenCV backend reconnects on its own with
exponential backoff (1s → 2s → 4s → … capped at 30s), retrying **forever** until
the stream returns or you quit (`q` / close the window / `Ctrl-C`). The viewport
orientation (where you were looking) is preserved across a reconnect.

Disable it with `--no-reconnect` to exit on the first drop — useful for a finite
source you don't expect to come back:

```console
streamcatcher play rtsp://cam/live -b opencv --no-reconnect
```

The backoff is tunable via environment variables:

| Env var | Default | Meaning |
|---|---|---|
| `STREAMCATCHER_RECONNECT_ENABLED` | `true` | Master on/off |
| `STREAMCATCHER_RECONNECT_BASE_DELAY` | `1.0` | Seconds before the first retry |
| `STREAMCATCHER_RECONNECT_BACKOFF_FACTOR` | `2.0` | Multiplier after each failed attempt |
| `STREAMCATCHER_RECONNECT_MAX_DELAY` | `30.0` | Cap on the wait, in seconds |
