"""Typed, secret-safe configuration for Streamcatcher.

The stream URL is treated as a secret because RTSP/RTMP URLs routinely embed
credentials (``rtsp://user:pass@host``). It is stored as a ``SecretStr`` so it
never prints in reprs/tracebacks, and :meth:`Settings.secret_values` exposes the
plaintext only to seed the log-redaction filter (see ``logging_setup``).
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, populated from ``STREAMCATCHER_*`` environment vars."""

    model_config = SettingsConfigDict(
        env_prefix="STREAMCATCHER_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    stream_url: SecretStr | None = None

    def secret_values(self) -> list[str]:
        """Plaintext secret values, used only to seed log redaction."""
        values: list[str] = []
        if self.stream_url is not None:
            secret = self.stream_url.get_secret_value()
            if secret:
                values.append(secret)
        return values
