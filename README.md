# Streamcatcher

A cross-platform Python CLI that connects to an **RTSP** or **RTMP** video stream
and views it in a small desktop window — including **360° panoramic cameras**,
which it reprojects into a flat pan/tilt/zoom "look-around" viewport. Pure Python,
powered by OpenCV.

> **Status:** early development, built in small, tested vertical slices. Live
> video playback, the 360°/fisheye look-around viewport, named camera profiles,
> snapshots, auto-reconnect, and an HTTP control API all work today. Audio is on
> the [roadmap](#roadmap).

## Features

- **View RTSP/RTMP streams** in a native window (OpenCV — video only, no audio).
- **360° / fisheye support:** reproject an equirectangular panorama, a 180°
  hemisphere, or a raw fisheye lens into a flat look-around viewport.
- **Look around live:** `W`/`A`/`S`/`D` to pan and tilt, `+`/`-` to zoom, `q` to quit.
- **Snapshots:** press `p` in the viewer to save the current view, or grab one
  frame headlessly with `--snapshot out.jpg`.
- **Auto-reconnect:** when a live stream drops, reconnect with exponential
  backoff (retries forever by default; `--no-reconnect` to exit on the first drop).
- **Camera profiles:** presets for Ricoh Theta, Insta360 Pro, and generic
  360/180/fisheye rigs set the projection and any mounting offsets for you.
- **Offline-first:** the package and the entire test suite run with no network,
  no credentials, and no live stream. The default `stub` backend needs nothing
  installed; OpenCV is lazy-imported only on the live path.
- **Secrets-safe:** stream URLs (which may embed `user:pass@host`) are wrapped in
  `SecretStr` and scrubbed from logs by a redacting filter.

## Install

Requires **Python 3.12+**. Streamcatcher is not on PyPI yet, so install from source:

```console
pip install git+https://github.com/ThugipanSivanesan/Streamcatcher
```

The live viewer pulls in `opencv-python`; no separate system media player (VLC,
ffmpeg app, …) is required.

## Usage

```console
# View a plain 2D stream in a window
streamcatcher play rtsp://camera.local:554/stream1

# View a 360° equirectangular camera with a look-around viewport
streamcatcher play rtsp://123.456.7.890/live/live -b opencv -p equirect

# Use a named camera profile (sets projection + mounting offsets)
streamcatcher play rtsp://cam/live -b opencv --profile ricoh-theta

# Capture a single frame and exit — no window (respects -p/--profile)
streamcatcher play rtsp://cam/live -b opencv --snapshot shot.jpg
```

In the viewer window: **`W`/`A`/`S`/`D`** aim · **`+`/`-`** zoom · **`p`** snapshot · **`q`** quit.
The `p` hotkey writes a timestamped `streamcatcher-snapshot-YYYYMMDD-HHMMSS.jpg`
in the current directory (or in `--snapshot-dir` if set).

| Flag | Values | Env var |
|---|---|---|
| `--backend` / `-b` | `opencv` (live window), `stub` (offline, default) | `STREAMCATCHER_BACKEND` |
| `--projection` / `-p` | `flat` (default), `equirect`, `equirect-180`, `fisheye` | `STREAMCATCHER_PROJECTION` |
| `--profile` | `flat`, `generic-360`, `generic-180`, `generic-fisheye`, `insta360-pro`, `ricoh-theta` | `STREAMCATCHER_PROFILE` |
| `--snapshot` | `PATH` — save one frame there and exit | — |
| `--snapshot-dir` | `DIR` — directory for `p`-hotkey snapshots (default: current dir) | `STREAMCATCHER_SNAPSHOT_DIR` |
| `--reconnect` / `--no-reconnect` | auto-reconnect on drop (default on) | `STREAMCATCHER_RECONNECT_ENABLED` |

A profile overrides `--projection`. The default `stub` backend is a no-op used for
offline development and tests; pass `-b opencv` to open a real window.

## How it works

- **Playback:** OpenCV (`cv2.VideoCapture` + highgui) opens its own native window
  from a plain Python CLI. RTSP is forced over TCP to reduce dropped packets.
- **360° reprojection:** pure-NumPy equirectangular→pinhole and fisheye→pinhole
  remap tables are fed to `cv2.remap`. The math is deterministic and unit-tested
  with no GPU, window, or live stream needed.
- **Headless control core:** `StreamSession` drives open / read / render /
  look-around / close with no window attached — the same core the planned HTTP
  API will sit on.
- **CLI:** [Typer](https://typer.tiangolo.com/).

## HTTP control API

Install the `[api]` extra and run the server so another program — or an AI agent —
can open sessions, drive the look-around, and pull frames:

```console
pip install 'streamcatcher[api]'
streamcatcher serve                                   # binds 127.0.0.1:8000
streamcatcher serve --host 0.0.0.0 --port 9000 --token changeme
```

Interactive OpenAPI docs are served at `/docs`. Key endpoints:

| Endpoint | Purpose |
|---|---|
| `POST /session` | Open a session for a stream URL; returns an id (**the URL is never echoed back**). |
| `GET /session/{id}/frame` | Current look-around viewport as a JPEG — how an agent "sees" now. |
| `GET /session/{id}/panorama` | Raw, full-frame JPEG (before reprojection). |
| `GET /session/{id}/stream.mjpg` | MJPEG stream of the viewport. |
| `POST /session/{id}/look` | Pan/tilt/zoom by `{pan, tilt, zoom}` degree deltas. |
| `POST /session/{id}/look/{pan_left…zoom_out}` | Discrete look steps. |
| `GET /session/{id}/state` | Current projection and orientation. |
| `DELETE /session/{id}` | Close the session. |

The server binds `127.0.0.1` by default. Set `--token` (or `STREAMCATCHER_API_TOKEN`)
to require an `Authorization: Bearer <token>` header on every request. Stream URLs
and their credentials are never returned in any response.

## Documentation

Full docs — CLI usage, the 360°/camera guide, the Python and HTTP APIs,
architecture, and an API reference generated from the source — are built with
mkdocs-material under [`docs/`](docs/). Build them locally with
`uv run mkdocs serve` (see [Contributing](CONTRIBUTING.md)).

## Roadmap

- **Audio.** OpenCV decodes video only; audio playback is not yet supported.

See the [changelog](CHANGELOG.md) for what has shipped so far.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full development workflow. The short
version, using [uv](https://docs.astral.sh/uv/):

```console
uv sync --extra api           # create the environment (incl. the API extra)
uv run pytest                 # tests (offline, no credentials)
uv run ruff check .           # lint
uv run ruff format --check .  # format check
uv run mkdocs serve           # preview the docs (needs: uv sync --group docs)
pre-commit install            # enable local hooks
```

## Security

- CI runs [gitleaks](https://github.com/gitleaks/gitleaks) (secret scanning) and
  [osv-scanner](https://google.github.io/osv-scanner/) (dependency
  vulnerabilities) on every pull request.
- Pre-commit hooks scan for secrets and private keys before anything is committed.
- Stream URLs and their embedded credentials are never written to logs.

## License

[MIT](LICENSE)
