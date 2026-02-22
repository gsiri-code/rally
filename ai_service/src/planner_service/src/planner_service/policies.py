from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

from planner_service.schemas import Candidate


TIME_SENSITIVE_PATTERN = re.compile(
    r"\b(currently|right now|this weekend|pop-up|festival|event|temporary|seasonal)\b",
    re.IGNORECASE,
)
VERIFY_PATTERN = re.compile(
    r"\b(opening hours|hours|ticket|tickets|closure|closed|reservation|availability)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PolicyThresholds:
    min_raw_candidates: int = 8
    min_reranked_candidates: int = 5
    stale_ratio_threshold: float = 0.40
    stale_window_days: int = 180
    retrieve_top_k: int = 30
    rerank_top_n: int = 12


def is_time_sensitive(query_text: str) -> bool:
    return bool(TIME_SENSITIVE_PATTERN.search(query_text))


def needs_verification(query_text: str) -> bool:
    return bool(VERIFY_PATTERN.search(query_text))


def stale_ratio(candidates: list[Candidate], stale_window_days: int) -> float:
    if not candidates:
        return 1.0

    threshold = datetime.now(timezone.utc) - timedelta(days=stale_window_days)
    stale = 0
    considered = 0
    for item in candidates[:10]:
        if not item.ingested_at:
            stale += 1
            considered += 1
            continue
        try:
            normalized = item.ingested_at.replace("Z", "+00:00")
            ingested = datetime.fromisoformat(normalized)
            if ingested.tzinfo is None:
                ingested = ingested.replace(tzinfo=timezone.utc)
            if ingested < threshold:
                stale += 1
            considered += 1
        except ValueError:
            stale += 1
            considered += 1

    if considered == 0:
        return 1.0
    return stale / considered
