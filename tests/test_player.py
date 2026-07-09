import logging

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


# --- Live VLC-launcher backend --------------------------------------------
#
# The live player launches the installed VLC media player as a subprocess. The
# ``fake_vlc`` fixture (tests/conftest.py) makes VLC appear installed and
# replaces ``subprocess.Popen`` with a spy, so these tests never spawn a real
# VLC window and stay fully offline/headless.


def test_factory_returns_vlc_player_for_vlc_backend(fake_vlc):
    from streamcatcher.player.vlc_player import VlcPlayer

    settings = Settings(stream_url="rtsp://cam/stream", backend=Backend.VLC)
    assert isinstance(get_player(settings), VlcPlayer)


def test_vlc_player_satisfies_player_protocol(fake_vlc):
    from streamcatcher.player.vlc_player import VlcPlayer

    assert isinstance(VlcPlayer("rtsp://cam/stream"), Player)


def test_vlc_player_play_launches_vlc_with_stream_and_buffer_option(fake_vlc):
    from streamcatcher.player.vlc_player import VlcPlayer

    VlcPlayer("rtsp://user:pass@cam/stream").play()

    cmd = fake_vlc.last_command
    assert cmd is not None
    assert "rtsp://user:pass@cam/stream" in cmd
    assert any(arg.startswith("--rtsp-frame-buffer-size=") for arg in cmd)
    # play() blocks on the process, then cleans up.
    assert fake_vlc.last_process.wait_calls == 1


def test_vlc_player_play_stops_on_keyboard_interrupt(fake_vlc):
    from streamcatcher.player.vlc_player import VlcPlayer

    fake_vlc.wait_exc = KeyboardInterrupt()
    VlcPlayer("rtsp://cam/stream").play()  # should swallow the interrupt
    assert fake_vlc.last_process.terminate_calls == 1


def test_vlc_player_is_playing_reflects_process(fake_vlc):
    from streamcatcher.player.vlc_player import VlcPlayer

    player = VlcPlayer("rtsp://cam/stream")
    assert player.is_playing() is False  # nothing launched yet

    player._process = fake_vlc.spawn(["vlc"])
    assert player.is_playing() is True

    player._process.wait()  # simulate VLC exiting
    assert player.is_playing() is False


def test_vlc_player_snapshot_not_supported_in_interim(fake_vlc):
    from streamcatcher.player.vlc_player import VlcPlayer

    with pytest.raises(NotImplementedError):
        VlcPlayer("rtsp://cam/stream").snapshot("shot.png")


def test_vlc_player_missing_vlc_raises_clear_error(monkeypatch):
    import streamcatcher.player.vlc_player as vlc_player

    monkeypatch.setattr(vlc_player.shutil, "which", lambda _name: None)
    # Force the non-macOS path so the local VLC.app install can't satisfy it.
    monkeypatch.setattr(vlc_player.sys, "platform", "linux")

    from streamcatcher.player.vlc_player import VlcMissingError, VlcPlayer

    with pytest.raises(VlcMissingError):
        VlcPlayer("rtsp://cam/stream")


def test_vlc_player_does_not_log_the_url(fake_vlc, caplog):
    from streamcatcher.player.vlc_player import VlcPlayer

    with caplog.at_level(logging.INFO):
        VlcPlayer("rtsp://user:secretpass@cam.local/stream").play()
    assert "secretpass" not in caplog.text
