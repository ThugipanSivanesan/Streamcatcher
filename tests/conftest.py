"""Shared test fixtures.

The ``fake_cv2`` fixture injects a fake ``cv2`` module so the OpenCV player can
be exercised without a real decoder, window, or network. Its ``VideoCapture``
yields a scripted number of frames and ``imshow``/``waitKey``/``getWindowProperty``
are spies, keeping the suite fully offline and headless (e.g. in CI).
"""

import sys

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
            return True, object()  # a stand-in frame
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

    def __init__(self) -> None:
        self.captures: list[_FakeCapture] = []
        self.named_windows: list[str] = []
        self.destroyed_windows: list[str] = []
        self.imshow_calls = 0
        # Knobs the tests set to script behaviour.
        self.open_ok = True
        self.frames = 3
        self.keys: list[int] = []  # scripted waitKey return values
        self.window_visible = 1
        self._key_idx = 0

    def VideoCapture(self, url, api=None):  # noqa: N802 - mirrors the cv2 API name
        cap = _FakeCapture(url, frames=self.frames, opened=self.open_ok)
        self.captures.append(cap)
        return cap

    def namedWindow(self, title, flags=0):  # noqa: N802
        self.named_windows.append(title)

    def imshow(self, title, frame) -> None:
        self.imshow_calls += 1

    def waitKey(self, delay):  # noqa: N802
        if self._key_idx < len(self.keys):
            key = self.keys[self._key_idx]
            self._key_idx += 1
            return key
        return -1  # no key pressed

    def getWindowProperty(self, title, prop):  # noqa: N802
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
