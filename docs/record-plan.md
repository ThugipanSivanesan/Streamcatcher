# Implementation plan — recording live streams

Status: **implemented** on branch `feat/record-stream`. This doc is kept as the
design record; a few details below were refined during implementation — see
"Refinements during implementation" at the end.

Adds the ability to record a live stream to a file during `streamcatcher play`,
via a pluggable `Recorder` with two selectable backends:

- `--record-mode opencv` — tee the already-decoded frames into a
  `cv2.VideoWriter`. No new dependency; **video only, re-encoded**.
- `--record-mode ffmpeg` — spawn `ffmpeg -c copy` alongside the capture to copy
  the original stream losslessly, **with audio**. Requires the `ffmpeg` binary on
  `PATH`.

CLI shape:

```
streamcatcher play URL --record [PATH] [--record-mode opencv|ffmpeg]
```

Like `--snapshot`, `--record` takes an optional path; with none it writes a
timestamped file in the current directory (`.mp4`).

---

## 1. Scope

**In scope**

- A `Recorder` protocol + `OpenCvRecorder` + `FfmpegRecorder`.
- Recording as an add-on to `play()` (the live window loop).
- CLI flags, `Settings` fields, factory wiring, and full test coverage.
- Docs + changelog.

**Out of scope (call out as follow-ups)**

- Recording from the HTTP API (`serve`) — see §9.
- Headless / windowless recording — see §9. (`ffmpeg` mode technically needs no
  window, but v1 launches recording from `play()`, which opens one.)
- Segmenting/rotating files by size or time; scheduled/timed recordings.

---

## 2. Design

### 2.1 `Recorder` protocol — `src/streamcatcher/player/recorder.py` (new)

Mirror the existing `Player` Protocol style (`player/base.py`).

```python
@runtime_checkable
class Recorder(Protocol):
    def start(self, sample_frame, fps: float | None) -> None:
        """Open the output. `sample_frame` supplies width/height; `fps` may be None."""
    def write(self, frame) -> None:
        """Append one frame (opencv) or a no-op (ffmpeg copies the stream itself)."""
    def stop(self) -> None:
        """Finalize and close the output. Safe to call more than once."""
    def is_recording(self) -> bool: ...
```

Plus `class RecordError(RuntimeError)` and `class FfmpegNotFoundError(RecordError)`.

Rationale for `start(sample_frame, fps)` rather than opening in `__init__`: a
`cv2.VideoWriter` needs the frame size, which is only known once the first frame
arrives (the just-opened decoder can return empty reads first — see
`session.py:41-43`). Deferring the open also lets the player construct the
recorder before the stream is up.

### 2.2 `OpenCvRecorder`

- Wraps `cv2.VideoWriter(path, fourcc, fps, (w, h))`.
- `cv2` imported lazily via the existing `_load_cv2()` (`session.py:61`) so
  importing the module never needs OpenCV, consistent with the rest of `player/`.
- **fps**: live captures frequently report `CAP_PROP_FPS == 0`. Resolution:
  the player passes `cap.get(CAP_PROP_FPS)` when > 0, else `None`; the recorder
  falls back to `Settings.record_fps` (default 25). Wrong fps only affects
  playback speed of the file, not data integrity.
- **fourcc**: `Settings.record_fourcc` (default `"mp4v"`, container `.mp4`).
- **What it records**: the **raw** decoded frame off `FrameReader.latest()` —
  i.e. the full frame as received (the entire equirect panorama in 360 mode),
  *not* the reprojected look-around viewport. See §6 for why.
- **Resolution changes on reconnect**: if a reconnect returns a different frame
  size, `VideoWriter` silently drops mismatched frames. Handle it in the player
  (§4): on reconnect, `stop()` the recorder and `start()` a new one; the new
  segment gets a `-002`, `-003`… suffix. Document this as expected behavior.

### 2.3 `FfmpegRecorder`

- Independent of OpenCV: it opens its **own** connection to the URL, so it
  records the original elementary streams (video **and** audio) with no re-encode.
- `write()` is a no-op — ffmpeg pulls the stream itself.
- Startup: `shutil.which("ffmpeg")`; if absent, raise `FfmpegNotFoundError` with
  an actionable message (how to install ffmpeg). Do this in `start()`.
- Command (draft):
  ```
  ffmpeg -nostdin? NO — we need stdin for graceful stop; use:
  ffmpeg -y -rtsp_transport tcp -i <URL> -c copy -f <mux> <path>
  ```
  For resilience on network drops add `-reconnect 1 -reconnect_streamed 1
  -reconnect_delay_max 30` (mirrors the existing backoff cap,
  `Settings.reconnect_max_delay`).
- **Graceful stop is mandatory for `.mp4`**: killing ffmpeg with `SIGKILL`
  leaves an unfinalized container (no moov atom → unplayable). `stop()` sends
  `q\n` to ffmpeg's stdin (or `SIGINT`), then `wait(timeout=…)`, escalating to
  `terminate()` then `kill()` only if it hangs.
- **URL redaction**: the URL is already redacted from logs
  (`install_secret_redaction`, `cli.py:126`); never log the ffmpeg argv. Security
  caveat: the URL (with credentials) is visible in the process list (`ps`) for
  the ffmpeg mode — document in `docs/security.md` and §8 here.

---

## 3. Config — `src/streamcatcher/config.py`

Add a `RecordMode` enum next to `Backend`/`Projection` (`config.py:18-29`):

```python
class RecordMode(StrEnum):
    OPENCV = "opencv"   # cv2.VideoWriter, video-only, re-encoded
    FFMPEG = "ffmpeg"   # ffmpeg -c copy, lossless, with audio
```

Add fields to `Settings` (after the reconnect block, ~`config.py:62`):

```python
record_mode: RecordMode = RecordMode.OPENCV
record_fps: int = 25          # fallback when the stream doesn't report fps (opencv mode)
record_fourcc: str = "mp4v"   # cv2.VideoWriter codec (opencv mode)
```

The output path is a CLI concern (not persisted in `Settings`), matching how
`--snapshot` passes its path straight to the player rather than through
`Settings`.

---

## 4. Player wiring — `src/streamcatcher/player/opencv_player.py`

`OpenCvPlayer.__init__` (`opencv_player.py:71`) gains
`recorder: Recorder | None = None`, stored as `self._recorder`.

In `play()` (`opencv_player.py:86-141`):

- After the first `raw` frame is available, lazily `self._recorder.start(raw,
  fps)` where `fps = cap.get(CAP_PROP_FPS) or None`. (Needs a small accessor on
  `StreamSession`, e.g. `capture_fps()`, since `_cap` is private.)
- On each **new** raw frame (the existing `raw is not self._last_raw` branch,
  `opencv_player.py:116`), call `self._recorder.write(raw)`. Writing the raw
  frame — not `self._last_frame` (the rendered viewport) — keeps recording
  decoupled from display cadence and from mouse look (§6).
- In `_reconnect` handling (`opencv_player.py:127-135`): `self._recorder.stop()`
  before reconnecting and re-`start()` after, so a resolution change starts a new
  segment.
- In the `finally` block (`opencv_player.py:138-141`): `self._recorder.stop()`
  so the file is finalized on quit / window close / `KeyboardInterrupt`.

`ffmpeg` mode: `write()` is a no-op, but `start()`/`stop()` still bracket the
subprocess lifecycle, so the same call sites work for both backends.

Add a log line on start ("Recording to %s (mode: %s)") and on stop, using the
redacted path (path is local, safe to log).

---

## 5. CLI — `src/streamcatcher/cli.py`

Add to `play` (`cli.py:73-108`):

```python
record: str | None = typer.Option(None, "--record", metavar="[PATH]", help=...)
record_mode: RecordMode | None = typer.Option(None, "--record-mode", help=...)
```

- **Optional-path parsing**: generalize `_OptionalSnapshotPathCommand`
  (`cli.py:41-65`) to also normalize a bare `--record` to
  `--record=<timestamped .mp4>`. Cleanest: rename it to
  `_OptionalPathCommand` and drive it from a small table
  `{"--snapshot": _default_snapshot_path, "--record": _default_record_path}`.
- Add `_default_record_path()` →
  `f"streamcatcher-recording-{time.strftime('%Y%m%d-%H%M%S')}.mp4"`.
- **Validation**: `--record` + `--snapshot` are mutually exclusive (snapshot is
  one-frame-and-exit). Raise `typer.BadParameter` if both are set.
- Thread `record_mode` into `overrides` only when given (same env-var-friendly
  pattern as `backend`/`projection`, `cli.py:113-123`).
- Pass the record path to the player. Since the path isn't in `Settings`, either
  (a) pass it to `get_player(settings, record_path=…)`, or (b) build the recorder
  in the CLI and inject it. Prefer routing through the factory (§7) for symmetry
  with backend selection.

---

## 6. Decision: record the raw frame, not the look-around viewport

For `opencv` mode in 360 the recorder writes the **full equirect panorama**
(the raw frame), not the cropped viewport the user is looking at.

- A faithful archive shouldn't follow the operator's mouse; you want the whole
  panorama so you can re-aim in review.
- It keeps the two modes consistent: `ffmpeg -c copy` also records the raw
  original.
- Rendering every frame (`session.render()` → `cv2.remap`, `session.py:168-176`)
  just to record it would burn CPU the display loop deliberately avoids
  (`opencv_player.py:114-116`).

Rejected alternative: a `--record-view` flag to capture the rendered viewport
instead. Note it as a possible future option; not in v1.

---

## 7. Factory — `src/streamcatcher/player/factory.py`

`get_player` (`factory.py:17`) gains `record_path: str | None = None` and reads
`settings.record_mode`. For `Backend.OPENCV`, when `record_path` is set, build
the matching recorder and pass it to `OpenCvPlayer(..., recorder=…)`:

```python
recorder = build_recorder(settings.record_mode, record_path, settings, url)
```

`build_recorder` lives in `recorder.py`. `Backend.STUB` ignores recording (or
raises a clear "recording needs the opencv backend" error — TBD, see §10).

---

## 8. Edge cases & failure modes

| Case | Handling |
|---|---|
| Stream reports `fps == 0` | Fall back to `record_fps` (opencv). |
| Resolution changes on reconnect (opencv) | `stop()` + new segment file (`-002`…). |
| `ffmpeg` binary missing | `FfmpegNotFoundError` with install hint, fail fast in `start()`. |
| Unwritable path / bad extension | `RecordError`; player logs and stops recording (keep playing? see §10). |
| `--record` + `--snapshot` together | `typer.BadParameter` at parse time. |
| Ctrl-C / window closed | `finally` → `recorder.stop()` finalizes the file. |
| `ffmpeg` mp4 finalization | Graceful stop via stdin `q` / SIGINT, never SIGKILL first. |
| Credentials in `ps` (ffmpeg mode) | Documented security caveat in `docs/security.md`. |
| Disk fills mid-record | Surfaced as `RecordError` on the next write / ffmpeg exit; log and stop. |

---

## 9. Follow-ups (explicitly not in v1)

- **Headless recording**: allow `--record` without opening a window (esp.
  `ffmpeg` mode, which never touches highgui). Natural next slice for servers.
- **Recording via `serve`**: a `POST /record` on the HTTP API
  (`api/app.py`), reusing the same `Recorder`.
- File segmentation by time/size; timed/scheduled recordings.
- `--record-view` (capture the reprojected viewport).

---

## 10. Open questions for review

1. **STUB backend + `--record`**: silently ignore, or hard error? (Leaning:
   error — recording implies a real stream.)
2. **A recorder failure mid-playback**: keep playing with a warning (recording
   is best-effort, like snapshots at `opencv_player.py:240-243`), or abort
   playback? (Leaning: warn + keep playing.)
3. **Default container/codec**: `.mp4` + `mp4v` is the safe, widely-playable
   default for opencv mode. OK? (ffmpeg mode infers the muxer from the path
   extension.)
4. **`--record-mode` default**: `opencv` (zero-dependency, always works) vs
   `ffmpeg` (better output but needs the binary). Leaning `opencv` as default.

---

## 11. Test plan

Extend the fake cv2 and add focused suites; the suite stays fully offline
(`tests/conftest.py`).

**`tests/conftest.py`** — extend `_FakeCv2`:
- `VideoWriter(path, fourcc, fps, size)` → a `_FakeVideoWriter` recording
  `written_frames`, `isOpened()`, `release()`.
- `VideoWriter_fourcc(*chars)` and `CAP_PROP_FPS` constant.
- `_FakeCapture.get(prop)` returning a scriptable fps.

**`tests/test_recorder.py`** (new):
- `OpenCvRecorder.start` opens the writer with the sample frame's `(w, h)` and
  the given fps; falls back to `record_fps` when fps is `None`.
- `write` forwards frames; `stop` releases and is idempotent.
- `FfmpegRecorder`: monkeypatch `shutil.which` + `subprocess.Popen`; assert argv
  contains `-i <url>`, `-c copy`, the output path, and reconnect flags; assert
  `stop()` sends `q`/SIGINT and waits; assert missing binary → `FfmpegNotFoundError`.

**`tests/test_player.py`**: `play()` with an injected fake recorder — `start`
called once with the first frame, `write` called per new frame, `stop` called in
`finally`; recorder re-`start`ed across a reconnect.

**`tests/test_cli.py`**: `--record` builds a recorder; bare `--record` →
timestamped default path; `--record` + `--snapshot` → error; `--record-mode`
parses and overrides.

**`tests/test_config.py`**: `RecordMode` + new fields parse from
`STREAMCATCHER_RECORD_*` env vars.

---

## 12. File-by-file change summary

| File | Change |
|---|---|
| `src/streamcatcher/player/recorder.py` | **New** — `Recorder` protocol, `OpenCvRecorder`, `FfmpegRecorder`, `build_recorder`, `RecordError`, `FfmpegNotFoundError`. |
| `src/streamcatcher/config.py` | `RecordMode` enum; `record_mode`/`record_fps`/`record_fourcc` fields (~`:18`, `:62`). |
| `src/streamcatcher/cli.py` | `--record`/`--record-mode` options; generalize `_OptionalSnapshotPathCommand`; `_default_record_path`; mutual-exclusion check; wiring (`:41`, `:73`, `:129`). |
| `src/streamcatcher/player/opencv_player.py` | `recorder` ctor arg; `start`/`write`/`stop` in `play()` + reconnect + `finally` (`:71`, `:112`, `:127`, `:138`). |
| `src/streamcatcher/player/session.py` | small `capture_fps()` accessor. |
| `src/streamcatcher/player/factory.py` | `record_path` param; build + inject the recorder (`:17`). |
| `tests/conftest.py` | fake `VideoWriter` + fps plumbing. |
| `tests/test_recorder.py` | **New** — recorder unit tests. |
| `tests/test_player.py`, `test_cli.py`, `test_config.py` | recording coverage. |
| `docs/usage.md`, `docs/security.md`, `CHANGELOG.md` | document `--record`, the ffmpeg-binary requirement, the `ps` credential caveat, and an `Unreleased → Added` entry. |

---

## Refinements during implementation

- **Reconnect handling simplified.** Instead of the player calling
  `stop()`/`start()` around a reconnect, `OpenCvRecorder.write()` detects a
  frame-size change itself and rolls to a new numbered segment. This decouples
  recording from the reconnect path entirely (§4 no longer touches the recorder
  on reconnect) and keeps `ffmpeg` mode running continuously across an OpenCV
  drop, letting ffmpeg handle its own reconnection.
- **Open questions (§10) resolved:** (1) `--record` on the stub backend raises a
  clear `ValueError` in the factory; (2) a recorder failure mid-playback logs a
  warning and keeps playing (recording is best-effort); (3) default
  `--record-mode` is `opencv`; (4) default container/codec is `.mp4` / `mp4v`.
- **Tests:** `tests/test_recorder.py` (both backends, with a fake `cv2` and a
  fake `subprocess`/`shutil.which`), plus recording cases added to
  `test_player.py`, `test_cli.py`, and `test_config.py`. Full suite green,
  `ruff` clean.
