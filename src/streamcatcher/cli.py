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


# Options that take an optional output path: bare use falls back to a timestamped
# default. Both write a local file, never a stream URL.
_OPTIONAL_PATH_DEFAULTS = {
    "--snapshot": _default_snapshot_path,
    "--record": _default_record_path,
}

# Schemes a stream URL uses. An output path is always a local file, never a
# stream URL, so a token with one of these schemes right after a bare optional
# option is the URL argument, not that option's path (see below).
_STREAM_URL_SCHEMES = ("rtsp://", "rtmp://")


def _looks_like_stream_url(token: str) -> bool:
    """Whether ``token`` is a stream URL rather than an output path."""
    return token.lower().startswith(_STREAM_URL_SCHEMES)


class _OptionalPathCommand(TyperCommand):
    """Let ``--snapshot``/``--record`` be used with a path or as bare flags.

    Typer string options normally require a value. Normalize a bare option to
    an attached default before Click parses it, while leaving ``--opt PATH`` and
    ``--opt=PATH`` untouched.

    An option is treated as bare when it is the last token, when the next token
    is another option (``-``…), or when the next token is the stream URL itself —
    so ``play --record rtsp://cam/stream`` (option before the URL) records to the
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
        "See --record-mode. Mutually exclusive with --snapshot.",
    ),
    record_mode: RecordMode | None = typer.Option(
        None,
        "--record-mode",
        help="How to record: 'opencv' writes the decoded frames (video only, "
        "no audio), 'ffmpeg' copies the original stream losslessly with audio "
        "(needs the ffmpeg binary). Defaults to STREAMCATCHER_RECORD_MODE, or opencv.",
    ),
) -> None:
    """Connect to URL and play the stream (optionally recording, or one --snapshot)."""
    if snapshot is not None and record is not None:
        raise typer.BadParameter(
            "--snapshot captures a single frame and exits, so it can't be combined "
            "with --record. Use one or the other."
        )
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
    settings = Settings(**overrides)
    # Seed redaction with the raw URL so credentials can't leak anywhere in logs.
    install_secret_redaction(settings.secret_values())

    log.info("Connecting to %s", settings.display_url)
    player = get_player(settings, record_path=record)
    if snapshot is not None:
        player.snapshot(snapshot)
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
