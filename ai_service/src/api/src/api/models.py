from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator


class ApiError(BaseModel):
    message: str
    code: str


class SearchRefs(BaseModel):
    flight_search_id: str
    attractions_search_id: str


class TripBlock(BaseModel):
    block_id: str
    kind: str
    status: str
    title: str
    description: str
    start_time: str
    end_time: str
    citations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TripPlan(BaseModel):
    trip_id: str
    destination: str | None = None
    timezone: str
    blocks: list[TripBlock]
    warnings: list[str] = Field(default_factory=list)
    search_refs: SearchRefs


class ComposeTripRequest(BaseModel):
    text: str | None = None
    voice_mp3_path: str | None = None
    destination: str | None = None
    timezone: str = "UTC"
    days: int = Field(default=3, ge=1, le=14)
    budget_level: str | None = None
    preferences: dict = Field(default_factory=dict)
    constraints: dict = Field(default_factory=dict)
    user_id: str | None = None
    tenant_id: str | None = None
    request_id: str

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        candidate = value.strip() or "UTC"
        try:
            ZoneInfo(candidate)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown timezone '{candidate}'.") from exc
        return candidate


class FeedbackRequest(BaseModel):
    feedback: str
    timezone: str = "UTC"
    user_id: str
    request_id: str
    tenant_id: str | None = None
    created_at: datetime | None = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        candidate = value.strip() or "UTC"
        try:
            ZoneInfo(candidate)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown timezone '{candidate}'.") from exc
        return candidate
