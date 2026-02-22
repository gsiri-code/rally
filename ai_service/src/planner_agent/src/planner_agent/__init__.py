from __future__ import annotations

from orchestrator_agent.contracts import (
    ItineraryPlan,
    PlannerGenerateInput,
    PlannerRegenerateInput,
)

from planner_agent.agent import PlannerPackageAgent

_DEFAULT_AGENT: PlannerPackageAgent | None = None


def _get_default_agent() -> PlannerPackageAgent:
    global _DEFAULT_AGENT
    if _DEFAULT_AGENT is None:
        _DEFAULT_AGENT = PlannerPackageAgent()
    return _DEFAULT_AGENT


def generate(payload: PlannerGenerateInput) -> ItineraryPlan:
    return _get_default_agent().generate(payload)


def regenerate(payload: PlannerRegenerateInput) -> ItineraryPlan:
    return _get_default_agent().regenerate(payload)


def main() -> None:
    print(
        "planner_agent is an in-process package; import and call generate/regenerate."
    )


__all__ = ["PlannerPackageAgent", "generate", "regenerate", "main"]
