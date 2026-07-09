"""Streamcatcher command-line interface."""

from __future__ import annotations

import logging

import typer

from streamcatcher.config import Backend, Projection, Settings
from streamcatcher.logging_setup import install_secret_redaction
from streamcatcher.player.factory import get_player

app = typer.Typer(
    help="Connect to an RTMP/RTSP stream and view it in a small window.",
    add_completion=False,
    no_args_is_help=True,
)

log = logging.getLogger("streamcatcher")


@app.callback()
def _cli() -> None:
    """Streamcatcher — connect to an RTMP/RTSP stream and view it in a window."""


@app.command()
def play(
    url: str = typer.Argument(
        ..., metavar="URL", help="RTMP or RTSP stream URL (rtsp://… or rtmp://…)."
    ),
    backend: Backend | None = typer.Option(
        None,
        "--backend",
        "-b",
        help="Playback backend: 'opencv' (live OpenCV window, video only) or "
        "'stub' (offline). Defaults to STREAMCATCHER_BACKEND, or the offline stub.",
    ),
    projection: Projection | None = typer.Option(
        None,
        "--projection",
        "-p",
        help="Frame geometry: 'equirect' reprojects a 360 equirectangular stream "
        "to a look-around viewport (W/A/S/D to aim, +/- to zoom); 'flat' shows "
        "frames as-is. Defaults to STREAMCATCHER_PROJECTION, or flat.",
    ),
) -> None:
    """Connect to URL and play the stream."""
    # Pass ``backend``/``projection`` only when given so the STREAMCATCHER_* env
    # vars still apply as defaults; an explicit flag overrides them.
    overrides: dict[str, object] = {"stream_url": url}
    if backend is not None:
        overrides["backend"] = backend
    if projection is not None:
        overrides["projection"] = projection
    settings = Settings(**overrides)
    # Seed redaction with the raw URL so credentials can't leak anywhere in logs.
    install_secret_redaction(settings.secret_values())

    log.info("Connecting to %s", settings.display_url)
    player = get_player(settings)
    player.play()
    log.info("Backend: %s", settings.backend.value)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
