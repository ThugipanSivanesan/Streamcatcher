# Changelog

All notable changes to Streamcatcher are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The project is pre-1.0 and built in small, tested vertical slices.

## [Unreleased]

### Added

- **Recording** — `streamcatcher play --record [PATH]` records a live stream to a
  file while you watch it (bare `--record` writes a timestamped `.mp4` in the
  current directory). Two selectable backends via `--record-mode`: `opencv`
  (default; re-encodes the decoded frames, video only, no extra dependency) and
  `ffmpeg` (`ffmpeg -c copy` — lossless and keeps audio, needs the `ffmpeg`
  binary). In 360 the `opencv` recorder captures the full equirectangular
  panorama, and rolls to a new numbered segment if the stream resolution changes.
  `--record` and `--snapshot` are mutually exclusive. New `STREAMCATCHER_RECORD_*`
  settings tune the mode, fallback fps, and codec.

## [0.2.0] - 2026-07-21

### Added

- **Headless / server support** — documented the `opencv-python-headless` swap so
  `streamcatcher serve` and `streamcatcher play --snapshot` run on machines with no
  display or GUI system libraries (`libGL.so.1` on Linux). A CI smoke job now
  exercises the headless build.

### Changed

- `play`'s live window now exits with a clear, actionable message when run against a
  headless OpenCV build, instead of dying on a cryptic highgui `cv2.error`. The
  window is also created before the network connection, so headless machines fail
  fast without first opening the stream.

## [0.1.0] - 2026-07-21

First release on PyPI: `pip install streamcatcher`.

### Added

- **Documentation site** — a mkdocs-material site (usage, 360/cameras, Python API,
  HTTP API, architecture, security, and an auto-generated API reference), plus this
  changelog and a contributing guide.
- **Snapshots** — press `p` in the viewer to save the current view to a timestamped
  file, or capture one frame headlessly with `play --snapshot`, optionally passing
  an exact output path. Both respect the active projection; snapshots default to
  the current directory.
- **Auto-reconnect** — when a live stream drops, the OpenCV backend reconnects with
  exponential backoff (retries forever by default; `--no-reconnect` to opt out).
  The viewport orientation is preserved across a reconnect.
- **HTTP control API** (optional `[api]` extra) — `streamcatcher serve` runs a
  localhost FastAPI server so another program or an AI agent can open sessions,
  drive the look-around, and pull JPEG/MJPEG frames. The stream URL is never echoed
  back; optional bearer-token auth. An optional per-session background reader
  (`STREAMCATCHER_API_READER_ENABLED`) keeps the latest frame cached so requests
  don't block on a read.
- **360° equirectangular viewport** — pure-NumPy equirectangular→pinhole
  reprojection into a flat, steerable look-around view (`W/A/S/D` or **mouse drag**
  to aim, `+/-` to zoom).
- **Live OpenCV player** — view RTSP/RTMP streams in a native window from a plain
  Python CLI on macOS, Linux, and Windows (video only, no audio). RTSP is forced
  over TCP.
- **CLI skeleton** — `streamcatcher play` with an offline `stub` backend, typed
  `STREAMCATCHER_*` configuration, and a `SecretStr` stream URL with log redaction.
- **Secure project baseline** — CI secret scanning (gitleaks, GitGuardian) and
  dependency vulnerability scanning (osv-scanner), pre-commit hooks, and a
  TDD/branch-per-slice workflow.

### Changed

- Playback backend moved from libVLC to **OpenCV**, which owns its own native
  window without an external media player (fixes a macOS windowing blocker). This
  made playback **video-only** — audio is no longer in scope.

[Unreleased]: https://github.com/ThugipanSivanesan/Streamcatcher/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/ThugipanSivanesan/Streamcatcher/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ThugipanSivanesan/Streamcatcher/releases/tag/v0.1.0
