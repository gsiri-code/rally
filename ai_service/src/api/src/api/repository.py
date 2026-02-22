from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from typing import Protocol

from models.persistence_types import (
    PersistedSearchRecord,
    PersistedTripRecord,
    SearchPersistenceStore,
    TripPersistenceStore,
)
from orchestrator_agent.contracts import ItineraryPlan, PlanRequest

from api.errors import CacheDomainError, RepositoryDomainError
from api.models import SearchResponse, TripPlan


@dataclass
class TripRecord:
    trip: TripPlan
    itinerary: ItineraryPlan
    plan_request: PlanRequest
    timezone: str


class TripRepository(Protocol):
    def save_trip_record(self, record: TripRecord) -> None: ...

    def get_trip_record(self, trip_id: str) -> TripRecord | None: ...


class SearchRepository(Protocol):
    def save_search(self, search: SearchResponse, *, search_type: str) -> None: ...

    def get_search(self, search_id: str) -> SearchResponse | None: ...


def build_trip_repository_from_env() -> TripRepository:
    if not os.getenv("DATABRICKS_SERVER_HOSTNAME") or not os.getenv(
        "DATABRICKS_HTTP_PATH"
    ):
        return InMemoryTripRepository()

    try:
        from warehouse_db.databricks_repository import (
            DatabricksSqlConfig,
            DatabricksSqlTripRepository,
        )

        config = DatabricksSqlConfig.from_env()
        store = DatabricksSqlTripRepository(config)
        return WarehouseTripRepositoryAdapter(store)
    except Exception as exc:  # noqa: BLE001
        raise RepositoryDomainError("Failed to initialize trip repository.") from exc


def build_search_repository_from_env() -> SearchRepository:
    if not os.getenv("DATABRICKS_SERVER_HOSTNAME") or not os.getenv(
        "DATABRICKS_HTTP_PATH"
    ):
        return InMemorySearchRepository()

    try:
        from warehouse_db.databricks_repository import (
            DatabricksSqlConfig,
            DatabricksSqlSearchRepository,
        )

        config = DatabricksSqlConfig.from_env()
        store = DatabricksSqlSearchRepository(config)
        return WarehouseSearchRepositoryAdapter(store)
    except Exception as exc:  # noqa: BLE001
        raise RepositoryDomainError("Failed to initialize search repository.") from exc


@dataclass
class WarehouseTripRepositoryAdapter:
    store: TripPersistenceStore

    def save_trip_record(self, record: TripRecord) -> None:
        try:
            persisted = PersistedTripRecord(
                tenant_id=record.plan_request.context.tenant_id or "default",
                trip_id=record.trip.trip_id,
                user_id=record.plan_request.context.user_id or "unknown",
                request_id=record.plan_request.context.request_id,
                destination=(
                    record.trip.inputs.destinations[0]
                    if record.trip.inputs.destinations
                    else None
                ),
                timezone=record.timezone,
                trip_plan_json=record.trip.model_dump_json(),
                itinerary_json=record.itinerary.model_dump_json(),
                plan_request_json=record.plan_request.model_dump_json(),
                parent_trip_id=(
                    record.plan_request.prior_plan.plan_id
                    if record.plan_request.prior_plan is not None
                    else None
                ),
            )
            self.store.save_trip_record(persisted)
        except Exception as exc:  # noqa: BLE001
            raise RepositoryDomainError("Failed to save trip record.") from exc

    def get_trip_record(self, trip_id: str) -> TripRecord | None:
        try:
            persisted = self.store.get_trip_record(trip_id)
            if persisted is None:
                return None

            return TripRecord(
                trip=TripPlan.model_validate_json(persisted.trip_plan_json),
                itinerary=ItineraryPlan.model_validate_json(persisted.itinerary_json),
                plan_request=PlanRequest.model_validate_json(
                    persisted.plan_request_json
                ),
                timezone=persisted.timezone,
            )
        except Exception as exc:  # noqa: BLE001
            raise CacheDomainError("Failed to read cached trip record.") from exc


@dataclass
class InMemoryTripRepository:
    trips: dict[str, TripRecord] = field(default_factory=dict)

    def save_trip_record(self, record: TripRecord) -> None:
        try:
            self.trips[record.trip.trip_id] = record
        except Exception as exc:  # noqa: BLE001
            raise RepositoryDomainError("Failed to save trip record.") from exc

    def get_trip_record(self, trip_id: str) -> TripRecord | None:
        try:
            return self.trips.get(trip_id)
        except Exception as exc:  # noqa: BLE001
            raise CacheDomainError("Failed to read cached trip record.") from exc


@dataclass
class WarehouseSearchRepositoryAdapter:
    store: SearchPersistenceStore

    def save_search(self, search: SearchResponse, *, search_type: str) -> None:
        now = datetime.now(timezone.utc)
        try:
            persisted = PersistedSearchRecord(
                search_id=search.search_id,
                search_type=search_type,
                query_json=json.dumps(search.query, sort_keys=True),
                status=search.status,
                results_json=json.dumps(search.results, sort_keys=True),
                notes_json=json.dumps(search.notes, sort_keys=True),
                error_json=(
                    json.dumps(search.error, sort_keys=True)
                    if search.error is not None
                    else None
                ),
                created_at=datetime.fromisoformat(
                    search.created_at.replace("Z", "+00:00")
                ),
                expires_at=datetime.fromisoformat(
                    search.expires_at.replace("Z", "+00:00")
                ),
                updated_at=now,
            )
            self.store.save_search_record(persisted)
        except Exception as exc:  # noqa: BLE001
            raise RepositoryDomainError("Failed to save search record.") from exc

    def get_search(self, search_id: str) -> SearchResponse | None:
        try:
            persisted = self.store.get_search_record(search_id)
            if persisted is None:
                return None
            return SearchResponse(
                search_id=persisted.search_id,
                query=json.loads(persisted.query_json),
                status=persisted.status,
                results=json.loads(persisted.results_json),
                notes=json.loads(persisted.notes_json),
                error=(
                    json.loads(persisted.error_json)
                    if persisted.error_json is not None
                    else None
                ),
                created_at=persisted.created_at.astimezone(timezone.utc).isoformat(),
                expires_at=persisted.expires_at.astimezone(timezone.utc).isoformat(),
            )
        except Exception as exc:  # noqa: BLE001
            raise CacheDomainError("Failed to read cached search record.") from exc


@dataclass
class InMemorySearchRepository:
    searches: dict[str, SearchResponse] = field(default_factory=dict)

    def save_search(self, search: SearchResponse, *, search_type: str) -> None:
        _ = search_type
        try:
            self.searches[search.search_id] = search
        except Exception as exc:  # noqa: BLE001
            raise RepositoryDomainError("Failed to save search record.") from exc

    def get_search(self, search_id: str) -> SearchResponse | None:
        try:
            return self.searches.get(search_id)
        except Exception as exc:  # noqa: BLE001
            raise CacheDomainError("Failed to read cached search record.") from exc
