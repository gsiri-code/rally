from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.models import ApiError
from api.repository import InMemoryTripRepository
from api.routes import router
from api.service import (
    ApiInputError,
    ApiNotFoundError,
    ApiUpstreamError,
    TripPlanningService,
)

_REPOSITORY = InMemoryTripRepository()
_SERVICE = TripPlanningService(repository=_REPOSITORY)

app = FastAPI(title="Trip Planner API", version="v1")
app.include_router(router)


def get_service() -> TripPlanningService:
    return _SERVICE


@app.exception_handler(ApiInputError)
def handle_input_error(_: Request, exc: ApiInputError) -> JSONResponse:
    payload = ApiError(message=str(exc), code="bad_request")
    return _error_response(status_code=400, payload=payload)


@app.exception_handler(RequestValidationError)
def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    payload = ApiError(message=str(exc), code="bad_request")
    return _error_response(status_code=400, payload=payload)


@app.exception_handler(ApiNotFoundError)
def handle_not_found(_: Request, exc: ApiNotFoundError) -> JSONResponse:
    payload = ApiError(message=str(exc), code="not_found")
    return _error_response(status_code=404, payload=payload)


@app.exception_handler(ApiUpstreamError)
def handle_upstream_error(_: Request, exc: ApiUpstreamError) -> JSONResponse:
    payload = ApiError(message=str(exc), code="upstream_error")
    return _error_response(status_code=502, payload=payload)


@app.exception_handler(Exception)
def handle_unknown_error(_: Request, exc: Exception) -> JSONResponse:
    payload = ApiError(message=f"Unhandled error: {exc}", code="upstream_error")
    return _error_response(status_code=502, payload=payload)


def _error_response(*, status_code: int, payload: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(),
        headers={"Cache-Control": "no-store"},
    )
