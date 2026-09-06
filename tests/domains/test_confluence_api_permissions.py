"""Remaining Dev-2.4 behavioral coverage: page-level permissions and route surface."""

from collections.abc import AsyncIterator

import httpx
import pytest
from domains.confluence.world.api.app import create_app
from domains.confluence.world.fixtures.builder import build_store


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    store = build_store(seed=1, variant="permissions")
    async with httpx.ASGITransport(app=create_app(store)) as transport:
        yield httpx.AsyncClient(transport=transport, base_url="http://world")


async def test_page_level_restriction_overrides_space_access(client: httpx.AsyncClient) -> None:
    """page-6 carries explicit page-level readers/writers (fixture variant 'permissions')."""
    # carol: space-3 writer and page-6 writer -> full access
    own = await client.put(
        "/api/pages/page-6", headers={"X-Actor": "carol", "If-Version": "1"}, json={"body": "x"}
    )
    assert own.status_code == 200

    # alice: space-3 reader, page-6 reader -> read 200, write 403
    read = await client.get("/api/pages/page-6", headers={"X-Actor": "alice"})
    assert read.status_code == 200
    write = await client.put(
        "/api/pages/page-6", headers={"X-Actor": "alice", "If-Version": "2"}, json={"body": "y"}
    )
    assert write.status_code == 403

    # bob: no space-3 access and no page-6 grant -> 403 on read
    denied = await client.get("/api/pages/page-6", headers={"X-Actor": "bob"})
    assert denied.status_code == 403


async def test_api_exposes_only_raw_route_surface(client: httpx.AsyncClient) -> None:
    """SPEC §13/§56: only raw endpoints exist — no convenience operations."""
    expected = {
        ("GET", "/api/pages"),
        ("POST", "/api/pages"),
        ("POST", "/api/pages/search"),
        ("GET", "/api/pages/{page_id}"),
        ("PUT", "/api/pages/{page_id}"),
        ("GET", "/api/pages/{page_id}/versions"),
    }
    from domains.confluence.world.api.routes import router
    from fastapi.routing import APIRoute

    actual = {
        (method, route.path)
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
        if method != "HEAD"
    }
    assert actual == expected
