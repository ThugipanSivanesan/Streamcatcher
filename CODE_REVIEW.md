# Streamcatcher code review — 2026-07-28

Scope: full read of the package (CLI, config, player core, reader, recorder,
reprojection, API layer, CI). Overall a well-built codebase — clean layering
around `StreamSession`, offline-first lazy imports, deliberate secret handling,
and unusually good docstrings. Findings below, ordered by priority.

**Status (2026-07-28):** items 1–5 are fixed on `fix/code-review-1-5`, each with
a regression test verified to fail without its fix, plus the broken local venv
that made item 1's fix invisible (see item 1). Item 8 needed no change (it was
already documented). Items 6, 7 and 9–16 are open. Suite: 215 passed, 0 skipped.

## Bugs worth fixing first

1. ~~**The package version is wrong.**~~ **Fixed.**
   `src/streamcatcher/__init__.py` derived `__version__` from a hardcoded
   `"0.0.1"` while `pyproject.toml` said `0.2.0`, and the FastAPI app reported
   the stale value. It now reads
   `importlib.metadata.version("streamcatcher")`, falling back to
   `0.0.0+unknown` when no distribution metadata is installed.

   ✅ **Environment follow-up — also fixed.** The fix was initially inert here
   because 16 of the console scripts in the project-local `.venv/bin` carried a
   shebang pointing at *another* interpreter:

   ```
   $ head -1 .venv/bin/pytest
   #!/Users/pad/.superset/projects/Streamcatcher/.venv/bin/python
   ```

   `uv run python` execs `.venv/bin/python` (a real binary, so correct), but
   `uv run pytest` execs the *script*, and the shebang wins — so the suite ran
   on a foreign interpreter with foreign `site-packages`. The venv was in a
   mixed state: 16 scripts broken, 11 correct.

   The split this produced is worth recording, because it is easy to
   misdiagnose: `pythonpath = ["src"]` in `pyproject.toml` still prepended
   *this* checkout's source, so `streamcatcher.__file__` was correct and the
   suite genuinely exercised local code — but `importlib.metadata` found no
   `dist-info` under `src/` and fell through to the foreign venv's
   `streamcatcher-0.0.1.dist-info`. Correct code, foreign metadata. Item 1's fix
   is the one change that straddles that seam, which is why it alone broke.

   Fixed by recreating the environment (`rm -rf .venv && uv sync --all-extras`),
   reproducible from the committed `uv.lock`. Zero broken shebangs remain and
   pytest now resolves `0.2.0` from this checkout's own metadata.
   `tests/test_version.py` no longer skips: the old `skipif` was a workaround
   for this exact bug and would have hidden a recurrence, so it is now an
   explicit `test_metadata_comes_from_this_checkout` that fails with the
   recreate command in its message.

2. ~~**The idle reaper can kill a session that's actively being streamed.**~~
   **Fixed.** The MJPEG generator in `src/streamcatcher/api/app.py` now calls
   `managed.touch()` at the top of each `frames()` iteration, so a long-lived
   viewer keeps its own session alive.

3. ~~**Secret redaction forgets earlier sessions' credentials.**~~ **Fixed.**
   `install_secret_redaction` now keeps a single process-wide
   `SecretRedactingFilter` and **accumulates** into it via a new
   `add_secrets()`, instead of building a replacement filter and removing the
   old one. Session A's credentials stay redacted after session B opens. Added
   `reset_secret_redaction()` so tests can isolate the process-wide state.

4. ~~**Reader-thread shutdown can race the capture teardown.**~~ **Fixed.**
   `FrameReader.stop()` now joins in 1-second slices up to a 10-second budget
   and **returns whether the thread actually exited** (it also logs while
   waiting, and warns if it gives up). The player routes every teardown through
   a new `_release_reader()`: on `False` it calls the new
   `StreamSession.abandon()`, which drops the capture reference *without*
   releasing it, so the native object is never released under an in-flight
   `read()`. The capture leaks until process exit — a deliberate trade against a
   possible segfault, and the last resort after a long wait.

   Worth noting the API path never had this bug: `ManagedSession.close()`
   re-acquires the lock the reader holds across `read_frame()`, so it already
   blocked correctly. The fix is GUI-side only.

5. ~~**Session-limit check is racy.**~~ **Fixed.** `SessionManager.create` now
   **reserves a slot** (`self._pending`) under the lock before the blocking
   `open()`, and registers the session while releasing the reservation in a
   single acquisition — so the slot is never double-counted or briefly free.
   A failed open releases its reservation via `finally`, so a stream that won't
   open can't permanently shrink the cap.

## Security tightening

6. **The API accepts any string as a stream URL.** `CreateSessionRequest.url`
   (`src/streamcatcher/api/models.py:18`) is an unvalidated `str`, and the
   factory doesn't validate schemes either — `cv2.VideoCapture` will happily
   open local file paths, `http://` URLs, etc. Anyone with API access can point
   the server at arbitrary local files or internal hosts (SSRF-ish).
   Validate `rtsp://`/`rtmp://` in the model to match the CLI's stated
   contract. (`CODEBASE_NOTES.md` claims the factory "validates the stream
   URL" — it only checks for `None`.)

7. **Bearer-token check isn't constant-time.** `require_token`
   (`src/streamcatcher/api/app.py:76`) compares with `!=`; use
   `secrets.compare_digest`. Low risk on localhost, one-line fix.

8. ~~**`FfmpegRecorder` exposes credentials in the process list.**~~ **No action
   needed — already documented.** The exposure is real (the full `user:pass@`
   URL goes on the ffmpeg command line at
   `src/streamcatcher/player/recorder.py:198`), but the remedy this item asked
   for is already in place: `docs/security.md:19-21` documents it explicitly,
   including that the default `opencv` record mode doesn't spawn a subprocess.
   Left open only if you want to go beyond documenting it.

9. **ffmpeg failures are silent until stop.** `stderr` goes to `DEVNULL` and
   nothing ever polls the process (`src/streamcatcher/player/recorder.py:202-210`),
   so if ffmpeg dies immediately (bad codec for the container, auth failure on
   its own connection), the user records nothing and `stop()` still logs
   "Recording finalized". Cheap fix: have `write()` poll `self._proc` and raise
   `RecordError` once it has exited — the player already handles that path
   gracefully — and capture stderr into a pipe or tempfile for the message.

## Robustness and UX polish

10. **Known errors surface as raw tracebacks in the CLI.** `play` doesn't catch
    `StreamOpenError`, `SnapshotError`, `OrientationError`, or the factory's
    `ValueError` (stub + `--record`), so a wrong URL gives the user a stack
    trace instead of the carefully written friendly messages. A small
    try/except in `cli.py:play` printing the message and exiting 1 would let
    all that good error text land properly.

11. **`Settings` numeric fields are unconstrained.** Negative
    `reconnect_base_delay`, zero `orientation_size`, `record_fps <= 0`, etc.
    pass validation and fail later in confusing ways. Pydantic `Field(gt=0)` /
    `ge=0` constraints are free.

12. **The GUI loop busy-spins.** With `_WAITKEY_MS = 1`, the loop in
    `src/streamcatcher/player/opencv_player.py:127-159` runs ~1000
    iterations/s doing `latest()` + `getWindowProperty` even when no new frame
    arrived — noticeable CPU for a 25/30 fps stream. A slightly larger waitKey
    (5–10 ms) or an adaptive wait when there's no new frame would cut it
    substantially without hurting responsiveness.

13. **API clients can't tell a stream has ended.** In reader mode, after EOF
    the cache serves the last good frame forever
    (`src/streamcatcher/api/sessions.py:100`), and
    `ViewState`/`SessionStateResponse` don't expose liveness. Add an
    `ended`/`is_open` field to the state response — and perhaps a reconnect
    endpoint; API sessions currently have no reconnect at all, unlike the GUI.

14. **Small nits.**
    - `log.info("Backend: %s", ...)` at `src/streamcatcher/cli.py:214` fires
      only after playback *ends* — log it before `play()`.
    - `StreamSession.close()` logs "Stream session closed" even when nothing
      was open.
    - `_on_mouse` re-imports cv2 on every mouse-move event; cache it on the
      instance.
    - `strip_url_credentials` mangles IPv6 hosts (`parts.hostname` drops the
      brackets).

## Housekeeping

15. `.gitignore` covers `streamcatcher-snapshot-*.jpg` but not the newer
    outputs: `streamcatcher-recording-*.mp4` and
    `streamcatcher-orientations-*/`. The untracked `views/` directory with four
    JPEGs in the repo right now is exactly this leak — the artifacts of an
    `--orientations views` run.

16. `CODEBASE_NOTES.md` is stale in several places (says version 0.0.1,
    references a `STREAMCATCHER_SNAPSHOT_DIR` removal task that seems done, and
    the incorrect factory-validation claim) — worth refreshing since it's the
    AI-context file.

## Verification notes

Every finding above was checked against the code before any fix was written.
Two corrections to the original review:

- **Item 8 was already done** (see above).
- **Item 12 is overstated.** The ~1000 iterations/s figure is right, but the
  costly 360 `remap` is already gated behind `new_frame or self._view_dirty`
  (`opencv_player.py:133`); each idle tick only does `latest()` (a lock plus an
  attribute read) and `getWindowProperty`. Real waste, small.
- **Item 13's scope is narrower than it reads.** In the default on-demand mode a
  dead stream yields `None` → 503, so clients *can* detect it. The gap is
  reader mode (`api_reader_enabled=true`), where the cache serves the last good
  frame forever.

Item 4's "segfault" is the worst case rather than the expected one, but the fix
treats it as unacceptable regardless since the alternative is a long wait.

## Remaining work

Next most valuable, in order:

1. **Item 9** (silent ffmpeg failure) — the only remaining finding that loses
   user data with no signal until `stop()` claims success.
2. **Item 10** (raw tracebacks in the CLI) — the one users hit most often, and
   it currently wastes the carefully written error messages already in the code.
3. **Item 6** (unvalidated stream URL) — the only real security finding left
   now that 7 is a one-liner and 8 is documented.
4. Items 7, 11, 14, 15, 16 — small, independent, and each a few lines.
