import logging

from streamcatcher.logging_setup import (
    REDACTION,
    SecretRedactingFilter,
    install_secret_redaction,
)


def _record(msg, args=None):
    return logging.LogRecord("test", logging.INFO, __file__, 1, msg, args, None)


def test_redacts_literal_secret_value():
    filt = SecretRedactingFilter(["supersecretvalue"])
    record = _record("connecting with supersecretvalue")

    assert filt.filter(record) is True
    assert "supersecretvalue" not in record.getMessage()
    assert REDACTION in record.getMessage()


def test_redacts_credentials_embedded_in_url():
    filt = SecretRedactingFilter()
    record = _record("opening rtsp://alice:hunter2@cam.local/stream")

    filt.filter(record)
    message = record.getMessage()
    assert "hunter2" not in message
    assert "alice" not in message
    assert "rtsp://" in message  # scheme is preserved, only userinfo is scrubbed


def test_redacts_bearer_token_and_api_key():
    filt = SecretRedactingFilter()
    record = _record("auth Bearer abc.def.ghijkl using sk-0123456789abcdefABCD")

    filt.filter(record)
    message = record.getMessage()
    assert "abc.def.ghijkl" not in message
    assert "sk-0123456789abcdefABCD" not in message


def test_redacts_after_args_formatting():
    filt = SecretRedactingFilter(["tok_secret"])
    record = _record("value=%s", ("tok_secret",))

    filt.filter(record)
    assert record.getMessage() == "value=" + REDACTION


def test_clean_message_passes_through_unchanged():
    filt = SecretRedactingFilter(["secret"])
    record = _record("stream connected")

    filt.filter(record)
    assert record.getMessage() == "stream connected"


def test_install_attaches_filter_to_root_handlers():
    filt = install_secret_redaction(["tok_live_123"])
    root = logging.getLogger()
    try:
        assert any(filt in handler.filters for handler in root.handlers)
    finally:
        for handler in root.handlers:
            handler.removeFilter(filt)
