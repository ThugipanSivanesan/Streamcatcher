"""Shared test fixtures.

The ``fake_cv2`` fixture injects a fake ``cv2`` module so the OpenCV player can
be exercised without a real decoder, window, or network. Its ``VideoCapture``
yields a scripted number of frames and ``imshow``/``waitKey``/``getWindowProperty``
are spies, keeping the suite fully offline and headless (e.g. in CI).
"""

import sys

import numpy as np
import pytest


class _FakeCapture:
    """Stand-in for ``cv2.VideoCapture`` that yields a fixed number of frames."""

    def __init__(self, url: str, frames: int, opened: bool) -> None:
        self.url = url
        self._frames_left = frames
        self._opened = opened
        self.release_calls = 0

    def isOpened(self) -> bool:  # noqa: N802 - mirrors the cv2 API name
        return self._opened

    def read(self):
        if self._frames_left > 0:
            self._frames_left -= 1
            # A tiny real array so callers can read ``frame.shape`` (360 remap).
            return True, np.zeros((8, 16, 3), dtype=np.uint8)
        return False, None

    def release(self) -> None:
        self.release_calls += 1
        self._opened = False


class _FakeCv2:
    """Minimal fake of the ``cv2`` module used by :mod:`opencv_player`."""

    # Constants the player reads off the module.
    CAP_FFMPEG = 1900
    WINDOW_NORMAL = 0
    WND_PROP_VISIBLE = 1
    INTER_LINEAR = 1

    def __init__(self) -> None:
        self.captures: list[_FakeCapture] = []
        self.named_windows: list[str] = []
        self.destroyed_windows: list[str] = []
        self.imshow_calls = 0
        self.remap_calls = 0
        self.imencode_calls = 0
        self.imwrite_calls = 0
        self.written: list[tuple[str, object]] = []  # (path, frame) per imwrite
        # Knobs the tests set to script behaviour.
        self.open_ok = True
        self.imwrite_ok = True  # scripts imwrite's success return
        self.frames = 3
        self.keys: list[int] = []  # scripted waitKey return values
        self.window_visible = 1
        self._key_idx = 0
        # Reconnect-test knobs. ``open_results`` scripts each VideoCapture's
        # opened state (e.g. [True, False, True] to fail one reconnect before
        # succeeding); once exhausted it falls back to ``open_ok``.
        # ``close_window_after_captures`` reports the window closed once more
        # than N captures exist, giving retry-forever tests a deterministic exit.
        self.open_results: list[bool] | None = None
        self.close_window_after_captures: int | None = None
        self._open_idx = 0

    def VideoCapture(self, url, api=None):  # noqa: N802 - mirrors the cv2 API name
        if self.open_results is not None and self._open_idx < len(self.open_results):
            opened = self.open_results[self._open_idx]
            self._open_idx += 1
        else:
            opened = self.open_ok
        cap = _FakeCapture(url, frames=self.frames, opened=opened)
        self.captures.append(cap)
        return cap

    def namedWindow(self, title, flags=0):  # noqa: N802
        self.named_windows.append(title)

    def imshow(self, title, frame) -> None:
        self.imshow_calls += 1

    def remap(self, frame, map_x, map_y, interpolation):  # noqa: N802 - cv2 API
        self.remap_calls += 1
        return frame

    def imencode(self, ext, frame, params=None):  # noqa: N802 - mirrors the cv2 API
        # Return a tiny stand-in for a JPEG buffer with a real JPEG SOI marker so
        # callers get plausible bytes without a real encoder.
        self.imencode_calls += 1
        return True, np.frombuffer(b"\xff\xd8\xffFAKEJPEG", dtype=np.uint8)

    def imwrite(self, path, frame, params=None) -> bool:  # noqa: N802 - mirrors the cv2 API
        # Record the write instead of touching disk; ``imwrite_ok`` scripts the
        # real API's bool return (False on encode/write failure).
        self.imwrite_calls += 1
        self.written.append((path, frame))
        return self.imwrite_ok

    def waitKey(self, delay):  # noqa: N802
        if self._key_idx < len(self.keys):
            key = self.keys[self._key_idx]
            self._key_idx += 1
            return key
        return -1  # no key pressed

    def getWindowProperty(self, title, prop):  # noqa: N802
        if (
            self.close_window_after_captures is not None
            and len(self.captures) > self.close_window_after_captures
        ):
            return 0  # user "closed" the window once enough captures were opened
        return self.window_visible

    def destroyWindow(self, title) -> None:  # noqa: N802
        self.destroyed_windows.append(title)

    @property
    def last_capture(self) -> _FakeCapture | None:
        return self.captures[-1] if self.captures else None


@pytest.fixture
def fake_cv2(monkeypatch):
    """Inject a fake ``cv2`` so the OpenCV player runs headless and offline."""
    fake = _FakeCv2()
    monkeypatch.setitem(sys.modules, "cv2", fake)
    return fake
