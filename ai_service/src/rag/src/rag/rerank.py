from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


DEFAULT_RERANK_MODEL = "nvidia/nv-rerankqa-mistral-4b-v3"
DEFAULT_RERANK_URL = "https://integrate.api.nvidia.com/v1/retranking"


@dataclass(frozen=True)
class RerankSettings:
    api_key: str
    model: str = DEFAULT_RERANK_MODEL
    endpoint_url: str = DEFAULT_RERANK_URL
    timeout_sec: float = 15.0
    max_attempts: int = 2


def rerank_candidates(
    *,
    query_text: str,
    candidates: list[dict[str, Any]],
    settings: RerankSettings,
    top_n: int,
) -> list[dict[str, Any]]:
    if not candidates:
        return []

    payload = {
        "model": settings.model,
        "query": query_text,
        "passages": [
            {
                "text": _candidate_text(candidate),
                "id": str(index),
            }
            for index, candidate in enumerate(candidates)
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
    }

    last_error: Exception | None = None
    for _ in range(settings.max_attempts):
        try:
            with httpx.Client(timeout=settings.timeout_sec) as client:
                response = client.post(
                    settings.endpoint_url,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                body = response.json()

            ranked = _parse_ranked_results(body=body, candidates=candidates)
            return ranked[: max(1, top_n)]
        except Exception as exc:  # noqa: BLE001
            last_error = exc

    if last_error is not None:
        raise RuntimeError(f"Reranking failed: {last_error}")
    raise RuntimeError("Reranking failed.")


def _candidate_text(candidate: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Name: {candidate.get('name') or ''}",
            f"Summary: {candidate.get('summary') or ''}",
            f"Type: {candidate.get('type') or ''}",
            f"Destination: {candidate.get('destination') or ''}",
            f"Source: {candidate.get('source') or ''}",
        ]
    ).strip()


def _parse_ranked_results(
    *, body: dict[str, Any], candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rankings = body.get("rankings")
    if not isinstance(rankings, list):
        rankings = body.get("results")
    if not isinstance(rankings, list):
        raise RuntimeError("Reranker response missing rankings/results list.")

    scored: list[tuple[float, dict[str, Any]]] = []
    for item in rankings:
        if not isinstance(item, dict):
            continue
        index_value = item.get("index")
        if not isinstance(index_value, int):
            continue
        if index_value < 0 or index_value >= len(candidates):
            continue

        score = item.get("relevance_score")
        if score is None:
            score = item.get("score")
        if score is None:
            score = item.get("logit")
        try:
            rank_score = float(score) if score is not None else 0.0
        except (TypeError, ValueError):
            rank_score = 0.0

        ranked_item = dict(candidates[index_value])
        ranked_item["rerank_score"] = rank_score
        ranked_item["rank_source"] = "rerank"
        scored.append((rank_score, ranked_item))

    if not scored:
        raise RuntimeError("Reranker returned no usable ranking entries.")

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored]
