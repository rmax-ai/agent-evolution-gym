"""Primitive FastMCP tools for the simulated Confluence raw API."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import httpx
from fastmcp import FastMCP

_DEFAULT_WORLD_API_URL = "http://127.0.0.1:8000"

mcp = FastMCP("baseline-confluence")


def _world_api_url() -> str:
    """Return the raw world API base URL from the process environment."""

    return os.environ.get("WORLD_API_URL", _DEFAULT_WORLD_API_URL).rstrip("/")


def _request_url(path: str) -> str:
    """Build an absolute URL for a raw world API path."""

    return f"{_world_api_url()}/{path.lstrip('/')}"


async def _request(
    method: str,
    path: str,
    *,
    params: Mapping[str, str | int] | None = None,
    payload: Mapping[str, Any] | None = None,
    if_version: int | str | None = None,
) -> Any:
    """Send one authenticated request to the raw world API and return its JSON body."""

    headers = {"X-Actor": os.environ.get("ACTOR_ID", "")}
    if if_version is not None:
        headers["If-Version"] = str(if_version)

    request_kwargs: dict[str, Any] = {"headers": headers}
    if params is not None:
        request_kwargs["params"] = dict(params)
    if payload is not None:
        request_kwargs["json"] = dict(payload)

    async with httpx.AsyncClient() as client:
        response = await client.request(method, _request_url(path), **request_kwargs)
        response.raise_for_status()
        return response.json()


@mcp.tool()
async def search_pages(
    query: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Search readable Confluence pages by text, with limit/offset pagination."""

    params: dict[str, str | int] = {"limit": limit, "offset": offset}
    if query is not None:
        params["q"] = query
    return await _request("POST", "/api/pages/search", params=params)


@mcp.tool()
async def get_page(page_id: str) -> dict[str, Any]:
    """Retrieve the current representation of one readable Confluence page."""

    return await _request("GET", f"/api/pages/{page_id}")


@mcp.tool()
async def get_page_versions(page_id: str) -> list[dict[str, Any]]:
    """Retrieve the immutable version history for one readable page."""

    return await _request("GET", f"/api/pages/{page_id}/versions")


@mcp.tool()
async def create_page(
    page_id: str,
    space_id: str,
    title: str,
    body: str = "",
    owner_id: str | None = None,
) -> dict[str, Any]:
    """Create one page in a space through the raw Confluence API."""

    payload: dict[str, Any] = {
        "id": page_id,
        "space_id": space_id,
        "title": title,
        "body": body,
    }
    if owner_id is not None:
        payload["owner_id"] = owner_id
    return await _request("POST", "/api/pages", payload=payload)


@mcp.tool()
async def update_page(
    page_id: str,
    version: int,
    body: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Update mutable page fields using the supplied optimistic-lock version."""

    payload: dict[str, Any] = {}
    if body is not None:
        payload["body"] = body
    if title is not None:
        payload["title"] = title
    return await _request(
        "PUT",
        f"/api/pages/{page_id}",
        payload=payload,
        if_version=version,
    )


if __name__ == "__main__":
    mcp.run()
