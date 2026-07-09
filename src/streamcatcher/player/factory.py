"""Player factory — selects a backend from settings.

Defaults to the offline stub. The live libVLC backend is added in a later slice;
it will lazy-import ``vlc`` inside its own module so importing this factory never
requires VLC to be installed.
"""

from __future__ import annotations

from streamcatcher.config import Backend, Settings
from streamcatcher.player.base import Player
from streamcatcher.player.stub_player import StubPlayer


def get_player(settings: Settings) -> Player:
    """Build the player for ``settings.backend`` using its stream URL."""
    if settings.stream_url is None:
        raise ValueError("No stream URL configured.")
    url = settings.stream_url.get_secret_value()

    if settings.backend is Backend.STUB:
        return StubPlayer(url)

    raise NotImplementedError(f"Backend {settings.backend.value!r} is not available yet.")
