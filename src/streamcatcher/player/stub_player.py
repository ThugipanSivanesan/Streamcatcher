"""Offline stub player — the default backend.

Implements the :class:`~streamcatcher.player.base.Player` interface without any
window, decoder, or network, so the app and the whole test suite run fully
offline. It records what it was asked to do rather than doing it.
"""

from __future__ import annotations

import logging

log = logging.getLogger("streamcatcher.player.stub")


class StubPlayer:
    """A no-op player that records requests instead of touching a stream."""

    def __init__(self, url: str) -> None:
        self._url = url  # held for parity with live backends; never logged
        self._playing = False
        self.last_snapshot: str | None = None
        self.last_orientations: str | None = None

    def play(self) -> None:
        self._playing = True
        log.info("Stub player: pretending to play the stream (offline backend).")

    def stop(self) -> None:
        self._playing = False
        log.info("Stub player: stopped.")

    def snapshot(self, path: str) -> None:
        self.last_snapshot = path
        log.info("Stub player: snapshot requested at %s (no-op).", path)

    def save_orientations(self, out_dir: str) -> None:
        self.last_orientations = out_dir
        log.info("Stub player: orientation split requested at %s (no-op).", out_dir)

    def is_playing(self) -> bool:
        return self._playing
