"""Pydantic request and response models for the Confluence raw API."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PageResponse(BaseModel):
    """A page returned by the raw Confluence API."""

    model_config = ConfigDict(extra="allow")

    id: str
    space_id: str
    title: str
    body: str
    version: int
    owner_id: str


class PageCreateRequest(BaseModel):
    """Fields accepted when creating a page."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    space_id: str = Field(min_length=1)
    title: str
    body: str = ""
    owner_id: str | None = None


class PageUpdateRequest(BaseModel):
    """Mutable page fields accepted by an update request."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    body: str | None = None


class PageSearchRequest(BaseModel):
    """Optional body accepted by the page search endpoint."""

    model_config = ConfigDict(extra="forbid")

    q: str | None = None
    query: str | None = None


class PageListResponse(BaseModel):
    """A paginated collection of pages."""

    items: list[PageResponse]
    total: int
    limit: int
    offset: int


class ErrorDetail(BaseModel):
    """Machine-readable and human-readable error information."""

    code: str
    message: str


class ErrorResponse(BaseModel):
    """The common error envelope returned by the raw API."""

    error: ErrorDetail


PageData = dict[str, Any]
