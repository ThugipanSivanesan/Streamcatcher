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

# Record the stream to a file while you watch it
streamcatcher play rtsp://camera.local/live -b opencv --record capture.mp4

# Record losslessly with audio (needs the ffmpeg binary on PATH)
streamcatcher play rtsp://camera.local/live -b opencv --record capture.mp4 --record-mode ffmpeg

# Record a fixed length, then stop automatically (here: 30 seconds)
streamcatcher play rtsp://camera.local/live -b opencv --record capture.mp4 --duration 30
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
| `--record` | optional `PATH` — record while playing; defaults to a timestamped `.mp4` in the current directory. Mutually exclusive with `--snapshot` and `--orientations` | — |
| `--record-mode` | `opencv` (default), `ffmpeg` | `STREAMCATCHER_RECORD_MODE` |
| `--duration` | `SECONDS` — stop recording and playback this long after the first frame; requires `--record` | `STREAMCATCHER_RECORD_DURATION` |
| `--orientations` | optional `DIR` — split one 360 frame into four flat views and exit; defaults to a timestamped folder. Mutually exclusive with `--snapshot` and `--record` | `STREAMCATCHER_ORIENTATION_SIZE`, `STREAMCATCHER_ORIENTATION_HFOV_DEG` |
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

## Recording

Record a live stream to a file while you watch it with `--record`. Like
`--snapshot`, the path is optional — bare `--record` writes a timestamped
`streamcatcher-recording-YYYYMMDD-HHMMSS.mp4` in the current directory; missing
parent directories are created. `--record` can't be combined with `--snapshot` or
`--orientations` (those capture and exit). By default there is **no time limit** —
the recording runs until you quit (`q` / close the window / `Ctrl-C`), or, if
`--no-reconnect` is set, until the stream ends. Pass `--duration SECONDS` to cap
it: recording (and playback) stop automatically that many seconds after the
first frame. The recording is always finalized on the way out.

Two modes, chosen with `--record-mode`:

| Mode | Output | Audio | Needs | Notes |
|---|---|---|---|---|
| `opencv` (default) | re-encoded video | ❌ no | nothing extra | Records the raw decoded frame — in 360 that's the **full equirectangular panorama**, not the look-around viewport, so a recording never follows where you're looking. If the stream resolution changes (e.g. after a reconnect) it rolls to a new numbered segment (`capture-002.mp4`, …). |
| `ffmpeg` | lossless copy | ✅ yes | the `ffmpeg` binary on `PATH` | Copies the original stream with `ffmpeg -c copy` on its own connection — no re-encode, keeps audio. Records the raw stream (not the reprojected viewport). |

```console
# Default opencv mode — video only, no extra dependency
streamcatcher play rtsp://cam/live -b opencv --record capture.mp4

# ffmpeg mode — lossless, with audio (install ffmpeg first)
streamcatcher play rtsp://cam/live -b opencv --record capture.mp4 --record-mode ffmpeg

# Fixed-length capture — records ~60s from the first frame, then stops
streamcatcher play rtsp://cam/live -b opencv --record capture.mp4 --duration 60
```

`--duration SECONDS` bounds the capture: the clock starts on the **first
recorded frame** (not when playback opens), so it measures recorded time rather
than time spent waiting for the stream. It works in both modes and requires
`--record`. The default (`STREAMCATCHER_RECORD_DURATION`) is unset — an
open-ended recording.

Recording is best-effort: if the output can't be opened or a write fails,
Streamcatcher logs a warning and keeps playing rather than aborting. The
`opencv` codec (`STREAMCATCHER_RECORD_FOURCC`, default `mp4v`) and the fallback
frame rate used when the stream doesn't report one (`STREAMCATCHER_RECORD_FPS`,
default `25`) are configurable.

!!! note "ffmpeg mode and credentials"
    In `ffmpeg` mode the stream URL is passed to the `ffmpeg` subprocess, so a
    URL with embedded credentials is briefly visible in the machine's process
    list (`ps`). Prefer `opencv` mode on shared hosts. See [Security](security.md).

## Four-orientation split

`--orientations` takes a single frame from a **360° equirectangular** stream and
reprojects it into four flat, undistorted views — **front, right, back, left** —
then exits without opening a window (so it works on a headless OpenCV build too).
With the default 90° field of view the four views tile the whole horizon.

```console
# Write front.jpg / right.jpg / back.jpg / left.jpg into ./views/
streamcatcher play rtsp://cam/live -b opencv --orientations ./views

# No DIR → a timestamped streamcatcher-orientations-YYYYMMDD-HHMMSS/ folder
streamcatcher play rtsp://cam/live -b opencv --orientations
```

The source is always treated as a full 360°×180° panorama regardless of
`--projection`. Tune the output with environment variables:

| Env var | Default | Meaning |
|---|---|---|
| `STREAMCATCHER_ORIENTATION_SIZE` | `1024` | Side length, in pixels, of each square view |
| `STREAMCATCHER_ORIENTATION_HFOV_DEG` | `90.0` | Horizontal field of view per view (90° tiles the horizon) |

An interactive explainer for how the split works lives in
[`docs/orientation-split.html`](orientation-split.html).

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
