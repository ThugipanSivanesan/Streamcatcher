"""Request and response models for the HTTP control API.

These use only Pydantic (already a core dependency), so this module imports with
no web stack. The stream URL is accepted on input but **never** returned in any
response — responses expose only the opaque session id and the viewport state.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from streamcatcher.config import Projection


class CreateSessionRequest(BaseModel):
    """Body for ``POST /session``."""

    url: str = Field(description="RTMP/RTSP stream URL (may embed credentials; never echoed back).")
    projection: Projection = Projection.FLAT
    profile: str | None = Field(
        default=None,
        description="Named camera preset; overrides `projection` when set.",
    )


class LookRequest(BaseModel):
    """Body for ``POST /session/{id}/look`` — pan/tilt/zoom degree deltas."""

    pan: float = Field(default=0.0, description="Yaw delta in degrees (+ right).")
    tilt: float = Field(default=0.0, description="Pitch delta in degrees (+ up).")
    zoom: float = Field(
        default=0.0,
        description="Horizontal-FOV delta in degrees; negative narrows the view (zooms in).",
    )


class SessionStateResponse(BaseModel):
    """The public state of a session — its id plus the viewport orientation."""

    id: str
    projection: str
    yaw_deg: float | None = None
    pitch_deg: float | None = None
    hfov_deg: float | None = None
