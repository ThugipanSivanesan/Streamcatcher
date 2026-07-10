# Changelog

All notable changes to Streamcatcher are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The project is pre-1.0 and built in small, tested vertical slices; everything so
far is unreleased (no version has been tagged yet).

## [Unreleased]

### Added

- **Documentation site** — a mkdocs-material site (usage, 360/cameras, Python API,
  HTTP API, architecture, security, and an auto-generated API reference), plus this
  changelog and a contributing guide.
- **Snapshots** — press `p` in the viewer to save the current view to a timestamped
  file, or capture one frame headlessly with `play --snapshot PATH`. Both respect
  the active projection/profile. Use `--snapshot-dir DIR`
  (`STREAMCATCHER_SNAPSHOT_DIR`) to choose where the `p` hotkey writes.
- **Auto-reconnect** — when a live stream drops, the OpenCV backend reconnects with
  exponential backoff (retries forever by default; `--no-reconnect` to opt out).
  The viewport orientation is preserved across a reconnect.
- **HTTP control API** (optional `[api]` extra) — `streamcatcher serve` runs a
  localhost FastAPI server so another program or an AI agent can open sessions,
  drive the look-around, and pull JPEG/MJPEG frames. The stream URL is never echoed
  back; optional bearer-token auth.
- **Camera profiles** — named presets (`ricoh-theta`, `insta360-pro`,
  `generic-360/180/fisheye`, `flat`) that set the projection and mounting offsets.
- **360°, 180°, and fisheye viewports** — pure-NumPy equirectangular→pinhole and
  fisheye→pinhole reprojection into a flat, steerable look-around view
  (`W/A/S/D` or **mouse drag** to aim, `+/-` to zoom).
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

[Unreleased]: https://github.com/ThugipanSivanesan/Streamcatcher/commits/main
