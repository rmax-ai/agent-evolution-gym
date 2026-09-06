"""Trusted lifecycle and control routes for process-based Confluence worlds.

The routes in this module are deliberately kept separate from the raw API
router.  A process world gets them only when the application factory receives a
control key; an agent-facing application therefore retains exactly the raw
Confluence surface from :mod:`domains.confluence.world.api.routes`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.status import HTTP_403_FORBIDDEN, HTTP_404_NOT_FOUND

from agentgym.world.snapshot import WorldSnapshot
from agentgym.world.store import InMemoryConfluenceStore, VersionConflictError


async def start_world(store: InMemoryConfluenceStore | None = None) -> Any:
    """Lazily re-export the application lifecycle helper."""

    from .app import start_world as _start_world

    return await _start_world(store)


async def stop_world(application: Any | None = None) -> None:
    """Lazily re-export the application lifecycle helper."""

    from .app import stop_world as _stop_world

    await _stop_world(application)


class HumanEditRequest(BaseModel):
    """Trusted runner payload for the deterministic concurrent-editor hook."""

    model_config = ConfigDict(extra="forbid")

    page_id: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    body: str


def create_control_router(control_key: str) -> APIRouter:
    """Build the private control router closed over one execution key."""

    if not control_key:
        raise ValueError("control_key must not be empty")

    router = APIRouter(prefix="/api/control", tags=["world-control"])

    def require_control_key(
        x_control_key: Annotated[str | None, Header(alias="X-Control-Key")] = None,
    ) -> None:
        if x_control_key != control_key:
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail="invalid control key",
            )

    def store_from_request(request: Request) -> InMemoryConfluenceStore:
        store = getattr(request.app.state, "store", None)
        if not isinstance(store, InMemoryConfluenceStore):
            raise RuntimeError("Confluence app has no configured store")
        return store

    @router.post("/snapshot", response_model=WorldSnapshot)
    async def capture_snapshot(
        request: Request,
    ) -> WorldSnapshot:
        """Capture complete state for the trusted runner."""

        # The dependency is called explicitly so the route remains easy to use
        # from an ordinary HTTP client and cannot accidentally become public.
        require_control_key(request.headers.get("X-Control-Key"))
        return store_from_request(request).snapshot()

    @router.post("/human-edit")
    async def apply_human_edit(
        request: Request,
        edit: HumanEditRequest,
    ) -> dict[str, Any]:
        """Apply one trusted human edit using the current page version."""

        require_control_key(request.headers.get("X-Control-Key"))
        store = store_from_request(request)
        try:
            current = store.pages[edit.page_id]
        except KeyError as error:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=f"unknown page: {edit.page_id}",
            ) from error

        try:
            updated = store.update_page(
                edit.page_id,
                body=edit.body,
                expected_version=int(current.get("version", 1)),
            )
        except VersionConflictError as error:
            # The current-version read and update are synchronous inside one
            # event loop.  Preserve a clear trusted-control error if a future
            # store implementation introduces a competing writer.
            raise HTTPException(status_code=409, detail=str(error)) from error

        return updated.model_dump(mode="json")

    @router.post("/restore", response_model=WorldSnapshot)
    async def restore_snapshot(
        request: Request,
        snapshot: WorldSnapshot,
    ) -> WorldSnapshot:
        """Restore a complete snapshot through the trusted control channel."""

        require_control_key(request.headers.get("X-Control-Key"))
        store = store_from_request(request)
        store.restore(snapshot)
        return store.snapshot(snapshot_id=snapshot.id, timestamp=snapshot.timestamp)

    return router


__all__ = ["HumanEditRequest", "create_control_router", "start_world", "stop_world"]
