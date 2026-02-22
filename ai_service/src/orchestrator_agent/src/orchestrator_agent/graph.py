from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from orchestrator_agent.contracts import (
    EvidenceTrigger,
    ItineraryPlan,
    PlanDiagnostics,
    PlanRequest,
    PlanResponse,
    PlannerGenerateInput,
    PlannerRegenerateInput,
    ResearchEvidence,
)
from orchestrator_agent.interfaces import OrchestratorComponents
from orchestrator_agent.policies import OrchestrationPolicy, compute_stale_ratio


class GraphState(TypedDict, total=False):
    request: PlanRequest
    user_text: str
    candidates: list
    stale_ratio: float
    trigger_reasons: list[str]
    use_research_evidence: bool
    research_evidence: list[ResearchEvidence]
    itinerary: ItineraryPlan
    retries_used: dict[str, int]
    phase_path: list[str]
    image_coverage_ratio: float


def _with_phase(state: GraphState, phase: str) -> dict[str, Any]:
    phases = list(state.get("phase_path", []))
    phases.append(phase)
    return {"phase_path": phases}


class TravelOrchestrator:
    def __init__(
        self,
        components: OrchestratorComponents,
        policy: OrchestrationPolicy | None = None,
    ) -> None:
        self.components = components
        self.policy = policy or OrchestrationPolicy()
        self.graph = self._build_graph()

    def run(self, request: PlanRequest) -> PlanResponse:
        final = self.graph.invoke({"request": request, "retries_used": {}})
        itinerary = final["itinerary"]

        diagnostics = PlanDiagnostics(
            phase_path=final.get("phase_path", []),
            trigger_reasons=final.get("trigger_reasons", []),
            retries_used=final.get("retries_used", {}),
            candidate_count=len(final.get("candidates", [])),
            stale_ratio=final.get("stale_ratio", 0.0),
            used_research_evidence=final.get("use_research_evidence", False),
            image_coverage_ratio=final.get("image_coverage_ratio", 0.0),
            generated_at=datetime.now(timezone.utc),
        )
        return PlanResponse(itinerary=itinerary, diagnostics=diagnostics)

    def _call_with_retry(self, state: GraphState, node_name: str, fn, **kwargs: Any):
        retries_used = dict(state.get("retries_used", {}))
        attempts = 0
        while True:
            try:
                result = fn(**kwargs)
                retries_used[node_name] = attempts
                return result, retries_used
            except Exception:  # noqa: BLE001
                attempts += 1
                if attempts > self.policy.max_retries_per_node:
                    retries_used[node_name] = attempts
                    raise

    def _ingest_input(self, state: GraphState) -> dict[str, Any]:
        request = state["request"]
        out = _with_phase(state, "ingest_input")

        if request.text and request.text.strip():
            out["user_text"] = " ".join(request.text.strip().split())
            return out

        if request.voice_mp3_path:
            result, retries_used = self._call_with_retry(
                state,
                "transcription",
                self.components.transcription.transcribe_mp3,
                mp3_path=request.voice_mp3_path,
                request_id=request.context.request_id,
            )
            out["user_text"] = " ".join(result.text.strip().split())
            out["retries_used"] = retries_used
            return out

        raise ValueError("Either text or voice_mp3_path must be provided.")

    def _retrieve_rag(self, state: GraphState) -> dict[str, Any]:
        request = state["request"]
        out = _with_phase(state, "retrieve_rag")
        candidates, retries_used = self._call_with_retry(
            state,
            "rag_retrieve",
            self.components.rag.retrieve,
            query_text=state["user_text"],
            destination=request.destination,
            top_k=self.policy.top_k_retrieve,
            freshness_days=self.policy.retrieve_freshness_days,
        )
        out["candidates"] = candidates
        out["retries_used"] = retries_used
        return out

    def _quality_gate(self, state: GraphState) -> dict[str, Any]:
        out = _with_phase(state, "quality_gate")
        candidates = state.get("candidates", [])
        stale_ratio = compute_stale_ratio(candidates, self.policy.stale_window_days)
        out["stale_ratio"] = stale_ratio

        triggers: list[str] = []
        if len(candidates) < self.policy.low_evidence_min_candidates:
            triggers.append(EvidenceTrigger.LOW_EVIDENCE.value)
        if stale_ratio >= self.policy.stale_evidence_ratio_threshold:
            triggers.append(EvidenceTrigger.STALE_EVIDENCE.value)

        out["trigger_reasons"] = triggers
        out["use_research_evidence"] = bool(triggers)
        return out

    def _route_after_quality(self, state: GraphState) -> str:
        if state.get("use_research_evidence"):
            return "research_evidence"
        return "planner_generate"

    def _research_evidence(self, state: GraphState) -> dict[str, Any]:
        request = state["request"]
        out = _with_phase(state, "research_evidence")
        result, retries_used = self._call_with_retry(
            state,
            "research_evidence",
            self.components.research.gather_evidence,
            query_text=state["user_text"],
            destination=request.destination,
            constraints=request.constraints,
        )
        out["research_evidence"] = result.evidence
        out["retries_used"] = retries_used

        docs = [
            {
                "name": item.name,
                "summary": item.summary,
                "destination": request.destination or "Unknown",
                "type": "attraction",
                "url": item.link,
                "ingested_at": item.ingested_at,
                "source": item.source,
                "confidence": item.confidence,
            }
            for item in result.evidence
        ]
        if docs:
            try:
                self.components.rag.upsert_evidence(docs)
            except Exception:  # noqa: BLE001
                pass
        return out

    def _planner_generate(self, state: GraphState) -> dict[str, Any]:
        request = state["request"]
        out = _with_phase(state, "planner_generate")
        base_payload = PlannerGenerateInput(
            user_text=state["user_text"],
            destination=request.destination,
            days=request.days,
            budget_level=request.budget_level,
            constraints=request.constraints,
            preferences=request.preferences,
            rag_candidates=state.get("candidates", []),
            research_evidence=state.get("research_evidence", []),
        )

        if request.feedback and request.prior_plan:
            regen_payload = PlannerRegenerateInput(
                **base_payload.model_dump(),
                prior_plan=request.prior_plan,
                feedback=request.feedback,
            )
            itinerary, retries_used = self._call_with_retry(
                state,
                "planner_regenerate",
                self.components.planner.regenerate,
                payload=regen_payload,
            )
        else:
            itinerary, retries_used = self._call_with_retry(
                state,
                "planner_generate",
                self.components.planner.generate,
                payload=base_payload,
            )

        out["itinerary"] = itinerary
        out["retries_used"] = retries_used
        return out

    def _research_images(self, state: GraphState) -> dict[str, Any]:
        out = _with_phase(state, "research_images")
        itinerary = state["itinerary"].model_copy(deep=True)
        hints: dict[str, Any] = {}
        for day in itinerary.days:
            for segment in day.segments:
                hints[segment.segment_id] = segment.image_hints

        images_result, retries_used = self._call_with_retry(
            state,
            "research_images",
            self.components.research.gather_images,
            image_hints_by_segment=hints,
            destination=itinerary.destination,
        )

        for day in itinerary.days:
            for segment in day.segments:
                fetched = images_result.images_by_segment.get(segment.segment_id, [])
                segment.images = fetched[: self.policy.max_images_per_segment]

        out["itinerary"] = itinerary
        out["retries_used"] = retries_used
        return out

    def _merge_validate(self, state: GraphState) -> dict[str, Any]:
        out = _with_phase(state, "merge_validate")
        itinerary = state["itinerary"].model_copy(deep=True)

        total_segments = 0
        with_images = 0
        for day in itinerary.days:
            for segment in day.segments:
                total_segments += 1
                if segment.images:
                    with_images += 1
                else:
                    itinerary.warnings.append(f"missing_media:{segment.segment_id}")

        coverage = (with_images / total_segments) if total_segments else 0.0
        out["image_coverage_ratio"] = coverage
        out["itinerary"] = itinerary
        return out

    def _build_graph(self):
        graph = StateGraph(GraphState)

        graph.add_node("ingest_input", self._ingest_input)
        graph.add_node("retrieve_rag", self._retrieve_rag)
        graph.add_node("quality_gate", self._quality_gate)
        graph.add_node("research_evidence", self._research_evidence)
        graph.add_node("planner_generate", self._planner_generate)
        graph.add_node("research_images", self._research_images)
        graph.add_node("merge_validate", self._merge_validate)

        graph.set_entry_point("ingest_input")
        graph.add_edge("ingest_input", "retrieve_rag")
        graph.add_edge("retrieve_rag", "quality_gate")
        graph.add_conditional_edges(
            "quality_gate",
            self._route_after_quality,
            {
                "research_evidence": "research_evidence",
                "planner_generate": "planner_generate",
            },
        )
        graph.add_edge("research_evidence", "planner_generate")
        graph.add_edge("planner_generate", "research_images")
        graph.add_edge("research_images", "merge_validate")
        graph.add_edge("merge_validate", END)

        return graph.compile()
