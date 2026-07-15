# Architecture

Streamcatcher is small, but deliberately layered so the same logic serves a
desktop window, a headless script, and an HTTP server without duplication.

## Offline-first, secrets-safe

Two principles shape everything:

- **Offline-first.** Importing the package touches no network, no window, and no
  decoder. OpenCV (`cv2`) is imported *lazily*, inside `StreamSession.open()` — so
  the CLI, the factory, and the entire test suite import and run with OpenCV
  absent. The default `stub` backend does nothing but log, which keeps development
  and CI fully offline. The web stack (`fastapi`, `uvicorn`) is likewise imported
  only inside `create_app`.
- **Secrets-safe.** A stream URL can embed `user:pass@host`, so it's treated as a
  secret end to end (see [Security](security.md)).

## The layers

```
        CLI (Typer)                 HTTP API (FastAPI, optional extra)
     play  │  serve                 create_app → routes
           │                                  │
   ┌───────┴────────┐                         │
   │  Player factory │                        │
   └───────┬────────┘                         │
     ┌─────┴─────┐                            │
     │  backends │  StubPlayer / OpenCvPlayer │
     └─────┬─────┘        (window + keys)     │
           └──────────────┬───────────────────┘
                          ▼
                   StreamSession                ← the one control core
              open · read · render · look ·
              snapshot · reconnect · state
                          │
             ┌────────────┴─────────────┐
             ▼                          ▼
       reprojection               reconnect
       (pure NumPy)               (backoff)
```

### `StreamSession` — the control core

[`StreamSession`](python-api.md) owns the OpenCV capture and the optional 360
viewport and exposes *programmatic* controls with **no window and no keyboard
loop**. Both the GUI player and the HTTP server drive it, so open / read / render /
look-around / snapshot / reconnect logic lives in exactly one place.

### Backends and the factory

A tiny [`Player`][streamcatcher.player.base.Player] protocol (`play` / `stop` /
`snapshot` / `is_playing`) has two implementations:

- **`StubPlayer`** — the offline default; records requests instead of doing them.
- **`OpenCvPlayer`** — a *thin* shell over `StreamSession` that adds a native
  window, the `waitKey` loop, and the keyboard bindings (`W/A/S/D`, `+/-`, `p`, `q`).

The factory picks one from `Settings.backend`. Because the OpenCV backend
lazy-loads `cv2` inside `play()`, importing the factory never needs OpenCV.

### Reprojection

[`reprojection.py`][streamcatcher.player.reprojection] builds `cv2.remap` lookup
tables with **pure NumPy** — equirectangular→pinhole — so the geometry is
deterministic, GPU-free, and unit-testable without a live stream. See
[360° & cameras](cameras.md) for the math. Maps are cached and rebuilt only when
the view moves.

### Reconnect

[`reconnect.py`][streamcatcher.player.reconnect] is a pure module: a frozen
`ReconnectPolicy` and an infinite exponential-backoff generator. `StreamSession`
exposes `reconnect()`; the OpenCV backend wires the retry loop into its frame
loop, staying responsive to `q` / window-close between waits. The viewport
orientation survives a reconnect.

## Configuration

[`Settings`][streamcatcher.config.Settings] (pydantic-settings) is populated from
`STREAMCATCHER_*` environment variables, with CLI flags overriding them only when
passed. The stream URL is a `SecretStr`; `display_url` is the credential-stripped
form safe to log.

## Tooling choices

- **CLI:** [Typer](https://typer.tiangolo.com/).
- **Config & models:** [pydantic](https://docs.pydantic.dev/) / pydantic-settings.
- **Video & remap:** [OpenCV](https://opencv.org/) + NumPy.
- **HTTP:** [FastAPI](https://fastapi.tiangolo.com/) + uvicorn (optional).
- **Dev:** [uv](https://docs.astral.sh/uv/), [ruff](https://docs.astral.sh/ruff/),
  [pytest](https://docs.pytest.org/); see [Contributing](contributing.md).
