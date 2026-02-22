# api

FastAPI boundary layer for v1 trip planning routes.

## Routes

- `POST /v1/trips/compose`
- `GET /v1/trips/{trip_id}`
- `POST /v1/trips/{trip_id}/feedback`

## Notes

- Internal orchestrator contracts remain unchanged (`PlanRequest`/`ItineraryPlan`).
- API response shape is `TripPlan` from `api.models`.
- Compose and feedback paths set `Cache-Control: no-store`.
- Read path sets `Cache-Control: private, max-age=60`.
