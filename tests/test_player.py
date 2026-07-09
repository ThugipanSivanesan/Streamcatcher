import logging
import sys

import pytest

from streamcatcher.config import Backend, Settings
from streamcatcher.player.base import Player
from streamcatcher.player.factory import get_player
from streamcatcher.player.stub_player import StubPlayer

# The ``fake_vlc`` fixture lives in tests/conftest.py.


def test_factory_returns_stub_by_default():
    settings = Settings(stream_url="rtsp://cam.local/stream")
    assert isinstance(get_player(settings), StubPlayer)


def test_factory_requires_a_url(monkeypatch):
    monkeypatch.delenv("STREAMCATCHER_STREAM_URL", raising=False)
    with pytest.raises(ValueError):
        get_player(Settings())


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
    with caplog.at_level(logging.INFO):
        StubPlayer("rtsp://user:secretpass@cam.local/stream").play()
    assert "secretpass" not in caplog.text


# --- Live libVLC backend ---------------------------------------------------
#
# These tests never touch the real ``vlc`` module or libVLC: the ``fake_vlc``
# fixture (tests/conftest.py) injects a stand-in into ``sys.modules`` so the
# live player's lazy ``import vlc`` picks it up, keeping the suite offline.


def test_factory_returns_vlc_player_for_vlc_backend(fake_vlc):
    from streamcatcher.player.vlc_player import VlcPlayer

    settings = Settings(stream_url="rtsp://cam/stream", backend=Backend.VLC)
    assert isinstance(get_player(settings), VlcPlayer)


def test_vlc_player_satisfies_player_protocol(fake_vlc):
    from streamcatcher.player.vlc_player import VlcPlayer

    assert isinstance(VlcPlayer("rtsp://cam/stream"), Player)


def test_vlc_player_play_opens_stream_and_blocks_until_stopped(fake_vlc):
    from streamcatcher.player.vlc_player import VlcPlayer

    fake_vlc.instance.player.play_states = [1, 1, 0]
    player = VlcPlayer("rtsp://user:pass@cam/stream")
    player.play()

    assert fake_vlc.instance.medias == ["rtsp://user:pass@cam/stream"]
    assert fake_vlc.instance.player.play_calls == 1
    # play() blocks until playback ends, then releases the player.
    assert fake_vlc.instance.player.stop_calls == 1


def test_vlc_player_play_stops_on_keyboard_interrupt(fake_vlc, monkeypatch):
    import streamcatcher.player.vlc_player as vlc_player

    def _interrupt(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(vlc_player.time, "sleep", _interrupt)

    player = vlc_player.VlcPlayer("rtsp://cam/stream")
    player.play()  # should swallow KeyboardInterrupt and stop cleanly
    assert fake_vlc.instance.player.stop_calls == 1


def test_vlc_player_stop_releases(fake_vlc):
    from streamcatcher.player.vlc_player import VlcPlayer

    player = VlcPlayer("rtsp://cam/stream")
    player.stop()
    assert fake_vlc.instance.player.stop_calls == 1


def test_vlc_player_snapshot(fake_vlc):
    from streamcatcher.player.vlc_player import VlcPlayer

    player = VlcPlayer("rtsp://cam/stream")
    player.snapshot("shot.png")
    assert fake_vlc.instance.player.snapshots == ["shot.png"]


def test_vlc_player_is_playing_reflects_backend(fake_vlc):
    from streamcatcher.player.vlc_player import VlcPlayer

    player = VlcPlayer("rtsp://cam/stream")
    assert player.is_playing() is False
    fake_vlc.instance.player._playing = True
    assert player.is_playing() is True


def test_vlc_player_missing_libvlc_raises_clear_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _fail_vlc_import(name, *args, **kwargs):
        if name == "vlc":
            raise OSError("cannot load libvlc; VLC is not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "vlc", raising=False)
    monkeypatch.setattr(builtins, "__import__", _fail_vlc_import)

    from streamcatcher.player.vlc_player import VlcMissingError, VlcPlayer

    with pytest.raises(VlcMissingError):
        VlcPlayer("rtsp://cam/stream")


def test_vlc_player_does_not_log_the_url(fake_vlc, caplog):
    from streamcatcher.player.vlc_player import VlcPlayer

    fake_vlc.instance.player.play_states = [0]
    with caplog.at_level(logging.INFO):
        VlcPlayer("rtsp://user:secretpass@cam.local/stream").play()
    assert "secretpass" not in caplog.text
