"""Root-logger secret redaction for Streamcatcher.

Seeds a logging filter from known secret values (e.g. the stream URL, which may
embed credentials) plus regexes for common secret shapes, so credentials never
leak into logs or tracebacks. Defense-in-depth: this sits alongside the typed
``SecretStr`` wrapper in ``config`` — not instead of it.
"""

from __future__ import annotations

import logging
import re
import threading
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


# The one filter installed on the root handlers; secrets accumulate into it.
_installed_filter: SecretRedactingFilter | None = None


class SecretRedactingFilter(logging.Filter):
    """Replace known secret values and secret-shaped substrings with ``***``."""

    def __init__(self, secret_values: Iterable[str] = ()) -> None:
        super().__init__()
        # De-duplicate, drop empties, keep order.
        self._literals: tuple[str, ...] = ()
        self._add_lock = threading.Lock()  # serialises concurrent add_secrets calls
        self.add_secrets(secret_values)

    def add_secrets(self, secret_values: Iterable[str]) -> None:
        """Add more literals to redact, keeping the ones already known.

        Secrets accumulate because a single process can learn them one at a
        time — the API opens a session per stream URL — and forgetting the
        earlier ones would un-redact credentials that are still in use. The
        literal tuple is swapped in atomically, so :meth:`filter` running on
        another thread always sees a consistent set.
        """
        with self._add_lock:
            merged = dict.fromkeys(self._literals)
            merged.update(dict.fromkeys(s for s in secret_values if s))
            self._literals = tuple(merged)

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

    There is exactly one filter per process and repeated calls **accumulate**
    into it: the API installs a new URL's credentials on every session it opens,
    and replacing the filter would stop redacting every earlier session's
    still-live credentials.
    """
    global _installed_filter

    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
    if _installed_filter is None:
        _installed_filter = SecretRedactingFilter(secret_values)
    else:
        _installed_filter.add_secrets(secret_values)
    redaction_filter = _installed_filter
    for handler in root.handlers:
        # Drop any *other* redaction filter so repeated calls don't pile filters
        # up on the shared handler, then attach ours if it isn't there yet.
        for existing in [
            f
            for f in handler.filters
            if isinstance(f, SecretRedactingFilter) and f is not redaction_filter
        ]:
            handler.removeFilter(existing)
        if redaction_filter not in handler.filters:
            handler.addFilter(redaction_filter)
    return redaction_filter


def reset_secret_redaction() -> None:
    """Forget the process-wide filter and detach it (for tests)."""
    global _installed_filter

    if _installed_filter is not None:
        for handler in logging.getLogger().handlers:
            handler.removeFilter(_installed_filter)
    _installed_filter = None
