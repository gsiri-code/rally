from __future__ import annotations

from fastapi import APIRouter, Response

from api.mapping import map_compose_request_to_plan_request
from api.models import ComposeTripRequest, FeedbackRequest, TripPlan
from api.service import TripPlanningService

router = APIRouter(prefix="/v1")


@router.post("/trips/compose", response_model=TripPlan)
def compose_trip(payload: ComposeTripRequest, response: Response) -> TripPlan:
    service = _service()
    plan_request = map_compose_request_to_plan_request(payload)
    trip = service.compose_trip(plan_request=plan_request, timezone=payload.timezone)
    response.headers["Cache-Control"] = "no-store"
    return trip


@router.get("/trips/{trip_id}", response_model=TripPlan)
def get_trip(trip_id: str, response: Response) -> TripPlan:
    service = _service()
    trip = service.get_trip(trip_id)
    response.headers["Cache-Control"] = "private, max-age=60"
    return trip


@router.post("/trips/{trip_id}/feedback", response_model=TripPlan)
def submit_feedback(
    trip_id: str, payload: FeedbackRequest, response: Response
) -> TripPlan:
    service = _service()
    trip = service.apply_feedback(trip_id, payload)
    response.headers["Cache-Control"] = "no-store"
    return trip


def _service() -> TripPlanningService:
    from api.app import get_service

    return get_service()
