from streamcatcher.config import Backend, RecordMode, Settings, strip_url_credentials


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


def test_record_defaults(monkeypatch):
    for var in (
        "STREAMCATCHER_RECORD_MODE",
        "STREAMCATCHER_RECORD_FPS",
        "STREAMCATCHER_RECORD_FOURCC",
    ):
        monkeypatch.delenv(var, raising=False)
    settings = Settings()
    assert settings.record_mode is RecordMode.OPENCV
    assert settings.record_fps == 25.0
    assert settings.record_fourcc == "mp4v"
    assert settings.record_duration is None


def test_record_mode_loaded_from_env(monkeypatch):
    monkeypatch.setenv("STREAMCATCHER_RECORD_MODE", "ffmpeg")
    assert Settings().record_mode is RecordMode.FFMPEG


def test_record_duration_loaded_from_env(monkeypatch):
    monkeypatch.setenv("STREAMCATCHER_RECORD_DURATION", "30")
    assert Settings().record_duration == 30.0


def test_api_reader_defaults_off(monkeypatch):
    monkeypatch.delenv("STREAMCATCHER_API_READER_ENABLED", raising=False)
    settings = Settings()
    assert settings.api_reader_enabled is False
    assert settings.api_reader_fps == 30


def test_display_url_strips_credentials():
    settings = Settings(stream_url="rtsp://user:pass@cam.local:554/stream1")
    assert settings.display_url == "rtsp://cam.local:554/stream1"


def test_display_url_is_none_without_url(monkeypatch):
    monkeypatch.delenv("STREAMCATCHER_STREAM_URL", raising=False)
    assert Settings().display_url is None


def test_strip_url_credentials_leaves_clean_url_untouched():
    assert strip_url_credentials("rtmp://live.example/app/key") == "rtmp://live.example/app/key"
