from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import Any

import httpx
from langchain_core.tools import StructuredTool

from planner_service.config import AgentSettings
from planner_service.schemas import Candidate, Citation, WebResult


def _import_rag_api() -> tuple[Any, Any]:
    try:
        from rag import rag_retrieve, rag_upsert_documents  # type: ignore

        return rag_retrieve, rag_upsert_documents
    except ImportError:
        repo_root = Path(__file__).resolve().parents[5]
        rag_src = repo_root / "ai_service" / "src" / "rag" / "src"
        if str(rag_src) not in sys.path:
            sys.path.append(str(rag_src))
        from rag import rag_retrieve, rag_upsert_documents  # type: ignore

        return rag_retrieve, rag_upsert_documents


class ToolExecutionError(RuntimeError):
    pass


@dataclass
class AgentToolClients:
    settings: AgentSettings

    def text_input(self, text: str) -> dict[str, str]:
        normalized = " ".join(text.strip().split())
        if not normalized:
            raise ToolExecutionError("User request cannot be empty.")
        return {"text": normalized}

    def rag_retrieve(
        self,
        query_text: str,
        destination: str | None = None,
        types: list[str] | None = None,
        popularity_range: tuple[int, int] | None = None,
        geo_radius_meters: float | None = None,
        near_latlon: tuple[float, float] | None = None,
        freshness_days: int | None = None,
        top_k: int = 30,
    ) -> dict[str, Any]:
        rag_retrieve_fn, _ = _import_rag_api()
        return rag_retrieve_fn(
            query_text=query_text,
            destination=destination,
            types=types,
            popularity_range=popularity_range,
            geo_radius_meters=geo_radius_meters,
            near_latlon=near_latlon,
            freshness_days=freshness_days,
            top_k=top_k,
        )

    def rag_upsert_documents(self, docs: list[dict[str, Any]]) -> dict[str, Any]:
        _, rag_upsert_documents_fn = _import_rag_api()
        return rag_upsert_documents_fn(docs=docs)

    def web_search(
        self,
        query: str,
        recency_days: int | None = None,
        domain_allowlist: list[str] | None = None,
    ) -> dict[str, Any]:
        if not self.settings.web_search_api_url:
            return {"results": []}

        payload: dict[str, Any] = {"query": query}
        if recency_days is not None:
            payload["recency_days"] = recency_days
        if domain_allowlist:
            payload["domain_allowlist"] = domain_allowlist

        headers = {}
        if self.settings.web_search_api_key:
            headers["Authorization"] = f"Bearer {self.settings.web_search_api_key}"

        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                self.settings.web_search_api_url,
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            if "results" not in data:
                raise ToolExecutionError("web_search response missing `results`.")
            return data

    def rerank_candidates(
        self,
        query_text: str,
        candidates: list[dict[str, Any]],
        top_n: int,
    ) -> dict[str, Any]:
        if self.settings.rerank_api_url:
            headers = {}
            if self.settings.rerank_api_key:
                headers["Authorization"] = f"Bearer {self.settings.rerank_api_key}"
            payload = {
                "query_text": query_text,
                "candidates": candidates,
                "top_n": top_n,
            }
            with httpx.Client(timeout=20.0) as client:
                response = client.post(
                    self.settings.rerank_api_url,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
                if "reranked" not in data:
                    raise ToolExecutionError(
                        "rerank_candidates response missing `reranked`."
                    )
                return data

        query_terms = set(re.findall(r"[a-zA-Z0-9]+", query_text.lower()))

        def local_score(item: dict[str, Any]) -> float:
            text = " ".join(
                [
                    str(item.get("name") or ""),
                    str(item.get("summary") or ""),
                    str(item.get("type") or ""),
                    str(item.get("destination") or ""),
                ]
            ).lower()
            tokens = set(re.findall(r"[a-zA-Z0-9]+", text))
            overlap = len(query_terms.intersection(tokens))
            popularity = float(item.get("popularity_score") or 0) / 100.0
            return overlap + popularity

        ranked = sorted(candidates, key=local_score, reverse=True)
        output = []
        for candidate in ranked[:top_n]:
            scored = dict(candidate)
            scored["score"] = local_score(candidate)
            output.append(scored)
        return {"reranked": output}

    def generate_itinerary(
        self,
        user_request: str,
        user_prefs: dict[str, Any],
        constraints: dict[str, Any],
        reranked_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if self.settings.generate_api_url:
            headers = {}
            if self.settings.generate_api_key:
                headers["Authorization"] = f"Bearer {self.settings.generate_api_key}"
            payload = {
                "user_request": user_request,
                "user_prefs": user_prefs,
                "constraints": constraints,
                "reranked_items": reranked_items,
            }
            with httpx.Client(timeout=25.0) as client:
                response = client.post(
                    self.settings.generate_api_url,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
                if "itinerary_markdown" not in data:
                    raise ToolExecutionError(
                        "generate_itinerary response missing `itinerary_markdown`."
                    )
                return data

        days = int(constraints.get("days") or 3)
        days = max(1, min(days, 7))
        picks = reranked_items[: max(3, days * 3)]
        if not picks:
            picks = [
                {
                    "name": "Central activity area",
                    "summary": "Explore top-rated neighborhoods and local spots.",
                    "link": "https://example.com",
                }
            ]

        lines: list[str] = []
        idx = 0
        for day in range(1, days + 1):
            morning = picks[idx % len(picks)]
            afternoon = picks[(idx + 1) % len(picks)]
            evening = picks[(idx + 2) % len(picks)]
            idx += 3
            lines.append(f"## Day {day}")
            lines.append(
                f"- Morning: {morning.get('name')} - {morning.get('summary', '')}"
            )
            lines.append(
                f"- Afternoon: {afternoon.get('name')} - {afternoon.get('summary', '')}"
            )
            lines.append(
                f"- Evening: {evening.get('name')} - {evening.get('summary', '')}"
            )

        citations = [
            {
                "name": str(item.get("name") or "Recommendation"),
                "url": str(item["link"]),
            }
            for item in picks
            if item.get("link")
        ]
        assumptions = [
            "Trip pace defaults to balanced unless otherwise specified.",
            "Final operating hours and ticket requirements should be re-checked before visiting.",
        ]
        return {
            "itinerary_markdown": "\n".join(lines),
            "assumptions": assumptions,
            "citations": citations,
        }


def build_langchain_tools(clients: AgentToolClients) -> dict[str, StructuredTool]:
    return {
        "text_input": StructuredTool.from_function(
            func=clients.text_input,
            name="text_input",
            description="Normalize and validate raw text user request.",
        ),
        "rag_retrieve": StructuredTool.from_function(
            func=clients.rag_retrieve,
            name="rag_retrieve",
            description="Retrieve candidate travel items from RAG datastore.",
        ),
        "rag_upsert_documents": StructuredTool.from_function(
            func=clients.rag_upsert_documents,
            name="rag_upsert_documents",
            description="Upsert verified web candidates into RAG datastore.",
        ),
        "web_search": StructuredTool.from_function(
            func=clients.web_search,
            name="web_search",
            description="Run a web search for verification or recovery.",
        ),
        "rerank_candidates": StructuredTool.from_function(
            func=clients.rerank_candidates,
            name="rerank_candidates",
            description="Rerank candidates against query intent.",
        ),
        "generate_itinerary": StructuredTool.from_function(
            func=clients.generate_itinerary,
            name="generate_itinerary",
            description="Generate itinerary markdown with assumptions and citations.",
        ),
    }


def normalize_candidates(raw_candidates: list[dict[str, Any]]) -> list[Candidate]:
    return [Candidate.model_validate(candidate) for candidate in raw_candidates]


def normalize_web_results(raw_results: list[dict[str, Any]]) -> list[WebResult]:
    return [WebResult.model_validate(result) for result in raw_results]


def extract_citations(candidates: list[Candidate], limit: int = 10) -> list[Citation]:
    output: list[Citation] = []
    seen: set[str] = set()
    for item in candidates:
        if not item.link or item.link in seen:
            continue
        seen.add(item.link)
        output.append(Citation(name=item.name, url=item.link))
        if len(output) >= limit:
            break
    return output
