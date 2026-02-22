from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ApiError(BaseModel):
    message: str
    code: str | None = None


class ErrorMessage(ApiError):
    pass


class HealthzResponse(BaseModel):
    ok: bool
    db: bool


class FlightSearchCreateInput(BaseModel):
    origins: list[str]
    destinations: list[str]
    depart_date: str
    return_date: str | None = None
    adults: int | None = None
    cabin: Literal["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"] | None = None
    nonstop_preferred: bool | None = None
    max_stops: int | None = None
    currency: str | None = None
    limit: int | None = None
    trip_id: str | None = None


class SearchResponse(BaseModel):
    search_id: str
    query: dict[str, Any]
    status: Literal["running", "completed", "error"]
    results: list[dict[str, Any]]
    notes: list[str]
    error: dict[str, Any] | None = None
    created_at: str
    expires_at: str


class FlightSearchResponse(SearchResponse):
    pass


class AttractionsSearchInput(BaseModel):
    city: str
    date: str
    categories: list[str]
    neighborhoods: list[str] | None = None
    interests: list[str] | None = None
    budget_level: str | None = None
    limit: int | None = None
    trip_id: str | None = None


class CacheInfo(BaseModel):
    hit: bool
    key: str


class AttractionsSearchResponse(BaseModel):
    search_id: str
    type: str
    query: dict[str, Any]
    status: Literal["running", "completed", "error"]
    results: list[dict[str, Any]]
    notes: list[str]
    error: dict[str, Any] | None = None
    created_at: str
    expires_at: str
    cache: CacheInfo


class TripCreateInput(BaseModel):
    start_date: str
    end_date: str
    origin: str
    destinations: list[str]
    budget_level: str
    pace: str | None = None
    limit: int | None = None
    neighborhoods: list[str] | None = None
    interests: list[str] | None = None


class ComposeInput(BaseModel):
    trip_id: str
    start_date: str
    end_date: str
    attractions_search_id: str
    flight_search_id: str
    timezone: str


class ChangeBlockInput(BaseModel):
    preference_text: str | None = None
    direction: Literal["cheaper", "closer", "higher_rated"] | None = Field(default=None)


class SearchRefs(BaseModel):
    flight_search_id: str
    attractions_search_id: str


class PlaceRef(BaseModel):
    search_id: str | None = None
    result_id: str | None = None
    place_id: str | None = None
    maps_url: str | None = None
    address: str | None = None
    lat: float | None = None
    lng: float | None = None


class BlockMeta(BaseModel):
    area_bucket: str | None = None
    price_tier: str | None = None
    rating: float | None = None
    review_count: float | None = None
    airline: str | None = None
    flight_number: str | None = None
    depart_at: str | None = None
    arrive_at: str | None = None
    depart_at_local_trip_tz: str | None = None
    arrive_at_local_trip_tz: str | None = None
    outlier_reason: str | None = None
    cost_hint: str | None = None
    low_priority: bool | None = None


class ItineraryBlock(BaseModel):
    block_id: str
    start_at: str
    end_at: str
    kind: Literal[
        "flight",
        "cafe",
        "attraction",
        "lunch",
        "dinner",
        "viewpoint",
        "evening_activity",
        "free_time",
    ]
    title: str
    place_ref: PlaceRef | None = None
    status: Literal["planned", "skipped", "replaced"]
    meta: BlockMeta | None = None


class DayPlan(BaseModel):
    date: str
    timezone: str
    day_summary: str
    used_place_ids: list[str]
    used_titles: list[str]
    transit_refs: list[str] | None = None
    blocks: list[ItineraryBlock]


class ChangeEvent(BaseModel):
    ts: str
    action: Literal["skip", "change", "normalize"]
    block_id: str
    old_place_id: str | None = None
    new_place_id: str | None = None
    reason: str | None = None
    direction: str | None = None
    event: str | None = None
    old_kind: str | None = None
    old_title: str | None = None
    old_start_at: str | None = None
    old_end_at: str | None = None


class TripPlan(BaseModel):
    trip_id: str
    inputs: TripCreateInput
    timezone: str
    search_refs: SearchRefs
    used_place_ids: list[str]
    itinerary: list[DayPlan]
    transit: list[ItineraryBlock]
    audit_log: list[ChangeEvent]
    estimated_cost_level: str | None = None


class VoiceTranscribeResponse(BaseModel):
    transcript: str
    error: str | None = None


class VoiceDecideInput(BaseModel):
    trip_id: str
    transcript: str
    selected_block_id: str | None = None


class VoiceDecision(BaseModel):
    action: Literal["skip", "change", "none"]
    block_id: str | None = None
    direction: Literal["cheaper", "closer", "higher_rated"] | None = None
    preference_text: str | None = None


class VoiceDecideResponse(BaseModel):
    transcript: str
    decision_summary: str | None = None
    actions: list[dict[str, Any]] = Field(default_factory=list)
    updated_trip_plan: TripPlan | None = None
    needs_clarification: bool | None = None
    options: list[dict[str, Any]] = Field(default_factory=list)


class VoiceIntentResponse(BaseModel):
    transcript: str
    decision: VoiceDecision
    agent_message: str
    trip: TripPlan
