from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from orchestrator_agent.contracts import (
    Citation,
    ConfidenceInfo,
    DayPlan,
    ImageHint,
    ItineraryPlan,
    PlannerGenerateInput,
    PlannerRegenerateInput,
    SegmentPlan,
    SegmentSlot,
)

from planner_agent.errors import PlannerGenerationError, PlannerValidationError
from planner_agent.fallback import build_fallback_outline
from planner_agent.llm import OpenRouterNemotronClient, assert_hardcoded_model_guard
from planner_agent.validation import validate_itinerary_semantics

SLOTS: tuple[SegmentSlot, ...] = (
    SegmentSlot.MORNING,
    SegmentSlot.AFTERNOON,
    SegmentSlot.EVENING,
)


class PlannerPackageAgent:
    def __init__(self, llm_client: OpenRouterNemotronClient | None = None) -> None:
        assert_hardcoded_model_guard()
        self._llm_client = llm_client or OpenRouterNemotronClient.from_env()

    def generate(self, payload: PlannerGenerateInput) -> ItineraryPlan:
        return self._build_itinerary(payload=payload, prior_plan=None, feedback=None)

    def regenerate(self, payload: PlannerRegenerateInput) -> ItineraryPlan:
        return self._build_itinerary(
            payload=payload,
            prior_plan=payload.prior_plan,
            feedback=payload.feedback,
        )

    def _build_itinerary(
        self,
        *,
        payload: PlannerGenerateInput,
        prior_plan: ItineraryPlan | None,
        feedback: str | None,
    ) -> ItineraryPlan:
        citations, source_items = _build_sources(payload=payload)
        destination = payload.destination or _guess_destination(payload.user_text)
        prompt_payload = {
            "user_text": payload.user_text,
            "destination": destination,
            "days": payload.days,
            "budget_level": payload.budget_level,
            "constraints": payload.constraints,
            "preferences": payload.preferences,
            "candidates": source_items,
            "feedback": feedback,
            "prior_plan": prior_plan.model_dump() if prior_plan else None,
        }

        warnings: list[str] = []
        outline: dict[str, Any]
        used_llm = False
        if self._llm_client is not None:
            try:
                outline = self._llm_client.generate_outline(
                    prompt_payload=prompt_payload
                )
                used_llm = True
            except PlannerGenerationError as exc:
                warnings.append(f"llm_fallback:{exc}")
                outline = build_fallback_outline(
                    user_text=payload.user_text,
                    destination=destination,
                    days=payload.days,
                    source_items=source_items,
                    feedback=feedback,
                    prior_plan=prior_plan.model_dump() if prior_plan else None,
                )
        else:
            outline = build_fallback_outline(
                user_text=payload.user_text,
                destination=destination,
                days=payload.days,
                source_items=source_items,
                feedback=feedback,
                prior_plan=prior_plan.model_dump() if prior_plan else None,
            )

        warnings.extend(
            _detect_feedback_conflicts(
                feedback=feedback, constraints=payload.constraints
            )
        )
        plan = _assemble_contract_plan(
            payload=payload,
            outline=outline,
            destination=destination,
            citations=citations,
            source_items=source_items,
            warnings=warnings,
            used_llm=used_llm,
            feedback=feedback,
            prior_plan=prior_plan,
        )
        validate_itinerary_semantics(plan)
        return ItineraryPlan.model_validate(plan.model_dump())


def _assemble_contract_plan(
    *,
    payload: PlannerGenerateInput,
    outline: dict[str, Any],
    destination: str | None,
    citations: list[Citation],
    source_items: list[dict[str, Any]],
    warnings: list[str],
    used_llm: bool,
    feedback: str | None,
    prior_plan: ItineraryPlan | None,
) -> ItineraryPlan:
    citation_by_url = {citation.url: citation.id for citation in citations}
    citation_ids = {citation.id for citation in citations}

    raw_days = outline.get("days")
    if not isinstance(raw_days, list) or not raw_days:
        raise PlannerValidationError(
            "Planner outline did not provide at least one day."
        )

    days: list[DayPlan] = []
    for day_idx, raw_day in enumerate(raw_days, start=1):
        raw_segments = raw_day.get("segments") if isinstance(raw_day, dict) else []
        if not isinstance(raw_segments, list):
            raw_segments = []

        segment_by_slot: dict[SegmentSlot, SegmentPlan] = {}
        for fallback_slot in SLOTS:
            candidate = _pick_segment_for_slot(
                raw_segments=raw_segments, slot=fallback_slot
            )
            slot = fallback_slot
            title = _sanitize_text(
                (candidate or {}).get("title"),
                fallback=f"{slot.value.title()} in {destination or 'destination'}",
            )
            description = _sanitize_text(
                (candidate or {}).get("description"),
                fallback=(
                    f"{slot.value.title()} activity aligned with travel preferences and"
                    " practical pacing."
                ),
            )
            place_name = _sanitize_optional((candidate or {}).get("place_name"))
            seg_citations = _resolve_segment_citations(
                candidate=candidate,
                citation_by_url=citation_by_url,
                citation_ids=citation_ids,
                source_items=source_items,
                day_index=day_idx,
                slot=slot,
            )
            image_hint = _build_image_hint(
                slot=slot,
                title=title,
                destination=destination,
                place_name=place_name,
            )
            segment_by_slot[slot] = SegmentPlan(
                segment_id=f"d{day_idx}-{slot.value}",
                slot=slot,
                title=title,
                description=description,
                place_ids=[],
                citations=seg_citations,
                image_hints=image_hint,
                images=[],
            )

        day_plan = DayPlan(
            day_index=day_idx,
            segments=[segment_by_slot[slot] for slot in SLOTS],
        )
        days.append(day_plan)

    assumptions = _sanitize_list(outline.get("assumptions"))
    budget_notes = _sanitize_list(outline.get("budget_notes"))
    open_questions = _sanitize_list(outline.get("open_questions"))
    warnings_full = list(warnings) + _sanitize_list(outline.get("warnings"))

    if feedback and "budget" in feedback.lower() and not budget_notes:
        budget_notes.append(
            "Feedback requested budget sensitivity; plan emphasizes lower-cost options where possible."
        )

    confidence = ConfidenceInfo(
        score=_confidence_score(citation_count=len(citations), used_llm=used_llm),
        reasons=_build_confidence_reasons(
            used_llm=used_llm,
            citations=len(citations),
            outline_reasons=_sanitize_list(outline.get("confidence_reasons")),
        ),
    )

    plan_id = _stable_plan_id(
        payload=payload,
        feedback=feedback,
        prior_plan=prior_plan,
        destination=destination,
    )
    return ItineraryPlan(
        plan_id=plan_id,
        destination=outline.get("destination") or destination,
        days=days,
        assumptions=assumptions,
        open_questions=open_questions,
        budget_notes=budget_notes,
        warnings=_dedupe_preserve_order(warnings_full),
        citations=citations,
        confidence=confidence,
    )


def _build_sources(
    payload: PlannerGenerateInput,
) -> tuple[list[Citation], list[dict[str, Any]]]:
    citations_by_url: dict[str, Citation] = {}
    source_items: list[dict[str, Any]] = []

    for candidate in payload.rag_candidates:
        canonical = _canonicalize_url(candidate.link)
        citation = citations_by_url.get(canonical)
        if citation is None:
            citation = Citation(
                id=_stable_citation_id(canonical),
                url=canonical,
                source=(candidate.source or "rag").strip() or "rag",
                title=candidate.name,
            )
            citations_by_url[canonical] = citation
        source_items.append(
            {
                "name": candidate.name,
                "summary": candidate.summary or "",
                "url": canonical,
                "citation_id": citation.id,
            }
        )

    for evidence in payload.research_evidence:
        canonical = _canonicalize_url(evidence.link)
        citation = citations_by_url.get(canonical)
        if citation is None:
            citation = Citation(
                id=_stable_citation_id(canonical),
                url=canonical,
                source=(evidence.source or "research").strip() or "research",
                title=evidence.name,
            )
            citations_by_url[canonical] = citation
        source_items.append(
            {
                "name": evidence.name,
                "summary": evidence.summary,
                "url": canonical,
                "citation_id": citation.id,
            }
        )

    deduped_items: list[dict[str, Any]] = []
    seen = set()
    for item in source_items:
        marker = (item.get("name"), item.get("url"))
        if marker in seen:
            continue
        seen.add(marker)
        deduped_items.append(item)

    citations = list(citations_by_url.values())
    citations.sort(key=lambda item: item.id)
    return citations, deduped_items


def _pick_segment_for_slot(
    *, raw_segments: list[Any], slot: SegmentSlot
) -> dict[str, Any] | None:
    for segment in raw_segments:
        if not isinstance(segment, dict):
            continue
        raw_slot = str(segment.get("slot") or "").strip().lower()
        if raw_slot == slot.value:
            return segment
    return None


def _resolve_segment_citations(
    *,
    candidate: dict[str, Any] | None,
    citation_by_url: dict[str, str],
    citation_ids: set[str],
    source_items: list[dict[str, Any]],
    day_index: int,
    slot: SegmentSlot,
) -> list[str]:
    resolved: list[str] = []
    if candidate:
        explicit_ids = candidate.get("citation_ids")
        if isinstance(explicit_ids, list):
            for item in explicit_ids:
                text = str(item).strip()
                if text in citation_ids:
                    resolved.append(text)

        citation_urls = candidate.get("citation_urls")
        if isinstance(citation_urls, list):
            for url in citation_urls:
                canonical = _canonicalize_url(str(url))
                citation_id = citation_by_url.get(canonical)
                if citation_id:
                    resolved.append(citation_id)

    if not resolved and source_items:
        slot_index = SLOTS.index(slot)
        source = source_items[((day_index - 1) * 3 + slot_index) % len(source_items)]
        citation_id = source.get("citation_id")
        if citation_id in citation_ids:
            resolved.append(citation_id)

    return _dedupe_preserve_order(resolved)


def _build_image_hint(
    *,
    slot: SegmentSlot,
    title: str,
    destination: str | None,
    place_name: str | None,
) -> ImageHint:
    topic = place_name or title
    place = place_name.strip() if place_name and place_name.strip() else None
    dest = destination or "travel destination"
    query = f"{topic}, {dest}, {slot.value} travel photo"
    return ImageHint(
        query=query.strip(),
        place_name=place,
        must_match_landmark=bool(place),
    )


def _confidence_score(*, citation_count: int, used_llm: bool) -> float:
    base = 0.45 if used_llm else 0.4
    score = base + min(0.4, citation_count * 0.05)
    return max(0.0, min(1.0, score))


def _build_confidence_reasons(
    *, used_llm: bool, citations: int, outline_reasons: list[str]
) -> list[str]:
    reasons = [
        "Used structured itinerary schema validation.",
        f"Linked itinerary to {citations} deduplicated citations.",
        "Generation path: LLM."
        if used_llm
        else "Generation path: deterministic fallback.",
    ]
    reasons.extend(outline_reasons)
    return _dedupe_preserve_order([item for item in reasons if item])


def _detect_feedback_conflicts(feedback: str | None, constraints: dict) -> list[str]:
    if not feedback:
        return []

    text = feedback.lower()
    warnings: list[str] = []
    pace = str(constraints.get("pace") or "").lower()
    if pace:
        if ("slow" in text or "relax" in text) and any(
            token in pace for token in ("fast", "packed", "intense")
        ):
            warnings.append("feedback_conflict:requested_slow_pace_vs_fast_constraint")
        if any(token in text for token in ("fast", "packed", "intense")) and any(
            token in pace for token in ("slow", "relaxed")
        ):
            warnings.append("feedback_conflict:requested_fast_pace_vs_slow_constraint")

    budget = str(
        constraints.get("budget") or constraints.get("budget_level") or ""
    ).lower()
    if budget:
        if any(token in text for token in ("cheap", "budget", "low cost")) and any(
            token in budget for token in ("luxury", "high")
        ):
            warnings.append("feedback_conflict:budget_feedback_vs_luxury_constraint")

    return warnings


def _stable_plan_id(
    *,
    payload: PlannerGenerateInput,
    feedback: str | None,
    prior_plan: ItineraryPlan | None,
    destination: str | None,
) -> str:
    basis = {
        "user_text": payload.user_text,
        "destination": destination,
        "days": payload.days,
        "budget_level": payload.budget_level,
        "constraints": payload.constraints,
        "preferences": payload.preferences,
        "candidate_links": sorted(
            _canonicalize_url(item.link) for item in payload.rag_candidates
        ),
        "evidence_links": sorted(
            _canonicalize_url(item.link) for item in payload.research_evidence
        ),
        "feedback": feedback or "",
        "prior_plan_id": prior_plan.plan_id if prior_plan else "",
    }
    digest = hashlib.sha1(
        json.dumps(basis, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()[:12]
    return f"plan_{digest}"


def _stable_citation_id(url: str) -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return f"cit_{digest}"


def _canonicalize_url(url: str) -> str:
    split = urlsplit((url or "").strip())
    scheme = (split.scheme or "https").lower()
    netloc = split.netloc.lower()
    path = split.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


def _sanitize_text(value: Any, *, fallback: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text or fallback


def _sanitize_optional(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _sanitize_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    out: list[str] = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _guess_destination(user_text: str) -> str | None:
    lower = user_text.lower()
    trigger_words = ("to ", "in ", "visit ")
    for trigger in trigger_words:
        idx = lower.find(trigger)
        if idx == -1:
            continue
        candidate = user_text[idx + len(trigger) :].strip(" .,!?")
        if candidate:
            return candidate.split(" ")[0].title()
    return None
