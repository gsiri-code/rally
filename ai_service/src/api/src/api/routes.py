from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Header, Response, UploadFile

from api.deps import get_trip_planning_service
from api.mapping import to_ics
from api.models import (
    AttractionsSearchInput,
    AttractionsSearchResponse,
    ChangeBlockInput,
    ComposeInput,
    ErrorMessage,
    FlightSearchCreateInput,
    FlightSearchResponse,
    HealthzResponse,
    SearchResponse,
    TripCreateInput,
    TripPlan,
    VoiceDecideInput,
    VoiceDecideResponse,
    VoiceIntentResponse,
    VoiceTranscribeResponse,
)
from api.service import TripPlanningService

router = APIRouter()


@router.get("/healthz", tags=["health"], summary="Health check")
def healthz(
    service: TripPlanningService = Depends(get_trip_planning_service),
) -> HealthzResponse:
    return service.healthz()


@router.post(
    "/v1/searches/flights",
    response_model=FlightSearchResponse,
    tags=["searches"],
    summary="Create flight search",
    responses={
        400: {"model": ErrorMessage, "description": "Validation error"},
        502: {"model": ErrorMessage, "description": "Upstream search failed"},
    },
)
def create_flight_search(
    payload: FlightSearchCreateInput,
    service: TripPlanningService = Depends(get_trip_planning_service),
) -> FlightSearchResponse:
    return service.create_flight_search(payload)


@router.get(
    "/v1/searches/{search_id}",
    response_model=SearchResponse,
    tags=["searches"],
    summary="Fetch search result",
    responses={
        404: {"model": ErrorMessage, "description": "Search not found"},
    },
)
def get_search(
    search_id: str,
    service: TripPlanningService = Depends(get_trip_planning_service),
) -> SearchResponse:
    return service.get_search(search_id)


@router.post(
    "/v1/attractions/search",
    response_model=AttractionsSearchResponse,
    tags=["attractions"],
    summary="Create attractions search",
    responses={
        202: {
            "model": AttractionsSearchResponse,
            "description": "Search still running",
        },
        400: {"model": ErrorMessage, "description": "Validation error"},
        502: {"model": ErrorMessage, "description": "Upstream search failed"},
    },
)
def create_attractions_search(
    payload: AttractionsSearchInput,
    response: Response,
    service: TripPlanningService = Depends(get_trip_planning_service),
) -> AttractionsSearchResponse:
    search, status_code = service.create_attractions_search(payload)
    response.status_code = status_code
    return search


@router.post(
    "/v1/trips",
    response_model=TripPlan,
    tags=["trips"],
    summary="Create trip and compose itinerary",
    description=(
        "Runs flight + attraction searches, composes an itinerary, normalizes it, "
        "persists the trip, and returns the plan. Uses sqlite cache unless "
        "the `cache: false` header is provided."
    ),
    responses={
        400: {"model": ErrorMessage, "description": "Validation error"},
        502: {
            "model": ErrorMessage,
            "description": "Upstream search or compose failed",
        },
    },
)
def create_trip(
    payload: TripCreateInput,
    response: Response,
    cache: str | None = Header(
        default=None, description="Set to false to bypass cache."
    ),
    service: TripPlanningService = Depends(get_trip_planning_service),
) -> TripPlan:
    trip = service.create_trip(payload=payload, use_cache=_use_cache(cache))
    response.headers["Cache-Control"] = "no-store"
    return trip


@router.post(
    "/v1/itinerary/compose",
    response_model=TripPlan,
    tags=["trips"],
    summary="Compose itinerary for an existing trip",
    description=(
        "Composes a trip plan from existing search IDs and timezone. If the trip "
        "already has a plan stored, it is returned unless `cache: false` is sent."
    ),
    responses={
        400: {"model": ErrorMessage, "description": "Validation error"},
        404: {
            "model": ErrorMessage,
            "description": "Searches not ready or not found",
        },
    },
)
def compose_itinerary(
    payload: ComposeInput,
    response: Response,
    cache: str | None = Header(
        default=None,
        description="Set to false to bypass cached trip plan.",
    ),
    service: TripPlanningService = Depends(get_trip_planning_service),
) -> TripPlan:
    trip = service.compose_itinerary(payload=payload, use_cache=_use_cache(cache))
    response.headers["Cache-Control"] = "no-store"
    return trip


@router.get(
    "/v1/trips/{trip_id}",
    response_model=TripPlan,
    tags=["trips"],
    summary="Fetch trip plan",
    responses={404: {"model": ErrorMessage, "description": "Trip not found"}},
)
def get_trip(
    trip_id: str,
    response: Response,
    service: TripPlanningService = Depends(get_trip_planning_service),
) -> TripPlan:
    trip = service.get_trip(trip_id)
    response.headers["Cache-Control"] = "private, max-age=60"
    return trip


@router.get(
    "/v1/trips/{trip_id}/calendar.ics",
    tags=["trips"],
    summary="Export trip as iCalendar",
    response_class=Response,
    responses={
        200: {
            "content": {"text/calendar": {"schema": {"type": "string"}}},
            "description": "iCalendar file",
        },
        404: {"model": ErrorMessage, "description": "Trip not found"},
    },
)
def export_trip_calendar(
    trip_id: str,
    service: TripPlanningService = Depends(get_trip_planning_service),
) -> Response:
    trip = service.get_trip(trip_id)
    return Response(
        content=to_ics(trip),
        media_type="text/calendar",
        headers={
            "Content-Disposition": f'attachment; filename="{trip_id}.ics"',
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/v1/trips/{trip_id}/blocks/{block_id}/skip",
    response_model=TripPlan,
    tags=["trips"],
    summary="Skip a trip block",
    responses={404: {"model": ErrorMessage, "description": "Trip not found"}},
)
def skip_trip_block(
    trip_id: str,
    block_id: str,
    response: Response,
    service: TripPlanningService = Depends(get_trip_planning_service),
) -> TripPlan:
    trip = service.skip_block(trip_id, block_id)
    response.headers["Cache-Control"] = "no-store"
    return trip


@router.post(
    "/v1/trips/{trip_id}/blocks/{block_id}/change",
    response_model=TripPlan,
    tags=["trips"],
    summary="Replace a trip block with a new attraction",
    responses={404: {"model": ErrorMessage, "description": "Trip or search not found"}},
)
def change_trip_block(
    trip_id: str,
    block_id: str,
    payload: ChangeBlockInput,
    response: Response,
    service: TripPlanningService = Depends(get_trip_planning_service),
) -> TripPlan:
    trip = service.change_block(trip_id, block_id, payload)
    response.headers["Cache-Control"] = "no-store"
    return trip


@router.post(
    "/v1/voice/transcribe",
    response_model=VoiceTranscribeResponse,
    tags=["voice"],
    summary="Transcribe audio via OpenClaw",
    responses={
        400: {"model": ErrorMessage, "description": "Validation error"},
        413: {
            "model": ErrorMessage,
            "description": "Audio too large or long",
        },
        502: {"model": ErrorMessage, "description": "Transcription failed"},
    },
)
async def voice_transcribe(
    file: UploadFile = File(...),
    mime_type: str | None = Form(default=None),
    service: TripPlanningService = Depends(get_trip_planning_service),
) -> VoiceTranscribeResponse:
    data = await file.read()
    _ = mime_type
    return service.transcribe_audio(file.filename or "audio", data)


@router.post(
    "/v1/voice/decide",
    response_model=VoiceDecideResponse,
    tags=["voice"],
    summary="Decide intent from transcript (legacy)",
    responses={
        400: {"model": ErrorMessage, "description": "Validation error"},
        404: {"model": ErrorMessage, "description": "Trip not found"},
    },
)
def voice_decide(
    payload: VoiceDecideInput,
    service: TripPlanningService = Depends(get_trip_planning_service),
) -> VoiceDecideResponse:
    return service.decide_voice(payload)


@router.post(
    "/v1/voice/intent",
    response_model=VoiceIntentResponse,
    tags=["voice"],
    summary="Transcribe and apply a voice command",
    responses={
        400: {"model": ErrorMessage, "description": "Validation error"},
        404: {"model": ErrorMessage, "description": "Trip not found"},
        413: {
            "model": ErrorMessage,
            "description": "Audio too large or long",
        },
        502: {"model": ErrorMessage, "description": "Voice intent failed"},
    },
)
async def voice_intent(
    trip_id: str = Form(...),
    audio: UploadFile = File(...),
    service: TripPlanningService = Depends(get_trip_planning_service),
) -> VoiceIntentResponse:
    data = await audio.read()
    return service.apply_voice_intent(trip_id, audio.filename or "audio", data)


def _use_cache(cache_header: str | None) -> bool:
    return (cache_header or "true").strip().lower() != "false"
