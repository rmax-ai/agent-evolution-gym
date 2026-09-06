"""Raw Confluence REST routes and authorization helpers."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_CONTENT,
    HTTP_428_PRECONDITION_REQUIRED,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from agentgym.world.store import InMemoryConfluenceStore, Page
from domains.confluence.world.models import (
    PageCreateRequest,
    PageListResponse,
    PageResponse,
    PageSearchRequest,
    PageUpdateRequest,
)

router = APIRouter(prefix="/api", tags=["confluence"])

_READ_PERMISSION_KEYS = ("read", "view", "reader", "readers", "viewers")
_WRITE_PERMISSION_KEYS = (
    "write",
    "edit",
    "editor",
    "editors",
    "update",
    "manage",
    "admin",
    "admins",
)
_FULL_ACCESS_KEYS = ("users", "actors", "members", "allowed", "allow", "access")
_SCOPED_SECTION_NAMES = {
    "page": ("page", "pages", "page_permissions", "pages_permissions"),
    "space": ("space", "spaces", "space_permissions", "spaces_permissions"),
}
_READ_TOKENS = frozenset(_READ_PERMISSION_KEYS)
_WRITE_TOKENS = frozenset(_WRITE_PERMISSION_KEYS)
_ADMIN_TOKENS = frozenset({"admin", "administrator", "owner", "full", "all"})


class APIError(Exception):
    """An expected raw-API failure represented by the common error envelope."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = dict(headers or {})


@dataclass(frozen=True)
class ActorIdentity:
    """The canonical user id and aliases associated with an actor header."""

    user_id: str
    aliases: frozenset[str]


@dataclass(frozen=True)
class ActorScopedPermission:
    """A permission value already selected by an actor id in the state map."""

    value: Any


class PermissionResolver:
    """Resolve page and space permissions from the store's flexible state maps."""

    def __init__(self, store: InMemoryConfluenceStore) -> None:
        self.store = store

    def can_read_page(self, page: Mapping[str, Any], actor: ActorIdentity) -> bool:
        """Return whether an actor may read a page."""

        return self._can_access_page(page, actor, operation="read")

    def can_write_page(self, page: Mapping[str, Any], actor: ActorIdentity) -> bool:
        """Return whether an actor may edit a page."""

        return self._can_access_page(page, actor, operation="write")

    def can_create_page(self, space_id: str, actor: ActorIdentity) -> bool:
        """Return whether an actor may create a page in a space."""

        if self._is_global_admin(actor) or self._is_space_owner(space_id, actor):
            return True

        entries = self._permission_entries("space", space_id, actor)
        return bool(entries) and self._entries_grant(entries, actor, operation="write")

    def _can_access_page(
        self,
        page: Mapping[str, Any],
        actor: ActorIdentity,
        *,
        operation: str,
    ) -> bool:
        page_id = str(page["id"])
        space_id = str(page["space_id"])
        if self._is_global_admin(actor) or self._is_page_owner(page, actor):
            return True

        page_entries = self._permission_entries("page", page_id, actor)
        space_entries = self._permission_entries("space", space_id, actor)
        page_defined = bool(page_entries)
        space_defined = bool(space_entries)
        page_granted = self._entries_grant(page_entries, actor, operation=operation)
        space_granted = self._entries_grant(space_entries, actor, operation=operation)

        if page_defined and space_defined:
            return page_granted and space_granted
        return page_granted or space_granted

    def _permission_entries(
        self,
        scope: str,
        resource_id: str,
        actor: ActorIdentity,
    ) -> list[Any]:
        permissions = self.store.permissions
        entries: list[Any] = []
        section_names = _SCOPED_SECTION_NAMES[scope]

        for section_name in section_names:
            section = permissions.get(section_name)
            if isinstance(section, Mapping) and resource_id in section:
                entries.append(section[resource_id])

        if resource_id in permissions:
            entries.append(permissions[resource_id])

        for alias in actor.aliases:
            actor_permissions = permissions.get(alias)
            if not isinstance(actor_permissions, Mapping):
                continue
            for section_name in section_names:
                section = actor_permissions.get(section_name)
                if isinstance(section, Mapping) and resource_id in section:
                    entries.append(ActorScopedPermission(section[resource_id]))
            if resource_id in actor_permissions:
                entries.append(ActorScopedPermission(actor_permissions[resource_id]))

        resource = self._resource(resource_id, scope)
        if isinstance(resource, Mapping):
            for key in ("permissions", "permission", "access"):
                if key in resource:
                    entries.append(resource[key])

        return entries

    def _resource(self, resource_id: str, scope: str) -> Any:
        resources = self.store.pages if scope == "page" else self.store.spaces
        return resources.get(resource_id)

    def _is_global_admin(self, actor: ActorIdentity) -> bool:
        user = self.store.users.get(actor.user_id)
        if not isinstance(user, Mapping):
            return False
        if user.get("is_admin") is True or user.get("admin") is True:
            return True
        role = user.get("role")
        return isinstance(role, str) and role.casefold() in _ADMIN_TOKENS

    def _is_page_owner(self, page: Mapping[str, Any], actor: ActorIdentity) -> bool:
        owner_id = page.get("owner_id")
        return owner_id is not None and str(owner_id) in actor.aliases

    def _is_space_owner(self, space_id: str, actor: ActorIdentity) -> bool:
        space = self.store.spaces.get(space_id)
        if not isinstance(space, Mapping):
            return False
        owner_id = space.get("owner_id")
        if owner_id is not None and str(owner_id) in actor.aliases:
            return True
        administrators = space.get("admins", space.get("administrators", []))
        return _actor_in_value(administrators, actor.aliases)

    @staticmethod
    def _entries_grant(entries: Sequence[Any], actor: ActorIdentity, *, operation: str) -> bool:
        return any(_entry_grants(entry, actor.aliases, operation=operation) for entry in entries)


def _actor_in_value(value: Any, aliases: frozenset[str]) -> bool:
    """Return whether a value contains an actor alias or wildcard."""

    if isinstance(value, str):
        return value == "*" or value in aliases
    if isinstance(value, Mapping):
        return any(key == "*" or str(key) in aliases for key in value)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return any(_actor_in_value(item, aliases) for item in value)
    return bool(value) if isinstance(value, bool) else False


def _entry_grants(entry: Any, aliases: frozenset[str], *, operation: str) -> bool:
    """Interpret a permission entry without requiring one storage shape."""

    if isinstance(entry, ActorScopedPermission):
        return _scoped_value_grants(entry.value, operation=operation)
    if isinstance(entry, bool):
        return entry
    if isinstance(entry, str):
        return entry == "*" or entry in aliases
    if isinstance(entry, Sequence) and not isinstance(entry, str | bytes | bytearray):
        return _actor_in_value(entry, aliases)
    if not isinstance(entry, Mapping):
        return False

    for alias in aliases:
        if alias in entry and _scoped_value_grants(entry[alias], operation=operation):
            return True
    if "*" in entry and _scoped_value_grants(entry["*"], operation=operation):
        return True

    for key in _FULL_ACCESS_KEYS:
        if key in entry and _actor_in_value(entry[key], aliases):
            return True

    keys = _READ_PERMISSION_KEYS if operation == "read" else _WRITE_PERMISSION_KEYS
    if operation == "read":
        keys = (*keys, *_WRITE_PERMISSION_KEYS)
    for key in keys:
        if key in entry and _actor_in_value(entry[key], aliases):
            return True
        if key in entry and isinstance(entry[key], bool) and entry[key]:
            return True

    for key in ("permissions", "permission", "access"):
        if key in entry and _entry_grants(entry[key], aliases, operation=operation):
            return True
    return False


def _scoped_value_grants(value: Any, *, operation: str) -> bool:
    """Interpret the value stored directly under one actor id."""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.casefold()
        return (
            token in _ADMIN_TOKENS
            or token in _WRITE_TOKENS
            or (operation == "read" and token in _READ_TOKENS)
        )
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        tokens = {item.casefold() for item in value if isinstance(item, str)}
        return (
            bool(tokens & _ADMIN_TOKENS)
            or bool(tokens & _WRITE_TOKENS)
            or (operation == "read" and bool(tokens & _READ_TOKENS))
        )
    if isinstance(value, Mapping):
        for key in _WRITE_PERMISSION_KEYS:
            if value.get(key) is True:
                return True
        if operation == "read":
            for key in _READ_PERMISSION_KEYS:
                if value.get(key) is True:
                    return True
        role = value.get("role")
        if isinstance(role, str):
            token = role.casefold()
            if token in _ADMIN_TOKENS or token in _WRITE_TOKENS:
                return True
            if operation == "read" and token in _READ_TOKENS:
                return True
    return False


def _resolve_actor(store: InMemoryConfluenceStore, actor_header: str | None) -> ActorIdentity:
    """Resolve an X-Actor value against the store's user collection."""

    if actor_header is None or not actor_header.strip():
        raise APIError(
            HTTP_401_UNAUTHORIZED,
            "missing_actor",
            "X-Actor header is required",
            headers={"WWW-Authenticate": "X-Actor"},
        )

    requested = actor_header.strip()
    for user_id, user in store.users.items():
        aliases = {str(user_id)}
        if isinstance(user, Mapping):
            for field in ("id", "user_id", "username", "name", "email"):
                value = user.get(field)
                if isinstance(value, str) and value:
                    aliases.add(value)
        elif isinstance(user, str) and user:
            aliases.add(user)
        if requested in aliases:
            return ActorIdentity(str(user_id), frozenset(aliases))

    raise APIError(
        HTTP_401_UNAUTHORIZED,
        "unknown_actor",
        f"unknown actor: {requested}",
        headers={"WWW-Authenticate": "X-Actor"},
    )


def _store_from_request(request: Request) -> InMemoryConfluenceStore:
    try:
        store = request.app.state.store
    except AttributeError as error:
        raise RuntimeError("Confluence app has no configured store") from error
    if not isinstance(store, InMemoryConfluenceStore):
        raise RuntimeError("Confluence app store has an unsupported type")
    return store


async def require_actor(
    request: Request,
    x_actor: Annotated[str | None, Header(alias="X-Actor")] = None,
) -> ActorIdentity:
    """Authenticate a request using the raw API actor header."""

    return _resolve_actor(_store_from_request(request), x_actor)


def _page_response(page: Mapping[str, Any]) -> PageResponse:
    return PageResponse.model_validate(page)


def _visible_pages(
    store: InMemoryConfluenceStore,
    actor: ActorIdentity,
    *,
    query: str | None = None,
) -> list[PageResponse]:
    resolver = PermissionResolver(store)
    normalized_query = query.casefold() if query is not None else None
    visible: list[PageResponse] = []
    for page in store.pages.values():
        if not resolver.can_read_page(page, actor):
            continue
        if normalized_query is not None:
            haystack = " ".join(
                str(page.get(field, "")) for field in ("id", "space_id", "title", "body")
            ).casefold()
            if normalized_query not in haystack:
                continue
        visible.append(_page_response(page))
    return visible


def _paginated(
    pages: list[PageResponse],
    *,
    limit: int,
    offset: int,
) -> PageListResponse:
    return PageListResponse(
        items=pages[offset : offset + limit],
        total=len(pages),
        limit=limit,
        offset=offset,
    )


@router.get("/pages", response_model=PageListResponse, status_code=HTTP_200_OK)
async def list_pages(
    request: Request,
    actor: Annotated[ActorIdentity, Depends(require_actor)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageListResponse:
    """List pages readable by the authenticated actor."""

    pages = _visible_pages(_store_from_request(request), actor)
    return _paginated(pages, limit=limit, offset=offset)


@router.post("/pages/search", response_model=PageListResponse, status_code=HTTP_200_OK)
async def search_pages(
    request: Request,
    actor: Annotated[ActorIdentity, Depends(require_actor)],
    q: Annotated[str | None, Query()] = None,
    body: Annotated[PageSearchRequest | None, Body()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageListResponse:
    """Search readable pages by id, space, title, or body text."""

    query = q if q is not None else (body.q if body and body.q is not None else None)
    if query is None and body is not None:
        query = body.query
    pages = _visible_pages(_store_from_request(request), actor, query=query or "")
    return _paginated(pages, limit=limit, offset=offset)


@router.get("/pages/{page_id}", response_model=PageResponse, status_code=HTTP_200_OK)
async def get_page(
    page_id: str,
    request: Request,
    actor: Annotated[ActorIdentity, Depends(require_actor)],
) -> PageResponse:
    """Return one page after authentication and read authorization."""

    store = _store_from_request(request)
    page = store.pages.get(page_id)
    if page is None:
        raise APIError(HTTP_404_NOT_FOUND, "page_not_found", f"unknown page: {page_id}")
    if not PermissionResolver(store).can_read_page(page, actor):
        raise APIError(HTTP_403_FORBIDDEN, "forbidden", "actor cannot read this page")
    return _page_response(page)


@router.get("/pages/{page_id}/versions", response_model=list[PageResponse], status_code=HTTP_200_OK)
async def get_page_versions(
    page_id: str,
    request: Request,
    actor: Annotated[ActorIdentity, Depends(require_actor)],
) -> list[PageResponse]:
    """Return the immutable version history for a readable page."""

    store = _store_from_request(request)
    page = store.pages.get(page_id)
    if page is None:
        raise APIError(HTTP_404_NOT_FOUND, "page_not_found", f"unknown page: {page_id}")
    if not PermissionResolver(store).can_read_page(page, actor):
        raise APIError(HTTP_403_FORBIDDEN, "forbidden", "actor cannot read this page")
    return [_page_response(version) for version in store.get_page_versions(page_id)]


@router.post("/pages", response_model=PageResponse, status_code=HTTP_201_CREATED)
async def create_page(
    payload: PageCreateRequest,
    request: Request,
    actor: Annotated[ActorIdentity, Depends(require_actor)],
) -> PageResponse:
    """Create a page when the actor can write to its space."""

    store = _store_from_request(request)
    if store.spaces and payload.space_id not in store.spaces:
        raise APIError(
            HTTP_404_NOT_FOUND,
            "space_not_found",
            f"unknown space: {payload.space_id}",
        )
    resolver = PermissionResolver(store)
    if not resolver.can_create_page(payload.space_id, actor):
        raise APIError(HTTP_403_FORBIDDEN, "forbidden", "actor cannot create pages in this space")
    if payload.id in store.pages:
        raise APIError(HTTP_409_CONFLICT, "page_exists", f"page already exists: {payload.id}")

    page = store.add_page(
        Page(
            id=payload.id,
            space_id=payload.space_id,
            title=payload.title,
            body=payload.body,
            owner_id=payload.owner_id or actor.user_id,
        )
    )
    return _page_response(page.model_dump(mode="python"))


@router.put("/pages/{page_id}", response_model=PageResponse, status_code=HTTP_200_OK)
async def update_page(
    page_id: str,
    payload: PageUpdateRequest,
    request: Request,
    actor: Annotated[ActorIdentity, Depends(require_actor)],
    if_version: Annotated[str | None, Header(alias="If-Version")] = None,
) -> PageResponse:
    """Update a page with an optimistic-concurrency precondition."""

    store = _store_from_request(request)
    page = store.pages.get(page_id)
    if page is None:
        raise APIError(HTTP_404_NOT_FOUND, "page_not_found", f"unknown page: {page_id}")

    resolver = PermissionResolver(store)
    if not resolver.can_write_page(page, actor):
        if resolver.can_read_page(page, actor):
            raise APIError(HTTP_403_FORBIDDEN, "forbidden", "actor cannot edit this page")
        raise APIError(HTTP_403_FORBIDDEN, "forbidden", "actor cannot access this page")

    if if_version is None or not if_version.strip():
        raise APIError(
            HTTP_428_PRECONDITION_REQUIRED,
            "if_version_required",
            "If-Version header is required",
        )
    try:
        expected_version = int(if_version)
    except ValueError as error:
        raise APIError(
            HTTP_400_BAD_REQUEST,
            "invalid_if_version",
            "If-Version must be an integer",
        ) from error

    current_version = int(page.get("version", 1))
    if expected_version != current_version:
        raise APIError(
            HTTP_409_CONFLICT,
            "version_conflict",
            f"page {page_id} is at version {current_version}; "
            f"received If-Version {expected_version}",
        )

    updates = {
        key: value
        for key, value in payload.model_dump(exclude_unset=True).items()
        if value is not None
    }
    updated = store.update_page(page_id, updates)
    return _page_response(updated.model_dump(mode="python"))


async def api_error_handler(_: Request, error: Exception) -> JSONResponse:
    """Render expected API failures using the common error envelope."""

    if not isinstance(error, APIError):
        return JSONResponse(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": {"code": "internal_error", "message": str(error)}},
        )
    return JSONResponse(
        status_code=error.status_code,
        content={"error": {"code": error.code, "message": error.message}},
        headers=error.headers,
    )


async def validation_error_handler(_: Request, error: Exception) -> JSONResponse:
    """Render request validation failures using the common error envelope."""

    if not isinstance(error, RequestValidationError):
        return JSONResponse(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": {"code": "internal_error", "message": str(error)}},
        )
    return JSONResponse(
        status_code=HTTP_422_UNPROCESSABLE_CONTENT,
        content={"error": {"code": "validation_error", "message": str(error)}},
    )


async def http_exception_handler(_: Request, error: Exception) -> JSONResponse:
    """Render framework-generated HTTP failures using the common error envelope."""

    if not isinstance(error, StarletteHTTPException):
        return JSONResponse(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": {"code": "internal_error", "message": str(error)}},
        )
    detail = error.detail
    if isinstance(detail, Mapping):
        code = str(detail.get("code", "http_error"))
        message = str(detail.get("message", detail))
    else:
        code = "http_error"
        message = str(detail)
    return JSONResponse(
        status_code=error.status_code,
        content={"error": {"code": code, "message": message}},
        headers=error.headers,
    )
