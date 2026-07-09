"""Shared test fixtures.

The ``fake_vlc`` fixture makes the live player believe VLC is installed and
replaces ``subprocess.Popen`` with a spy, so tests exercise the VLC-launcher
backend without spawning a real VLC window. This keeps the suite offline and
headless (e.g. in CI).
"""

import pytest


class _FakeProcess:
    """Stand-in for the VLC subprocess handle."""

    def __init__(self, cmd: list[str], wait_exc: BaseException | None = None) -> None:
        self.cmd = cmd
        self._running = True
        self.wait_calls = 0
        self.terminate_calls = 0
        self._wait_exc = wait_exc

    def wait(self) -> int:
        self.wait_calls += 1
        if self._wait_exc is not None:
            raise self._wait_exc
        self._running = False  # VLC window closed on its own
        return 0

    def poll(self) -> int | None:
        return None if self._running else 0

    def terminate(self) -> None:
        self.terminate_calls += 1
        self._running = False


class _VlcLauncherSpy:
    """Records the commands the player would launch and the fake processes."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.processes: list[_FakeProcess] = []
        # Set to simulate an interrupt (Ctrl-C) while blocking on the process.
        self.wait_exc: BaseException | None = None

    def spawn(self, cmd: list[str], *args: object, **kwargs: object) -> _FakeProcess:
        proc = _FakeProcess(cmd, wait_exc=self.wait_exc)
        self.commands.append(cmd)
        self.processes.append(proc)
        return proc

    @property
    def last_command(self) -> list[str] | None:
        return self.commands[-1] if self.commands else None

    @property
    def last_process(self) -> _FakeProcess | None:
        return self.processes[-1] if self.processes else None


@pytest.fixture
def fake_vlc(monkeypatch, tmp_path):
    """Pretend VLC is installed and capture launches instead of running VLC."""
    import streamcatcher.player.vlc_player as vlc_player

    fake_bin = tmp_path / "vlc"
    fake_bin.write_text("")
    monkeypatch.setattr(vlc_player.shutil, "which", lambda _name: str(fake_bin))

    spy = _VlcLauncherSpy()
    monkeypatch.setattr(vlc_player.subprocess, "Popen", spy.spawn)
    return spy
