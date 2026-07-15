import logging
import os

from typer.testing import CliRunner

from streamcatcher.cli import app

runner = CliRunner()


def test_play_backend_stub_exits_cleanly(caplog):
    with caplog.at_level(logging.INFO):
        result = runner.invoke(app, ["play", "rtsp://cam.local:554/stream1", "-b", "stub"])
    assert result.exit_code == 0
    assert "cam.local" in caplog.text
    assert "stub" in caplog.text


def test_play_defaults_to_opencv_without_flag_or_env(fake_cv2, caplog):
    # No --backend flag and no STREAMCATCHER_BACKEND env var: `play` should pick
    # the live opencv backend, not the offline stub.
    with caplog.at_level(logging.INFO):
        result = runner.invoke(app, ["play", "rtsp://cam.local/stream1", "--no-reconnect"])
    assert result.exit_code == 0
    assert fake_cv2.last_capture is not None  # the live player opened the stream
    assert fake_cv2.last_capture.url == "rtsp://cam.local/stream1"
    assert "opencv" in caplog.text


def test_play_backend_env_var_overrides_opencv_default(caplog):
    # An explicit env var still wins over the play-command opencv default.
    with caplog.at_level(logging.INFO):
        result = runner.invoke(
            app,
            ["play", "rtsp://cam.local/stream1"],
            env={"STREAMCATCHER_BACKEND": "stub"},
        )
    assert result.exit_code == 0
    assert "stub" in caplog.text


def test_play_does_not_leak_credentials(caplog):
    with caplog.at_level(logging.INFO):
        result = runner.invoke(
            app, ["play", "rtsp://alice:hunter2@cam.local:554/stream1", "-b", "stub"]
        )
    assert result.exit_code == 0
    combined = caplog.text + result.output
    assert "hunter2" not in combined
    assert "alice" not in combined
    assert "cam.local" in caplog.text  # sanitized host is still shown


def test_play_backend_opencv_uses_live_player(fake_cv2, caplog):
    with caplog.at_level(logging.INFO):
        result = runner.invoke(
            app, ["play", "rtsp://cam.local/stream1", "--backend", "opencv", "--no-reconnect"]
        )
    assert result.exit_code == 0
    assert fake_cv2.last_capture is not None
    assert fake_cv2.last_capture.url == "rtsp://cam.local/stream1"
    assert "opencv" in caplog.text
    assert "Opening live stream with OpenCV" in caplog.text


def test_play_projection_equirect_enables_360_viewport(fake_cv2, caplog):
    with caplog.at_level(logging.INFO):
        result = runner.invoke(
            app,
            [
                "play",
                "rtsp://cam.local/stream1",
                "-b",
                "opencv",
                "-p",
                "equirect",
                "--no-reconnect",
            ],
        )
    assert result.exit_code == 0
    assert fake_cv2.remap_calls == fake_cv2.frames  # frames were reprojected
    assert "360 viewport" in caplog.text


def test_play_profile_selects_a_camera_and_reprojects(fake_cv2, caplog):
    with caplog.at_level(logging.INFO):
        result = runner.invoke(
            app,
            [
                "play",
                "rtsp://cam.local/stream1",
                "-b",
                "opencv",
                "--profile",
                "generic-360",
                "--no-reconnect",
            ],
        )
    assert result.exit_code == 0
    assert fake_cv2.remap_calls == fake_cv2.frames  # equirect profile reprojected


def test_play_unknown_profile_fails(fake_cv2):
    result = runner.invoke(
        app,
        ["play", "rtsp://cam.local/stream1", "-b", "opencv", "--profile", "no-such-cam"],
    )
    assert result.exit_code != 0


def test_play_snapshot_flag_captures_one_frame_without_a_window(fake_cv2, tmp_path, caplog):
    path = str(tmp_path / "shot.jpg")
    with caplog.at_level(logging.INFO):
        result = runner.invoke(
            app, ["play", "rtsp://cam.local/stream1", "-b", "opencv", "--snapshot", path]
        )
    assert result.exit_code == 0
    assert fake_cv2.imwrite_calls == 1  # a still was written
    assert fake_cv2.written[0][0] == path
    assert fake_cv2.imshow_calls == 0  # no playback window was opened
    assert "Snapshot saved to" in caplog.text


def test_play_snapshot_dir_flag_sets_hotkey_destination(fake_cv2, tmp_path):
    fake_cv2.keys = [ord("p")]  # press 'p' during live playback
    result = runner.invoke(
        app,
        [
            "play",
            "rtsp://cam.local/stream1",
            "-b",
            "opencv",
            "--snapshot-dir",
            str(tmp_path),
            "--no-reconnect",
        ],
    )
    assert result.exit_code == 0
    assert fake_cv2.imwrite_calls == 1
    saved_path = fake_cv2.written[0][0]
    assert os.path.dirname(saved_path) == str(tmp_path)  # hotkey snapshot landed in the flag dir
    assert os.path.basename(saved_path).startswith("streamcatcher-snapshot-")


def test_play_requires_a_url():
    result = runner.invoke(app, ["play"])
    assert result.exit_code != 0


def test_no_args_shows_help():
    result = runner.invoke(app, [])
    assert result.exit_code != 0
    assert "Usage" in result.output
