from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from orchestrator_agent.contracts import Candidate


@dataclass(frozen=True)
class OrchestrationPolicy:
    low_evidence_min_candidates: int = 5
    stale_evidence_ratio_threshold: float = 0.40
    stale_window_days: int = 180
    top_k_retrieve: int = 40
    retrieve_freshness_days: int = 180
    max_retries_per_node: int = 2
    max_images_per_segment: int = 3


def compute_stale_ratio(candidates: list[Candidate], stale_window_days: int) -> float:
    if not candidates:
        return 1.0

    threshold = datetime.now(timezone.utc) - timedelta(days=stale_window_days)
    stale = 0
    considered = 0
    for item in candidates[:10]:
        considered += 1
        if not item.ingested_at:
            stale += 1
            continue
        try:
            parsed = datetime.fromisoformat(item.ingested_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed < threshold:
                stale += 1
        except ValueError:
            stale += 1

    return stale / considered if considered else 1.0
