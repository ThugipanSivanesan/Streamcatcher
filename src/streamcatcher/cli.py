"""Streamcatcher command-line interface."""

from __future__ import annotations

import logging
import os
import time

import typer
from typer.core import TyperCommand

from streamcatcher.config import Backend, Projection, RecordMode, Settings
from streamcatcher.logging_setup import install_secret_redaction
from streamcatcher.player.factory import get_player

app = typer.Typer(
    help="Connect to an RTMP/RTSP stream and view it in a small window.",
    add_completion=False,
    no_args_is_help=True,
)

log = logging.getLogger("streamcatcher")


def _default_snapshot_path() -> str:
    """A timestamped snapshot filename in the current directory."""
    return f"streamcatcher-snapshot-{time.strftime('%Y%m%d-%H%M%S')}.jpg"


def _default_record_path() -> str:
    """A timestamped recording filename in the current directory."""
    return f"streamcatcher-recording-{time.strftime('%Y%m%d-%H%M%S')}.mp4"


def _default_orientations_dir() -> str:
    """A timestamped directory name for a four-orientation split."""
    return f"streamcatcher-orientations-{time.strftime('%Y%m%d-%H%M%S')}"


# Options that take an optional output path/dir: bare use falls back to a
# timestamped default. Each writes to a local path, never a stream URL.
_OPTIONAL_PATH_DEFAULTS = {
    "--snapshot": _default_snapshot_path,
    "--record": _default_record_path,
    "--orientations": _default_orientations_dir,
}

# Schemes a stream URL uses. An output path is always a local path, never a
# stream URL, so a token with one of these schemes right after a bare optional
# option is the URL argument, not that option's path (see below).
_STREAM_URL_SCHEMES = ("rtsp://", "rtmp://")


def _looks_like_stream_url(token: str) -> bool:
    """Whether ``token`` is a stream URL rather than an output path."""
    return token.lower().startswith(_STREAM_URL_SCHEMES)


class _OptionalPathCommand(TyperCommand):
    """Let ``--snapshot``/``--record``/``--orientations`` take a path or be bare flags.

    Typer string options normally require a value. Normalize a bare option to
    an attached default before Click parses it, while leaving ``--opt PATH`` and
    ``--opt=PATH`` untouched.

    An option is treated as bare when it is the last token, when the next token
    is another option (``-``…), or when the next token is the stream URL itself —
    so e.g. ``play --record rtsp://cam/stream`` (option before the URL) uses the
    default path instead of swallowing the URL as the path.
    """

    def parse_args(self, ctx, args):
        normalized = list(args)
        for index, argument in enumerate(normalized):
            default_factory = _OPTIONAL_PATH_DEFAULTS.get(argument)
            if default_factory is None:
                continue
            following = normalized[index + 1] if index + 1 < len(normalized) else None
            is_bare = (
                following is None or following.startswith("-") or _looks_like_stream_url(following)
            )
            if is_bare:
                normalized[index] = f"{argument}={default_factory()}"
        return super().parse_args(ctx, normalized)


@app.callback()
def _cli() -> None:
    """Streamcatcher — connect to an RTMP/RTSP stream and view it in a window."""


@app.command(cls=_OptionalPathCommand)
def play(
    url: str = typer.Argument(
        ..., metavar="URL", help="RTMP or RTSP stream URL (rtsp://… or rtmp://…)."
    ),
    backend: Backend | None = typer.Option(
        None,
        "--backend",
        "-b",
        help="Playback backend: 'opencv' (live OpenCV window, video only) or "
        "'stub' (offline no-op). Defaults to STREAMCATCHER_BACKEND, or 'opencv'.",
    ),
    projection: Projection | None = typer.Option(
        None,
        "--projection",
        "-p",
        help="Frame geometry: 'equirect' reprojects a 360 panorama to a "
        "look-around viewport (W/A/S/D to aim, +/- to zoom); 'flat' shows "
        "frames as-is. Defaults to STREAMCATCHER_PROJECTION, or flat.",
    ),
    reconnect: bool | None = typer.Option(
        None,
        "--reconnect/--no-reconnect",
        help="Auto-reconnect with backoff when the stream drops (default), or "
        "--no-reconnect to exit on the first drop. Defaults to "
        "STREAMCATCHER_RECONNECT_ENABLED.",
    ),
    snapshot: str | None = typer.Option(
        None,
        "--snapshot",
        metavar="[PATH]",
        help="Capture one frame and exit without opening a window. With no PATH, "
        "save a timestamped JPEG in the current directory; otherwise save to "
        "PATH. Respects --projection. During playback, press 'p' instead.",
    ),
    record: str | None = typer.Option(
        None,
        "--record",
        metavar="[PATH]",
        help="Record the stream to a file while playing. With no PATH, save a "
        "timestamped .mp4 in the current directory; otherwise save to PATH. "
        "See --record-mode. Mutually exclusive with --snapshot and --orientations.",
    ),
    record_mode: RecordMode | None = typer.Option(
        None,
        "--record-mode",
        help="How to record: 'opencv' writes the decoded frames (video only, "
        "no audio), 'ffmpeg' copies the original stream losslessly with audio "
        "(needs the ffmpeg binary). Defaults to STREAMCATCHER_RECORD_MODE, or opencv.",
    ),
    duration: float | None = typer.Option(
        None,
        "--duration",
        metavar="SECONDS",
        help="Stop recording (and playback) this many seconds after the first "
        "frame. Requires --record; without it a recording runs until you quit. "
        "Defaults to STREAMCATCHER_RECORD_DURATION.",
    ),
    orientations: str | None = typer.Option(
        None,
        "--orientations",
        metavar="[DIR]",
        help="Split one 360 frame into four flat views (front/right/back/left) "
        "and exit without a window. With no DIR, save into a timestamped folder "
        "in the current directory; otherwise into DIR. Treats the source as a "
        "360 equirectangular panorama. Mutually exclusive with --snapshot and --record.",
    ),
) -> None:
    """Connect to URL and play, record, snapshot one frame, or split four orientations."""
    if snapshot is not None and record is not None:
        raise typer.BadParameter(
            "--snapshot captures a single frame and exits, so it can't be combined "
            "with --record. Use one or the other."
        )
    if snapshot is not None and orientations is not None:
        raise typer.BadParameter(
            "--snapshot and --orientations each capture and exit, so they can't be "
            "combined. Use one or the other."
        )
    if record is not None and orientations is not None:
        raise typer.BadParameter(
            "--orientations captures four views and exits, so it can't be combined "
            "with --record. Use one or the other."
        )
    if duration is not None:
        if record is None:
            raise typer.BadParameter(
                "--duration limits how long --record runs, so it needs --record. "
                "Add --record to capture the stream, or drop --duration."
            )
        if duration <= 0:
            raise typer.BadParameter("--duration must be a positive number of seconds.")
    # Pass flags only when given so the STREAMCATCHER_* env vars still apply as
    # defaults; an explicit flag overrides them.
    overrides: dict[str, object] = {"stream_url": url}
    if backend is not None:
        overrides["backend"] = backend
    elif not any(key.upper() == "STREAMCATCHER_BACKEND" for key in os.environ):
        # No flag and no env var: a human running `play` wants live video, so
        # default to opencv here. The Settings field stays STUB so tests, the
        # library, and `serve` keep the offline-first default.
        overrides["backend"] = Backend.OPENCV
    if projection is not None:
        overrides["projection"] = projection
    if reconnect is not None:
        overrides["reconnect_enabled"] = reconnect
    if record_mode is not None:
        overrides["record_mode"] = record_mode
    if duration is not None:
        overrides["record_duration"] = duration
    settings = Settings(**overrides)
    # Seed redaction with the raw URL so credentials can't leak anywhere in logs.
    install_secret_redaction(settings.secret_values())

    log.info("Connecting to %s", settings.display_url)
    player = get_player(settings, record_path=record)
    if snapshot is not None:
        player.snapshot(snapshot)
    elif orientations is not None:
        player.save_orientations(orientations)
    else:
        player.play()
    log.info("Backend: %s", settings.backend.value)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Address to bind. Defaults to localhost only."),
    port: int = typer.Option(8000, help="Port to listen on."),
    token: str | None = typer.Option(
        None,
        "--token",
        help="Require this bearer token on every request. Defaults to "
        "STREAMCATCHER_API_TOKEN; unset means no auth (localhost only).",
    ),
) -> None:
    """Run the HTTP control API so other programs can drive stream sessions."""
    try:
        import fastapi  # noqa: F401 - presence check for the optional [api] extra
        import uvicorn
    except ModuleNotFoundError:
        typer.secho(
            "The HTTP API needs the optional '[api]' extra. Install it with:\n"
            "    pip install 'streamcatcher[api]'",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1) from None

    from streamcatcher.api.app import create_app

    # Pass --token only when given so STREAMCATCHER_API_TOKEN stays the default.
    overrides: dict[str, object] = {}
    if token is not None:
        overrides["api_token"] = token
    application = create_app(Settings(**overrides))

    log.info("Serving Streamcatcher control API on http://%s:%d", host, port)
    uvicorn.run(application, host=host, port=port, log_level="info")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
