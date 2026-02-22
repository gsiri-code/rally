# planner_agent

In-process planner package that generates and regenerates structured `ItineraryPlan` objects compatible with `orchestrator_agent` contracts.

## Environment variables

- `OPENROUTER_API_KEY`: required for LLM planning mode.
- `OPENROUTER_BASE_URL`: optional, defaults to `https://openrouter.ai/api/v1`.
- `OPENROUTER_MODEL`: optional, but must be exactly `nvidia/nemotron-3-nano-30b-a3b:free` if present.

Planner model is hardcoded to:

`nvidia/nemotron-3-nano-30b-a3b:free`

If `OPENROUTER_API_KEY` is not set, planner uses deterministic fallback assembly.

## Usage

```python
from orchestrator_agent.contracts import PlannerGenerateInput, PlannerRegenerateInput
from planner_agent import generate, regenerate

payload = PlannerGenerateInput(
    user_text="Plan me 3 days in Kyoto with good food and temples",
    destination="Kyoto",
    days=3,
)
plan = generate(payload)

regen_payload = PlannerRegenerateInput(
    **payload.model_dump(),
    prior_plan=plan,
    feedback="Make this slower paced and more budget-friendly",
)
updated = regenerate(regen_payload)
```

## Expected output shape

```text
ItineraryPlan
  plan_id: str
  destination: str | None
  days: list[DayPlan]
    day_index: int
    segments: list[SegmentPlan]
      segment_id: str
      slot: "morning" | "afternoon" | "evening"
      title: str
      description: str
      citations: list[str]
      image_hints: { query: str, place_name: str | None, must_match_landmark: bool }
      images: list[ImageAsset]
  assumptions: list[str]
  budget_notes: list[str]
  warnings: list[str]
  citations: list[Citation]
  confidence: { score: float, reasons: list[str] }
```
