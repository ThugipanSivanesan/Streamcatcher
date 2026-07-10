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
        help="Frame geometry: 'equirect'/'equirect-180' reproject a 360/hemisphere "
        "panorama and 'fisheye' undistorts a raw lens, each to a look-around "
        "viewport (W/A/S/D to aim, +/- to zoom); 'flat' shows frames as-is. "
        "Defaults to STREAMCATCHER_PROJECTION, or flat.",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Named camera preset (e.g. 'ricoh-theta', 'insta360-pro', "
        "'generic-360', 'generic-180', 'generic-fisheye'). Sets the projection "
        "and any mounting offsets, overriding --projection. Defaults to "
        "STREAMCATCHER_PROFILE.",
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
        metavar="PATH",
        help="Capture a single frame to PATH (e.g. shot.jpg) and exit without "
        "opening a window. Respects --projection/--profile. During live playback, "
        "press 'p' instead to save a timestamped snapshot.",
    ),
    snapshot_dir: str | None = typer.Option(
        None,
        "--snapshot-dir",
        metavar="DIR",
        help="Directory for snapshots saved with the 'p' hotkey during live "
        "playback (created if missing). Defaults to STREAMCATCHER_SNAPSHOT_DIR, "
        "or the current directory.",
    ),
) -> None:
    """Connect to URL and play the stream (or capture one frame with --snapshot)."""
    # Pass flags only when given so the STREAMCATCHER_* env vars still apply as
    # defaults; an explicit flag overrides them.
    overrides: dict[str, object] = {"stream_url": url}
    if backend is not None:
        overrides["backend"] = backend
    if projection is not None:
        overrides["projection"] = projection
    if profile is not None:
        overrides["profile"] = profile
    if snapshot_dir is not None:
        overrides["snapshot_dir"] = snapshot_dir
    if reconnect is not None:
        overrides["reconnect_enabled"] = reconnect
    settings = Settings(**overrides)
    # Seed redaction with the raw URL so credentials can't leak anywhere in logs.
    install_secret_redaction(settings.secret_values())

    log.info("Connecting to %s", settings.display_url)
    player = get_player(settings)
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
