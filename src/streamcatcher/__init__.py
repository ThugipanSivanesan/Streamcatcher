"""Streamcatcher — view RTMP/RTSP streams (incl. 360) in a window, or drive them headless.

:class:`StreamSession` is the importable control core: open a stream, read/render
frames, and look around a 360 viewport, with no window and no keyboard loop.
"""

from streamcatcher.player.session import StreamSession, ViewState

__all__ = ["StreamSession", "ViewState", "__version__"]

__version__ = "0.0.1"
