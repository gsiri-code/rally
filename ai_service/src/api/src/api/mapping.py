from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from orchestrator_agent.contracts import (
    ItineraryPlan,
    PlanRequest,
    SegmentSlot,
    UserContext,
)

from api.models import (
    ChangeEvent,
    ComposeInput,
    DayPlan,
    ItineraryBlock,
    PlaceRef,
    SearchRefs,
    TripCreateInput,
    TripPlan,
)

_NON_TRANSIT_WINDOWS = {
    SegmentSlot.MORNING: (9, 0, 12, 0),
    SegmentSlot.AFTERNOON: (13, 0, 17, 0),
    SegmentSlot.EVENING: (18, 0, 21, 0),
}
_SLOT_ORDER: tuple[SegmentSlot, ...] = (
    SegmentSlot.MORNING,
    SegmentSlot.AFTERNOON,
    SegmentSlot.EVENING,
)


def build_trip_id(payload: TripCreateInput) -> str:
    canonical = json.dumps(payload.model_dump(), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"trip_{digest}"


def map_trip_create_input_to_plan_request(
    payload: TripCreateInput,
    *,
    request_id: str,
) -> PlanRequest:
    destination = payload.destinations[0] if payload.destinations else None
    return PlanRequest(
        text=_compose_user_text(payload),
        destination=destination,
        days=_trip_days(payload),
        budget_level=payload.budget_level,
        preferences={
            "pace": payload.pace,
            "neighborhoods": payload.neighborhoods or [],
            "interests": payload.interests or [],
        },
        constraints={"limit": payload.limit},
        context=UserContext(request_id=request_id),
    )


def map_compose_input_to_plan_request(
    payload: ComposeInput,
    *,
    request_id: str,
    base_inputs: TripCreateInput,
) -> PlanRequest:
    plan_request = map_trip_create_input_to_plan_request(
        base_inputs, request_id=request_id
    )
    return plan_request.model_copy(
        update={
            "constraints": {
                **plan_request.constraints,
                "flight_search_id": payload.flight_search_id,
                "attractions_search_id": payload.attractions_search_id,
            }
        }
    )


def map_itinerary_to_trip_plan(
    *,
    itinerary: ItineraryPlan,
    trip_id: str,
    inputs: TripCreateInput,
    timezone: str,
    search_refs: SearchRefs,
    audit_log: list[ChangeEvent] | None = None,
    transit: list[ItineraryBlock] | None = None,
) -> TripPlan:
    tz_name = timezone.strip() or "UTC"
    all_place_ids: list[str] = []
    day_plans: list[DayPlan] = []
    start_date = _parse_date(inputs.start_date)

    for day in sorted(itinerary.days, key=lambda item: item.day_index):
        anchor = _anchor_day(start_date, day.day_index, tz_name)
        day_blocks: list[ItineraryBlock] = []
        day_titles: list[str] = []
        day_place_ids: list[str] = []
        segment_by_slot = {segment.slot: segment for segment in day.segments}

        for slot in _SLOT_ORDER:
            segment = segment_by_slot.get(slot)
            if segment is None:
                continue
            start_at, end_at = _segment_times(anchor, segment.slot)
            place_id = segment.place_ids[0] if segment.place_ids else None
            day_place_ids.extend(segment.place_ids)
            day_titles.append(segment.title)
            day_blocks.append(
                ItineraryBlock(
                    block_id=segment.segment_id,
                    start_at=start_at,
                    end_at=end_at,
                    kind=_slot_kind(segment.slot),
                    title=segment.title,
                    place_ref=PlaceRef(
                        search_id=(
                            search_refs.attractions_search_id
                            if segment.slot != SegmentSlot.EVENING
                            else search_refs.flight_search_id
                        ),
                        result_id=segment.segment_id,
                        place_id=place_id,
                    ),
                    status="planned",
                )
            )

        all_place_ids.extend(day_place_ids)
        day_plans.append(
            DayPlan(
                date=(
                    start_date + timedelta(days=max(0, day.day_index - 1))
                ).isoformat(),
                timezone=tz_name,
                day_summary=f"Day {day.day_index} in {itinerary.destination or inputs.destinations[0]}",
                used_place_ids=day_place_ids,
                used_titles=day_titles,
                blocks=day_blocks,
            )
        )

    unique_place_ids = list(dict.fromkeys(pid for pid in all_place_ids if pid))
    return TripPlan(
        trip_id=trip_id,
        inputs=inputs,
        timezone=tz_name,
        search_refs=search_refs,
        used_place_ids=unique_place_ids,
        itinerary=day_plans,
        transit=transit or [],
        audit_log=audit_log or [],
        estimated_cost_level=inputs.budget_level,
    )


def _trip_days(payload: TripCreateInput) -> int:
    start = _parse_date(payload.start_date)
    end = _parse_date(payload.end_date)
    return max(1, (end - start).days + 1)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _anchor_day(start_date: date, day_index: int, timezone: str) -> datetime:
    try:
        tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    current = start_date + timedelta(days=max(0, day_index - 1))
    return datetime(current.year, current.month, current.day, 0, 0, 0, tzinfo=tz)


def _segment_times(day_anchor: datetime, slot: SegmentSlot) -> tuple[str, str]:
    start_h, start_m, end_h, end_m = _NON_TRANSIT_WINDOWS[slot]
    start = day_anchor.replace(hour=start_h, minute=start_m)
    end = day_anchor.replace(hour=end_h, minute=end_m)
    return start.isoformat(), end.isoformat()


def _slot_kind(slot: SegmentSlot) -> str:
    if slot == SegmentSlot.MORNING:
        return "cafe"
    if slot == SegmentSlot.AFTERNOON:
        return "attraction"
    return "dinner"


def _compose_user_text(payload: TripCreateInput) -> str:
    destination = payload.destinations[0] if payload.destinations else "destination"
    parts: list[str] = [
        f"Plan a trip from {payload.origin} to {destination}.",
        f"Dates: {payload.start_date} to {payload.end_date}.",
        f"Budget: {payload.budget_level}.",
    ]
    if payload.interests:
        parts.append(f"Interests: {', '.join(payload.interests)}.")
    if payload.neighborhoods:
        parts.append(f"Neighborhoods: {', '.join(payload.neighborhoods)}.")
    if payload.pace:
        parts.append(f"Pace: {payload.pace}.")
    return " ".join(parts)


def to_ics(trip: TripPlan) -> str:
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Rally//Trip Planner//EN",
        "CALSCALE:GREGORIAN",
    ]
    for day in trip.itinerary:
        for block in day.blocks:
            dt_start = _ics_datetime(block.start_at)
            dt_end = _ics_datetime(block.end_at)
            lines.extend(
                [
                    "BEGIN:VEVENT",
                    f"UID:{trip.trip_id}-{block.block_id}@rally",
                    f"DTSTART:{dt_start}",
                    f"DTEND:{dt_end}",
                    f"SUMMARY:{_escape_ics(block.title)}",
                    "END:VEVENT",
                ]
            )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _ics_datetime(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    return parsed.strftime("%Y%m%dT%H%M%S")


def _escape_ics(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
