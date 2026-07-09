"""Shared test fixtures.

The ``fake_vlc`` fixture injects a stand-in ``vlc`` module into ``sys.modules``
so the live player's lazy ``import vlc`` picks it up. This keeps the whole suite
runnable offline and headless (e.g. in CI) without libVLC installed.
"""

import sys

import pytest


class _FakeMediaPlayer:
    def __init__(self) -> None:
        self.media: object | None = None
        self._playing = False
        self.play_calls = 0
        self.stop_calls = 0
        self.snapshots: list[str] = []
        # Optional scripted return values for ``is_playing`` — each call pops the
        # next value, letting a test drive the blocking playback loop.
        self.play_states: list[int] | None = None

    def set_media(self, media: object) -> None:
        self.media = media

    def play(self) -> int:
        self.play_calls += 1
        self._playing = True
        return 0

    def stop(self) -> None:
        self.stop_calls += 1
        self._playing = False

    def is_playing(self) -> int:
        if self.play_states is not None:
            return self.play_states.pop(0) if self.play_states else 0
        return 1 if self._playing else 0

    def video_take_snapshot(self, num: int, path: str, width: int, height: int) -> int:
        self.snapshots.append(path)
        return 0


class _FakeInstance:
    def __init__(self) -> None:
        self.player = _FakeMediaPlayer()
        self.medias: list[str] = []

    def media_player_new(self) -> _FakeMediaPlayer:
        return self.player

    def media_new(self, url: str) -> tuple[str, str]:
        self.medias.append(url)
        return ("media", url)


class _FakeVlc:
    def __init__(self) -> None:
        self.instance = _FakeInstance()

    def Instance(self, *args: object, **kwargs: object) -> _FakeInstance:  # noqa: N802 (vlc API)
        return self.instance


@pytest.fixture
def fake_vlc(monkeypatch):
    """Inject a fake ``vlc`` module and neutralise the playback poll sleep."""
    fake = _FakeVlc()
    monkeypatch.setitem(sys.modules, "vlc", fake)

    import streamcatcher.player.vlc_player as vlc_player

    monkeypatch.setattr(vlc_player.time, "sleep", lambda _seconds: None)
    return fake
