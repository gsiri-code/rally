from __future__ import annotations

import unittest

from api.app import create_app
from api.models import (
    AttractionsSearchInput,
    AttractionsSearchResponse,
    FlightSearchCreateInput,
    FlightSearchResponse,
    HealthzResponse,
    SearchResponse,
    ChangeBlockInput,
    ComposeInput,
    ErrorMessage,
    ItineraryBlock,
    TripCreateInput,
    TripPlan,
    VoiceDecideInput,
    VoiceDecideResponse,
    VoiceIntentResponse,
    VoiceTranscribeResponse,
)


class ApiContractTests(unittest.TestCase):
    def test_openapi_paths_and_error_responses_match_phase_contract(self) -> None:
        spec = create_app().openapi()
        self.assertEqual(
            set(spec["paths"].keys()),
            {
                "/healthz",
                "/v1/searches/flights",
                "/v1/searches/{search_id}",
                "/v1/attractions/search",
                "/v1/trips",
                "/v1/itinerary/compose",
                "/v1/trips/{trip_id}",
                "/v1/trips/{trip_id}/calendar.ics",
                "/v1/trips/{trip_id}/blocks/{block_id}/skip",
                "/v1/trips/{trip_id}/blocks/{block_id}/change",
                "/v1/voice/transcribe",
                "/v1/voice/decide",
                "/v1/voice/intent",
            },
        )
        self.assertEqual(
            set(spec["paths"]["/v1/trips"]["post"]["responses"].keys()),
            {"200", "400", "502"},
        )

    def test_new_schema_names_exist(self) -> None:
        schema_names = set(create_app().openapi()["components"]["schemas"].keys())
        self.assertTrue("HealthzResponse" in schema_names)
        self.assertTrue("FlightSearchCreateInput" in schema_names)
        self.assertTrue("FlightSearchResponse" in schema_names)
        self.assertTrue("SearchResponse" in schema_names)
        self.assertTrue("AttractionsSearchInput" in schema_names)
        self.assertTrue("AttractionsSearchResponse" in schema_names)
        self.assertTrue("VoiceTranscribeResponse" in schema_names)
        self.assertTrue("VoiceDecideInput" in schema_names)
        self.assertTrue("VoiceDecideResponse" in schema_names)
        self.assertTrue("VoiceIntentResponse" in schema_names)

    def test_trip_create_input_schema_fields_are_stable(self) -> None:
        self.assertEqual(
            set(TripCreateInput.model_json_schema()["properties"].keys()),
            {
                "start_date",
                "end_date",
                "origin",
                "destinations",
                "budget_level",
                "pace",
                "limit",
                "neighborhoods",
                "interests",
            },
        )

    def test_compose_input_schema_fields_are_stable(self) -> None:
        self.assertEqual(
            set(ComposeInput.model_json_schema()["properties"].keys()),
            {
                "trip_id",
                "start_date",
                "end_date",
                "attractions_search_id",
                "flight_search_id",
                "timezone",
            },
        )

    def test_trip_plan_schema_has_expected_required_fields(self) -> None:
        required = set(TripPlan.model_json_schema()["required"])
        self.assertEqual(
            required,
            {
                "trip_id",
                "inputs",
                "timezone",
                "search_refs",
                "used_place_ids",
                "itinerary",
                "transit",
                "audit_log",
            },
        )

    def test_change_block_input_direction_enum_matches_contract(self) -> None:
        direction = ChangeBlockInput.model_json_schema()["properties"]["direction"]
        enum_values = direction["anyOf"][0]["enum"]
        self.assertEqual(enum_values, ["cheaper", "closer", "higher_rated"])

    def test_itinerary_block_status_enum_matches_contract(self) -> None:
        status = ItineraryBlock.model_json_schema()["properties"]["status"]
        self.assertEqual(status["enum"], ["planned", "skipped", "replaced"])

    def test_error_message_shape(self) -> None:
        self.assertEqual(
            set(ErrorMessage.model_json_schema()["properties"].keys()),
            {"message", "code"},
        )

    def test_added_models_construct(self) -> None:
        self.assertEqual(HealthzResponse(ok=True, db=True).ok, True)
        self.assertEqual(
            FlightSearchCreateInput(
                origins=["JFK"],
                destinations=["LHR"],
                depart_date="2026-03-14",
            ).depart_date,
            "2026-03-14",
        )
        self.assertEqual(
            FlightSearchResponse(
                search_id="s1",
                query={},
                status="completed",
                results=[],
                notes=[],
                error=None,
                created_at="t1",
                expires_at="t2",
            ).search_id,
            "s1",
        )
        self.assertEqual(
            SearchResponse(
                search_id="s2",
                query={},
                status="running",
                results=[],
                notes=[],
                error=None,
                created_at="t1",
                expires_at="t2",
            ).status,
            "running",
        )
        self.assertEqual(
            AttractionsSearchInput(
                city="London",
                date="2026-03-14",
                categories=["museum"],
            ).city,
            "London",
        )
        self.assertEqual(
            AttractionsSearchResponse(
                search_id="a1",
                type="attractions",
                query={},
                status="completed",
                results=[],
                notes=[],
                error=None,
                created_at="t1",
                expires_at="t2",
                cache={"hit": False, "key": "k"},
            ).type,
            "attractions",
        )
        self.assertEqual(
            VoiceTranscribeResponse(transcript="hello", error=None).transcript,
            "hello",
        )
        self.assertEqual(
            VoiceDecideInput(trip_id="t1", transcript="skip this").trip_id,
            "t1",
        )
        self.assertEqual(
            VoiceDecideResponse(transcript="x", actions=[], options=[]).transcript,
            "x",
        )
        self.assertEqual(
            VoiceIntentResponse.model_json_schema()["required"],
            ["transcript", "decision", "agent_message", "trip"],
        )


if __name__ == "__main__":
    unittest.main()
