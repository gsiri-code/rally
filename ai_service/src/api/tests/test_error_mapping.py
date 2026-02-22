from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from api.app import create_app
from api.container import ApiContainer
from api.errors import NotFoundDomainError, RepositoryDomainError, UpstreamDomainError
from api.models import (
    DayPlan,
    HealthzResponse,
    ItineraryBlock,
    SearchRefs,
    TripCreateInput,
    TripPlan,
)
from api.repository import InMemorySearchRepository, InMemoryTripRepository


def _sample_trip() -> TripPlan:
    return TripPlan(
        trip_id="trip_1",
        inputs=TripCreateInput(
            start_date="2026-03-14",
            end_date="2026-03-16",
            origin="JFK",
            destinations=["LHR"],
            budget_level="mid",
        ),
        timezone="UTC",
        search_refs=SearchRefs(
            flight_search_id="flight_1",
            attractions_search_id="attr_1",
        ),
        used_place_ids=[],
        itinerary=[
            DayPlan(
                date="2026-03-14",
                timezone="UTC",
                day_summary="Day 1",
                used_place_ids=[],
                used_titles=[],
                blocks=[
                    ItineraryBlock(
                        block_id="b1",
                        start_at="2026-03-14T09:00:00+00:00",
                        end_at="2026-03-14T12:00:00+00:00",
                        kind="cafe",
                        title="Coffee",
                        status="planned",
                    )
                ],
            )
        ],
        transit=[],
        audit_log=[],
    )


class _StubService:
    def __init__(self) -> None:
        self.create_exception: Exception | None = None
        self.compose_exception: Exception | None = None
        self.get_exception: Exception | None = None

    def create_trip(self, *, payload, use_cache: bool):
        if self.create_exception is not None:
            raise self.create_exception
        return _sample_trip()

    def compose_itinerary(self, *, payload, use_cache: bool):
        if self.compose_exception is not None:
            raise self.compose_exception
        return _sample_trip()

    def get_trip(self, trip_id: str):
        if self.get_exception is not None:
            raise self.get_exception
        return _sample_trip()

    def skip_block(self, trip_id: str, block_id: str):
        if self.get_exception is not None:
            raise self.get_exception
        return _sample_trip()

    def change_block(self, trip_id: str, block_id: str, payload):
        if self.get_exception is not None:
            raise self.get_exception
        return _sample_trip()

    def healthz(self):
        return HealthzResponse(ok=True, db=True)


def _client_for(service: _StubService) -> TestClient:
    container = ApiContainer(
        repository=InMemoryTripRepository(),
        search_repository=InMemorySearchRepository(),
        service=service,
    )
    return TestClient(create_app(container=container), raise_server_exceptions=False)


class ErrorMappingTests(unittest.TestCase):
    def test_healthz_returns_200(self) -> None:
        service = _StubService()
        client = _client_for(service)

        response = client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "db": True})

    def test_request_validation_maps_to_400_bad_request(self) -> None:
        service = _StubService()
        client = _client_for(service)

        response = client.post("/v1/trips", json={"origin": "JFK"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "bad_request")

    def test_not_found_maps_to_404(self) -> None:
        service = _StubService()
        service.get_exception = NotFoundDomainError("Trip 'missing' was not found.")
        client = _client_for(service)

        response = client.get("/v1/trips/missing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "not_found")

    def test_upstream_maps_to_502(self) -> None:
        service = _StubService()
        service.create_exception = UpstreamDomainError("Upstream dependency failure.")
        client = _client_for(service)

        response = client.post(
            "/v1/trips",
            json={
                "start_date": "2026-03-14",
                "end_date": "2026-03-16",
                "origin": "JFK",
                "destinations": ["LHR"],
                "budget_level": "mid",
            },
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "upstream_error")

    def test_repository_error_maps_to_502_repository_error(self) -> None:
        service = _StubService()
        service.get_exception = RepositoryDomainError("Failed to load trip record.")
        client = _client_for(service)

        response = client.get("/v1/trips/t1")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "repository_error")


if __name__ == "__main__":
    unittest.main()
