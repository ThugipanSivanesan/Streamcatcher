"""Player factory — selects a backend from settings.

Defaults to the offline stub. The live OpenCV backend (:class:`OpenCvPlayer`)
lazy-imports ``cv2`` inside its own ``play`` method, so importing this factory
never requires OpenCV to be installed — only playing a stream does.
"""

from __future__ import annotations

from streamcatcher.config import Backend, Settings
from streamcatcher.player.base import Player
from streamcatcher.player.opencv_player import OpenCvPlayer
from streamcatcher.player.reconnect import ReconnectPolicy
from streamcatcher.player.recorder import build_recorder
from streamcatcher.player.stub_player import StubPlayer


def get_player(settings: Settings, record_path: str | None = None) -> Player:
    """Build the player for ``settings.backend`` using its stream URL.

    When ``record_path`` is set, the OpenCV backend also records the stream to
    that file (see ``settings.record_mode``). Recording requires the OpenCV
    backend — it is not supported for the offline stub.
    """
    if settings.stream_url is None:
        raise ValueError("No stream URL configured.")
    url = settings.stream_url.get_secret_value()

    if settings.backend is Backend.STUB:
        if record_path is not None:
            raise ValueError(
                "Recording needs the 'opencv' backend; the stub backend cannot record."
            )
        return StubPlayer(url)
    if settings.backend is Backend.OPENCV:
        policy = ReconnectPolicy(
            enabled=settings.reconnect_enabled,
            base_delay=settings.reconnect_base_delay,
            factor=settings.reconnect_backoff_factor,
            max_delay=settings.reconnect_max_delay,
        )
        recorder = (
            build_recorder(settings.record_mode, record_path, settings, url)
            if record_path is not None
            else None
        )
        return OpenCvPlayer(
            url,
            projection=settings.projection,
            reconnect=policy,
            recorder=recorder,
            record_duration=settings.record_duration if record_path is not None else None,
            orientation_size=settings.orientation_size,
            orientation_hfov_deg=settings.orientation_hfov_deg,
        )

    raise NotImplementedError(  # pragma: no cover - defensive: Backend is exhaustive
        f"Backend {settings.backend.value!r} is not supported."
    )
