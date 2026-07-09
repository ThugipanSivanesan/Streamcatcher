"""Player factory — selects a backend from settings.

Defaults to the offline stub. The live libVLC backend (:class:`VlcPlayer`)
lazy-imports ``vlc`` inside its own module, so importing this factory never
requires VLC to be installed — only constructing the live player does.
"""

from __future__ import annotations

from streamcatcher.config import Backend, Settings
from streamcatcher.player.base import Player
from streamcatcher.player.stub_player import StubPlayer
from streamcatcher.player.vlc_player import VlcPlayer


def get_player(settings: Settings) -> Player:
    """Build the player for ``settings.backend`` using its stream URL."""
    if settings.stream_url is None:
        raise ValueError("No stream URL configured.")
    url = settings.stream_url.get_secret_value()

    if settings.backend is Backend.STUB:
        return StubPlayer(url)
    if settings.backend is Backend.VLC:
        return VlcPlayer(url)

    raise NotImplementedError(  # pragma: no cover - defensive: Backend is exhaustive
        f"Backend {settings.backend.value!r} is not supported."
    )
