from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class PersistedTripRecord:
    tenant_id: str
    trip_id: str
    user_id: str
    request_id: str
    destination: str | None
    timezone: str
    trip_plan_json: str
    itinerary_json: str
    plan_request_json: str
    parent_trip_id: str | None = None
    search_refs_mode: str = "synthetic"
    transit_policy_version: str = "v1"


@dataclass(frozen=True)
class PersistedFeedbackEvent:
    tenant_id: str
    trip_id: str
    user_id: str
    request_id: str
    feedback: str
    timezone: str
    created_at: datetime


@dataclass(frozen=True)
class PersistedSearchRecord:
    search_id: str
    search_type: str
    query_json: str
    status: str
    results_json: str
    notes_json: str
    error_json: str | None
    created_at: datetime
    expires_at: datetime
    updated_at: datetime


class TripPersistenceStore(Protocol):
    def save_trip_record(self, record: PersistedTripRecord) -> None: ...

    def get_trip_record(self, trip_id: str) -> PersistedTripRecord | None: ...

    def save_feedback(self, event: PersistedFeedbackEvent) -> None: ...


class SearchPersistenceStore(Protocol):
    def save_search_record(self, record: PersistedSearchRecord) -> None: ...

    def get_search_record(self, search_id: str) -> PersistedSearchRecord | None: ...
