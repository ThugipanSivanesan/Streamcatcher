"""Streamcatcher — view RTMP/RTSP streams (incl. 360) in a window, or drive them headless.

:class:`StreamSession` is the importable control core: open a stream, read/render
frames, and look around a 360 viewport, with no window and no keyboard loop.
"""

from importlib.metadata import PackageNotFoundError, version

from streamcatcher.player.session import StreamSession, ViewState

__all__ = ["StreamSession", "ViewState", "__version__"]

# Derived from the installed distribution metadata so the version lives in
# exactly one place (pyproject.toml) and can't drift.
try:
    __version__ = version("streamcatcher")
except PackageNotFoundError:  # pragma: no cover - a source tree with no install
    __version__ = "0.0.0+unknown"
