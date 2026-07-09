"""Streamcatcher HTTP control API (optional ``[api]`` extra).

:func:`create_app` builds a FastAPI application that lets another program — or an
AI agent — open a stream session, drive the 360 look-around, and pull frames as
JPEG stills or an MJPEG stream. FastAPI/uvicorn are imported lazily (inside
:func:`create_app` and the ``serve`` CLI command), so importing this package
never requires the web stack.
"""

from streamcatcher.api.app import create_app

__all__ = ["create_app"]
