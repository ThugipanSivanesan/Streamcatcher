"""The player interface: a Protocol every backend implements."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Player(Protocol):
    """A stream player: connect, show a window, snapshot, and stop."""

    def play(self) -> None:
        """Open the stream and start playback (blocks for live backends)."""
        ...

    def stop(self) -> None:
        """Stop playback and release resources."""
        ...

    def snapshot(self, path: str) -> None:
        """Save a single still frame to ``path``."""
        ...

    def is_playing(self) -> bool:
        """Whether playback is currently active."""
        ...
