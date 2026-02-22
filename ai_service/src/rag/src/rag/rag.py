from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings
from qdrant_client import QdrantClient, models

from rag.rerank import RerankSettings, rerank_candidates
from rag.retrieval import normalize_query_text

DEFAULT_TOP_K = 40
DEFAULT_FRESHNESS_DAYS = 180
DEFAULT_GEO_RADIUS_METERS = 2500.0
FALLBACK_DEDUPE_RADIUS_METERS = 300.0


@dataclass(frozen=True)
class RagSettings:
    qdrant_url: str
    qdrant_api_key: str
    nvidia_api_key: str
    nvidia_model: str
    rerank_enabled: bool
    rerank_model: str
    rerank_url: str
    rerank_top_n: int
    rerank_timeout_sec: float
    rerank_max_attempts: int


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalized_url(url: str) -> str:
    split = urlsplit(url.strip())
    scheme = (split.scheme or "https").lower()
    netloc = split.netloc.lower()
    path = split.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


def _load_settings() -> RagSettings:
    import os

    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    nvidia_api_key = os.getenv("NVIDIA_API_KEY")
    nvidia_model = os.getenv(
        "NVIDIA_EMBED_MODEL", "nvidia/llama-nemotron-embed-vl-1b-v2"
    )
    rerank_enabled = os.getenv("RAG_RERANK_ENABLED", "true").lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    rerank_model = os.getenv("NVIDIA_RERANK_MODEL", "nvidia/nv-rerankqa-mistral-4b-v3")
    rerank_url = os.getenv(
        "NVIDIA_RERANK_URL", "https://integrate.api.nvidia.com/v1/retranking"
    )
    rerank_top_n = int(os.getenv("RAG_RERANK_TOP_N", "15"))
    rerank_timeout_sec = float(os.getenv("RAG_RERANK_TIMEOUT_SEC", "15"))
    rerank_max_attempts = int(os.getenv("RAG_RERANK_MAX_ATTEMPTS", "2"))

    if not qdrant_url or not qdrant_api_key:
        raise RuntimeError("Missing QDRANT_URL or QDRANT_API_KEY.")
    if not nvidia_api_key:
        raise RuntimeError("Missing NVIDIA_API_KEY.")

    return RagSettings(
        qdrant_url=qdrant_url,
        qdrant_api_key=qdrant_api_key,
        nvidia_api_key=nvidia_api_key,
        nvidia_model=nvidia_model,
        rerank_enabled=rerank_enabled,
        rerank_model=rerank_model,
        rerank_url=rerank_url,
        rerank_top_n=max(1, rerank_top_n),
        rerank_timeout_sec=max(1.0, rerank_timeout_sec),
        rerank_max_attempts=max(1, rerank_max_attempts),
    )


def _embed_text(text: str, settings: RagSettings) -> list[float]:
    embedder = NVIDIAEmbeddings(
        model=settings.nvidia_model,
        api_key=settings.nvidia_api_key,
        truncate="NONE",
    )
    return embedder.embed_query(text)


def _haversine_meters(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    radius = 6371000.0
    d_lat = math.radians(b_lat - a_lat)
    d_lon = math.radians(b_lon - a_lon)
    aa = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(a_lat))
        * math.cos(math.radians(b_lat))
        * math.sin(d_lon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(aa))


def _candidate_payload(doc: dict[str, Any]) -> dict[str, Any]:
    now_iso = _to_iso(datetime.now(timezone.utc))
    fetched_at = doc.get("fetched_at") or now_iso
    ingested_at = doc.get("ingested_at") or now_iso
    url = str(doc.get("url") or doc.get("link") or "").strip()
    if not url:
        raise RuntimeError("Document missing required citation URL (url/link).")

    name = str(doc.get("name") or "").strip()
    summary = str(doc.get("summary") or "").strip()
    item_type = str(doc.get("type") or "").strip().lower()
    destination = str(doc.get("destination") or "").strip()
    if not name or not summary or not item_type or not destination:
        raise RuntimeError(
            "Document must include name, summary, type, and destination."
        )

    chunks = doc.get("chunks") or []
    chunk_texts: list[str] = []
    for chunk in chunks:
        if isinstance(chunk, str):
            txt = chunk.strip()
            if txt:
                chunk_texts.append(txt)
        elif isinstance(chunk, dict):
            txt = str(chunk.get("text") or chunk.get("summary") or "").strip()
            if txt:
                chunk_texts.append(txt)

    geo = doc.get("geo")
    normalized_geo = None
    if isinstance(geo, dict) and "lat" in geo and "lon" in geo:
        normalized_geo = {"lat": float(geo["lat"]), "lon": float(geo["lon"])}

    confidence_raw = doc.get("confidence")
    confidence = 0.5
    if isinstance(confidence_raw, (int, float, str)):
        confidence = float(confidence_raw)

    popularity_raw = doc.get("popularity_score")
    popularity_score = None
    if isinstance(popularity_raw, (int, float, str)):
        popularity_score = int(popularity_raw)

    return {
        "name": name,
        "summary": summary,
        "type": item_type,
        "destination": destination,
        "link": _normalized_url(url),
        "published_at": doc.get("published_at"),
        "ingested_at": ingested_at,
        "fetched_at": fetched_at,
        "source": doc.get("source") or "unknown",
        "confidence": confidence,
        "popularity_score": popularity_score,
        "geo": normalized_geo,
        "chunks": chunk_texts,
        "metadata": doc.get("metadata")
        if isinstance(doc.get("metadata"), dict)
        else {},
    }


def _build_embedding_text(payload: dict[str, Any]) -> str:
    chunk_text = "\n".join(payload.get("chunks") or [])
    return (
        f"Name: {payload['name']}\n"
        f"Summary: {payload['summary']}\n"
        f"Type: {payload['type']}\n"
        f"Destination: {payload['destination']}\n"
        f"Source: {payload['source']}\n"
        f"Evidence Chunks:\n{chunk_text}"
    )


def _find_existing_by_url(
    qdrant: QdrantClient,
    collection_name: str,
    normalized_url: str,
) -> models.Record | None:
    points, _ = qdrant.scroll(
        collection_name=collection_name,
        scroll_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="link",
                    match=models.MatchValue(value=normalized_url),
                )
            ]
        ),
        limit=1,
        with_payload=True,
        with_vectors=False,
    )
    return points[0] if points else None


def _find_existing_by_name_geo(
    qdrant: QdrantClient,
    collection_name: str,
    payload: dict[str, Any],
    radius_meters: float = FALLBACK_DEDUPE_RADIUS_METERS,
) -> models.Record | None:
    geo = payload.get("geo")
    if not geo:
        return None

    points, _ = qdrant.scroll(
        collection_name=collection_name,
        scroll_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="destination",
                    match=models.MatchValue(value=payload["destination"]),
                ),
                models.FieldCondition(
                    key="type",
                    match=models.MatchValue(value=payload["type"]),
                ),
            ]
        ),
        limit=100,
        with_payload=True,
        with_vectors=False,
    )

    target_name = str(payload.get("name", "")).strip().lower()
    for point in points:
        existing_name = str((point.payload or {}).get("name", "")).strip().lower()
        if existing_name != target_name:
            continue

        existing_geo = (point.payload or {}).get("geo")
        if not isinstance(existing_geo, dict):
            continue
        if "lat" not in existing_geo or "lon" not in existing_geo:
            continue
        distance = _haversine_meters(
            float(geo["lat"]),
            float(geo["lon"]),
            float(existing_geo["lat"]),
            float(existing_geo["lon"]),
        )
        if distance <= radius_meters:
            return point
    return None


def _merge_payload(
    existing: dict[str, Any], incoming: dict[str, Any]
) -> dict[str, Any]:
    merged = dict(existing)
    existing_conf = float(existing.get("confidence") or 0.0)
    incoming_conf = float(incoming.get("confidence") or 0.0)

    protected_fields = {
        "name",
        "summary",
        "destination",
        "type",
        "geo",
        "published_at",
        "popularity_score",
    }

    for key, value in incoming.items():
        if value is None:
            continue
        if (
            key in protected_fields
            and existing.get(key) is not None
            and incoming_conf < existing_conf
        ):
            continue
        merged[key] = value

    existing_fetched = _parse_iso_datetime(existing.get("fetched_at"))
    incoming_fetched = _parse_iso_datetime(incoming.get("fetched_at"))
    if existing_fetched and incoming_fetched and incoming_fetched < existing_fetched:
        merged["fetched_at"] = existing.get("fetched_at")

    existing_ingested = _parse_iso_datetime(existing.get("ingested_at"))
    incoming_ingested = _parse_iso_datetime(incoming.get("ingested_at"))
    if (
        existing_ingested
        and incoming_ingested
        and incoming_ingested < existing_ingested
    ):
        merged["ingested_at"] = existing.get("ingested_at")

    merged["updated_at"] = _to_iso(datetime.now(timezone.utc))
    return merged


def rag_upsert_documents(
    docs: list[dict[str, Any]],
    collection_name: str = "travel_items",
) -> dict[str, Any]:
    settings = _load_settings()
    qdrant = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    if not qdrant.collection_exists(collection_name):
        raise RuntimeError(f"Collection '{collection_name}' does not exist.")

    updated_ids: list[str] = []
    inserted_ids: list[str] = []
    errors: list[dict[str, Any]] = []

    for idx, doc in enumerate(docs):
        try:
            incoming = _candidate_payload(doc)
            existing_point = _find_existing_by_url(
                qdrant, collection_name, incoming["link"]
            )
            if existing_point is None:
                existing_point = _find_existing_by_name_geo(
                    qdrant, collection_name, incoming
                )

            if existing_point is not None:
                existing_payload = dict(existing_point.payload or {})
                final_payload = _merge_payload(existing_payload, incoming)
                point_id = existing_point.id
                updated_ids.append(str(point_id))
            else:
                final_payload = incoming
                point_id = str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"link::{incoming['link']}")
                )
                inserted_ids.append(str(point_id))

            vector = _embed_text(_build_embedding_text(final_payload), settings)
            qdrant.upsert(
                collection_name=collection_name,
                points=[
                    models.PointStruct(
                        id=point_id,
                        vector=vector,
                        payload=final_payload,
                    )
                ],
                wait=True,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append({"index": idx, "error": str(exc)})

    return {
        "upserted_count": len(updated_ids) + len(inserted_ids),
        "updated_ids": updated_ids,
        "inserted_ids": inserted_ids,
        "errors": errors,
    }


def rag_retrieve(
    query_text: str,
    destination: str | None = None,
    types: list[str] | None = None,
    popularity_range: tuple[int, int] | None = None,
    geo_radius_meters: float | None = None,
    near_latlon: tuple[float, float] | None = None,
    freshness_days: int | None = None,
    top_k: int | None = None,
    collection_name: str = "travel_items",
) -> dict[str, Any]:
    settings = _load_settings()
    qdrant = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    if not qdrant.collection_exists(collection_name):
        raise RuntimeError(f"Collection '{collection_name}' does not exist.")

    normalized_query = normalize_query_text(query_text)
    query_vec = _embed_text(normalized_query, settings)

    effective_top_k = top_k or DEFAULT_TOP_K
    effective_top_k = max(30, min(80, effective_top_k))
    effective_freshness_days = (
        freshness_days if freshness_days is not None else DEFAULT_FRESHNESS_DAYS
    )

    conditions: list[models.Condition] = []
    if destination:
        conditions.append(
            models.FieldCondition(
                key="destination", match=models.MatchValue(value=destination)
            )
        )

    if types:
        normalized_types = [t.strip().lower() for t in types if t.strip()]
        if normalized_types:
            conditions.append(
                models.FieldCondition(
                    key="type",
                    match=models.MatchAny(any=normalized_types),
                )
            )

    if popularity_range:
        conditions.append(
            models.FieldCondition(
                key="popularity_score",
                range=models.Range(
                    gte=int(popularity_range[0]), lte=int(popularity_range[1])
                ),
            )
        )

    effective_radius = (
        geo_radius_meters
        if geo_radius_meters is not None
        else DEFAULT_GEO_RADIUS_METERS
    )
    if near_latlon is not None:
        conditions.append(
            models.FieldCondition(
                key="geo",
                geo_radius=models.GeoRadius(
                    center=models.GeoPoint(
                        lat=float(near_latlon[0]), lon=float(near_latlon[1])
                    ),
                    radius=float(effective_radius),
                ),
            )
        )

    if effective_freshness_days is not None:
        threshold = datetime.now(timezone.utc) - timedelta(
            days=int(effective_freshness_days)
        )
        conditions.append(
            models.FieldCondition(
                key="ingested_at",
                range=models.DatetimeRange(gte=threshold),
            )
        )

    q_filter = models.Filter(must=conditions) if conditions else None
    response = qdrant.query_points(
        collection_name=collection_name,
        query=query_vec,
        query_filter=q_filter,
        limit=effective_top_k,
        with_payload=True,
        with_vectors=False,
    )

    candidates: list[dict[str, Any]] = []
    for hit in response.points:
        payload = dict(hit.payload or {})
        link = payload.get("link") or payload.get("url")
        if not link:
            continue
        candidates.append(
            {
                "id": str(hit.id),
                "name": payload.get("name"),
                "summary": payload.get("summary") or payload.get("description"),
                "type": payload.get("type"),
                "destination": payload.get("destination"),
                "link": link,
                "geo": payload.get("geo"),
                "ingested_at": payload.get("ingested_at"),
                "popularity_score": payload.get("popularity_score"),
                "source": payload.get("source"),
                "confidence": payload.get("confidence"),
                "published_at": payload.get("published_at"),
                "vector_score": hit.score,
                "rank_source": "vector",
            }
        )

    rerank_applied = False
    rerank_error: str | None = None
    rerank_latency_ms: int | None = None
    if settings.rerank_enabled and candidates:
        rerank_settings = RerankSettings(
            api_key=settings.nvidia_api_key,
            model=settings.rerank_model,
            endpoint_url=settings.rerank_url,
            timeout_sec=settings.rerank_timeout_sec,
            max_attempts=settings.rerank_max_attempts,
        )
        started = datetime.now(timezone.utc)
        try:
            candidates = rerank_candidates(
                query_text=normalized_query,
                candidates=candidates,
                settings=rerank_settings,
                top_n=min(settings.rerank_top_n, len(candidates)),
            )
            rerank_applied = True
        except Exception as exc:  # noqa: BLE001
            rerank_error = str(exc)
        finally:
            elapsed = datetime.now(timezone.utc) - started
            rerank_latency_ms = int(elapsed.total_seconds() * 1000)

    return {
        "candidates": candidates,
        "count": len(candidates),
        "rerank_applied": rerank_applied,
        "rerank_model": settings.rerank_model if settings.rerank_enabled else None,
        "rerank_latency_ms": rerank_latency_ms,
        "rerank_error": rerank_error,
    }
