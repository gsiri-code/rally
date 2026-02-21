from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings
from qdrant_client import QdrantClient, models


DESTINATION_ALIASES = {
    "nyc": "New York City",
    "new york": "New York City",
    "new york city": "New York City",
    "paris": "Paris",
    "london": "London",
}


@dataclass(frozen=True)
class RetrievalRequest:
    raw_query: str
    destination: str | None = None
    item_type: str | None = None
    popularity_mode: str | None = None
    origin_lat: float | None = None
    origin_lon: float | None = None
    radius_meters: float | None = None
    freshness_days: int | None = None
    limit: int = 50


def normalize_query_text(raw_query: str) -> str:
    normalized = " ".join(raw_query.strip().split())
    if not normalized:
        raise RuntimeError("Query cannot be empty.")
    return normalized


def infer_destination(query_text: str) -> str | None:
    lowered = query_text.lower()
    for alias, canonical in DESTINATION_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return canonical
    return None


def infer_item_type(query_text: str) -> str | None:
    lowered = query_text.lower()
    if re.search(r"\b(hotel|stay|accommodation|hostel)\b", lowered):
        return "hotel"
    if re.search(r"\b(restaurant|food|dining|nightlife|bar|club)\b", lowered):
        return "restaurant"
    if re.search(r"\b(museum|attraction|sight|itinerary|activity)\b", lowered):
        return "attraction"
    return None


def infer_popularity_mode(query_text: str) -> str | None:
    lowered = query_text.lower()
    if re.search(
        r"\b(hidden gem|hidden gems|offbeat|underrated|local spots?)\b", lowered
    ):
        return "hidden_gems"
    if re.search(r"\b(iconic|must-see|top|famous|popular)\b", lowered):
        return "iconic"
    return None


def infer_geo_radius(query_text: str, radius_meters: float | None) -> float | None:
    if radius_meters is not None:
        return radius_meters

    lowered = query_text.lower()
    if re.search(r"\b(walkable|walking distance|nearby|near me|close by)\b", lowered):
        return 2500.0
    return None


def infer_freshness_days(query_text: str, freshness_days: int | None) -> int | None:
    if freshness_days is not None:
        return freshness_days

    lowered = query_text.lower()
    if re.search(r"\b(recent|new|latest|fresh)\b", lowered):
        return 30
    return None


def build_filters(request: RetrievalRequest, query_text: str) -> models.Filter | None:
    destination = request.destination or infer_destination(query_text)
    item_type = request.item_type or infer_item_type(query_text)
    popularity_mode = request.popularity_mode or infer_popularity_mode(query_text)
    radius_meters = infer_geo_radius(query_text, request.radius_meters)
    freshness_days = infer_freshness_days(query_text, request.freshness_days)

    conditions: list[models.Condition] = []

    if destination:
        conditions.append(
            models.FieldCondition(
                key="destination",
                match=models.MatchValue(value=destination),
            )
        )

    if item_type:
        conditions.append(
            models.FieldCondition(
                key="type",
                match=models.MatchValue(value=item_type),
            )
        )

    if popularity_mode == "hidden_gems":
        conditions.append(
            models.FieldCondition(
                key="popularity_score",
                range=models.Range(lte=50),
            )
        )
    elif popularity_mode == "iconic":
        conditions.append(
            models.FieldCondition(
                key="popularity_score",
                range=models.Range(gte=80),
            )
        )

    if (
        radius_meters is not None
        and request.origin_lat is not None
        and request.origin_lon is not None
    ):
        conditions.append(
            models.FieldCondition(
                key="geo",
                geo_radius=models.GeoRadius(
                    center=models.GeoPoint(
                        lat=request.origin_lat, lon=request.origin_lon
                    ),
                    radius=radius_meters,
                ),
            )
        )

    if freshness_days is not None:
        threshold = datetime.now(timezone.utc) - timedelta(days=freshness_days)
        conditions.append(
            models.FieldCondition(
                key="ingested_at",
                range=models.DatetimeRange(gte=threshold),
            )
        )

    if not conditions:
        return None
    return models.Filter(must=conditions)


def retrieve_travel_candidates(
    request: RetrievalRequest,
    *,
    qdrant_url: str,
    qdrant_api_key: str,
    nvidia_api_key: str,
    nvidia_model: str = "nvidia/llama-nemotron-embed-vl-1b-v2",
    collection_name: str = "travel_items",
) -> list[dict]:
    query_text = normalize_query_text(request.raw_query)
    q_filter = build_filters(request, query_text)

    embedder = NVIDIAEmbeddings(
        model=nvidia_model,
        api_key=nvidia_api_key,
        truncate="NONE",
    )
    q_vec = embedder.embed_query(query_text)

    qdrant = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
    if not qdrant.collection_exists(collection_name):
        raise RuntimeError(f"Collection '{collection_name}' does not exist.")

    limit = max(30, min(80, request.limit))
    response = qdrant.query_points(
        collection_name=collection_name,
        query=q_vec,
        query_filter=q_filter,
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    hits = response.points

    return [
        {
            "id": str(hit.id),
            "score": hit.score,
            "payload": hit.payload,
        }
        for hit in hits
    ]


def env_settings() -> tuple[str, str, str, str]:
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
