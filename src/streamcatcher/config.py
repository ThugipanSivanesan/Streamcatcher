"""Typed, secret-safe configuration for Streamcatcher.

The stream URL is treated as a secret because RTSP/RTMP URLs routinely embed
credentials (``rtsp://user:pass@host``). It is stored as a ``SecretStr`` so it
never prints in reprs/tracebacks, and :meth:`Settings.secret_values` exposes the
plaintext only to seed the log-redaction filter (see ``logging_setup``).
"""

from __future__ import annotations

from enum import StrEnum
from urllib.parse import urlsplit, urlunsplit

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Backend(StrEnum):
    """Playback backend that the player factory dispatches on."""

    STUB = "stub"  # offline default: no window, deterministic, used by tests
    OPENCV = "opencv"  # live OpenCV player (video only, owns its own window)


class Projection(StrEnum):
    """How the player interprets each frame's geometry."""

    FLAT = "flat"  # ordinary rectilinear video — shown as-is
    EQUIRECT = "equirect"  # 360 equirectangular panorama — reprojected to a viewport


class RecordMode(StrEnum):
    """How ``streamcatcher play --record`` writes the stream to disk."""

    OPENCV = "opencv"  # cv2.VideoWriter over the decoded frames — video only, re-encoded
    FFMPEG = "ffmpeg"  # `ffmpeg -c copy` subprocess — lossless, keeps audio, needs the binary


def strip_url_credentials(url: str) -> str:
    """Return ``url`` with any ``user:pass@`` userinfo removed (host/port kept)."""
    parts = urlsplit(url)
    if parts.username or parts.password:
        host = parts.hostname or ""
        if parts.port is not None:
            host = f"{host}:{parts.port}"
        parts = parts._replace(netloc=host)
    return urlunsplit(parts)


class Settings(BaseSettings):
    """Runtime settings, populated from ``STREAMCATCHER_*`` environment vars."""

    model_config = SettingsConfigDict(
        env_prefix="STREAMCATCHER_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    stream_url: SecretStr | None = None
    backend: Backend = Backend.STUB
    projection: Projection = Projection.FLAT

    # Auto-reconnect (live OpenCV backend). On a dropped stream the player
    # retries forever with exponential backoff until it returns or the user
    # quits; disable to exit on the first drop (e.g. for a finite source).
    reconnect_enabled: bool = True
    reconnect_base_delay: float = 1.0  # seconds before the first retry
    reconnect_backoff_factor: float = 2.0  # multiply the wait after each failure
    reconnect_max_delay: float = 30.0  # cap on the backoff wait, in seconds

    # Recording (`streamcatcher play --record`). The output path is a CLI
    # argument, not a setting; these tune how the recorder writes.
    record_mode: RecordMode = RecordMode.OPENCV  # opencv (video only) or ffmpeg (lossless + audio)
    record_fps: float = 25.0  # fallback frame rate when the stream doesn't report one (opencv)
    record_fourcc: str = "mp4v"  # cv2.VideoWriter codec fourcc (opencv mode)
    # Optional cap on recording length, in seconds. None (the default) records
    # until playback stops (q / window close / Ctrl-C); a positive value stops
    # the recording — and playback — that many seconds after the first frame.
    record_duration: float | None = None

    # HTTP control API (`streamcatcher serve`). All optional; sensible for a
    # single-user, localhost-bound control surface.
    api_token: SecretStr | None = None  # when set, require this bearer token on every route
    api_idle_timeout: int = 300  # seconds of inactivity before a session is reaped
    api_max_sessions: int = 8  # cap on concurrent sessions, to bound resource use
    api_stream_fps: int = 10  # frame rate cap for the MJPEG stream
    # Optional per-session background reader: when enabled, a thread keeps the
    # latest frame cached so requests don't block on cap.read(). Off by default,
    # which keeps the on-demand read behaviour.
    api_reader_enabled: bool = False
    api_reader_fps: int = 30  # reader refresh-rate cap when enabled

    def secret_values(self) -> list[str]:
        """Plaintext credentials from the stream URL, to seed log redaction.

        Returns the embedded password and username (if any) — the sensitive
        parts of an ``rtsp://user:pass@host`` URL — rather than the whole URL,
        so the non-secret host can still be logged.
        """
        if self.stream_url is None:
            return []
        parts = urlsplit(self.stream_url.get_secret_value())
        return [value for value in (parts.password, parts.username) if value]

    @property
    def display_url(self) -> str | None:
        """The stream URL with credentials stripped — safe to log or print."""
        if self.stream_url is None:
            return None
        return strip_url_credentials(self.stream_url.get_secret_value())
