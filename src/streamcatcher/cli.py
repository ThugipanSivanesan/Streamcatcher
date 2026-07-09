"""Streamcatcher command-line interface."""

from __future__ import annotations

import logging

import typer

from streamcatcher.config import Settings
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
) -> None:
    """Connect to URL and play the stream."""
    settings = Settings(stream_url=url)
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
