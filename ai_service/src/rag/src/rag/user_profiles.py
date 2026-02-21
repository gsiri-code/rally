from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings
from qdrant_client import QdrantClient, models


@dataclass(frozen=True)
class UserProfile:
    user_id: str
    budget_level: int
    travel_style: list[str]
    preferred_tags: list[str]
    avoid_tags: list[str]
    pace_transport: str


def build_profile_text(profile: UserProfile) -> str:
    styles = ", ".join(profile.travel_style)
    preferred = ", ".join(profile.preferred_tags)
    avoid = ", ".join(profile.avoid_tags)
    return (
        "Traveler profile summary:\n"
        f"- User ID: {profile.user_id}\n"
        f"- Budget level: {profile.budget_level}\n"
        f"- Travel style: {styles}\n"
        f"- Preferred tags: {preferred}\n"
        f"- Avoid tags: {avoid}\n"
        f"- Pace/transport: {profile.pace_transport}"
    )


def point_id_from_user_id(user_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"user-profile::{user_id}"))


def upsert_user_profile(
    profile: UserProfile,
    qdrant_url: str,
    qdrant_api_key: str,
    nvidia_api_key: str,
    collection_name: str = "user_profiles",
    nvidia_model: str = "nvidia/llama-nemotron-embed-vl-1b-v2",
) -> dict:
    profile_text = build_profile_text(profile)

    embedder = NVIDIAEmbeddings(
        model=nvidia_model,
        api_key=nvidia_api_key,
        truncate="NONE",
    )
    vector = embedder.embed_query(profile_text)

    qdrant = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
    if not qdrant.collection_exists(collection_name):
        raise RuntimeError(f"Collection '{collection_name}' does not exist.")

    point_id = point_id_from_user_id(profile.user_id)
    payload = {
        "user_id": profile.user_id,
        "profile_text": profile_text,
        "budget_level": profile.budget_level,
        "travel_style": profile.travel_style,
        "preferred_tags": profile.preferred_tags,
        "avoid_tags": profile.avoid_tags,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
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
        "user_id": profile.user_id,
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
