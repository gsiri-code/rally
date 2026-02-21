from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Callable

from agent.config import AgentSettings
from agent.policies import (
    PolicyThresholds,
    is_time_sensitive,
    needs_verification,
    stale_ratio,
)
from agent.schemas import GenerateResult, PlannerRequest, PlannerResponse
from agent.state import AgentPhase, OrchestratorState
from agent.tools import (
    AgentToolClients,
    ToolExecutionError,
    build_langchain_tools,
    extract_citations,
    normalize_candidates,
    normalize_web_results,
)


def _infer_destination(text: str) -> str | None:
    known = ["new york city", "nyc", "paris", "london", "tokyo", "rome", "bangkok"]
    lowered = text.lower()
    for candidate in known:
        if candidate in lowered:
            return "New York City" if candidate == "nyc" else candidate.title()
    return None


def _infer_days(text: str) -> int:
    lowered = text.lower()
    if "weekend" in lowered:
        return 2
    match = re.search(r"(\d+)\s*(day|days)", lowered)
    if match:
        return max(1, min(int(match.group(1)), 7))
    return 3


def _infer_budget(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ["luxury", "high end", "premium"]):
        return "high"
    if any(token in lowered for token in ["budget", "cheap", "affordable"]):
        return "low"
    return "mid"


def _tool_invoke_with_retry(
    state: OrchestratorState,
    fn: Callable[..., Any],
    *,
    tool_name: str,
    max_retries: int,
    **kwargs: Any,
) -> Any:
    attempts = 0
    while True:
        try:
            return fn(**kwargs)
        except Exception as exc:  # noqa: BLE001
            attempts += 1
            if attempts > max_retries:
                msg = f"{tool_name} failed after retries: {exc}"
                state.errors.append(msg)
                raise ToolExecutionError(msg) from exc


class TravelPlannerOrchestrator:
    def __init__(
        self,
        settings: AgentSettings,
        clients: AgentToolClients,
        thresholds: PolicyThresholds | None = None,
    ) -> None:
        self.settings = settings
        self.clients = clients
        self.thresholds = thresholds or PolicyThresholds()
        self.tools = build_langchain_tools(clients)

    def run(self, request: PlannerRequest) -> PlannerResponse:
        state = OrchestratorState(request=request)

        while state.phase not in {AgentPhase.DONE, AgentPhase.FAILED}:
            state.iteration_count += 1
            if state.iteration_count > self.settings.max_iterations:
                state.errors.append("Max iterations reached.")
                state.phase = AgentPhase.FAILED
                break

            if state.phase == AgentPhase.INTAKE_TEXT:
                data = _tool_invoke_with_retry(
                    state,
                    self.tools["text_input"].invoke,
                    tool_name="text_input",
                    max_retries=self.settings.max_tool_retries,
                    input={"text": request.user_request},
                )
                state.user_request_text = data["text"]
                state.phase = AgentPhase.UNDERSTAND
                continue

            if state.phase == AgentPhase.UNDERSTAND:
                destination = request.constraints.get(
                    "destination"
                ) or _infer_destination(state.user_request_text)
                days = int(
                    request.constraints.get("days")
                    or _infer_days(state.user_request_text)
                )
                budget = request.constraints.get("budget_level") or _infer_budget(
                    state.user_request_text
                )

                state.extracted_constraints = {
                    "destination": destination,
                    "days": days,
                    "budget_level": budget,
                }
                state.retrieval_filters = {
                    "destination": destination,
                    "types": request.constraints.get("types"),
                    "freshness_days": request.constraints.get("freshness_days", 180),
                    "geo_radius_meters": request.constraints.get(
                        "geo_radius_meters", 3000
                    ),
                    "top_k": self.thresholds.retrieve_top_k,
                }
                if not destination:
                    state.assumptions.append(
                        "Destination not explicitly provided; retrieval may use broader relevance."
                    )
                state.phase = AgentPhase.RETRIEVE
                continue

            if state.phase in {AgentPhase.RETRIEVE, AgentPhase.RETRIEVE_AGAIN}:
                data = _tool_invoke_with_retry(
                    state,
                    self.tools["rag_retrieve"].invoke,
                    tool_name="rag_retrieve",
                    max_retries=self.settings.max_tool_retries,
                    input={
                        "query_text": state.user_request_text,
                        "destination": state.retrieval_filters.get("destination"),
                        "types": state.retrieval_filters.get("types"),
                        "freshness_days": state.retrieval_filters.get("freshness_days"),
                        "geo_radius_meters": state.retrieval_filters.get(
                            "geo_radius_meters"
                        ),
                        "top_k": state.retrieval_filters.get("top_k", 30),
                    },
                )
                state.candidates_raw = normalize_candidates(data.get("candidates", []))
                state.low_recall = (
                    len(state.candidates_raw) < self.thresholds.min_raw_candidates
                )
                state.phase = AgentPhase.RERANK
                continue

            if state.phase in {AgentPhase.RERANK, AgentPhase.RERANK_AGAIN}:
                data = _tool_invoke_with_retry(
                    state,
                    self.tools["rerank_candidates"].invoke,
                    tool_name="rerank_candidates",
                    max_retries=self.settings.max_tool_retries,
                    input={
                        "query_text": state.user_request_text,
                        "candidates": [c.model_dump() for c in state.candidates_raw],
                        "top_n": self.thresholds.rerank_top_n,
                    },
                )
                state.candidates_reranked = normalize_candidates(
                    data.get("reranked", [])
                )
                state.citations = extract_citations(state.candidates_reranked)
                state.phase = AgentPhase.QUALITY_CHECK
                continue

            if state.phase == AgentPhase.QUALITY_CHECK:
                reranked_count = len(state.candidates_reranked)
                stale = stale_ratio(
                    state.candidates_reranked, self.thresholds.stale_window_days
                )
                state.stale_results = stale >= self.thresholds.stale_ratio_threshold
                state.needs_web_verification = (
                    state.low_recall
                    or reranked_count < self.thresholds.min_reranked_candidates
                    or state.stale_results
                    or is_time_sensitive(state.user_request_text)
                    or needs_verification(state.user_request_text)
                )

                if (
                    state.needs_web_verification
                    and state.recovery_loops < self.settings.max_recovery_loops
                ):
                    state.phase = AgentPhase.WEB_FALLBACK
                else:
                    state.phase = AgentPhase.GENERATE
                continue

            if state.phase == AgentPhase.WEB_FALLBACK:
                recency_days = 7 if is_time_sensitive(state.user_request_text) else 30
                web_data = _tool_invoke_with_retry(
                    state,
                    self.tools["web_search"].invoke,
                    tool_name="web_search",
                    max_retries=self.settings.max_tool_retries,
                    input={
                        "query": state.user_request_text,
                        "recency_days": recency_days,
                    },
                )
                state.web_results = normalize_web_results(web_data.get("results", []))
                if state.web_results:
                    docs = self._web_results_to_rag_docs(state)
                    upserted = _tool_invoke_with_retry(
                        state,
                        self.tools["rag_upsert_documents"].invoke,
                        tool_name="rag_upsert_documents",
                        max_retries=self.settings.max_tool_retries,
                        input={"docs": docs},
                    )
                    if upserted.get("upserted_count", 0) > 0:
                        state.recovery_loops += 1
                        state.phase = AgentPhase.RETRIEVE_AGAIN
                        continue
                state.recovery_loops += 1
                state.phase = AgentPhase.GENERATE
                continue

            if state.phase == AgentPhase.GENERATE:
                payload = {
                    "user_request": state.user_request_text,
                    "user_prefs": request.user_prefs,
                    "constraints": {
                        **request.constraints,
                        **state.extracted_constraints,
                    },
                    "reranked_items": [
                        c.model_dump() for c in state.candidates_reranked
                    ],
                }
                generated = _tool_invoke_with_retry(
                    state,
                    self.tools["generate_itinerary"].invoke,
                    tool_name="generate_itinerary",
                    max_retries=self.settings.max_tool_retries,
                    input=payload,
                )
                parsed = GenerateResult.model_validate(generated)
                state.itinerary_markdown = parsed.itinerary_markdown
                state.assumptions = parsed.assumptions
                if parsed.citations:
                    state.citations = parsed.citations
                state.budget_notes = self._budget_notes(state)
                state.confidence = self._confidence(state)
                state.phase = AgentPhase.VALIDATE
                continue

            if state.phase == AgentPhase.VALIDATE:
                if self._is_valid_final(state):
                    state.phase = AgentPhase.DONE
                else:
                    state.errors.append("Final output failed validation checks.")
                    state.phase = AgentPhase.FAILED
                continue

        if state.phase == AgentPhase.FAILED:
            return self._graceful_failure(state)

        diagnostics = {
            "iterations": state.iteration_count,
            "recovery_loops": state.recovery_loops,
            "candidate_count": len(state.candidates_reranked),
            "used_web_fallback": bool(state.web_results),
            "errors": state.errors,
        }
        return PlannerResponse(
            itinerary_markdown=state.itinerary_markdown,
            assumptions=state.assumptions,
            budget_notes=state.budget_notes,
            citations=state.citations,
            confidence=state.confidence,
            diagnostics=diagnostics,
        )

    def _web_results_to_rag_docs(
        self, state: OrchestratorState
    ) -> list[dict[str, Any]]:
        destination = state.extracted_constraints.get("destination") or "Unknown"
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        docs: list[dict[str, Any]] = []
        for rank, result in enumerate(state.web_results[:12], start=1):
            docs.append(
                {
                    "name": result.title[:120],
                    "summary": result.snippet[:500],
                    "type": "attraction",
                    "destination": destination,
                    "url": result.url,
                    "published_at": result.published_at,
                    "ingested_at": now_iso,
                    "fetched_at": now_iso,
                    "source": "web_search",
                    "confidence": max(0.55, 0.95 - rank * 0.03),
                    "popularity_score": max(10, 100 - rank * 5),
                    "chunks": [result.snippet],
                }
            )
        return docs

    def _budget_notes(self, state: OrchestratorState) -> list[str]:
        budget = state.extracted_constraints.get("budget_level") or "mid"
        if budget == "low":
            return [
                "Prioritizes lower-cost attractions and local transit.",
                "Book tickets early to capture lower fare tiers.",
            ]
        if budget == "high":
            return [
                "Includes premium experiences and flexible transport assumptions.",
                "Expect dynamic pricing for high-demand activities.",
            ]
        return [
            "Balances paid attractions with free walking and neighborhood exploration.",
            "Assumes moderate daily spend with advance booking for major attractions.",
        ]

    def _confidence(self, state: OrchestratorState) -> float:
        score = 0.8
        if state.low_recall:
            score -= 0.2
        if state.stale_results:
            score -= 0.15
        if not state.citations:
            score -= 0.2
        if state.web_results:
            score += 0.05
        return max(0.2, min(0.95, round(score, 2)))

    def _is_valid_final(self, state: OrchestratorState) -> bool:
        text = state.itinerary_markdown.lower()
        if "morning" not in text or "afternoon" not in text or "evening" not in text:
            return False
        if not state.assumptions:
            return False
        if not state.budget_notes:
            return False
        if not state.citations:
            return False
        return True

    def _graceful_failure(self, state: OrchestratorState) -> PlannerResponse:
        assumptions = state.assumptions or [
            "Plan generated with limited evidence due to tool/runtime constraints."
        ]
        itinerary = state.itinerary_markdown or (
            "## Day 1\n"
            "- Morning: Explore the city center and verify openings before departure.\n"
            "- Afternoon: Visit one major attraction with official booking link.\n"
            "- Evening: Dine in a well-reviewed neighborhood and confirm hours."
        )
        citations = state.citations
        diagnostics = {
            "iterations": state.iteration_count,
            "recovery_loops": state.recovery_loops,
            "candidate_count": len(state.candidates_reranked),
            "used_web_fallback": bool(state.web_results),
            "errors": state.errors,
        }
        return PlannerResponse(
            itinerary_markdown=itinerary,
            assumptions=assumptions,
            budget_notes=state.budget_notes
            or ["Budget estimate unavailable in fallback mode."],
            citations=citations,
            confidence=0.3,
            diagnostics=diagnostics,
        )
