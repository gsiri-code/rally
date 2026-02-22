from __future__ import annotations

from fastapi import Depends, Request

from api.container import ApiContainer
from api.service import TripPlanningService


def get_container(request: Request) -> ApiContainer:
    return request.app.state.container


def get_trip_planning_service(
    container: ApiContainer = Depends(get_container),
) -> TripPlanningService:
    return container.service
