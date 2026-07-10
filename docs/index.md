# Streamcatcher

A cross-platform Python CLI that connects to an **RTSP** or **RTMP** video stream
and views it in a small desktop window — including **360° panoramic cameras**,
which it reprojects into a flat pan/tilt/zoom "look-around" viewport. Pure Python,
powered by OpenCV.

The same control core is importable, so another program — or an AI agent — can
open a stream headlessly, drive the look-around, and pull frames over an HTTP API.

!!! note "Status"
    Early development, built in small, tested vertical slices. Live playback, the
    360°/fisheye look-around viewport, named camera profiles, snapshots,
    auto-reconnect, and the HTTP control API all work today. Audio is on the
    roadmap (OpenCV decodes video only).

## What you can do

<div class="grid cards" markdown>

-   :material-monitor: __View any RTSP/RTMP stream__

    Open a live stream in a native window on macOS, Linux, or Windows — no
    external media player required.

    [:octicons-arrow-right-24: CLI usage](usage.md)

-   :material-panorama-sphere: __Look around a 360° camera__

    Reproject an equirectangular panorama, a 180° hemisphere, or a raw fisheye
    lens into a flat viewport you steer with the keyboard.

    [:octicons-arrow-right-24: 360° & cameras](cameras.md)

-   :material-code-braces: __Drive it from Python__

    `StreamSession` gives you open / read / render / look-around / snapshot with
    no window and no keyboard loop.

    [:octicons-arrow-right-24: Python API](python-api.md)

-   :material-api: __Serve it over HTTP__

    Run a localhost control API so another program or an AI agent can open
    sessions, aim the camera, and grab frames.

    [:octicons-arrow-right-24: HTTP control API](http-api.md)

</div>

## Quick start

```console
pip install git+https://github.com/ThugipanSivanesan/Streamcatcher

# View a plain 2D stream
streamcatcher play rtsp://camera.local:554/stream1 -b opencv

# View a 360° camera with a look-around viewport
streamcatcher play rtsp://camera.local/live -b opencv -p equirect
```

In the viewer window: **`W`/`A`/`S`/`D`** aim · **`+`/`-`** zoom · **`p`** snapshot · **`q`** quit.

## Design in one breath

- **Offline-first.** The package and the whole test suite run with no network, no
  credentials, and no live stream. OpenCV is imported lazily, only on the live path.
- **Secrets-safe.** Stream URLs (which may embed `user:pass@host`) are wrapped in
  `SecretStr` and scrubbed from logs by a redacting filter — and never returned by
  the HTTP API.
- **One control core.** The GUI window and the HTTP server both drive the same
  headless [`StreamSession`](reference.md), so the controls live in exactly one place.

See [Architecture](architecture.md) for the full picture.
