from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from langchain_core.tools import tool
from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings
from qdrant_client import QdrantClient, models


@dataclass(frozen=True)
class TravelItem:
    destination: str
    slug: str
    item_type: str
    link: str
    keywords: list[str]
    popularity_score: int
    ingested_at: str
    geo: dict[str, float]


@dataclass(frozen=True)
class TripMemory:
    user_id: str
    trip_id: str
    feedback: str
    created_at: str


def _parse_iso_datetime(value: str, field_name: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise RuntimeError(f"Invalid datetime for '{field_name}': {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _normalize_geo(geo: dict[str, float]) -> dict[str, float]:
    if "lat" not in geo or "lon" not in geo:
        raise RuntimeError("geo must include both 'lat' and 'lon'.")
    return {"lat": float(geo["lat"]), "lon": float(geo["lon"])}


def build_travel_item_text(item: TravelItem) -> str:
    keywords = ", ".join(item.keywords)
    return (
        "Travel item summary:\n"
        f"- Destination: {item.destination}\n"
        f"- Type: {item.item_type}\n"
        f"- Slug: {item.slug}\n"
        f"- Link: {item.link}\n"
        f"- Keywords: {keywords}\n"
        f"- Popularity score: {item.popularity_score}"
    )


def build_trip_memory_text(memory: TripMemory) -> str:
    return (
        "Trip memory summary:\n"
        f"- User ID: {memory.user_id}\n"
        f"- Trip ID: {memory.trip_id}\n"
        f"- Feedback: {memory.feedback}\n"
        f"- Created at: {memory.created_at}"
    )


def point_id_from_travel_item(item: TravelItem) -> str:
    seed = (
        f"travel-item::{item.destination}::{item.item_type}::{item.slug}::{item.link}"
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def point_id_from_trip_memory(memory: TripMemory) -> str:
    seed = f"trip-memory::{memory.user_id}::{memory.trip_id}::{memory.created_at}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def _embed_text(text: str, nvidia_api_key: str, nvidia_model: str) -> list[float]:
    embedder = NVIDIAEmbeddings(
        model=nvidia_model,
        api_key=nvidia_api_key,
        truncate="NONE",
    )
    return embedder.embed_query(text)


def ensure_travel_items_schema(
    qdrant_url: str,
    qdrant_api_key: str,
    collection_name: str = "travel_items",
) -> dict[str, Any]:
    qdrant = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
    if not qdrant.collection_exists(collection_name):
        raise RuntimeError(f"Collection '{collection_name}' does not exist.")

    schema = {
        "destination": models.PayloadSchemaType.KEYWORD,
        "slug": models.PayloadSchemaType.KEYWORD,
        "type": models.PayloadSchemaType.KEYWORD,
        "link": models.PayloadSchemaType.KEYWORD,
        "keywords": models.PayloadSchemaType.KEYWORD,
        "popularity_score": models.PayloadSchemaType.INTEGER,
        "ingested_at": models.PayloadSchemaType.DATETIME,
        "geo": models.PayloadSchemaType.GEO,
    }

    indexed_fields = []
    for field_name, field_schema in schema.items():
        qdrant.create_payload_index(
            collection_name=collection_name,
            field_name=field_name,
            field_schema=field_schema,
            wait=True,
        )
        indexed_fields.append(field_name)

    return {
        "collection": collection_name,
        "indexed_fields": indexed_fields,
        "field_count": len(indexed_fields),
    }


def ensure_trip_memory_schema(
    qdrant_url: str,
    qdrant_api_key: str,
    collection_name: str = "trip_memory",
) -> dict[str, Any]:
    qdrant = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
    if not qdrant.collection_exists(collection_name):
        raise RuntimeError(f"Collection '{collection_name}' does not exist.")

    schema = {
        "user_id": models.PayloadSchemaType.KEYWORD,
        "trip_id": models.PayloadSchemaType.KEYWORD,
        "feedback": models.PayloadSchemaType.KEYWORD,
        "created_at": models.PayloadSchemaType.DATETIME,
    }

    indexed_fields = []
    for field_name, field_schema in schema.items():
        qdrant.create_payload_index(
            collection_name=collection_name,
            field_name=field_name,
            field_schema=field_schema,
            wait=True,
        )
        indexed_fields.append(field_name)

    return {
        "collection": collection_name,
        "indexed_fields": indexed_fields,
        "field_count": len(indexed_fields),
    }


def upsert_travel_item(
    item: TravelItem,
    qdrant_url: str,
    qdrant_api_key: str,
    nvidia_api_key: str,
    collection_name: str = "travel_items",
    nvidia_model: str = "nvidia/llama-nemotron-embed-vl-1b-v2",
) -> dict[str, Any]:
    _parse_iso_datetime(item.ingested_at, "ingested_at")
    normalized_geo = _normalize_geo(item.geo)
    item_text = build_travel_item_text(item)
    vector = _embed_text(
        item_text, nvidia_api_key=nvidia_api_key, nvidia_model=nvidia_model
    )

    qdrant = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
    if not qdrant.collection_exists(collection_name):
        raise RuntimeError(f"Collection '{collection_name}' does not exist.")

    point_id = point_id_from_travel_item(item)
    payload = {
        "destination": item.destination,
        "slug": item.slug,
        "type": item.item_type,
        "link": item.link,
        "keywords": item.keywords,
        "popularity_score": int(item.popularity_score),
        "ingested_at": item.ingested_at,
        "geo": normalized_geo,
    }

    qdrant.upsert(
        collection_name=collection_name,
        points=[models.PointStruct(id=point_id, vector=vector, payload=payload)],
        wait=True,
    )

    return {
        "point_id": point_id,
        "collection": collection_name,
        "vector_dim": len(vector),
        "destination": item.destination,
        "slug": item.slug,
    }


def upsert_trip_memory(
    memory: TripMemory,
    qdrant_url: str,
    qdrant_api_key: str,
    nvidia_api_key: str,
    collection_name: str = "trip_memory",
    nvidia_model: str = "nvidia/llama-nemotron-embed-vl-1b-v2",
) -> dict[str, Any]:
    _parse_iso_datetime(memory.created_at, "created_at")
    memory_text = build_trip_memory_text(memory)
    vector = _embed_text(
        memory_text,
        nvidia_api_key=nvidia_api_key,
        nvidia_model=nvidia_model,
    )

    qdrant = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
    if not qdrant.collection_exists(collection_name):
        raise RuntimeError(f"Collection '{collection_name}' does not exist.")

    point_id = point_id_from_trip_memory(memory)
    payload = {
        "user_id": memory.user_id,
        "trip_id": memory.trip_id,
        "feedback": memory.feedback,
        "created_at": memory.created_at,
    }

    qdrant.upsert(
        collection_name=collection_name,
        points=[models.PointStruct(id=point_id, vector=vector, payload=payload)],
        wait=True,
    )

    return {
        "point_id": point_id,
        "collection": collection_name,
        "vector_dim": len(vector),
        "user_id": memory.user_id,
        "trip_id": memory.trip_id,
    }


def from_env() -> tuple[str, str, str, str]:
    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    nvidia_api_key = os.getenv("NVIDIA_API_KEY")
    nvidia_model = os.getenv(
        "NVIDIA_EMBED_MODEL", "nvidia/llama-nemotron-embed-vl-1b-v2"
    )

    if not qdrant_url or not qdrant_api_key:
        raise RuntimeError("Missing QDRANT_URL or QDRANT_API_KEY.")
    if not nvidia_api_key:
        raise RuntimeError("Missing NVIDIA_API_KEY.")

    return qdrant_url, qdrant_api_key, nvidia_api_key, nvidia_model


@tool
def upsert_travel_item_tool(
    destination: str,
    slug: str,
    item_type: str,
    link: str,
    keywords: list[str],
    popularity_score: int,
    ingested_at: str,
    lat: float,
    lon: float,
) -> dict[str, Any]:
    """Upsert one travel item into Qdrant travel_items collection."""
    qdrant_url, qdrant_api_key, nvidia_api_key, nvidia_model = from_env()
    item = TravelItem(
        destination=destination,
        slug=slug,
        item_type=item_type,
        link=link,
        keywords=keywords,
        popularity_score=popularity_score,
        ingested_at=ingested_at,
        geo={"lat": lat, "lon": lon},
    )
    return upsert_travel_item(
        item=item,
        qdrant_url=qdrant_url,
        qdrant_api_key=qdrant_api_key,
        nvidia_api_key=nvidia_api_key,
        nvidia_model=nvidia_model,
    )


@tool
def upsert_trip_memory_tool(
    user_id: str,
    trip_id: str,
    feedback: str,
    created_at: str,
) -> dict[str, Any]:
    """Upsert one trip memory into Qdrant trip_memory collection."""
    qdrant_url, qdrant_api_key, nvidia_api_key, nvidia_model = from_env()
    memory = TripMemory(
        user_id=user_id,
        trip_id=trip_id,
        feedback=feedback,
        created_at=created_at,
    )
    return upsert_trip_memory(
        memory=memory,
        qdrant_url=qdrant_url,
        qdrant_api_key=qdrant_api_key,
        nvidia_api_key=nvidia_api_key,
        nvidia_model=nvidia_model,
    )


@tool
def ensure_travel_items_schema_tool() -> dict[str, Any]:
    """Ensure payload indexes for travel_items collection."""
    qdrant_url, qdrant_api_key, _, _ = from_env()
    return ensure_travel_items_schema(
        qdrant_url=qdrant_url,
        qdrant_api_key=qdrant_api_key,
    )


@tool
def ensure_trip_memory_schema_tool() -> dict[str, Any]:
    """Ensure payload indexes for trip_memory collection."""
    qdrant_url, qdrant_api_key, _, _ = from_env()
    return ensure_trip_memory_schema(
        qdrant_url=qdrant_url,
        qdrant_api_key=qdrant_api_key,
    )


def get_langchain_tools() -> list[Any]:
    return [
        ensure_travel_items_schema_tool,
        ensure_trip_memory_schema_tool,
        upsert_travel_item_tool,
        upsert_trip_memory_tool,
    ]
