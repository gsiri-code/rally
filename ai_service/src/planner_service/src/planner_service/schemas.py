from __future__ import annotations

from pydantic import BaseModel, Field


class Citation(BaseModel):
    name: str
    url: str


class Candidate(BaseModel):
    id: str
    name: str
    summary: str | None = None
    type: str | None = None
    destination: str | None = None
    link: str
    geo: dict[str, float] | None = None
    ingested_at: str | None = None
    popularity_score: int | None = None
    source: str | None = None
    confidence: float | None = None
    published_at: str | None = None
    score: float | None = None


class WebResult(BaseModel):
    title: str
    url: str
    snippet: str
    published_at: str | None = None


class PlannerRequest(BaseModel):
    user_request: str = Field(min_length=1)
    user_prefs: dict = Field(default_factory=dict)
    constraints: dict = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    candidates: list[Candidate]
    count: int


class RerankResult(BaseModel):
    reranked: list[Candidate]


class WebSearchResult(BaseModel):
    results: list[WebResult]


class GenerateResult(BaseModel):
    itinerary_markdown: str
    assumptions: list[str]
    citations: list[Citation]


class PlannerResponse(BaseModel):
    itinerary_markdown: str
    assumptions: list[str]
    budget_notes: list[str]
    citations: list[Citation]
    confidence: float
    diagnostics: dict = Field(default_factory=dict)
