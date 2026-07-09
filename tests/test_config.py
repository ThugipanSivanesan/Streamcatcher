from streamcatcher.config import Settings


def test_stream_url_defaults_to_none(monkeypatch):
    monkeypatch.delenv("STREAMCATCHER_STREAM_URL", raising=False)
    settings = Settings()
    assert settings.stream_url is None
    assert settings.secret_values() == []


def test_stream_url_loaded_from_env(monkeypatch):
    url = "rtsp://user:pass@cam.local:554/stream1"
    monkeypatch.setenv("STREAMCATCHER_STREAM_URL", url)
    settings = Settings()

    assert settings.stream_url is not None
    # The plaintext (and its credentials) must not surface via repr/str.
    assert "pass" not in repr(settings.stream_url)
    assert "pass" not in str(settings.stream_url)
    # But it is retrievable solely to seed log redaction.
    assert settings.secret_values() == [url]
