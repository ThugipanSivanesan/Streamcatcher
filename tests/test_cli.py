import logging
import re
from pathlib import Path

from typer.testing import CliRunner

from streamcatcher.cli import app

runner = CliRunner()

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """Strip ANSI colour codes so rich splits option names back into substrings.

    Typer's rich help/error output colours each option name, breaking e.g.
    ``--snapshot`` into separate escape spans, so a literal ``"--snapshot" in
    output`` check fails on the raw string. Strip the codes first.
    """
    return _ANSI.sub("", text)


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
    assert fake_cv2.imwrite_calls == 0  # no snapshot unless --snapshot is passed
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
    assert fake_cv2.remap_calls >= 1  # frames were reprojected (stale ones dropped)
    assert "360 viewport" in caplog.text


def test_play_snapshot_flag_captures_one_frame_without_a_window(fake_cv2, tmp_path, caplog):
    target = tmp_path / "captures" / "shot.jpg"
    with caplog.at_level(logging.INFO):
        result = runner.invoke(
            app,
            ["play", "rtsp://cam.local/stream1", "-b", "opencv", "--snapshot", str(target)],
        )
    assert result.exit_code == 0
    assert fake_cv2.imwrite_calls == 1  # a still was written
    assert fake_cv2.written[0][0] == str(target)
    assert target.parent.is_dir()
    assert fake_cv2.imshow_calls == 0  # no playback window was opened
    assert "Snapshot saved to" in caplog.text


def test_play_snapshot_accepts_equals_path(fake_cv2, tmp_path):
    target = tmp_path / "shot.jpg"
    result = runner.invoke(
        app,
        [
            "play",
            "rtsp://cam.local/stream1",
            "-b",
            "opencv",
            f"--snapshot={target}",
        ],
    )
    assert result.exit_code == 0
    assert fake_cv2.written[0][0] == str(target)


def test_play_snapshot_without_path_defaults_to_current_directory(fake_cv2, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        [
            "play",
            "rtsp://cam.local/stream1",
            "-b",
            "opencv",
            "--snapshot",
            "--no-reconnect",
        ],
    )
    assert result.exit_code == 0
    assert fake_cv2.imwrite_calls == 1
    saved_path = Path(fake_cv2.written[0][0])
    assert saved_path.resolve().parent == tmp_path.resolve()
    assert saved_path.name.startswith("streamcatcher-snapshot-")
    assert saved_path.suffix == ".jpg"
    assert fake_cv2.imshow_calls == 0


def test_play_bare_snapshot_before_url_defaults_and_keeps_the_url(fake_cv2, tmp_path, monkeypatch):
    # A bare --snapshot placed before the positional URL must not swallow the
    # URL as its path: the stream URL is recognised and the snapshot defaults.
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["play", "--snapshot", "rtsp://cam.local/stream1", "-b", "opencv"],
    )
    assert result.exit_code == 0
    assert fake_cv2.last_capture.url == "rtsp://cam.local/stream1"  # URL parsed, not consumed
    assert fake_cv2.imwrite_calls == 1
    saved_path = Path(fake_cv2.written[0][0])
    assert saved_path.name.startswith("streamcatcher-snapshot-")
    assert saved_path.resolve().parent == tmp_path.resolve()
    assert fake_cv2.imshow_calls == 0  # snapshot mode, no window


def test_play_bare_snapshot_before_rtmp_url_defaults(fake_cv2, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["play", "--snapshot", "rtmp://cam.local/live", "-b", "opencv"],
    )
    assert result.exit_code == 0
    assert fake_cv2.last_capture.url == "rtmp://cam.local/live"
    assert fake_cv2.imwrite_calls == 1
    assert Path(fake_cv2.written[0][0]).name.startswith("streamcatcher-snapshot-")


def test_play_explicit_snapshot_path_before_url_is_honored(fake_cv2, tmp_path):
    # An explicit path before the URL is still taken as the path, not defaulted.
    target = tmp_path / "shot.jpg"
    result = runner.invoke(
        app,
        ["play", "--snapshot", str(target), "rtsp://cam.local/stream1", "-b", "opencv"],
    )
    assert result.exit_code == 0
    assert fake_cv2.last_capture.url == "rtsp://cam.local/stream1"
    assert fake_cv2.written[0][0] == str(target)


def test_play_rejects_removed_snapshot_dir_option(tmp_path):
    result = runner.invoke(
        app,
        [
            "play",
            "rtsp://cam.local/stream1",
            "--snapshot-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 2
    output = _plain(result.output)
    assert "No such option" in output
    assert "--snapshot-dir" in output


def test_play_help_only_lists_snapshot_option():
    result = runner.invoke(app, ["play", "--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "--snapshot" in output
    assert "--snapshot-dir" not in output


def test_play_requires_a_url():
    result = runner.invoke(app, ["play"])
    assert result.exit_code != 0


def test_no_args_shows_help():
    result = runner.invoke(app, [])
    assert result.exit_code != 0
    assert "Usage" in result.output
