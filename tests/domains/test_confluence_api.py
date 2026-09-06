"""Behavioral tests for the raw Confluence API over ASGI transport.

Covers SPEC §13 realism (auth, authorization, version conflicts, pagination,
realistic errors, immutable version history) and §57 Family E permission cases.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from domains.confluence.world.api.app import create_app

from agentgym.world.store import InMemoryConfluenceStore

ALICE = "alice"
BOB = "bob"
EVE = "eve"


def _fixture_store() -> InMemoryConfluenceStore:
    store = InMemoryConfluenceStore(
        users={
            ALICE: {"name": "Alice"},
            BOB: {"name": "Bob"},
            EVE: {"name": "Eve"},
            "admin": {"is_admin": True},
        },
        spaces={
            "space-1": {"name": "Engineering", "owner_id": ALICE},
            "space-2": {"name": "Finance", "owner_id": EVE},
        },
        permissions={"spaces": {"space-1": {"readers": [BOB]}}},
    )
    for page in (
        {
            "id": "p1",
            "space_id": "space-1",
            "title": "Deployment",
            "body": "Draft",
            "owner_id": ALICE,
        },
        {
            "id": "p2",
            "space_id": "space-1",
            "title": "Payments Architecture",
            "body": "Production rollout requires approval.",
            "owner_id": ALICE,
        },
        {
            "id": "p3",
            "space_id": "space-2",
            "title": "Secret Budget",
            "body": "Hidden",
            "owner_id": EVE,
        },
    ):
        store.add_page(page)
    return store


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    store = _fixture_store()
    app = create_app(store)
    async with httpx.ASGITransport(app=app) as transport:
        yield httpx.AsyncClient(transport=transport, base_url="http://world")


def _auth(headers: dict[str, str], actor: str) -> dict[str, str]:
    headers["X-Actor"] = actor
    return headers


async def test_get_page_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/pages/p1", headers=_auth({}, ALICE))
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "p1"
    assert body["version"] == 1
    assert body["body"] == "Draft"
    assert body["space_id"] == "space-1"


async def test_get_page_unknown_actor_rejected(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/pages/p1", headers=_auth({}, "ghost"))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unknown_actor"


async def test_get_page_missing_actor_header_rejected(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/pages/p1")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_actor"


async def test_get_page_other_space_forbidden(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/pages/p3", headers=_auth({}, ALICE))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_get_page_unknown_page_not_found(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/pages/nope", headers=_auth({}, ALICE))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "page_not_found"


async def test_read_only_user_cannot_write(client: httpx.AsyncClient) -> None:
    """Family E: readable but non-editable page."""
    response = await client.put(
        "/api/pages/p1", headers=_auth({"If-Version": "1"}, BOB), json={"body": "Hijack"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_admin_can_write_any_page(client: httpx.AsyncClient) -> None:
    response = await client.put(
        "/api/pages/p3", headers=_auth({"If-Version": "1"}, "admin"), json={"body": "Audited"}
    )
    assert response.status_code == 200
    assert response.json()["version"] == 2


async def test_update_requires_if_version(client: httpx.AsyncClient) -> None:
    response = await client.put(
        "/api/pages/p1", headers=_auth({}, ALICE), json={"body": "No precondition"}
    )
    assert response.status_code == 428
    assert response.json()["error"]["code"] == "if_version_required"


async def test_update_version_conflict_and_history(client: httpx.AsyncClient) -> None:
    response = await client.put(
        "/api/pages/p1", headers=_auth({"If-Version": "1"}, ALICE), json={"body": "Published"}
    )
    assert response.status_code == 200
    assert response.json()["version"] == 2

    stale = await client.put(
        "/api/pages/p1", headers=_auth({"If-Version": "1"}, ALICE), json={"body": "Stale write"}
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "version_conflict"

    current = await client.get("/api/pages/p1", headers=_auth({}, ALICE))
    assert current.json()["body"] == "Published"
    assert current.json()["version"] == 2


async def test_version_history_is_immutable(client: httpx.AsyncClient) -> None:
    await client.put(
        "/api/pages/p1", headers=_auth({"If-Version": "1"}, ALICE), json={"body": "V2 body"}
    )
    await client.put(
        "/api/pages/p1", headers=_auth({"If-Version": "2"}, ALICE), json={"body": "V3 body"}
    )
    response = await client.get("/api/pages/p1/versions", headers=_auth({}, ALICE))
    assert response.status_code == 200
    versions = response.json()
    assert [version["version"] for version in versions] == [1, 2, 3]
    assert versions[0]["body"] == "Draft"
    assert versions[1]["body"] == "V2 body"


async def test_list_pages_respects_visibility_and_pagination(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/pages?limit=1&offset=0", headers=_auth({}, ALICE))
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 2  # p3 in space-2 invisible to alice
    assert len(page["items"]) == 1
    assert page["items"][0]["id"] == "p1"

    second = await client.get("/api/pages?limit=1&offset=1", headers=_auth({}, ALICE))
    assert second.json()["items"][0]["id"] == "p2"

    reader = await client.get("/api/pages", headers=_auth({}, BOB))
    assert reader.json()["total"] == 2  # bob reads space-1 pages only


async def test_search_pages_case_insensitive(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/pages/search", headers=_auth({}, ALICE), json={"q": "deployment"}
    )
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert ids == ["p1"]


async def test_create_page_ok_and_conflict(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/pages",
        headers=_auth({}, ALICE),
        json={
            "id": "p4",
            "space_id": "space-1",
            "title": "New Page",
            "body": "Fresh",
        },
    )
    assert response.status_code == 201
    assert response.json()["owner_id"] == ALICE

    duplicate = await client.post(
        "/api/pages",
        headers=_auth({}, ALICE),
        json={"id": "p4", "space_id": "space-1", "title": "Dup"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "page_exists"


async def test_create_page_forbidden_without_space_write(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/pages",
        headers=_auth({}, EVE),
        json={"id": "p5", "space_id": "space-1", "title": "Intruder"},
    )
    assert response.status_code == 403


async def test_create_page_unknown_space(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/pages",
        headers=_auth({}, ALICE),
        json={"id": "p6", "space_id": "space-9", "title": "Orphan"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "space_not_found"


async def test_error_envelope_shape(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/pages/nope", headers=_auth({}, ALICE))
    payload = response.json()
    assert set(payload) == {"error"}
    assert set(payload["error"]) == {"code", "message"}
    assert isinstance(payload["error"]["code"], str)
    assert isinstance(payload["error"]["message"], str)
