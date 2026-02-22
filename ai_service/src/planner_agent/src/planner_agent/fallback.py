from __future__ import annotations

from typing import Any

SLOTS = ("morning", "afternoon", "evening")


def build_fallback_outline(
    *,
    user_text: str,
    destination: str | None,
    days: int,
    source_items: list[dict[str, Any]],
    feedback: str | None,
    prior_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    safe_days = max(1, days)
    feedback_text = (feedback or "").lower()
    relaxed = any(token in feedback_text for token in ("slow", "relax", "easy pace"))
    budget = any(token in feedback_text for token in ("budget", "cheap", "affordable"))

    prior_segments_by_slot = _collect_prior_segments(prior_plan)

    day_blocks: list[dict[str, Any]] = []
    for day_index in range(1, safe_days + 1):
        segments: list[dict[str, Any]] = []
        for slot_index, slot in enumerate(SLOTS):
            item = _pick_item(source_items, day_index, slot_index)
            prior = prior_segments_by_slot.get(slot)
            place_name = item.get("name") if item else None
            title = _segment_title(
                slot=slot,
                place_name=place_name,
                relaxed=relaxed,
                prior_title=(prior or {}).get("title"),
            )
            description = _segment_description(
                slot=slot,
                place_name=place_name,
                summary=(item or {}).get("summary"),
                destination=destination,
                relaxed=relaxed,
                budget=budget,
                user_text=user_text,
                prior_description=(prior or {}).get("description"),
            )
            citation_urls: list[str] = []
            if item and item.get("url"):
                citation_urls.append(item["url"])
            segments.append(
                {
                    "slot": slot,
                    "title": title,
                    "description": description,
                    "place_name": place_name,
                    "citation_urls": citation_urls,
                }
            )
        day_blocks.append({"day_index": day_index, "segments": segments})

    assumptions = [
        "Transit timing between activities may vary by season and traffic.",
    ]
    budget_notes = []
    warnings = []
    if relaxed:
        assumptions.append(
            "Plan pacing is adjusted to be slower and recovery-friendly."
        )
    if prior_plan:
        assumptions.append(
            "Regenerated as a full replacement using prior-plan context."
        )
    if budget:
        budget_notes.append(
            "Budget-focused plan: activities prioritize lower-cost options where evidence did not indicate fixed ticket pricing."
        )
    if not source_items:
        warnings.append("limited_evidence:fallback_used_without_candidates")

    return {
        "destination": destination,
        "days": day_blocks,
        "assumptions": assumptions,
        "budget_notes": budget_notes,
        "warnings": warnings,
        "open_questions": [],
        "confidence_reasons": ["Deterministic fallback was used."],
    }


def _pick_item(
    source_items: list[dict[str, Any]], day_index: int, slot_index: int
) -> dict[str, Any] | None:
    if not source_items:
        return None
    idx = ((day_index - 1) * 3 + slot_index) % len(source_items)
    return source_items[idx]


def _segment_title(
    *,
    slot: str,
    place_name: str | None,
    relaxed: bool,
    prior_title: str | None,
) -> str:
    noun = place_name or "local highlights"
    if prior_title and not place_name:
        noun = prior_title
    if slot == "morning":
        return f"Start at {noun}" if relaxed else f"Explore {noun}"
    if slot == "afternoon":
        return f"Unhurried afternoon at {noun}" if relaxed else f"Discover {noun}"
    return f"Easy evening around {noun}" if relaxed else f"Evening at {noun}"


def _segment_description(
    *,
    slot: str,
    place_name: str | None,
    summary: str | None,
    destination: str | None,
    relaxed: bool,
    budget: bool,
    user_text: str,
    prior_description: str | None,
) -> str:
    base_place = place_name or (destination or "the destination")
    summary_text = (summary or "").strip()
    intent = user_text.strip()[:120]

    pace_text = (
        "Keep transitions short and leave buffer time between stops."
        if relaxed
        else "Follow a steady pace with practical transfer windows."
    )
    budget_text = (
        " Prefer free viewpoints, public spaces, or low-cost entries when possible."
        if budget
        else ""
    )
    if summary_text:
        return (
            f"{slot.title()} focus at {base_place}. {summary_text} "
            f"{pace_text}{budget_text}"
        ).strip()
    if prior_description:
        return f"{prior_description.strip()} {pace_text}{budget_text}".strip()
    return (
        f"{slot.title()} focus at {base_place}, aligned to '{intent}'. "
        f"{pace_text}{budget_text}"
    ).strip()


def _collect_prior_segments(
    prior_plan: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(prior_plan, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for day in prior_plan.get("days", []):
        if not isinstance(day, dict):
            continue
        for segment in day.get("segments", []):
            if not isinstance(segment, dict):
                continue
            slot = str(segment.get("slot") or "").strip().lower()
            if slot in SLOTS and slot not in out:
                out[slot] = segment
    return out
