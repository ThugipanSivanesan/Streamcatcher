# Changelog

All notable changes to Streamcatcher are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The project is pre-1.0 and built in small, tested vertical slices.

## [Unreleased]

## [0.3.0] - 2026-07-28

### Added

- **Recording** — `streamcatcher play --record [PATH]` records a live stream to a
  file while you watch it (bare `--record` writes a timestamped `.mp4` in the
  current directory). Two selectable backends via `--record-mode`: `opencv`
  (default; re-encodes the decoded frames, video only, no extra dependency) and
  `ffmpeg` (`ffmpeg -c copy` — lossless and keeps audio, needs the `ffmpeg`
  binary). In 360 the `opencv` recorder captures the full equirectangular
  panorama, and rolls to a new numbered segment if the stream resolution changes.
  `--record` is mutually exclusive with `--snapshot` and `--orientations`. New
  `STREAMCATCHER_RECORD_*` settings tune the mode, fallback fps, and codec.
- **Timed recording** — `--duration SECONDS` (env `STREAMCATCHER_RECORD_DURATION`)
  caps a recording: playback and recording stop automatically that many seconds
  after the first recorded frame. Works in both record modes and requires
  `--record`; without it a recording runs open-ended until you quit.
- **Four-orientation split** — `streamcatcher play --orientations [DIR]` takes one
  frame from a 360 equirectangular stream and reprojects it into four flat views —
  front, right, back, left — writing `front.jpg`/`right.jpg`/`back.jpg`/`left.jpg`
  and exiting without a window (works headless). Bare `--orientations` writes into a
  timestamped folder; mutually exclusive with `--snapshot` and `--record`. View size
  and field of view are tunable via `STREAMCATCHER_ORIENTATION_SIZE` /
  `STREAMCATCHER_ORIENTATION_HFOV_DEG`. Reuses the existing equirect reprojection;
  an interactive explainer lives at `docs/orientation-split.html`.

### Fixed

- **The reported version could drift from the real one.** `__version__` was a
  hardcoded literal and had fallen behind `pyproject.toml`, so the HTTP API
  advertised a stale version. It is now read from the installed distribution
  metadata, which keeps the version in exactly one place.
- **A long-running MJPEG viewer could have its session reaped mid-stream.** An
  MJPEG client holds a single long request, so nothing marked the session as
  recently used and the idle reaper eventually closed it out from under the
  stream it was serving. The stream now marks its own session as active.
- **Credentials could stop being redacted from logs.** Opening a second stream
  replaced the redaction filter instead of extending it, so the first stream's
  credentials — still in use — were no longer masked. Secrets now accumulate
  into a single filter for the life of the process.
- **Closing a stream could race the background frame reader.** The capture could
  be released while the reader thread was still inside a blocking read, which is
  undefined behaviour in OpenCV's native layer. Shutdown now waits for the
  reader to actually exit, and declines to release the capture if it never does.
  This affected the desktop player only, not the HTTP API.
- **Concurrent requests could exceed the session limit.** Opening several
  sessions at once could overshoot `STREAMCATCHER_API_MAX_SESSIONS`, because
  each request checked the limit before the slow open rather than reserving a
  slot. A failed open no longer permanently shrinks the limit either.
- **The API accepted any string as a stream URL** (security). `POST /session`
  now requires an `rtsp://` or `rtmp://` URL with a host and rejects anything
  else with a 422. Previously the server would open whatever it was given —
  including local file paths and URLs aimed at internal hosts.
- **A failed `--record-mode ffmpeg` recording looked like a success.** If ffmpeg
  exited on its own (an unsupported codec for the container, its own connection
  refused), its output was discarded and nothing noticed, so no file was written
  yet the run still reported "Recording finalized". Such a failure is now
  reported while recording, quoting ffmpeg's own error.
- **Expected errors printed a stack trace.** A stream that wouldn't open, a
  snapshot that couldn't be captured, or `--record` on the `stub` backend
  produced a Python traceback instead of the intended message. `play` now prints
  the message and exits 1; unexpected errors still get a traceback.
- **`.gitignore` missed the newer capture outputs**, so files written by
  `--record` and `--orientations` showed up as untracked.

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

[Unreleased]: https://github.com/ThugipanSivanesan/Streamcatcher/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/ThugipanSivanesan/Streamcatcher/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/ThugipanSivanesan/Streamcatcher/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ThugipanSivanesan/Streamcatcher/releases/tag/v0.1.0
