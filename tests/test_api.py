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


def test_unknown_profile_is_422_and_lists_valid_names(client):
    resp = client.post("/session", json={"url": URL, "profile": "does-not-exist"})
    assert resp.status_code == 422
    assert "does-not-exist" in resp.text
    assert "ricoh-theta" in resp.text  # the error lists valid profiles
    assert URL not in resp.text


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
