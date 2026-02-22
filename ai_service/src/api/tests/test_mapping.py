from __future__ import annotations

import unittest

from orchestrator_agent.contracts import (
    ConfidenceInfo,
    DayPlan,
    ItineraryPlan,
    SegmentPlan,
    SegmentSlot,
)

from api.mapping import build_trip_id, map_itinerary_to_trip_plan, to_ics
from api.models import SearchRefs, TripCreateInput


def _sample_inputs() -> TripCreateInput:
    return TripCreateInput(
        start_date="2026-03-14",
        end_date="2026-03-16",
        origin="JFK",
        destinations=["LHR"],
        budget_level="mid",
    )


def _sample_itinerary(*, plan_id: str = "plan_abc") -> ItineraryPlan:
    return ItineraryPlan(
        plan_id=plan_id,
        destination="London",
        days=[
            DayPlan(
                day_index=1,
                segments=[
                    SegmentPlan(
                        segment_id="d1-morning",
                        slot=SegmentSlot.MORNING,
                        title="Coffee",
                        description="Morning coffee",
                        place_ids=["pl_1"],
                        image_hints={"query": "london coffee"},
                    ),
                    SegmentPlan(
                        segment_id="d1-afternoon",
                        slot=SegmentSlot.AFTERNOON,
                        title="Museum",
                        description="Afternoon museum",
                        place_ids=["pl_2"],
                        image_hints={"query": "london museum"},
                    ),
                    SegmentPlan(
                        segment_id="d1-evening",
                        slot=SegmentSlot.EVENING,
                        title="Dinner",
                        description="Evening dinner",
                        place_ids=["pl_3"],
                        image_hints={"query": "london dinner"},
                    ),
                ],
            )
        ],
        confidence=ConfidenceInfo(score=0.8, reasons=[]),
    )


class MappingTests(unittest.TestCase):
    def test_trip_id_is_deterministic(self) -> None:
        payload = _sample_inputs()
        self.assertEqual(build_trip_id(payload), build_trip_id(payload))

    def test_mapping_output_shape_matches_contract_fields(self) -> None:
        trip = map_itinerary_to_trip_plan(
            itinerary=_sample_itinerary(),
            trip_id="trip_1",
            inputs=_sample_inputs(),
            timezone="Europe/London",
            search_refs=SearchRefs(
                flight_search_id="flight_123",
                attractions_search_id="attr_456",
            ),
        )
        self.assertEqual(trip.trip_id, "trip_1")
        self.assertEqual(trip.inputs.origin, "JFK")
        self.assertEqual(trip.search_refs.flight_search_id, "flight_123")
        self.assertEqual(trip.itinerary[0].blocks[0].status, "planned")
        self.assertEqual(trip.itinerary[0].blocks[0].kind, "cafe")

    def test_ics_export_contains_calendar_and_events(self) -> None:
        trip = map_itinerary_to_trip_plan(
            itinerary=_sample_itinerary(plan_id="plan_ics"),
            trip_id="trip_ics",
            inputs=_sample_inputs(),
            timezone="UTC",
            search_refs=SearchRefs(
                flight_search_id="flight_ics",
                attractions_search_id="attr_ics",
            ),
        )
        ics = to_ics(trip)
        self.assertIn("BEGIN:VCALENDAR", ics)
        self.assertIn("BEGIN:VEVENT", ics)
        self.assertIn("UID:trip_ics-d1-morning@rally", ics)


if __name__ == "__main__":
    unittest.main()
