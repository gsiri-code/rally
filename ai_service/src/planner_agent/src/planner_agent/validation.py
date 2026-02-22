from __future__ import annotations

from orchestrator_agent.contracts import ItineraryPlan

from planner_agent.errors import PlannerValidationError


def validate_itinerary_semantics(plan: ItineraryPlan) -> None:
    if not plan.days:
        raise PlannerValidationError("Itinerary must contain at least one day.")

    citation_ids = {citation.id for citation in plan.citations}
    for day in plan.days:
        if not day.segments:
            raise PlannerValidationError(f"Day {day.day_index} has no segments.")
        if len(day.segments) > 3:
            raise PlannerValidationError(
                f"Day {day.day_index} has more than three canonical segments."
            )

        seen_slots: set[str] = set()
        for segment in day.segments:
            slot = segment.slot.value
            if slot in seen_slots:
                raise PlannerValidationError(
                    f"Day {day.day_index} has duplicate slot '{slot}'."
                )
            seen_slots.add(slot)

            if not segment.title.strip():
                raise PlannerValidationError(
                    f"Segment {segment.segment_id} has empty title."
                )
            if not segment.description.strip():
                raise PlannerValidationError(
                    f"Segment {segment.segment_id} has empty description."
                )
            if not segment.image_hints.query.strip():
                raise PlannerValidationError(
                    f"Segment {segment.segment_id} has empty image_hints.query."
                )

            for citation_id in segment.citations:
                if citation_id not in citation_ids:
                    raise PlannerValidationError(
                        f"Segment {segment.segment_id} references unknown citation '{citation_id}'."
                    )
