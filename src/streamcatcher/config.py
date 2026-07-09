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
