from __future__ import annotations

from dataclasses import dataclass

from orchestrator_agent import build_orchestrator

from api.repository import (
    SearchRepository,
    TripRepository,
    build_search_repository_from_env,
    build_trip_repository_from_env,
)
from api.service import TripPlanningService


@dataclass(frozen=True)
class ApiContainer:
    repository: TripRepository
    search_repository: SearchRepository
    service: TripPlanningService

    @classmethod
    def build_default(cls) -> ApiContainer:
        repository = build_trip_repository_from_env()
        search_repository = build_search_repository_from_env()
        orchestrator = build_orchestrator()
        service = TripPlanningService(
            repository=repository,
            search_repository=search_repository,
            orchestrator=orchestrator,
        )
        return cls(
            repository=repository,
            search_repository=search_repository,
            service=service,
        )
