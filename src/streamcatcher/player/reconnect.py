"""Reconnect policy and backoff schedule — pure, no OpenCV.

When a live stream drops, the GUI player retries the connection with
exponential backoff. The policy (how fast to back off, and whether to retry at
all) and the delay schedule live here, separate from any window or ``cv2`` so
they stay deterministic and unit-testable. The retry *loop* that consumes this
schedule lives in :class:`~streamcatcher.player.opencv_player.OpenCvPlayer`.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class ReconnectPolicy:
    """How to retry a dropped stream.

    ``enabled=False`` restores the old behaviour: exit on the first drop.
    Otherwise the player retries forever, waiting ``base_delay`` seconds and
    multiplying by ``factor`` after each failed attempt, capped at ``max_delay``.
    """

    enabled: bool = True
    base_delay: float = 1.0
    factor: float = 2.0
    max_delay: float = 30.0


def backoff_delays(policy: ReconnectPolicy) -> Iterator[float]:
    """Yield reconnect wait times forever: ``base, base·factor, … capped at max``.

    Infinite by design — with the default policy this is
    ``1, 2, 4, 8, 16, 30, 30, …`` — so the player retries until the stream
    returns or the user quits. The caller is responsible for stopping.
    """
    delay = policy.base_delay
    while True:
        yield min(delay, policy.max_delay)
        delay *= policy.factor
