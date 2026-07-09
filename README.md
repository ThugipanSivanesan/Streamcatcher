# Streamcatcher

A cross-platform Python CLI that connects to an **RTSP** or **RTMP** video stream
and views it in a small desktop window — including **360° panoramic cameras**,
which it reprojects into a flat pan/tilt/zoom "look-around" viewport. Pure Python,
powered by OpenCV.

> **Status:** early development, built in small, tested vertical slices. Live
> video playback, the 360°/fisheye look-around viewport, and named camera
> profiles work today. Audio, snapshot capture, auto-reconnect, and an HTTP
> control API are on the [roadmap](#roadmap).

## Features

- **View RTSP/RTMP streams** in a native window (OpenCV — video only, no audio).
- **360° / fisheye support:** reproject an equirectangular panorama, a 180°
  hemisphere, or a raw fisheye lens into a flat look-around viewport.
- **Look around live:** `W`/`A`/`S`/`D` to pan and tilt, `+`/`-` to zoom, `q` to quit.
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
streamcatcher play rtsp://192.168.0.201/live/live -b opencv -p equirect

# Use a named camera profile (sets projection + mounting offsets)
streamcatcher play rtsp://cam/live -b opencv --profile ricoh-theta
```

In the viewer window: **`W`/`A`/`S`/`D`** aim · **`+`/`-`** zoom · **`q`** quit.

| Flag | Values | Env var |
|---|---|---|
| `--backend` / `-b` | `opencv` (live window), `stub` (offline, default) | `STREAMCATCHER_BACKEND` |
| `--projection` / `-p` | `flat` (default), `equirect`, `equirect-180`, `fisheye` | `STREAMCATCHER_PROJECTION` |
| `--profile` | `flat`, `generic-360`, `generic-180`, `generic-fisheye`, `insta360-pro`, `ricoh-theta` | `STREAMCATCHER_PROFILE` |

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

## Roadmap

- **HTTP control API** (`streamcatcher serve`, FastAPI) so another program or AI
  agent can open a session, drive the look-around, and pull frames as JPEG stills
  or an MJPEG stream.
- **Snapshots:** live `s` hotkey plus a one-shot `--snapshot out.png`.
- **Auto-reconnect** with backoff when a stream drops.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```console
uv sync                       # create the environment
uv run pytest                 # tests (offline, no credentials)
uv run ruff check .           # lint
uv run ruff format --check .  # format check
pre-commit install            # enable local hooks
pre-commit run --all-files    # run all hooks
```

## Security

- CI runs [gitleaks](https://github.com/gitleaks/gitleaks) (secret scanning) and
  [osv-scanner](https://google.github.io/osv-scanner/) (dependency
  vulnerabilities) on every pull request.
- Pre-commit hooks scan for secrets and private keys before anything is committed.
- Stream URLs and their embedded credentials are never written to logs.

## License

[MIT](LICENSE)
