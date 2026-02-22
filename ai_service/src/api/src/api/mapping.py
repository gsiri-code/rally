from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from orchestrator_agent.contracts import (
    ItineraryPlan,
    PlanRequest,
    SegmentSlot,
    UserContext,
)

from api.models import ComposeTripRequest, SearchRefs, TripBlock, TripPlan

_NON_TRANSIT_WINDOWS = {
    SegmentSlot.MORNING: (9, 0, 12, 0),
    SegmentSlot.AFTERNOON: (13, 0, 17, 0),
    SegmentSlot.EVENING: (18, 0, 21, 0),
}


def map_compose_request_to_plan_request(payload: ComposeTripRequest) -> PlanRequest:
    return PlanRequest(
        text=payload.text,
        voice_mp3_path=payload.voice_mp3_path,
        destination=payload.destination,
        days=payload.days,
        budget_level=payload.budget_level,
        preferences=payload.preferences,
        constraints=payload.constraints,
        context=UserContext(
            user_id=payload.user_id,
            tenant_id=payload.tenant_id,
            request_id=payload.request_id,
        ),
    )


def map_itinerary_to_trip_plan(
    *,
    itinerary: ItineraryPlan,
    timezone: str,
    trip_id_override: str | None = None,
) -> TripPlan:
    tz_name = timezone.strip() or "UTC"
    trip_id = trip_id_override or itinerary.plan_id
    blocks: list[TripBlock] = []
    for day in itinerary.days:
        anchor = _anchor_day(day.day_index, tz_name)
        for segment in day.segments:
            start_time, end_time = _segment_times(anchor, segment.slot)
            block_id = (
                segment.segment_id
                or f"blk_{itinerary.plan_id}_{day.day_index}_{segment.slot.value}"
            )
            block_warnings = [
                warning
                for warning in itinerary.warnings
                if warning == f"missing_media:{segment.segment_id}"
            ]
            blocks.append(
                TripBlock(
                    block_id=block_id,
                    kind="activity",
                    status="proposed",
                    title=segment.title,
                    description=segment.description,
                    start_time=start_time,
                    end_time=end_time,
                    citations=list(segment.citations),
                    warnings=block_warnings,
                )
            )

    return TripPlan(
        trip_id=trip_id,
        destination=itinerary.destination,
        timezone=tz_name,
        blocks=blocks,
        warnings=list(itinerary.warnings),
        search_refs=SearchRefs(
            flight_search_id=f"gen_flight_{trip_id}",
            attractions_search_id=f"gen_attr_{trip_id}",
        ),
    )


def _anchor_day(day_index: int, timezone: str) -> datetime:
    try:
        tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    return datetime(2026, 1, 1 + max(0, day_index - 1), 0, 0, 0, tzinfo=tz)


def _segment_times(day_anchor: datetime, slot: SegmentSlot) -> tuple[str, str]:
    start_h, start_m, end_h, end_m = _NON_TRANSIT_WINDOWS[slot]
    start = day_anchor.replace(hour=start_h, minute=start_m)
    end = day_anchor.replace(hour=end_h, minute=end_m)
    return start.isoformat(), end.isoformat()
