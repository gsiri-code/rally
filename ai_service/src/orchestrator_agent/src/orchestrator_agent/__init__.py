from __future__ import annotations

import json

from orchestrator_agent.adapters import (
    PlannerPackageAdapter,
    RagPackageAdapter,
    ResearchPackageAdapter,
    TranscriptionPackageAdapter,
    build_contract_map,
)
from orchestrator_agent.contracts import PlanRequest, UserContext
from orchestrator_agent.graph import TravelOrchestrator
from orchestrator_agent.interfaces import OrchestratorComponents


def build_orchestrator() -> TravelOrchestrator:
    components = OrchestratorComponents(
        rag=RagPackageAdapter(),
        planner=PlannerPackageAdapter(),
        research=ResearchPackageAdapter(),
        transcription=TranscriptionPackageAdapter(),
    )
    return TravelOrchestrator(components=components)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run orchestrator contract checks")
    parser.add_argument("--show-contracts", action="store_true")
    parser.add_argument("--text")
    parser.add_argument("--voice-mp3-path")
    args = parser.parse_args()

    if args.show_contracts:
        print(json.dumps(build_contract_map(), indent=2))
        return

    if not args.text and not args.voice_mp3_path:
        print("Use --show-contracts, --text, or --voice-mp3-path")
        return

    request = PlanRequest(
        text=args.text,
        voice_mp3_path=args.voice_mp3_path,
        context=UserContext(request_id="local-cli"),
    )
    orchestrator = build_orchestrator()
    response = orchestrator.run(request)
    print(response.model_dump_json(indent=2))


__all__ = ["build_orchestrator", "main", "TravelOrchestrator"]
