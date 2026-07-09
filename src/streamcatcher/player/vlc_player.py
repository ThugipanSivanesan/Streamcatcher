"""Live stream player that launches the system VLC media player.

Interim implementation. Embedding libVLC in a window we own requires a native
drawable (``NSView`` / ``HWND`` / X window) and an event loop — on macOS a plain
Python CLI has neither, so libVLC decodes but cannot create a video output. Until
the embedded-window backend lands in a later slice, we hand the stream URL to the
installed VLC application, which opens its own audio+video window. This works on
any platform where VLC is installed.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("streamcatcher.player.vlc")

# libVLC's default RTSP receive buffer is 250 KB, which truncates high-resolution
# camera frames ("total received frame size exceeds the client's buffer size").
# Give VLC a roomier buffer so full frames arrive intact.
_RTSP_FRAME_BUFFER_BYTES = 2_000_000

# Standard macOS install location, used when ``vlc`` isn't on PATH.
_MACOS_VLC = Path("/Applications/VLC.app/Contents/MacOS/VLC")


class VlcMissingError(RuntimeError):
    """Raised when the VLC media player executable cannot be located."""


_INSTALL_HINT = (
    "Could not find the VLC media player. Install VLC (https://www.videolan.org/vlc/) "
    "and make sure the 'vlc' command is on your PATH."
)


def _find_vlc() -> str:
    """Return the path to the VLC executable, or raise :class:`VlcMissingError`."""
    on_path = shutil.which("vlc")
    if on_path:
        return on_path
    if sys.platform == "darwin" and _MACOS_VLC.exists():
        return str(_MACOS_VLC)
    raise VlcMissingError(_INSTALL_HINT)


class VlcPlayer:
    """Play a live RTMP/RTSP stream by launching the VLC media player."""

    def __init__(self, url: str) -> None:
        self._url = url  # secret: embeds credentials, so it is never logged
        self._vlc_bin = _find_vlc()
        self._process: subprocess.Popen | None = None

    def _command(self) -> list[str]:
        return [
            self._vlc_bin,
            f"--rtsp-frame-buffer-size={_RTSP_FRAME_BUFFER_BYTES}",
            self._url,
        ]

    def play(self) -> None:
        """Launch VLC on the stream and block until its window closes."""
        log.info("Launching VLC to view the live stream.")
        self._process = subprocess.Popen(self._command())
        try:
            self._process.wait()
        except KeyboardInterrupt:
            log.info("Interrupted — closing VLC.")
        finally:
            self.stop()

    def stop(self) -> None:
        """Terminate the VLC process if it is still running."""
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
        log.info("Live player: stopped.")

    def snapshot(self, path: str) -> None:
        """Not supported by the interim launcher — see the module docstring."""
        raise NotImplementedError(
            "Snapshots aren't supported by the interim VLC-launcher backend; "
            "they arrive with the embedded-window player in a later slice."
        )

    def is_playing(self) -> bool:
        """Whether the VLC process is currently running."""
        return self._process is not None and self._process.poll() is None
