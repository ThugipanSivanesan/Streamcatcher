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


def test_play_backend_opencv_uses_live_player(fake_cv2, caplog):
    with caplog.at_level(logging.INFO):
        result = runner.invoke(app, ["play", "rtsp://cam.local/stream1", "--backend", "opencv"])
    assert result.exit_code == 0
    assert fake_cv2.last_capture is not None
    assert fake_cv2.last_capture.url == "rtsp://cam.local/stream1"
    assert "opencv" in caplog.text
    assert "Opening live stream with OpenCV" in caplog.text


def test_play_projection_equirect_enables_360_viewport(fake_cv2, caplog):
    with caplog.at_level(logging.INFO):
        result = runner.invoke(
            app,
            ["play", "rtsp://cam.local/stream1", "-b", "opencv", "-p", "equirect"],
        )
    assert result.exit_code == 0
    assert fake_cv2.remap_calls == fake_cv2.frames  # frames were reprojected
    assert "360 viewport" in caplog.text


def test_play_profile_selects_a_camera_and_reprojects(fake_cv2, caplog):
    with caplog.at_level(logging.INFO):
        result = runner.invoke(
            app,
            ["play", "rtsp://cam.local/stream1", "-b", "opencv", "--profile", "generic-360"],
        )
    assert result.exit_code == 0
    assert fake_cv2.remap_calls == fake_cv2.frames  # equirect profile reprojected


def test_play_unknown_profile_fails(fake_cv2):
    result = runner.invoke(
        app,
        ["play", "rtsp://cam.local/stream1", "-b", "opencv", "--profile", "no-such-cam"],
    )
    assert result.exit_code != 0


def test_play_requires_a_url():
    result = runner.invoke(app, ["play"])
    assert result.exit_code != 0


def test_no_args_shows_help():
    result = runner.invoke(app, [])
    assert result.exit_code != 0
    assert "Usage" in result.output
