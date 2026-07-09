"""FastAPI control API for Streamcatcher.

:func:`create_app` returns a configured application. FastAPI (and, when serving,
uvicorn) are imported **inside** ``create_app`` so importing this module needs
only the core dependencies; the web stack is required only when an app is
actually built. Route handlers are declared as plain ``def`` (sync) so Starlette
runs them in its thread pool — a blocking ``cap.read()`` therefore never stalls
the event loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from streamcatcher import __version__
from streamcatcher.api.models import (
    CreateSessionRequest,
    LookRequest,
    SessionStateResponse,
)
from streamcatcher.api.sessions import (
    ManagedSession,
    SessionLimitError,
    SessionManager,
    SessionNotFoundError,
)
from streamcatcher.config import Settings
from streamcatcher.player.session import StreamOpenError, _load_cv2

log = logging.getLogger("streamcatcher.api")

_MJPEG_BOUNDARY = "frame"


def _encode_jpeg(frame) -> bytes:
    """Encode a frame to JPEG bytes via OpenCV (loaded lazily)."""
    cv2 = _load_cv2()
    ok, buffer = cv2.imencode(".jpg", frame)
    if not ok:  # pragma: no cover - imencode failure is not reproducible offline
        raise RuntimeError("Failed to encode frame as JPEG.")
    return buffer.tobytes()


def _state_of(managed: ManagedSession) -> SessionStateResponse:
    state = managed.state()
    return SessionStateResponse(
        id=managed.id,
        projection=state.projection,
        yaw_deg=state.yaw_deg,
        pitch_deg=state.pitch_deg,
        hfov_deg=state.hfov_deg,
    )


def create_app(settings: Settings | None = None):
    """Build the Streamcatcher control API application."""
    from fastapi import Depends, FastAPI, Header, HTTPException, Response
    from fastapi.responses import StreamingResponse

    settings = settings or Settings()
    manager = SessionManager(
        max_sessions=settings.api_max_sessions,
        idle_timeout=settings.api_idle_timeout,
    )
    token = settings.api_token.get_secret_value() if settings.api_token else None
    frame_interval = 1.0 / max(1, settings.api_stream_fps)

    def require_token(authorization: str | None = Header(default=None)) -> None:
        """Require ``Authorization: Bearer <token>`` when a token is configured."""
        if token is None:
            return
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="Missing or invalid API token.")

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        # A single background reaper closes idle sessions. Wake at a quarter of the
        # idle timeout (>=1s) so an idle session is dropped soon after it expires.
        stop = asyncio.Event()
        interval = max(1, settings.api_idle_timeout // 4)

        async def reaper() -> None:
            while not stop.is_set():
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=interval)
                await asyncio.to_thread(manager.reap)

        task = asyncio.create_task(reaper())
        try:
            yield
        finally:
            stop.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            manager.close_all()

    app = FastAPI(
        title="Streamcatcher control API",
        version=__version__,
        summary="Open RTMP/RTSP stream sessions, look around, and pull frames.",
        lifespan=lifespan,
        dependencies=[Depends(require_token)],
    )

    def _require_session(session_id: str) -> ManagedSession:
        try:
            return manager.get(session_id)
        except SessionNotFoundError:
            raise HTTPException(status_code=404, detail=f"No session {session_id!r}.") from None

    def _jpeg_response(frame) -> Response:
        if frame is None:
            raise HTTPException(status_code=503, detail="Stream produced no frame.")
        return Response(content=_encode_jpeg(frame), media_type="image/jpeg")

    @app.post("/session", response_model=SessionStateResponse, status_code=201)
    def create_session(body: CreateSessionRequest) -> SessionStateResponse:
        try:
            managed = manager.create(body.url, body.projection, body.profile)
        except ValueError as exc:  # unknown profile name
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except SessionLimitError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from None
        except StreamOpenError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        return _state_of(managed)

    @app.get("/sessions")
    def list_sessions() -> dict[str, list[str]]:
        return {"sessions": manager.list_ids()}

    @app.delete("/session/{session_id}", status_code=204)
    def delete_session(session_id: str):
        # No return annotation: a 204 must not declare a response body, which
        # FastAPI infers from the annotation.
        try:
            manager.delete(session_id)
        except SessionNotFoundError:
            raise HTTPException(status_code=404, detail=f"No session {session_id!r}.") from None
        return Response(status_code=204)

    @app.get("/session/{session_id}/state", response_model=SessionStateResponse)
    def get_state(session_id: str) -> SessionStateResponse:
        return _state_of(_require_session(session_id))

    @app.get("/session/{session_id}/frame")
    def get_frame(session_id: str) -> Response:
        """The current look-around viewport as a JPEG — how an agent 'sees' now."""
        return _jpeg_response(_require_session(session_id).grab_view())

    @app.get("/session/{session_id}/panorama")
    def get_panorama(session_id: str) -> Response:
        """The raw, pre-reprojection frame as a JPEG — the full field of view."""
        return _jpeg_response(_require_session(session_id).grab_raw())

    @app.post("/session/{session_id}/look", response_model=SessionStateResponse)
    def post_look(session_id: str, body: LookRequest) -> SessionStateResponse:
        managed = _require_session(session_id)
        managed.look(body.pan, body.tilt, body.zoom)
        return _state_of(managed)

    @app.post("/session/{session_id}/look/{action}", response_model=SessionStateResponse)
    def post_look_discrete(session_id: str, action: str) -> SessionStateResponse:
        managed = _require_session(session_id)
        try:
            managed.apply_discrete(action)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        return _state_of(managed)

    @app.get("/session/{session_id}/stream.mjpg")
    def stream_mjpeg(session_id: str) -> StreamingResponse:
        managed = _require_session(session_id)

        def frames():
            while True:
                frame = managed.grab_view()
                if frame is None:
                    break
                yield (
                    b"--" + _MJPEG_BOUNDARY.encode() + b"\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + _encode_jpeg(frame) + b"\r\n"
                )
                time.sleep(frame_interval)

        return StreamingResponse(
            frames(),
            media_type=f"multipart/x-mixed-replace; boundary={_MJPEG_BOUNDARY}",
        )

    return app
