from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from api.container import ApiContainer
from api.errors import DomainError, UpstreamDomainError, ValidationDomainError
from api.models import ApiError
from api.routes import router


def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
    payload = ApiError(message=exc.message, code=exc.code)
    return _error_response(status_code=exc.status_code, payload=payload)


def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    payload = ApiError(
        message=ValidationDomainError(str(exc)).message,
        code=ValidationDomainError.code,
    )
    return _error_response(
        status_code=ValidationDomainError.status_code, payload=payload
    )


def handle_unknown_error(_: Request, exc: Exception) -> JSONResponse:
    payload = ApiError(
        message=UpstreamDomainError("Upstream dependency failure.").message,
        code=UpstreamDomainError.code,
    )
    return _error_response(status_code=UpstreamDomainError.status_code, payload=payload)


def _error_response(*, status_code: int, payload: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(),
        headers={"Cache-Control": "no-store"},
    )


def create_app(*, container: ApiContainer | None = None) -> FastAPI:
    app = FastAPI(
        title="Rally Backend API",
        version="1.0.0",
        servers=[{"url": "http://localhost:8080"}],
        openapi_tags=[
            {"name": "health"},
            {"name": "searches"},
            {"name": "attractions"},
            {"name": "trips"},
            {"name": "voice"},
        ],
    )
    app.state.container = container or ApiContainer.build_default()
    app.include_router(router)
    app.add_exception_handler(DomainError, handle_domain_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unknown_error)
    app.openapi = lambda: _custom_openapi(app)
    return app


app = create_app()


def _custom_openapi(app: FastAPI) -> dict:
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
        servers=app.servers,
        tags=app.openapi_tags,
    )
    for path_item in openapi_schema.get("paths", {}).values():
        for operation in path_item.values():
            if isinstance(operation, dict):
                operation.get("responses", {}).pop("422", None)

    schemas = openapi_schema.get("components", {}).get("schemas", {})
    schemas.pop("HTTPValidationError", None)
    schemas.pop("ValidationError", None)

    app.openapi_schema = openapi_schema
    return app.openapi_schema
