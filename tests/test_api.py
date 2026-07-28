"""Tests for the HTTP control API.

Everything runs offline via the ``fake_cv2`` fixture (a fake OpenCV module that
yields scripted frames) and Starlette's in-process ``TestClient`` — no network,
no real decoder, no window. The stream URL below embeds credentials so we can
assert they never leak into a response.
"""

from __future__ import annotations

import importlib
import sys

import pytest

from streamcatcher.config import Settings

URL = "rtsp://user:changeme@cam.local/live"


def _create_app(fake_cv2, **overrides):
    from streamcatcher.api.app import create_app

    fake_cv2.frames = overrides.pop("_frames", 50)
    return create_app(Settings(**overrides))


@pytest.fixture
def client(fake_cv2):
    """A running client with default settings (no auth)."""
    from fastapi.testclient import TestClient

    with TestClient(_create_app(fake_cv2)) as running:
        yield running


# -- session lifecycle --------------------------------------------------------


def test_create_returns_id_and_never_echoes_the_url(client):
    resp = client.post("/session", json={"url": URL})
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"]
    assert body["projection"] == "flat"
    # The URL and its embedded credentials must not appear anywhere in the body.
    assert URL not in resp.text
    assert "changeme" not in resp.text


def test_create_equirect_exposes_viewport_state(client):
    body = client.post("/session", json={"url": URL, "projection": "equirect"}).json()
    assert body["projection"] == "equirect"
    assert body["yaw_deg"] is not None
    assert body["hfov_deg"] is not None


def test_invalid_projection_is_422(client):
    resp = client.post("/session", json={"url": URL, "projection": "spherical"})
    assert resp.status_code == 422


def test_list_and_delete_sessions(client):
    assert client.get("/sessions").json() == {"sessions": []}
    session_id = client.post("/session", json={"url": URL}).json()["id"]
    assert client.get("/sessions").json() == {"sessions": [session_id]}

    assert client.delete(f"/session/{session_id}").status_code == 204
    assert client.get("/sessions").json() == {"sessions": []}
    # Deleting or touching it again is a 404.
    assert client.delete(f"/session/{session_id}").status_code == 404
    assert client.get(f"/session/{session_id}/state").status_code == 404


def test_unknown_session_is_404(client):
    assert client.get("/session/deadbeef/state").status_code == 404
    assert client.get("/session/deadbeef/frame").status_code == 404
    assert client.post("/session/deadbeef/look", json={"pan": 1}).status_code == 404


def test_session_limit_returns_429(fake_cv2):
    from fastapi.testclient import TestClient

    with TestClient(_create_app(fake_cv2, api_max_sessions=1)) as client:
        assert client.post("/session", json={"url": URL}).status_code == 201
        assert client.post("/session", json={"url": URL}).status_code == 429


def test_open_failure_returns_502(fake_cv2):
    from fastapi.testclient import TestClient

    fake_cv2.open_ok = False
    with TestClient(_create_app(fake_cv2)) as client:
        resp = client.post("/session", json={"url": URL})
        assert resp.status_code == 502


def test_concurrent_creates_cannot_exceed_the_session_limit(fake_cv2, monkeypatch):
    # The cap check and the insertion are separated by a slow, unlocked open, so
    # without a reserved slot every concurrent create passes the check together.
    import threading
    import time

    from streamcatcher.api.sessions import SessionLimitError, SessionManager
    from streamcatcher.config import Projection
    from streamcatcher.player.session import StreamSession

    real_open = StreamSession.open

    def slow_open(self):
        time.sleep(0.05)  # widen the window every create is racing through
        real_open(self)

    monkeypatch.setattr(StreamSession, "open", slow_open)

    manager = SessionManager(max_sessions=2, idle_timeout=300)
    accepted: list[str] = []
    rejected: list[str] = []

    def create() -> None:
        try:
            accepted.append(manager.create(URL, Projection.FLAT).id)
        except SessionLimitError:
            rejected.append("429")

    threads = [threading.Thread(target=create) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10.0)

    try:
        assert len(accepted) == 2  # exactly the cap, never more
        assert len(rejected) == 6
        assert len(manager.list_ids()) == 2
    finally:
        manager.close_all()


def test_a_failed_open_releases_its_reserved_slot(fake_cv2):
    # A reservation that leaked on failure would permanently shrink the cap.
    from streamcatcher.api.sessions import SessionManager
    from streamcatcher.config import Projection
    from streamcatcher.player.session import StreamOpenError

    manager = SessionManager(max_sessions=1, idle_timeout=300)
    fake_cv2.open_ok = False
    with pytest.raises(StreamOpenError):
        manager.create(URL, Projection.FLAT)

    fake_cv2.open_ok = True
    try:
        assert manager.create(URL, Projection.FLAT).id  # the slot came back
    finally:
        manager.close_all()


# -- frames -------------------------------------------------------------------


def test_frame_and_panorama_return_jpeg(client):
    session_id = client.post("/session", json={"url": URL}).json()["id"]
    for path in (f"/session/{session_id}/frame", f"/session/{session_id}/panorama"):
        resp = client.get(path)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert resp.content.startswith(b"\xff\xd8\xff")  # JPEG SOI marker


def test_frame_after_stream_ends_is_503(fake_cv2):
    from fastapi.testclient import TestClient

    with TestClient(_create_app(fake_cv2, _frames=1)) as client:
        session_id = client.post("/session", json={"url": URL}).json()["id"]
        assert client.get(f"/session/{session_id}/frame").status_code == 200  # 1st frame
        assert client.get(f"/session/{session_id}/frame").status_code == 503  # stream ended


def test_mjpeg_stream_yields_frames(fake_cv2):
    from fastapi.testclient import TestClient

    with TestClient(_create_app(fake_cv2, _frames=3, api_stream_fps=1000)) as client:
        session_id = client.post("/session", json={"url": URL}).json()["id"]
        resp = client.get(f"/session/{session_id}/stream.mjpg")
        assert resp.status_code == 200
        assert "multipart/x-mixed-replace" in resp.headers["content-type"]
        assert b"--frame" in resp.content
        assert b"\xff\xd8\xff" in resp.content


def test_mjpeg_stream_keeps_its_session_alive(fake_cv2, monkeypatch):
    # A viewer holds one long request, so nothing else marks the session used:
    # without a per-frame touch the idle reaper closes it out from under them.
    from fastapi.testclient import TestClient

    from streamcatcher.api.sessions import ManagedSession

    touched: list[str] = []
    real_touch = ManagedSession.touch

    def spy(self) -> None:
        touched.append(self.id)
        real_touch(self)

    monkeypatch.setattr(ManagedSession, "touch", spy)

    with TestClient(_create_app(fake_cv2, _frames=3, api_stream_fps=1000)) as client:
        session_id = client.post("/session", json={"url": URL}).json()["id"]
        touched.clear()  # ignore the touch from resolving the route
        client.get(f"/session/{session_id}/stream.mjpg")

    # One touch when the route resolved the session, then one per streamed frame.
    assert touched.count(session_id) >= 4


def test_touching_a_session_saves_it_from_the_reaper(fake_cv2):
    # The mechanism the fix relies on: a touched session survives a sweep that
    # would otherwise close it, which is what each streamed frame now buys.
    import time

    from streamcatcher.api.sessions import SessionManager
    from streamcatcher.config import Projection

    manager = SessionManager(max_sessions=4, idle_timeout=1)
    stale = manager.create(URL, Projection.FLAT)
    active = manager.create(URL, Projection.FLAT)
    try:
        stale.last_access = time.monotonic() - 10  # idle well past the timeout
        active.last_access = time.monotonic() - 10
        active.touch()  # what the MJPEG loop does per frame

        assert manager.reap() == 1
        assert manager.list_ids() == [active.id]
    finally:
        manager.close_all()


# -- background reader (optional) ---------------------------------------------


def test_reader_enabled_serves_frames_from_cache(fake_cv2):
    from fastapi.testclient import TestClient

    with TestClient(_create_app(fake_cv2, api_reader_enabled=True)) as client:
        session_id = client.post("/session", json={"url": URL}).json()["id"]
        # The cache is primed at creation and holds the last good frame, so both
        # endpoints return a JPEG regardless of the reader thread's timing.
        for path in (f"/session/{session_id}/frame", f"/session/{session_id}/panorama"):
            resp = client.get(path)
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "image/jpeg"
            assert resp.content.startswith(b"\xff\xd8\xff")


def test_reader_enabled_is_503_when_no_frame_ever_arrives(fake_cv2):
    from fastapi.testclient import TestClient

    # Stream opens but yields no frames: the primed read gets nothing, so the
    # cache stays empty and the viewport request reports 503.
    with TestClient(_create_app(fake_cv2, _frames=0, api_reader_enabled=True)) as client:
        session_id = client.post("/session", json={"url": URL}).json()["id"]
        assert client.get(f"/session/{session_id}/frame").status_code == 503


def test_managed_session_reader_keeps_the_last_frame_after_the_stream_ends(fake_cv2):
    from streamcatcher.api.sessions import ManagedSession
    from streamcatcher.player.session import StreamSession

    fake_cv2.frames = 2
    session = StreamSession(URL)
    session.open()
    managed = ManagedSession("cache-test", session, reader_fps=1000)
    # The reader thread self-terminates once the finite fake stream is exhausted.
    assert managed._reader is not None
    managed._reader.join(timeout=2.0)

    assert managed._ended is True  # reached end of stream
    assert managed.grab_raw() is not None  # but the last good frame is retained
    managed.close()


def test_managed_session_close_stops_the_reader_thread(fake_cv2):
    from streamcatcher.api.sessions import ManagedSession
    from streamcatcher.player.session import StreamSession

    fake_cv2.frames = 1_000_000  # effectively endless, so the reader keeps running
    session = StreamSession(URL)
    session.open()
    managed = ManagedSession("stop-test", session, reader_fps=1000)
    assert managed._reader is not None and managed._reader.is_alive()

    managed.close()

    assert not managed._reader.is_alive()  # close() stopped and joined it


def test_managed_session_on_demand_by_default_has_no_reader(fake_cv2):
    from streamcatcher.api.sessions import ManagedSession
    from streamcatcher.player.session import StreamSession

    session = StreamSession(URL)
    session.open()
    managed = ManagedSession("default-test", session)  # reader_fps defaults to 0

    assert managed._reader is None  # on-demand: no background thread
    assert managed.grab_raw() is not None  # reads directly on request
    managed.close()


# -- secret redaction across sessions -----------------------------------------


def test_opening_a_second_session_keeps_redacting_the_first(fake_cv2):
    # Each create installs its URL's credentials; replacing the filter (rather
    # than accumulating) silently un-redacted every earlier session's password.
    import logging

    from streamcatcher.api.sessions import SessionManager
    from streamcatcher.config import Projection
    from streamcatcher.logging_setup import REDACTION, reset_secret_redaction

    reset_secret_redaction()
    manager = SessionManager(max_sessions=4, idle_timeout=300)
    try:
        manager.create("rtsp://alice:first_pw@cam-a.local/live", Projection.FLAT)
        filt = manager.create("rtsp://bob:second_pw@cam-b.local/live", Projection.FLAT)
        del filt

        from streamcatcher.logging_setup import _installed_filter

        record = logging.LogRecord(
            "test", logging.INFO, __file__, 1, "first_pw then second_pw", None, None
        )
        _installed_filter.filter(record)
        message = record.getMessage()

        assert "first_pw" not in message  # session A's password is still covered
        assert "second_pw" not in message
        assert message == f"{REDACTION} then {REDACTION}"
    finally:
        manager.close_all()
        reset_secret_redaction()


# -- look controls ------------------------------------------------------------


def test_look_changes_orientation(client):
    session_id = client.post("/session", json={"url": URL, "projection": "equirect"}).json()["id"]
    before = client.get(f"/session/{session_id}/state").json()
    after = client.post(f"/session/{session_id}/look", json={"pan": 10, "tilt": -5}).json()
    assert after["yaw_deg"] != before["yaw_deg"]
    assert after["pitch_deg"] != before["pitch_deg"]


@pytest.mark.parametrize(
    "action", ["pan_left", "pan_right", "tilt_up", "tilt_down", "zoom_in", "zoom_out"]
)
def test_discrete_look_actions(client, action):
    session_id = client.post("/session", json={"url": URL, "projection": "equirect"}).json()["id"]
    resp = client.post(f"/session/{session_id}/look/{action}")
    assert resp.status_code == 200
    assert resp.json()["projection"] == "equirect"


def test_unknown_discrete_action_is_404(client):
    session_id = client.post("/session", json={"url": URL, "projection": "equirect"}).json()["id"]
    resp = client.post(f"/session/{session_id}/look/spin")
    assert resp.status_code == 404


# -- auth ---------------------------------------------------------------------


def test_token_is_enforced_when_configured(fake_cv2):
    from fastapi.testclient import TestClient

    with TestClient(_create_app(fake_cv2, api_token="changeme")) as client:
        assert client.get("/sessions").status_code == 401
        assert client.post("/session", json={"url": URL}).status_code == 401

        auth = {"Authorization": "Bearer changeme"}
        assert client.post("/session", json={"url": URL}, headers=auth).status_code == 201
        assert client.get("/sessions", headers=auth).status_code == 200
        assert client.get("/sessions", headers={"Authorization": "Bearer wrong"}).status_code == 401


# -- offline-first guards -----------------------------------------------------


def test_serve_without_api_extra_prints_install_hint(monkeypatch):
    from typer.testing import CliRunner

    from streamcatcher.cli import app

    # Simulate the [api] extra being absent.
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    monkeypatch.setitem(sys.modules, "fastapi", None)

    result = CliRunner().invoke(app, ["serve"])
    assert result.exit_code == 1
    text = result.output
    try:
        text += result.stderr
    except ValueError:  # stderr not captured separately on this click version
        pass
    assert "pip install" in text


def test_api_app_module_imports_without_web_stack(monkeypatch):
    monkeypatch.setitem(sys.modules, "fastapi", None)
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    monkeypatch.delitem(sys.modules, "streamcatcher.api.app", raising=False)
    module = importlib.import_module("streamcatcher.api.app")
    assert hasattr(module, "create_app")


# -- stream URL validation ----------------------------------------------------
#
# cv2.VideoCapture opens local paths and http:// URLs just as readily as RTSP,
# so an unvalidated url field let anyone with API access read arbitrary files
# off the server or reach hosts only the server can see.


@pytest.mark.parametrize(
    "url",
    [
        "/etc/passwd",
        "file:///etc/passwd",
        "http://169.254.169.254/latest/meta-data/",
        "https://example.com/video.mp4",
        "rtsp://",
        "",
    ],
)
def test_create_rejects_urls_that_are_not_streams(client, url, fake_cv2):
    resp = client.post("/session", json={"url": url})
    assert resp.status_code == 422
    # Rejected at the model, before anything tries to open it.
    assert fake_cv2.last_capture is None


def test_create_still_accepts_rtsp_and_rtmp(client):
    assert client.post("/session", json={"url": URL}).status_code == 201
    assert client.post("/session", json={"url": "rtmp://live.example/app/key"}).status_code == 201


def test_rejected_url_does_not_consume_a_session_slot(fake_cv2):
    from fastapi.testclient import TestClient

    with TestClient(_create_app(fake_cv2, api_max_sessions=1)) as client:
        assert client.post("/session", json={"url": "file:///etc/passwd"}).status_code == 422
        # The bad request must not have reserved the only slot.
        assert client.post("/session", json={"url": URL}).status_code == 201
