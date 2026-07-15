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

# Capture a single frame in the current directory and exit — no window
streamcatcher play rtsp://camera.local/live -b opencv --snapshot

# Or choose the exact output path
streamcatcher play rtsp://camera.local/live -b opencv --snapshot shot.jpg
```

### In the viewer window

| Key | Action |
|---|---|
| `W` / `A` / `S` / `D` | Tilt up / pan left / tilt down / pan right *(equirect only)* |
| Mouse drag | Look around by dragging with the left button held *(equirect only)* |
| `+` / `-` | Zoom in / out *(equirect only)* |
| `p` | Save a snapshot |
| `q` | Quit |

Closing the window also quits.

### Options

| Flag | Values | Env var |
|---|---|---|
| `--backend` / `-b` | `opencv` (live window), `stub` (offline, default) | `STREAMCATCHER_BACKEND` |
| `--projection` / `-p` | `flat` (default), `equirect` | `STREAMCATCHER_PROJECTION` |
| `--snapshot` | optional `PATH` — save one frame and exit; defaults to a timestamped JPEG in the current directory | — |
| `--reconnect` / `--no-reconnect` | auto-reconnect on drop (default on) | `STREAMCATCHER_RECONNECT_ENABLED` |

Configuration-backed flags use environment-variable defaults with the
`STREAMCATCHER_` prefix; passing a flag overrides its environment value.

### Backends

- **`stub`** (default) — a no-op player that logs what it would do and touches no
  window, decoder, or network. It's the offline-first default so the package and
  the test suite run anywhere. It does nothing useful against a real camera.
- **`opencv`** — the live player. Opens the stream with OpenCV, forces RTSP over
  TCP to reduce dropped packets, and shows frames in a window it owns.

Pass `-b opencv` (or set `STREAMCATCHER_BACKEND=opencv`) for real playback.

## Projections

`flat` shows frames unchanged. `equirect` treats the frame as a full 360°×180°
equirectangular panorama and reprojects it into a flat, steerable viewport.

See [360° & cameras](cameras.md) for how this works.

## Snapshots

Two ways to grab a still:

- **Live:** press `p` in the viewer. The current view (the reprojected viewport in
  360 modes, the raw frame when flat) is written to a timestamped
  `streamcatcher-snapshot-YYYYMMDD-HHMMSS.jpg` in the current directory.
- **One-shot:** `--snapshot` opens the stream, grabs one rendered frame, writes a
  timestamped JPEG in the current directory, and exits without creating a window.
  Pass `--snapshot PATH` to write it to an exact custom path; missing parent
  directories are created automatically. It respects `--projection`, so the
  still matches what the window would show.

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
