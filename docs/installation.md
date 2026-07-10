# Installation

Streamcatcher requires **Python 3.12+** and is not on PyPI yet, so install it
straight from source.

## Core CLI

```console
pip install git+https://github.com/ThugipanSivanesan/Streamcatcher
```

This pulls in `opencv-python` for the live viewer — **no separate system media
player (VLC, an ffmpeg app, …) is required**. OpenCV opens and pumps its own
native window from a plain Python process, including on macOS.

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

The default `stub` backend needs nothing beyond the core install and runs fully
offline, so this works even without a camera on hand:

```console
streamcatcher play rtsp://example/stream   # stub backend: a no-op that logs
```

Pass `-b opencv` to open a real window against a real stream.
