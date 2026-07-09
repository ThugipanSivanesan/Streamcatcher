import logging

from typer.testing import CliRunner

from streamcatcher.cli import app

runner = CliRunner()


def test_play_selects_stub_and_exits_cleanly(caplog):
    with caplog.at_level(logging.INFO):
        result = runner.invoke(app, ["play", "rtsp://cam.local:554/stream1"])
    assert result.exit_code == 0
    assert "cam.local" in caplog.text
    assert "stub" in caplog.text


def test_play_does_not_leak_credentials(caplog):
    with caplog.at_level(logging.INFO):
        result = runner.invoke(app, ["play", "rtsp://alice:hunter2@cam.local:554/stream1"])
    assert result.exit_code == 0
    combined = caplog.text + result.output
    assert "hunter2" not in combined
    assert "alice" not in combined
    assert "cam.local" in caplog.text  # sanitized host is still shown


def test_play_backend_vlc_uses_live_player(fake_vlc, caplog):
    with caplog.at_level(logging.INFO):
        result = runner.invoke(app, ["play", "rtsp://cam.local/stream1", "--backend", "vlc"])
    assert result.exit_code == 0
    assert fake_vlc.last_command is not None
    assert "rtsp://cam.local/stream1" in fake_vlc.last_command
    assert "vlc" in caplog.text
    assert "Launching VLC" in caplog.text


def test_play_requires_a_url():
    result = runner.invoke(app, ["play"])
    assert result.exit_code != 0


def test_no_args_shows_help():
    result = runner.invoke(app, [])
    assert result.exit_code != 0
    assert "Usage" in result.output
