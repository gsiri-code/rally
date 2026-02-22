from orchestrator_agent import build_orchestrator
from orchestrator_agent.adapters import ResearchPackageAdapter


def test_orchestrator_wires_research_package_adapter() -> None:
    orchestrator = build_orchestrator()
    assert isinstance(orchestrator.components.research, ResearchPackageAdapter)
