from __future__ import annotations


def quote_identifier(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        raise ValueError("Identifier cannot be empty.")
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
    if any(ch not in allowed for ch in candidate):
        raise ValueError(f"Unsupported identifier '{value}'.")
    return f"`{candidate}`"


def fq_table(catalog: str, schema: str, table: str) -> str:
    return ".".join(
        [
            quote_identifier(catalog),
            quote_identifier(schema),
            quote_identifier(table),
        ]
    )


def create_schema_sql(catalog: str, schema: str) -> str:
    return f"CREATE SCHEMA IF NOT EXISTS {quote_identifier(catalog)}.{quote_identifier(schema)}"


def create_trips_table_sql(*, catalog: str, schema: str, table: str) -> str:
    trips = fq_table(catalog, schema, table)
    return (
        f"CREATE TABLE IF NOT EXISTS {trips} ("
        "tenant_id STRING,"
        "trip_id STRING,"
        "user_id STRING,"
        "destination STRING,"
        "timezone STRING,"
        "revision INT,"
        "status STRING,"
        "trip_plan_json STRING,"
        "itinerary_json STRING,"
        "plan_request_json STRING,"
        "search_refs_mode STRING,"
        "transit_policy_version STRING,"
        "parent_trip_id STRING,"
        "cache_key STRING,"
        "created_at TIMESTAMP,"
        "updated_at TIMESTAMP"
        ") USING DELTA"
    )


def create_events_table_sql(*, catalog: str, schema: str, table: str) -> str:
    events = fq_table(catalog, schema, table)
    return (
        f"CREATE TABLE IF NOT EXISTS {events} ("
        "event_id STRING,"
        "tenant_id STRING,"
        "trip_id STRING,"
        "user_id STRING,"
        "request_id STRING,"
        "event_type STRING,"
        "event_payload_json STRING,"
        "created_at TIMESTAMP"
        ") USING DELTA"
    )


def create_searches_table_sql(*, catalog: str, schema: str, table: str) -> str:
    searches = fq_table(catalog, schema, table)
    return (
        f"CREATE TABLE IF NOT EXISTS {searches} ("
        "search_id STRING,"
        "search_type STRING,"
        "query_json STRING,"
        "status STRING,"
        "results_json STRING,"
        "notes_json STRING,"
        "error_json STRING,"
        "created_at TIMESTAMP,"
        "expires_at TIMESTAMP,"
        "updated_at TIMESTAMP"
        ") USING DELTA"
    )
