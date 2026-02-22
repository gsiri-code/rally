from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import uuid

from models.persistence_types import (
    PersistedFeedbackEvent,
    PersistedSearchRecord,
    PersistedTripRecord,
    SearchPersistenceStore,
    TripPersistenceStore,
)

from warehouse_db.sql import (
    create_events_table_sql,
    create_searches_table_sql,
    create_schema_sql,
    create_trips_table_sql,
    fq_table,
)


@dataclass(frozen=True)
class DatabricksSqlConfig:
    server_hostname: str
    http_path: str
    access_token: str
    catalog: str = "main"
    schema: str = "trip_planner"
    trips_table: str = "trips"
    events_table: str = "trip_events"
    searches_table: str = "searches"

    @classmethod
    def from_env(cls) -> DatabricksSqlConfig:
        host = os.getenv("DATABRICKS_SERVER_HOSTNAME")
        http_path = os.getenv("DATABRICKS_HTTP_PATH")
        token = os.getenv("DATABRICKS_TOKEN")
        if not host or not http_path or not token:
            raise ValueError(
                "Missing Databricks SQL settings. Expected "
                "DATABRICKS_SERVER_HOSTNAME, DATABRICKS_HTTP_PATH, DATABRICKS_TOKEN."
            )

        return cls(
            server_hostname=host,
            http_path=http_path,
            access_token=token,
            catalog=os.getenv("TRIP_DBX_CATALOG", "main"),
            schema=os.getenv("TRIP_DBX_SCHEMA", "trip_planner"),
            trips_table=os.getenv("TRIP_DBX_TRIPS_TABLE", "trips"),
            events_table=os.getenv("TRIP_DBX_EVENTS_TABLE", "trip_events"),
            searches_table=os.getenv("TRIP_DBX_SEARCHES_TABLE", "searches"),
        )


class DatabricksSqlTripRepository(TripPersistenceStore):
    def __init__(self, config: DatabricksSqlConfig) -> None:
        self._config = config
        self._schema_ready = False

    def save_trip_record(self, record: PersistedTripRecord) -> None:
        self._ensure_schema()
        now = datetime.now(timezone.utc)

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    (
                        f"SELECT revision, created_at FROM {self._trips_table()} "
                        "WHERE tenant_id = ? AND trip_id = ? "
                        "ORDER BY revision DESC LIMIT 1"
                    ),
                    [record.tenant_id, record.trip_id],
                )
                row = cursor.fetchone()
                revision = 1 if row is None else int(row[0]) + 1
                created_at = now if row is None else row[1]

                cursor.execute(
                    (
                        f"DELETE FROM {self._trips_table()} "
                        "WHERE tenant_id = ? AND trip_id = ?"
                    ),
                    [record.tenant_id, record.trip_id],
                )
                cursor.execute(
                    (
                        f"INSERT INTO {self._trips_table()} ("
                        "tenant_id, trip_id, user_id, destination, timezone, revision, "
                        "status, trip_plan_json, itinerary_json, plan_request_json, "
                        "search_refs_mode, transit_policy_version, parent_trip_id, cache_key, "
                        "created_at, updated_at"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    ),
                    [
                        record.tenant_id,
                        record.trip_id,
                        record.user_id,
                        record.destination,
                        record.timezone,
                        revision,
                        "active",
                        record.trip_plan_json,
                        record.itinerary_json,
                        record.plan_request_json,
                        record.search_refs_mode,
                        record.transit_policy_version,
                        record.parent_trip_id,
                        None,
                        created_at,
                        now,
                    ],
                )

                event_payload = {
                    "destination": record.destination,
                    "revision": revision,
                    "timezone": record.timezone,
                    "trip_id": record.trip_id,
                }
                cursor.execute(
                    (
                        f"INSERT INTO {self._events_table()} ("
                        "event_id, tenant_id, trip_id, user_id, request_id, event_type, "
                        "event_payload_json, created_at"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                    ),
                    [
                        str(uuid.uuid4()),
                        record.tenant_id,
                        record.trip_id,
                        record.user_id,
                        record.request_id,
                        "trip_upsert",
                        json.dumps(event_payload, sort_keys=True),
                        now,
                    ],
                )

    def get_trip_record(self, trip_id: str) -> PersistedTripRecord | None:
        self._ensure_schema()

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    (
                        "SELECT tenant_id, trip_id, user_id, request_id, destination, "
                        "timezone, trip_plan_json, itinerary_json, plan_request_json, "
                        "parent_trip_id, search_refs_mode, transit_policy_version "
                        f"FROM {self._trips_table()} WHERE trip_id = ? "
                        "ORDER BY updated_at DESC LIMIT 1"
                    ),
                    [trip_id],
                )
                row = cursor.fetchone()
                if row is None:
                    return None

                return PersistedTripRecord(
                    tenant_id=str(row[0]),
                    trip_id=str(row[1]),
                    user_id=str(row[2]),
                    request_id=str(row[3]),
                    destination=str(row[4]) if row[4] is not None else None,
                    timezone=str(row[5]),
                    trip_plan_json=str(row[6]),
                    itinerary_json=str(row[7]),
                    plan_request_json=str(row[8]),
                    parent_trip_id=str(row[9]) if row[9] is not None else None,
                    search_refs_mode=str(row[10]),
                    transit_policy_version=str(row[11]),
                )

    def save_feedback(self, event: PersistedFeedbackEvent) -> None:
        self._ensure_schema()
        payload = {
            "feedback": event.feedback,
            "timezone": event.timezone,
        }

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    (
                        f"INSERT INTO {self._events_table()} ("
                        "event_id, tenant_id, trip_id, user_id, request_id, event_type, "
                        "event_payload_json, created_at"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                    ),
                    [
                        str(uuid.uuid4()),
                        event.tenant_id,
                        event.trip_id,
                        event.user_id,
                        event.request_id,
                        "feedback_submitted",
                        json.dumps(payload, sort_keys=True),
                        event.created_at,
                    ],
                )

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    create_schema_sql(self._config.catalog, self._config.schema)
                )
                cursor.execute(
                    create_trips_table_sql(
                        catalog=self._config.catalog,
                        schema=self._config.schema,
                        table=self._config.trips_table,
                    )
                )
                cursor.execute(
                    create_events_table_sql(
                        catalog=self._config.catalog,
                        schema=self._config.schema,
                        table=self._config.events_table,
                    )
                )
                cursor.execute(
                    create_searches_table_sql(
                        catalog=self._config.catalog,
                        schema=self._config.schema,
                        table=self._config.searches_table,
                    )
                )

        self._schema_ready = True

    def _trips_table(self) -> str:
        return fq_table(
            self._config.catalog,
            self._config.schema,
            self._config.trips_table,
        )

    def _events_table(self) -> str:
        return fq_table(
            self._config.catalog,
            self._config.schema,
            self._config.events_table,
        )

    def _connect(self):
        from databricks import sql

        return sql.connect(
            server_hostname=self._config.server_hostname,
            http_path=self._config.http_path,
            access_token=self._config.access_token,
            catalog=self._config.catalog,
            schema=self._config.schema,
        )


class DatabricksSqlSearchRepository(SearchPersistenceStore):
    def __init__(self, config: DatabricksSqlConfig) -> None:
        self._config = config
        self._schema_ready = False

    def save_search_record(self, record: PersistedSearchRecord) -> None:
        self._ensure_schema()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM {self._searches_table()} WHERE search_id = ?",
                    [record.search_id],
                )
                cursor.execute(
                    (
                        f"INSERT INTO {self._searches_table()} ("
                        "search_id, search_type, query_json, status, results_json, "
                        "notes_json, error_json, created_at, expires_at, updated_at"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    ),
                    [
                        record.search_id,
                        record.search_type,
                        record.query_json,
                        record.status,
                        record.results_json,
                        record.notes_json,
                        record.error_json,
                        record.created_at,
                        record.expires_at,
                        record.updated_at,
                    ],
                )

    def get_search_record(self, search_id: str) -> PersistedSearchRecord | None:
        self._ensure_schema()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    (
                        "SELECT search_id, search_type, query_json, status, results_json, "
                        "notes_json, error_json, created_at, expires_at, updated_at "
                        f"FROM {self._searches_table()} WHERE search_id = ? "
                        "ORDER BY updated_at DESC LIMIT 1"
                    ),
                    [search_id],
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                return PersistedSearchRecord(
                    search_id=str(row[0]),
                    search_type=str(row[1]),
                    query_json=str(row[2]),
                    status=str(row[3]),
                    results_json=str(row[4]),
                    notes_json=str(row[5]),
                    error_json=str(row[6]) if row[6] is not None else None,
                    created_at=row[7],
                    expires_at=row[8],
                    updated_at=row[9],
                )

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    create_schema_sql(self._config.catalog, self._config.schema)
                )
                cursor.execute(
                    create_searches_table_sql(
                        catalog=self._config.catalog,
                        schema=self._config.schema,
                        table=self._config.searches_table,
                    )
                )
        self._schema_ready = True

    def _searches_table(self) -> str:
        return fq_table(
            self._config.catalog,
            self._config.schema,
            self._config.searches_table,
        )

    def _connect(self):
        from databricks import sql

        return sql.connect(
            server_hostname=self._config.server_hostname,
            http_path=self._config.http_path,
            access_token=self._config.access_token,
            catalog=self._config.catalog,
            schema=self._config.schema,
        )
