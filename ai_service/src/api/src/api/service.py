from __future__ import annotations

from dataclasses import dataclass

from orchestrator_agent import build_orchestrator
from orchestrator_agent.contracts import PlanRequest

from api.mapping import map_itinerary_to_trip_plan
from api.models import FeedbackRequest, TripPlan
from api.repository import InMemoryTripRepository, TripRecord


class ApiInputError(Exception):
    pass


class ApiUpstreamError(Exception):
    pass


class ApiNotFoundError(Exception):
    pass


@dataclass
class TripPlanningService:
    repository: InMemoryTripRepository

    def __post_init__(self) -> None:
        self._orchestrator = build_orchestrator()

    def compose_trip(
        self,
        *,
        plan_request: PlanRequest,
        timezone: str,
        trip_id_override: str | None = None,
    ) -> TripPlan:
        try:
            response = self._orchestrator.run(plan_request)
        except ValueError as exc:
            raise ApiInputError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise ApiUpstreamError(str(exc)) from exc

        trip = map_itinerary_to_trip_plan(
            itinerary=response.itinerary,
            timezone=timezone,
            trip_id_override=trip_id_override,
        )
        self.repository.save_trip_record(
            TripRecord(
                trip=trip,
                itinerary=response.itinerary,
                plan_request=plan_request,
                timezone=timezone,
            )
        )
        return trip

    def get_trip(self, trip_id: str) -> TripPlan:
        record = self.repository.get_trip_record(trip_id)
        if record is None:
            raise ApiNotFoundError(f"Trip '{trip_id}' was not found.")
        return record.trip

    def apply_feedback(self, trip_id: str, payload: FeedbackRequest) -> TripPlan:
        record = self.repository.get_trip_record(trip_id)
        if record is None:
            raise ApiNotFoundError(f"Trip '{trip_id}' was not found.")

        feedback_request = PlanRequest(
            text=record.plan_request.text,
            voice_mp3_path=record.plan_request.voice_mp3_path,
            destination=record.plan_request.destination,
            days=record.plan_request.days,
            budget_level=record.plan_request.budget_level,
            preferences=record.plan_request.preferences,
            constraints=record.plan_request.constraints,
            feedback=payload.feedback,
            prior_plan=record.itinerary,
            context=record.plan_request.context.model_copy(
                update={
                    "request_id": payload.request_id,
                    "user_id": payload.user_id,
                    "tenant_id": payload.tenant_id,
                }
            ),
        )

        trip = self.compose_trip(
            plan_request=feedback_request,
            timezone=payload.timezone or record.timezone,
            trip_id_override=trip_id,
        )
        self.repository.save_feedback(trip_id, payload)
        return trip
