from __future__ import annotations

from fastapi import FastAPI

from planner_service.config import load_settings
from planner_service.orchestrator import TravelPlannerOrchestrator
from planner_service.schemas import PlannerRequest, PlannerResponse
from planner_service.tools import AgentToolClients


settings = load_settings()
clients = AgentToolClients(settings=settings)
orchestrator = TravelPlannerOrchestrator(settings=settings, clients=clients)

app = FastAPI(title="Travel Planner Agent", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/plan", response_model=PlannerResponse)
def plan_trip(request: PlannerRequest) -> PlannerResponse:
    return orchestrator.run(request)


def main() -> None:
    import uvicorn

    uvicorn.run("planner_service.api:app", host="0.0.0.0", port=8001, reload=False)
