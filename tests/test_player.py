import pytest

from streamcatcher.config import Backend, Settings
from streamcatcher.player.base import Player
from streamcatcher.player.factory import get_player
from streamcatcher.player.stub_player import StubPlayer


def test_factory_returns_stub_by_default():
    settings = Settings(stream_url="rtsp://cam.local/stream")
    assert isinstance(get_player(settings), StubPlayer)


def test_factory_requires_a_url(monkeypatch):
    monkeypatch.delenv("STREAMCATCHER_STREAM_URL", raising=False)
    with pytest.raises(ValueError):
        get_player(Settings())


def test_factory_vlc_backend_not_yet_available():
    settings = Settings(stream_url="rtsp://cam/stream", backend=Backend.VLC)
    with pytest.raises(NotImplementedError):
        get_player(settings)


def test_stub_satisfies_player_protocol():
    assert isinstance(StubPlayer("rtsp://cam/stream"), Player)


def test_stub_player_lifecycle():
    player = StubPlayer("rtsp://cam/stream")
    assert player.is_playing() is False

    player.play()
    assert player.is_playing() is True

    player.snapshot("shot.png")
    assert player.last_snapshot == "shot.png"

    player.stop()
    assert player.is_playing() is False


def test_stub_player_does_not_log_the_url(caplog):
    import logging

    with caplog.at_level(logging.INFO):
        StubPlayer("rtsp://user:secretpass@cam.local/stream").play()
    assert "secretpass" not in caplog.text
