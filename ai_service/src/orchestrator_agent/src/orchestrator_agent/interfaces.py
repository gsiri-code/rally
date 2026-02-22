from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from orchestrator_agent.contracts import (
    Candidate,
    ImageHint,
    PlannerGenerateInput,
    PlannerRegenerateInput,
    ResearchEvidenceResult,
    ResearchImagesResult,
    ItineraryPlan,
    TranscriptionResult,
)


class RagTool(Protocol):
    def retrieve(
        self,
        *,
        query_text: str,
        destination: str | None,
        top_k: int,
        freshness_days: int,
    ) -> list[Candidate]: ...

    def upsert_evidence(self, docs: list[dict]) -> dict: ...


class PlannerAgent(Protocol):
    def generate(self, payload: PlannerGenerateInput) -> ItineraryPlan: ...

    def regenerate(self, payload: PlannerRegenerateInput) -> ItineraryPlan: ...


class ResearchAgent(Protocol):
    def gather_evidence(
        self,
        *,
        query_text: str,
        destination: str | None,
        constraints: dict,
    ) -> ResearchEvidenceResult: ...

    def gather_images(
        self,
        *,
        image_hints_by_segment: dict[str, ImageHint],
        destination: str | None,
    ) -> ResearchImagesResult: ...


class TranscriptionTool(Protocol):
    def transcribe_mp3(
        self, *, mp3_path: str, request_id: str
    ) -> TranscriptionResult: ...


@dataclass(frozen=True)
class OrchestratorComponents:
    rag: RagTool
    planner: PlannerAgent
    research: ResearchAgent
    transcription: TranscriptionTool
