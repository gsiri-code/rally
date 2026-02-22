from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SegmentSlot(str, Enum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"


class EvidenceTrigger(str, Enum):
    LOW_EVIDENCE = "low_evidence"
    STALE_EVIDENCE = "stale_evidence"


class Citation(BaseModel):
    id: str
    url: str
    source: str
    title: str | None = None


class ImageHint(BaseModel):
    query: str
    place_name: str | None = None
    must_match_landmark: bool = False


class ImageAsset(BaseModel):
    id: str
    url: str
    thumbnail_url: str | None = None
    alt: str
    source: str
    attribution: str | None = None
    license: str | None = None
    width: int | None = None
    height: int | None = None
    confidence: float | None = None


class SegmentPlan(BaseModel):
    segment_id: str
    slot: SegmentSlot
    title: str
    description: str
    place_ids: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    image_hints: ImageHint
    images: list[ImageAsset] = Field(default_factory=list)


class DayPlan(BaseModel):
    day_index: int = Field(ge=1)
    segments: list[SegmentPlan]


class ConfidenceInfo(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)


class ItineraryPlan(BaseModel):
    plan_id: str
    destination: str | None = None
    days: list[DayPlan]
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    budget_notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    confidence: ConfidenceInfo
    contract_version: str = "v1"


class Candidate(BaseModel):
    id: str
    name: str
    summary: str | None = None
    type: str | None = None
    destination: str | None = None
    link: str
    ingested_at: str | None = None
    source: str | None = None
    confidence: float | None = None


class ResearchEvidence(BaseModel):
    evidence_id: str
    name: str
    summary: str
    link: str
    source: str
    ingested_at: str | None = None
    confidence: float | None = None


class ResearchEvidenceResult(BaseModel):
    evidence: list[ResearchEvidence]
    citations: list[Citation] = Field(default_factory=list)
    freshness_ratio: float | None = None


class ResearchImagesResult(BaseModel):
    images_by_segment: dict[str, list[ImageAsset]]


class PlannerGenerateInput(BaseModel):
    user_text: str
    destination: str | None = None
    days: int = Field(default=3, ge=1, le=14)
    budget_level: str | None = None
    constraints: dict = Field(default_factory=dict)
    preferences: dict = Field(default_factory=dict)
    rag_candidates: list[Candidate] = Field(default_factory=list)
    research_evidence: list[ResearchEvidence] = Field(default_factory=list)
    contract_version: str = "v1"


class PlannerRegenerateInput(PlannerGenerateInput):
    prior_plan: ItineraryPlan
    feedback: str


class TranscriptionResult(BaseModel):
    text: str
    confidence: float | None = None
    duration_sec: float | None = None
    segments: list[dict] = Field(default_factory=list)


class UserContext(BaseModel):
    user_id: str | None = None
    tenant_id: str | None = None
    request_id: str


class PlanRequest(BaseModel):
    text: str | None = None
    voice_mp3_path: str | None = None
    destination: str | None = None
    days: int = Field(default=3, ge=1, le=14)
    budget_level: str | None = None
    preferences: dict = Field(default_factory=dict)
    constraints: dict = Field(default_factory=dict)
    feedback: str | None = None
    prior_plan: ItineraryPlan | None = None
    context: UserContext


class PlanDiagnostics(BaseModel):
    phase_path: list[str] = Field(default_factory=list)
    trigger_reasons: list[str] = Field(default_factory=list)
    retries_used: dict[str, int] = Field(default_factory=dict)
    candidate_count: int = 0
    stale_ratio: float = 0.0
    used_research_evidence: bool = False
    image_coverage_ratio: float = 0.0
    generated_at: datetime


class PlanResponse(BaseModel):
    itinerary: ItineraryPlan
    diagnostics: PlanDiagnostics
