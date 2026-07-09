# Streamcatcher

A cross-platform Python CLI that connects to an **RTMP** or **RTSP** stream and
plays it (audio + video) in a small, positionable window — with snapshot capture
and resilient reconnection, built securely from commit #1.

> **Status:** early development. Slice 0 (secure baseline) is in place; the CLI
> and playback are being built up in small, tested vertical slices. See
> [`docs/plan.html`](docs/plan.html) for the full build plan.

## Planned usage

```console
streamcatcher play rtsp://camera.local:554/stream1
streamcatcher play rtmp://live.example/app/key --width 640 --height 360 --x 40 --y 40
streamcatcher play rtsp://cam/stream --snapshot shot.png   # grab one frame, exit
# while a window is open: press 's' to save a snapshot, 'q' to quit
```

## Design at a glance

- **Playback:** [python-vlc](https://pypi.org/project/python-vlc/) (libVLC) — robust
  RTMP + RTSP with audio, self-managed window, tolerant of stream hiccups.
- **CLI:** [Typer](https://typer.tiangolo.com/).
- **Offline-first:** the package and the entire test suite run with no network,
  no credentials, and no live stream; libVLC is lazy-imported only on the live
  path.
- **Secrets:** stream URLs (which may embed `user:pass@host`) are wrapped in
  `SecretStr` and scrubbed from logs by a redacting filter.

## System requirement

libVLC (the VLC runtime) must be installed on the machine:

- **macOS:** `brew install --cask vlc`
- **Debian/Ubuntu:** `sudo apt install vlc`
- **Windows:** install VLC from <https://www.videolan.org/>

## Development

Requires [uv](https://docs.astral.sh/uv/).

```console
uv sync                       # create the environment
uv run ruff check .           # lint
uv run ruff format --check .  # format check
uv run pytest                 # tests (offline, no credentials)
pre-commit install            # enable local hooks
pre-commit run --all-files    # run all hooks
```

## License

[MIT](LICENSE)
