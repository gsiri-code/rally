from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from orchestrator_agent.contracts import ItineraryPlan, PlanRequest

from api.models import FeedbackRequest, TripPlan


@dataclass
class TripRecord:
    trip: TripPlan
    itinerary: ItineraryPlan
    plan_request: PlanRequest
    timezone: str


@dataclass
class InMemoryTripRepository:
    trips: dict[str, TripRecord] = field(default_factory=dict)
    feedback_events: list[dict] = field(default_factory=list)

    def save_trip_record(self, record: TripRecord) -> None:
        self.trips[record.trip.trip_id] = record

    def get_trip_record(self, trip_id: str) -> TripRecord | None:
        return self.trips.get(trip_id)

    def save_feedback(self, trip_id: str, payload: FeedbackRequest) -> None:
        created_at = payload.created_at or datetime.now(timezone.utc)
        self.feedback_events.append(
            {
                "user_id": payload.user_id,
                "trip_id": trip_id,
                "feedback": payload.feedback,
                "created_at": created_at.astimezone(timezone.utc).isoformat(),
            }
        )
