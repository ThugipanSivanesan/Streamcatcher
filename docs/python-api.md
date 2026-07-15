# Python API

The importable heart of Streamcatcher is
[`StreamSession`][streamcatcher.player.session.StreamSession] — a **headless**
control core: open a stream, read and render frames, look around a
360 viewport, snapshot, and close, all with **no window and no keyboard loop**. The
GUI player and the HTTP server are both thin shells over it.

```python
from streamcatcher import StreamSession
```

!!! note "OpenCV is loaded lazily"
    Importing `streamcatcher` pulls in NumPy and pydantic but **not** OpenCV —
    `cv2` is imported only when you call `open()`. So importing the package is
    safe in environments without OpenCV; opening a stream is what needs it.

## Open, read, close

```python
from streamcatcher import StreamSession

session = StreamSession("rtsp://user:pass@camera.local/stream1")
session.open()                     # loads cv2, opens the capture (raises on failure)
try:
    frame = session.read_frame()   # a raw BGR ndarray, or None when the stream ends
    if frame is not None:
        view = session.render(frame)   # reproject in 360 modes; pass-through when flat
finally:
    session.close()                # safe to call more than once
```

`open()` raises [`StreamOpenError`][streamcatcher.player.session.StreamOpenError] if
the capture can't be opened (bad URL, network, or credentials). It forces RTSP over
TCP to reduce dropped high-resolution frames.

## Look around a 360 stream

Pass a `projection` to get a steerable viewport. `grab_view()` combines a read and
a render:

```python
from streamcatcher import StreamSession
from streamcatcher.config import Projection

session = StreamSession("rtsp://camera.local/live", projection=Projection.EQUIRECT)
session.open()

session.pan_right()          # discrete steps…
session.tilt_up()
session.zoom_in()
session.look(pan=30, tilt=-10, zoom=-15)   # …or explicit degree deltas

view = session.grab_view()   # read + reproject the current viewport
print(session.state())       # ViewState(projection='equirect', yaw_deg=…, pitch_deg=…, hfov_deg=…)
```

`look()`'s `zoom` is a horizontal-FOV **delta**: negative narrows the view (zooms
in), positive widens it. In flat mode the look controls are no-ops and `state()`
reports `None` orientation fields.

## Snapshots

```python
session.snapshot("shot.jpg")            # grab the current viewport and write it
```

`snapshot()` retries a few reads while a just-opened decoder warms up, renders the
frame (reprojected in 360, raw when flat), and writes it with `cv2.imwrite`,
creating parent directories as needed. It raises
[`SnapshotError`][streamcatcher.player.session.SnapshotError] if no frame arrives or
the file can't be written. To write a frame you already have in hand, use
`write_snapshot(frame, path)`.

## Reconnect

```python
if session.read_frame() is None:        # the stream dropped
    if session.reconnect():             # tear down + reopen; keeps the viewport orientation
        ...                             # back in business
```

`reconnect()` returns `False` (rather than raising) when the stream still can't be
opened, so you can back off and retry. See
[`ReconnectPolicy`][streamcatcher.player.reconnect.ReconnectPolicy] for the backoff
schedule the GUI player uses.

## The `Player` backends

If you want the *windowed* player rather than the headless core, the backends
implement a small [`Player`][streamcatcher.player.base.Player] protocol
(`play` / `stop` / `snapshot` / `is_playing`):

```python
from streamcatcher.player.opencv_player import OpenCvPlayer

player = OpenCvPlayer("rtsp://cam/live", projection=Projection.EQUIRECT)
player.play()          # blocks: opens a window and pumps frames until you quit
```

The full signatures are in the [API reference](reference.md).
