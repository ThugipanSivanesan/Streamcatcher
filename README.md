# Streamcatcher

[![PyPI version](https://img.shields.io/pypi/v/streamcatcher.svg)](https://pypi.org/project/streamcatcher/)
[![Python versions](https://img.shields.io/pypi/pyversions/streamcatcher.svg)](https://pypi.org/project/streamcatcher/)
[![License: MIT](https://img.shields.io/pypi/l/streamcatcher.svg)](LICENSE)

A cross-platform Python CLI that connects to an **RTSP** or **RTMP** video stream
and views it in a small desktop window — including **360° panoramic cameras**,
which it reprojects into a flat pan/tilt/zoom "look-around" viewport. Pure Python,
powered by OpenCV.

> **Status:** early development, built in small, tested vertical slices. Live
> video playback, the 360° equirectangular look-around viewport, snapshots,
> auto-reconnect, and an HTTP control API all work today. Video only — OpenCV
> does not decode audio.

## Features

- **View RTSP/RTMP streams** in a native window (OpenCV — video only, no audio).
- **360° support:** reproject an equirectangular panorama into a flat
  look-around viewport.
- **Look around live:** `W`/`A`/`S`/`D` to pan and tilt, `+`/`-` to zoom, `q` to quit.
- **Snapshots:** press `p` in the viewer to save the current view, or grab one
  frame headlessly with `--snapshot` (current directory) or `--snapshot out.jpg`.
- **Auto-reconnect:** when a live stream drops, reconnect with exponential
  backoff (retries forever by default; `--no-reconnect` to exit on the first drop).
- **Offline-first:** the package and the entire test suite run with no network,
  no credentials, and no live stream. OpenCV is lazy-imported only on the live
  path, and an offline `stub` backend (`-b stub`) needs nothing at all.
- **Secrets-safe:** stream URLs (which may embed `user:pass@host`) are wrapped in
  `SecretStr` and scrubbed from logs by a redacting filter.

## Install

Requires **Python 3.12+**.

```console
pip install streamcatcher
```

Or install the latest unreleased code straight from source:

```console
pip install git+https://github.com/ThugipanSivanesan/Streamcatcher
```

The live viewer pulls in `opencv-python`; no separate system media player (VLC,
ffmpeg app, …) is required.

### Headless / server install

On a server, container, or CI box you don't need the desktop window — and the
default GUI build's system libraries (`libGL.so.1` on Linux) may be missing.
Swap in the headless OpenCV build so `serve` and `--snapshot` run without them:

```console
pip install streamcatcher
pip uninstall opencv-python
pip install opencv-python-headless
```

`streamcatcher serve` and `streamcatcher play --snapshot` work fully headless.
Only the live `play` window needs the default `opencv-python` build; on a
headless build it exits with a clear message instead of a cryptic OpenCV error.
(The two wheels both provide `cv2` and can't coexist, so it's a swap, not an extra.)

## Usage

```console
# View a plain 2D stream in a window
streamcatcher play rtsp://camera.local:554/stream1

# View a 360° equirectangular camera with a look-around viewport
streamcatcher play rtsp://123.456.7.890/live/live -p equirect

# Capture a single frame in the current directory and exit — no window (respects -p)
streamcatcher play rtsp://cam/live --snapshot

# Or choose the exact output path
streamcatcher play rtsp://cam/live --snapshot shot.jpg
```

In the viewer window: **`W`/`A`/`S`/`D`** (or **drag the mouse**) aim · **`+`/`-`** zoom · **`p`** snapshot · **`q`** quit.
The `p` hotkey writes a timestamped `streamcatcher-snapshot-YYYYMMDD-HHMMSS.jpg`
in the current directory.

| Flag | Values | Env var |
|---|---|---|
| `--backend` / `-b` | `opencv` (live window, default), `stub` (offline no-op) | `STREAMCATCHER_BACKEND` |
| `--projection` / `-p` | `flat` (default), `equirect` | `STREAMCATCHER_PROJECTION` |
| `--snapshot` | optional `PATH` — save one frame and exit; defaults to a timestamped JPEG in the current directory | — |
| `--reconnect` / `--no-reconnect` | auto-reconnect on drop (default on) | `STREAMCATCHER_RECONNECT_ENABLED` |

`play` opens a real OpenCV window by default; pass `-b stub` (or set
`STREAMCATCHER_BACKEND=stub`) for the offline no-op backend used in development
and tests.

## How it works

- **Playback:** OpenCV (`cv2.VideoCapture` + highgui) opens its own native window
  from a plain Python CLI. RTSP is forced over TCP to reduce dropped packets.
- **360° reprojection:** pure-NumPy equirectangular→pinhole remap tables are fed
  to `cv2.remap`. The math is deterministic and unit-tested with no GPU, window,
  or live stream needed.
- **Headless control core:** `StreamSession` drives open / read / render /
  look-around / close with no window attached — the same core the HTTP control
  API sits on.
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
`uv run mkdocs serve` (see [Contributing](CONTRIBUTING.md)). See the
[changelog](CHANGELOG.md) for what has shipped so far.

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
