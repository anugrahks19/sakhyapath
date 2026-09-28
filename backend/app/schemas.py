from __future__ import annotations

from typing import Literal
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator, model_validator


class OwnedCameraInput(BaseModel):
    camera_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    display_name: str = Field(min_length=1, max_length=200)
    department: str = Field(default="Owned test", max_length=200)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    source_mode: Literal["owned_live", "owned_replay"] = "owned_live"
    rtsp_url: str | None = None
    hls_url: str | None = None
    codec: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    bitrate: int | None = Field(default=None, ge=0)

    @field_validator("rtsp_url")
    @classmethod
    def validate_rtsp(cls, value: str | None) -> str | None:
        if value and not value.startswith(("rtsp://", "rtsps://")):
            raise ValueError("RTSP URL must use rtsp:// or rtsps://")
        return value

    @field_validator("hls_url")
    @classmethod
    def validate_hls(cls, value: str | None) -> str | None:
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("HLS URL must use http:// or https://")
        return value


class LoginInput(BaseModel):
    operator_key: str


class AnalysisInput(BaseModel):
    sample_fps: float = Field(default=2.0, ge=0.2, le=10.0)


class WatchlistInput(BaseModel):
    plate: str = Field(min_length=4, max_length=32)
    category: Literal["representative"] = "representative"
    source_label: str = Field(default="Hackathon demo", min_length=1, max_length=120)
    expires_utc: str | None = None

    @field_validator("expires_utc")
    @classmethod
    def validate_expiry(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from datetime import datetime, timezone
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Expiry must include a timezone")
        return parsed.astimezone(timezone.utc).isoformat()


class PursuitInput(BaseModel):
    plate: str = Field(min_length=4, max_length=32)
    from_utc: str | None = None
    to_utc: str | None = None
    camera_id: str | None = None
    review_status: Literal["candidate", "confirmed", "reviewed_confirmed", "rejected"] | None = None
    max_speed_kmh: float = Field(default=160.0, ge=20, le=300)

    @field_validator("from_utc", "to_utc")
    @classmethod
    def validate_time(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Time filter must include a timezone")
        return parsed.astimezone(timezone.utc).isoformat()


class ReviewInput(BaseModel):
    decision: Literal["confirmed", "rejected"]
    corrected_plate: str | None = Field(default=None, max_length=32)
    note: str = Field(min_length=5, max_length=500)


class TimeMappingInput(BaseModel):
    stream_generation: int = Field(ge=1)
    pts_anchor: float = Field(ge=0)
    utc_anchor: str
    uncertainty_ms: float = Field(ge=0, le=60000)
    basis: Literal["owned_recording_clock_attested"]
    evidence_note: str = Field(min_length=12, max_length=500)

    @field_validator("utc_anchor")
    @classmethod
    def validate_anchor(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("UTC anchor must include a timezone")
        return parsed.astimezone(timezone.utc).isoformat()


class CapacityMeasurementInput(BaseModel):
    duration_seconds: float = Field(ge=10, le=3600)
    feed_count: int = Field(ge=1, le=100)
    decoded_frames: int = Field(ge=1)
    analyzed_frames: int = Field(ge=1)
    codec: str = Field(min_length=2, max_length=40)
    resolution: str = Field(min_length=3, max_length=40)
    model_provider: str = Field(min_length=2, max_length=120)
    source_mode: Literal["owned_live", "owned_replay", "sentinel_live"]
    method: str = Field(min_length=12, max_length=300)
    evidence_note: str = Field(min_length=12, max_length=500)


class CaseInput(BaseModel):
    reference: str = Field(min_length=3, max_length=80)
    kind: Literal["hit_and_run", "stolen_vehicle"]
    priority: Literal["routine", "urgent"] = "routine"
    plate_query: str = Field(min_length=3, max_length=32)
    query_mode: Literal["exact", "partial"] = "exact"
    vehicle_description: str = Field(default="", max_length=500)
    incident_latitude: float = Field(ge=-90, le=90)
    incident_longitude: float = Field(ge=-180, le=180)
    incident_utc: datetime
    search_until_utc: datetime | None = None
    lead_department: str = Field(min_length=1, max_length=200)

    @field_validator("incident_utc", "search_until_utc")
    @classmethod
    def case_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Incident time must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def check_window(self):
        if self.search_until_utc and self.search_until_utc < self.incident_utc:
            raise ValueError("Search end must follow incident time")
        return self


class CaseHandoffInput(BaseModel):
    recipient_department: str = Field(min_length=1, max_length=200)
    sighting_id: str = Field(min_length=1, max_length=80)
    note: str = Field(min_length=10, max_length=500)


class HandoffAcknowledgeInput(BaseModel):
    note: str = Field(min_length=5, max_length=500)


class CaseNoteInput(BaseModel):
    note: str = Field(min_length=5, max_length=500)


class CaseStatusInput(BaseModel):
    status: Literal["open", "closed"]
    note: str = Field(min_length=5, max_length=500)
