from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from planner_service.schemas import Candidate, Citation, PlannerRequest, WebResult


class AgentPhase(str, Enum):
    INTAKE_TEXT = "intake_text"
    UNDERSTAND = "understand"
    RETRIEVE = "retrieve"
    RERANK = "rerank"
    QUALITY_CHECK = "quality_check"
    WEB_FALLBACK = "web_fallback"
    RETRIEVE_AGAIN = "retrieve_again"
    RERANK_AGAIN = "rerank_again"
    GENERATE = "generate"
    VALIDATE = "validate"
    DONE = "done"
    FAILED = "failed"


@dataclass
class OrchestratorState:
    request: PlannerRequest
    phase: AgentPhase = AgentPhase.INTAKE_TEXT
    user_request_text: str = ""
    extracted_constraints: dict = field(default_factory=dict)
    retrieval_filters: dict = field(default_factory=dict)
    candidates_raw: list[Candidate] = field(default_factory=list)
    candidates_reranked: list[Candidate] = field(default_factory=list)
    web_results: list[WebResult] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    budget_notes: list[str] = field(default_factory=list)
    itinerary_markdown: str = ""
    errors: list[str] = field(default_factory=list)
    confidence: float = 0.0
    low_recall: bool = False
    stale_results: bool = False
    needs_web_verification: bool = False
    recovery_loops: int = 0
    iteration_count: int = 0
