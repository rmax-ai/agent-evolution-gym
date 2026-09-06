"""Focused HTTP contract tests for the baseline MCP server."""

import importlib
import sys
from types import ModuleType
from typing import Any, ClassVar

import pytest


@pytest.fixture(scope="module")
def server() -> ModuleType:
    """Import the package server without writing a cache into its artifact tree."""

    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        return importlib.import_module("packages.baseline.mcp.server")
    finally:
        sys.dont_write_bytecode = previous


class _Response:
    def __init__(self, body: Any) -> None:
        self.body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self.body


class _AsyncClient:
    calls: ClassVar[list[dict[str, Any]]] = []

    async def __aenter__(self) -> "_AsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def request(self, method: str, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        return _Response({"id": "page-1", "version": 2, "body": "new body"})


async def test_update_page_sends_actor_and_if_version(
    server: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The update tool sends the raw HTTP headers and JSON payload unchanged."""

    _AsyncClient.calls.clear()
    monkeypatch.setattr(server.httpx, "AsyncClient", _AsyncClient)
    monkeypatch.setenv("WORLD_API_URL", "http://world.example/base/")
    monkeypatch.setenv("ACTOR_ID", "alice")

    result = await server.update_page("page-1", 1, body="new body")

    assert result == {"id": "page-1", "version": 2, "body": "new body"}
    assert _AsyncClient.calls == [
        {
            "method": "PUT",
            "url": "http://world.example/base/api/pages/page-1",
            "headers": {"X-Actor": "alice", "If-Version": "1"},
            "json": {"body": "new body"},
        }
    ]
