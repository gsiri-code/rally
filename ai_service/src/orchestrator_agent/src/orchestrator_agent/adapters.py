from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
from orchestrator_agent.interfaces import (
    PlannerAgent,
    RagTool,
    ResearchAgent,
    TranscriptionTool,
)


@dataclass
class RagPackageAdapter(RagTool):
    def retrieve(
        self,
        *,
        query_text: str,
        destination: str | None,
        top_k: int,
        freshness_days: int,
    ) -> list[Candidate]:
        from rag import rag_retrieve

        raw = rag_retrieve(
            query_text=query_text,
            destination=destination,
            freshness_days=freshness_days,
            top_k=top_k,
        )
        return [Candidate.model_validate(item) for item in raw.get("candidates", [])]

    def upsert_evidence(self, docs: list[dict]) -> dict:
        from rag import rag_upsert_documents

        return rag_upsert_documents(docs=docs)


@dataclass
class TranscriptionPackageAdapter(TranscriptionTool):
    def transcribe_mp3(self, *, mp3_path: str, request_id: str) -> TranscriptionResult:
        from transcription import transcribe_mp3

        raw = transcribe_mp3(mp3_path=mp3_path, request_id=request_id)
        return TranscriptionResult.model_validate(raw)


class PlannerNotImplemented(PlannerAgent):
    def generate(self, payload: PlannerGenerateInput) -> ItineraryPlan:
        raise NotImplementedError("planner_agent.generate is not implemented yet.")

    def regenerate(self, payload: PlannerRegenerateInput) -> ItineraryPlan:
        raise NotImplementedError("planner_agent.regenerate is not implemented yet.")


@dataclass
class PlannerPackageAdapter(PlannerAgent):
    def generate(self, payload: PlannerGenerateInput) -> ItineraryPlan:
        from planner_agent import generate as planner_generate

        return planner_generate(payload)

    def regenerate(self, payload: PlannerRegenerateInput) -> ItineraryPlan:
        from planner_agent import regenerate as planner_regenerate

        return planner_regenerate(payload)


class ResearchNotImplemented(ResearchAgent):
    def gather_evidence(
        self,
        *,
        query_text: str,
        destination: str | None,
        constraints: dict,
    ) -> ResearchEvidenceResult:
        raise NotImplementedError(
            "research_agent.gather_evidence is not implemented yet."
        )

    def gather_images(
        self,
        *,
        image_hints_by_segment: dict,
        destination: str | None,
    ) -> ResearchImagesResult:
        raise NotImplementedError(
            "research_agent.gather_images is not implemented yet."
        )


@dataclass
class ResearchPackageAdapter(ResearchAgent):
    def gather_evidence(
        self,
        *,
        query_text: str,
        destination: str | None,
        constraints: dict,
    ) -> ResearchEvidenceResult:
        from web_agent import gather_evidence

        return gather_evidence(
            query_text=query_text,
            destination=destination,
            constraints=constraints,
        )

    def gather_images(
        self,
        *,
        image_hints_by_segment: dict[str, ImageHint],
        destination: str | None,
    ) -> ResearchImagesResult:
        from web_agent import gather_images

        return gather_images(
            image_hints_by_segment=image_hints_by_segment,
            destination=destination,
        )


class TranscriptionNotImplemented(TranscriptionTool):
    def transcribe_mp3(self, *, mp3_path: str, request_id: str) -> TranscriptionResult:
        raise NotImplementedError("transcription tool is not implemented yet.")


def build_contract_map() -> dict[str, Any]:
    return {
        "planner.generate": PlannerGenerateInput.model_json_schema(),
        "planner.regenerate": PlannerRegenerateInput.model_json_schema(),
        "research.gather_evidence": ResearchEvidenceResult.model_json_schema(),
        "research.gather_images": ResearchImagesResult.model_json_schema(),
        "transcription.transcribe_mp3": TranscriptionResult.model_json_schema(),
    }
