# HTTP control API

Streamcatcher can run a small **localhost HTTP API** so another program — or an AI
agent — can open a stream, drive the look-around, and pull frames. The motivating
scenario: point a vision model at a 360 camera, let it aim the view and grab
stills, and answer questions like *"is there a blue wall?"*.

It's an optional extra so the core CLI stays lean:

```console
pip install 'streamcatcher[api]'
```

## Running the server

```console
streamcatcher serve                                    # binds 127.0.0.1:8000
streamcatcher serve --host 0.0.0.0 --port 9000 --token changeme
```

| Option | Default | Meaning |
|---|---|---|
| `--host` | `127.0.0.1` | Bind address (localhost only by default) |
| `--port` | `8000` | Port to listen on |
| `--token` | — (`STREAMCATCHER_API_TOKEN`) | Require `Authorization: Bearer <token>` on every request |

Interactive OpenAPI docs are served at **`/docs`** — an agent-readable schema of
every endpoint.

!!! warning "Security posture"
    The server binds `127.0.0.1` by default. When a token is unset there is **no
    auth** (relying on the localhost bind); set `--token` (or
    `STREAMCATCHER_API_TOKEN`) before exposing it more widely. Stream URLs and
    their credentials are **never** returned in any response. See
    [Security](security.md).

## Endpoints

| Method & path | Purpose |
|---|---|
| `POST /session` | Open a session for a stream URL; returns an id + state (**the URL is never echoed back**). `201` |
| `GET /sessions` | List open session ids. |
| `GET /session/{id}/state` | Current projection and viewport orientation. |
| `GET /session/{id}/frame` | Current look-around viewport as a JPEG — how an agent "sees" now. |
| `GET /session/{id}/panorama` | Raw, pre-reprojection frame as a JPEG (the full field of view). |
| `GET /session/{id}/stream.mjpg` | MJPEG stream of the viewport (fps-capped). |
| `POST /session/{id}/look` | Pan/tilt/zoom by `{pan, tilt, zoom}` degree deltas. |
| `POST /session/{id}/look/{action}` | Discrete step: `pan_left`, `pan_right`, `tilt_up`, `tilt_down`, `zoom_in`, `zoom_out`. |
| `DELETE /session/{id}` | Close the session. `204` |

Status codes: unknown session id → `404`; unknown profile name → `422`; unknown
discrete action → `404`; too many sessions → `429`; the stream won't open → `502`.

Sessions are reaped after an idle timeout (default 300s) and capped in number
(default 8); tune with `STREAMCATCHER_API_IDLE_TIMEOUT`,
`STREAMCATCHER_API_MAX_SESSIONS`, and `STREAMCATCHER_API_STREAM_FPS`.

By default each frame request reads on demand. Set
`STREAMCATCHER_API_READER_ENABLED=true` to give every session a background reader
thread that keeps the latest frame cached (refresh rate capped by
`STREAMCATCHER_API_READER_FPS`, default 30), so `/frame` and `/panorama` return
the cached frame instead of blocking on a read. After a drop the cache holds the
last good frame until the stream returns.

## Walkthrough

Open a session, aim the camera, and grab the view an agent would reason over:

=== "curl"

    ```console
    # 1. Open a session (the URL is not echoed back)
    curl -sX POST localhost:8000/session \
      -H 'Content-Type: application/json' \
      -d '{"url": "rtsp://user:pass@camera.local/live", "projection": "equirect"}'
    # -> {"id":"a1b2c3","projection":"equirect","yaw_deg":0.0,"pitch_deg":0.0,"hfov_deg":100.0}

    # 2. Look right and up
    curl -sX POST localhost:8000/session/a1b2c3/look \
      -H 'Content-Type: application/json' -d '{"pan": 45, "tilt": 15}'

    # 3. Grab the current viewport as a JPEG
    curl -s localhost:8000/session/a1b2c3/frame -o view.jpg

    # 4. Close it
    curl -sX DELETE localhost:8000/session/a1b2c3
    ```

=== "Python (requests)"

    ```python
    import requests

    base = "http://localhost:8000"

    # 1. Open a session — the URL is accepted but never returned
    r = requests.post(f"{base}/session", json={
        "url": "rtsp://user:pass@camera.local/live",
        "projection": "equirect",
    })
    sid = r.json()["id"]

    # 2. Aim the virtual camera
    requests.post(f"{base}/session/{sid}/look", json={"pan": 45, "tilt": 15})
    requests.post(f"{base}/session/{sid}/look/zoom_in")

    # 3. Pull the frame the agent should reason over
    frame = requests.get(f"{base}/session/{sid}/frame").content  # JPEG bytes

    # 4. Done
    requests.delete(f"{base}/session/{sid}")
    ```

With a token set, add `-H 'Authorization: Bearer changeme'` (or
`headers={"Authorization": "Bearer changeme"}`) to every request.

## How it's built

Route handlers are plain synchronous `def`, so Starlette runs them in its thread
pool and a blocking `cap.read()` never stalls the event loop. Frames are read
**on demand** under a per-session lock by default; enabling the background reader
(above) instead has a per-session thread keep the latest frame cached. A single
background task reaps idle sessions. The server is a thin shell over the same
headless [`StreamSession`](python-api.md) the GUI uses.
