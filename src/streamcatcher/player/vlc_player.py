"""Live stream player backed by libVLC (python-vlc).

The ``vlc`` binding is imported lazily inside :func:`_load_vlc` rather than at
module import time, so importing this module — and the player factory — never
requires libVLC to be installed. Only actually constructing a :class:`VlcPlayer`
loads the native library, which lets the rest of the app and the whole test
suite run fully offline.
"""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger("streamcatcher.player.vlc")

# Seconds between playback-state checks while blocking in :meth:`VlcPlayer.play`.
_POLL_INTERVAL = 0.25


class VlcMissingError(RuntimeError):
    """Raised when the libVLC runtime / python-vlc binding cannot be loaded."""


_INSTALL_HINT = (
    "libVLC is required for the live player but could not be loaded. Install the "
    "VLC media player (https://www.videolan.org/vlc/) so the native libVLC library "
    "is available, then reinstall the 'python-vlc' package."
)


def _load_vlc() -> Any:
    """Import and return the ``vlc`` module, or raise :class:`VlcMissingError`."""
    try:
        import vlc  # noqa: PLC0415 (lazy import is intentional — see module docstring)
    except (ImportError, OSError) as exc:  # OSError: binding present but libVLC missing
        raise VlcMissingError(_INSTALL_HINT) from exc
    return vlc


class VlcPlayer:
    """Play a live RTMP/RTSP stream (audio + video) in a libVLC window."""

    def __init__(self, url: str) -> None:
        self._url = url  # secret: embeds credentials, so it is never logged
        self._vlc = _load_vlc()
        instance = self._vlc.Instance()
        if instance is None:  # libVLC failed to initialise (e.g. no codecs found)
            raise VlcMissingError(_INSTALL_HINT)
        self._instance = instance
        self._player = instance.media_player_new()

    def play(self) -> None:
        """Open the stream, start playback, and block until it stops."""
        media = self._instance.media_new(self._url)
        self._player.set_media(media)
        log.info("Opening live stream via libVLC.")
        self._player.play()
        self._wait_until_stopped()

    def _wait_until_stopped(self) -> None:
        """Block while the stream plays; stop cleanly on end or interrupt."""
        try:
            while True:
                # Sleep first so libVLC has a moment to start buffering before the
                # first state check (otherwise is_playing() may still be False).
                time.sleep(_POLL_INTERVAL)
                if not self._player.is_playing():
                    break
        except KeyboardInterrupt:
            log.info("Interrupted — stopping playback.")
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop playback and release the decoder/window."""
        self._player.stop()
        log.info("Live player: stopped.")

    def snapshot(self, path: str) -> None:
        """Save a single still frame from the current video to ``path``."""
        self._player.video_take_snapshot(0, path, 0, 0)
        log.info("Live player: snapshot saved to %s.", path)

    def is_playing(self) -> bool:
        """Whether libVLC currently reports active playback."""
        return bool(self._player.is_playing())
