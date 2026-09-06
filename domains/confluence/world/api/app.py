"""FastAPI application factory for the Confluence simulator world."""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from agentgym.world.store import InMemoryConfluenceStore

from .lifecycle import create_control_router
from .routes import (
    APIError,
    api_error_handler,
    http_exception_handler,
    router,
    validation_error_handler,
)

_active_app: FastAPI | None = None


def create_app(
    store: InMemoryConfluenceStore | None = None,
    control_key: str | None = None,
) -> FastAPI:
    """Create a raw Confluence API application backed by ``store``."""

    application = FastAPI(
        title="Enterprise Confluence Simulator",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.store = store if store is not None else InMemoryConfluenceStore()
    application.state.started = False
    application.state.control_key = control_key
    application.include_router(router)
    if control_key is not None:
        application.include_router(create_control_router(control_key))
    application.add_exception_handler(APIError, api_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    return application


async def start_world(store: InMemoryConfluenceStore | None = None) -> FastAPI:
    """Prepare an app for a loopback uvicorn process and return it."""

    global _active_app
    application = create_app(store) if store is not None else app
    application.state.started = True
    _active_app = application
    return application


async def stop_world(application: FastAPI | None = None) -> None:
    """Mark a loopback world as stopped after its server exits."""

    global _active_app
    target = application if application is not None else (_active_app or app)
    target.state.started = False
    if target is _active_app:
        _active_app = None


app = create_app()
