"""Root-logger secret redaction for Streamcatcher.

Seeds a logging filter from known secret values (e.g. the stream URL, which may
embed credentials) plus regexes for common secret shapes, so credentials never
leak into logs or tracebacks. Defense-in-depth: this sits alongside the typed
``SecretStr`` wrapper in ``config`` — not instead of it.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

REDACTION = "***"

# Credentials embedded in a URL userinfo section: scheme://user:pass@host
_URL_CREDENTIALS = re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://)[^/@\s]+@")

# Common standalone secret shapes.
_SECRET_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"\b[0-9a-fA-F]{64}\b"),
    re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{40,90}\b"),
)


class SecretRedactingFilter(logging.Filter):
    """Replace known secret values and secret-shaped substrings with ``***``."""

    def __init__(self, secret_values: Iterable[str] = ()) -> None:
        super().__init__()
        # De-duplicate, drop empties, keep order.
        self._literals = tuple(dict.fromkeys(s for s in secret_values if s))

    def _redact(self, text: str) -> str:
        for literal in self._literals:
            if literal in text:
                text = text.replace(literal, REDACTION)
        text = _URL_CREDENTIALS.sub(rf"\1{REDACTION}@", text)
        for pattern in _SECRET_PATTERNS:
            text = pattern.sub(REDACTION, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # never let redaction break logging
            return True
        redacted = self._redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def install_secret_redaction(
    secret_values: Iterable[str] = (), *, level: int = logging.INFO
) -> SecretRedactingFilter:
    """Install the redacting filter on the root logger's handlers.

    Creates a default stream handler if the root logger has none. Returns the
    installed filter so callers (and tests) can reference or remove it.
    """
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
    redaction_filter = SecretRedactingFilter(secret_values)
    for handler in root.handlers:
        handler.addFilter(redaction_filter)
    return redaction_filter
