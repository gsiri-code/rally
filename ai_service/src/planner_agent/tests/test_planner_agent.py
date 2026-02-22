from __future__ import annotations

import os
import unittest

from orchestrator_agent.contracts import (
    Candidate,
    ItineraryPlan,
    PlannerGenerateInput,
    PlannerRegenerateInput,
    ResearchEvidence,
)
from planner_agent.agent import PlannerPackageAgent


class PlannerAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.pop("OPENROUTER_API_KEY", None)

    def _sample_input(self) -> PlannerGenerateInput:
        return PlannerGenerateInput(
            user_text="Plan 2 days in Tokyo focused on food and neighborhoods",
            destination="Tokyo",
            days=2,
            constraints={"pace": "relaxed"},
            rag_candidates=[
                Candidate(
                    id="c1",
                    name="Senso-ji Temple",
                    summary="Historic Buddhist temple in Asakusa.",
                    type="attraction",
                    destination="Tokyo",
                    link="https://example.com/sensoji/",
                    source="rag",
                ),
                Candidate(
                    id="c2",
                    name="Shibuya Crossing",
                    summary="Iconic scramble crossing with nearby cafes.",
                    type="attraction",
                    destination="Tokyo",
                    link="https://example.com/shibuya",
                    source="rag",
                ),
            ],
            research_evidence=[
                ResearchEvidence(
                    evidence_id="e1",
                    name="Tsukiji Outer Market",
                    summary="Morning seafood market and street food area.",
                    link="https://example.com/tsukiji",
                    source="research",
                ),
                ResearchEvidence(
                    evidence_id="e2",
                    name="Senso-ji Temple",
                    summary="Extra detail for the same attraction.",
                    link="https://example.com/sensoji",
                    source="research",
                ),
            ],
        )

    def test_generate_returns_contract(self) -> None:
        agent = PlannerPackageAgent()
        plan = agent.generate(self._sample_input())

        self.assertIsInstance(plan, ItineraryPlan)
        self.assertGreaterEqual(len(plan.days), 1)
        for day in plan.days:
            self.assertLessEqual(len(day.segments), 3)
            for segment in day.segments:
                self.assertTrue(segment.title.strip())
                self.assertTrue(segment.description.strip())

    def test_generate_with_evidence_has_valid_citations(self) -> None:
        agent = PlannerPackageAgent()
        plan = agent.generate(self._sample_input())

        top_ids = {citation.id for citation in plan.citations}
        self.assertGreaterEqual(len(top_ids), 1)
        for day in plan.days:
            for segment in day.segments:
                for citation_id in segment.citations:
                    self.assertIn(citation_id, top_ids)

    def test_regenerate_uses_feedback(self) -> None:
        agent = PlannerPackageAgent()
        base_payload = self._sample_input()
        prior = agent.generate(base_payload)
        regen_payload = PlannerRegenerateInput(
            **base_payload.model_dump(),
            prior_plan=prior,
            feedback="Please make this slower and budget-friendly",
        )

        updated = agent.regenerate(regen_payload)
        self.assertIsInstance(updated, ItineraryPlan)
        self.assertGreaterEqual(len(updated.days), 1)
        combined_notes = " ".join(updated.assumptions + updated.budget_notes).lower()
        self.assertTrue("slow" in combined_notes or "relax" in combined_notes)
        self.assertIn("budget", combined_notes)

    def test_citation_dedupe_and_reference_integrity(self) -> None:
        agent = PlannerPackageAgent()
        plan = agent.generate(self._sample_input())

        citation_urls = [citation.url for citation in plan.citations]
        self.assertEqual(len(citation_urls), len(set(citation_urls)))

        top_ids = {citation.id for citation in plan.citations}
        for day in plan.days:
            for segment in day.segments:
                for citation_id in segment.citations:
                    self.assertIn(citation_id, top_ids)

    def test_image_hints_present_every_segment(self) -> None:
        agent = PlannerPackageAgent()
        plan = agent.generate(self._sample_input())

        for day in plan.days:
            for segment in day.segments:
                self.assertTrue(segment.image_hints.query.strip())

    def test_fallback_is_deterministic_without_key(self) -> None:
        agent = PlannerPackageAgent()
        payload = self._sample_input()
        first = agent.generate(payload)
        second = agent.generate(payload)

        self.assertEqual(first.model_dump(), second.model_dump())


if __name__ == "__main__":
    unittest.main()
