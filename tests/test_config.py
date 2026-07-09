from streamcatcher.config import Backend, Settings, strip_url_credentials


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
    # Only the embedded credentials are exposed (to seed redaction), not the URL.
    assert settings.secret_values() == ["pass", "user"]


def test_secret_values_empty_when_url_has_no_credentials():
    settings = Settings(stream_url="rtmp://live.example/app/key")
    assert settings.secret_values() == []


def test_backend_defaults_to_stub():
    assert Settings().backend is Backend.STUB


def test_profile_defaults_to_none(monkeypatch):
    monkeypatch.delenv("STREAMCATCHER_PROFILE", raising=False)
    assert Settings().profile is None


def test_profile_loaded_from_env(monkeypatch):
    monkeypatch.setenv("STREAMCATCHER_PROFILE", "ricoh-theta")
    assert Settings().profile == "ricoh-theta"


def test_display_url_strips_credentials():
    settings = Settings(stream_url="rtsp://user:pass@cam.local:554/stream1")
    assert settings.display_url == "rtsp://cam.local:554/stream1"


def test_display_url_is_none_without_url(monkeypatch):
    monkeypatch.delenv("STREAMCATCHER_STREAM_URL", raising=False)
    assert Settings().display_url is None


def test_strip_url_credentials_leaves_clean_url_untouched():
    assert strip_url_credentials("rtmp://live.example/app/key") == "rtmp://live.example/app/key"
