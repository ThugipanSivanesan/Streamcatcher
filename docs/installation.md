# Installation

Streamcatcher requires **Python 3.12+**.

## Core CLI

```console
pip install streamcatcher
```

To install the latest unreleased code instead, install straight from the repo:

```console
pip install git+https://github.com/ThugipanSivanesan/Streamcatcher
```

Either way this pulls in `opencv-python` for the live viewer — **no separate system media
player (VLC, an ffmpeg app, …) is required**. OpenCV opens and pumps its own
native window from a plain Python process, including on macOS.

## Headless / server install

The live `play` window needs the **desktop** build of OpenCV (`opencv-python`,
the default). On a headless box — a server, a container, CI — you don't want a
window, and the desktop build's GUI system libraries (`libGL.so.1` on Linux) may
be missing. Swap in the headless OpenCV build instead:

```console
pip install streamcatcher
pip uninstall opencv-python
pip install opencv-python-headless
```

`streamcatcher serve` (the [HTTP control API](http-api.md)) and
`streamcatcher play --snapshot` run **fully headless** — no display, no GUI
libraries. Only the live desktop window (`play` without `--snapshot`) needs the
desktop build; on a headless build it exits with a clear message pointing you
back to `opencv-python` rather than a cryptic OpenCV error.

!!! note
    `opencv-python` and `opencv-python-headless` both provide the `cv2` module
    and **cannot be installed together**, so this is an uninstall-then-install
    swap, not an optional extra.

## With the HTTP control API

The [HTTP control API](http-api.md) lives behind an optional extra so the core CLI
stays lean and imports with no web stack:

```console
pip install 'streamcatcher[api]'
```

This adds `fastapi` and `uvicorn`. Everything else — importing the package,
running the CLI, the whole test suite — works without it.

## From a clone (development)

Streamcatcher uses [uv](https://docs.astral.sh/uv/) for development:

```console
git clone https://github.com/ThugipanSivanesan/Streamcatcher
cd Streamcatcher
uv sync --extra api          # environment incl. the optional API extra
uv run streamcatcher --help
```

See [Contributing](contributing.md) for the full development workflow.

## Verify

```console
streamcatcher --help
```

The offline `stub` backend needs nothing beyond the core install and runs fully
offline, so this works even without a camera on hand:

```console
streamcatcher play rtsp://example/stream -b stub   # no-op backend that logs
```

`play` defaults to the `opencv` backend, which opens a real window against a real
stream; pass `-b stub` (as above) for the offline no-op used in development and tests.
