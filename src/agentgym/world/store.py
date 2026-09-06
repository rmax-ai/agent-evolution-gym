"""In-memory state store for the Confluence simulator."""

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import BaseModel, ConfigDict

from agentgym.world.snapshot import WorldSnapshot


class Page(BaseModel):
    """The mutable representation of a Confluence page."""

    model_config = ConfigDict(extra="allow")

    id: str
    space_id: str
    title: str
    body: str
    version: int = 1
    owner_id: str


PageData = dict[str, Any]
ResourceState = dict[str, Any]


class InMemoryConfluenceStore:
    """Hold Confluence resources and append-only page version history."""

    domain_id = "enterprise-confluence"
    schema_version = "1"

    def __init__(
        self,
        resources: Mapping[str, Any] | None = None,
        *,
        users: Mapping[str, Any] | None = None,
        spaces: Mapping[str, Any] | None = None,
        pages: Mapping[str, Any] | None = None,
        page_versions: Mapping[str, Any] | None = None,
        permissions: Mapping[str, Any] | None = None,
        domain_id: str = domain_id,
        schema_version: str = schema_version,
    ) -> None:
        """Create a store from resource collections or an initial resource mapping."""

        if resources is not None and any(
            value is not None for value in (users, spaces, pages, page_versions, permissions)
        ):
            raise ValueError("pass either resources or individual collections, not both")

        initial = (
            resources
            if resources is not None
            else {
                "users": users or {},
                "spaces": spaces or {},
                "pages": pages or {},
                "page_versions": page_versions or {},
                "permissions": permissions or {},
            }
        )

        self.domain_id = domain_id
        self.schema_version = schema_version
        self.users: dict[str, Any] = self._copy_mapping(initial.get("users", {}))
        self.spaces: dict[str, Any] = self._copy_mapping(initial.get("spaces", {}))
        self.pages: dict[str, PageData] = {
            page_id: self._page_data(page) for page_id, page in initial.get("pages", {}).items()
        }
        self.page_versions: dict[str, list[PageData]] = {
            page_id: [self._page_data(version) for version in versions]
            for page_id, versions in initial.get("page_versions", {}).items()
        }
        self.permissions: dict[str, Any] = self._copy_mapping(initial.get("permissions", {}))

    @property
    def resources(self) -> ResourceState:
        """Return the live resource collections held by this store."""

        return {
            "users": self.users,
            "spaces": self.spaces,
            "pages": self.pages,
            "page_versions": self.page_versions,
            "permissions": self.permissions,
        }

    def snapshot(
        self,
        *,
        snapshot_id: str = "confluence-snapshot",
        timestamp: str | None = None,
    ) -> WorldSnapshot:
        """Return a snapshot detached from all mutable store state.

        ``timestamp`` may be injected for reproducible state identity; when
        omitted a wall-clock ISO timestamp is recorded as provenance.
        """

        return WorldSnapshot(
            id=snapshot_id,
            domain_id=self.domain_id,
            schema_version=self.schema_version,
            timestamp=timestamp or datetime.now(UTC).isoformat(),
            resources=deepcopy(self.resources),
        )

    def restore(self, snapshot: WorldSnapshot) -> None:
        """Replace all resource collections with a deep copy of a snapshot."""

        resources = deepcopy(snapshot.resources)
        self.users = deepcopy(resources.get("users", {}))
        self.spaces = deepcopy(resources.get("spaces", {}))
        self.pages = {
            page_id: self._page_data(page) for page_id, page in resources.get("pages", {}).items()
        }
        self.page_versions = {
            page_id: [self._page_data(version) for version in versions]
            for page_id, versions in resources.get("page_versions", {}).items()
        }
        self.permissions = deepcopy(resources.get("permissions", {}))
        self.domain_id = snapshot.domain_id
        self.schema_version = snapshot.schema_version

    def add_page(self, page: Page | Mapping[str, Any]) -> Page:
        """Add a page and record its initial immutable version."""

        page_data = self._page_data(page)
        page_id = page_data["id"]
        if page_id in self.pages:
            raise ValueError(f"page already exists: {page_id}")

        self.pages[page_id] = deepcopy(page_data)
        self.page_versions[page_id] = []
        self.append_version(page_id)
        return self._page_model(self.pages[page_id])

    create_page = add_page

    def bump_version(self, page_id: str) -> int:
        """Increment a page version and return the new version number."""

        page = self._require_page(page_id)
        page["version"] = int(page.get("version", 1)) + 1
        return page["version"]

    def append_version(
        self,
        page_id: str,
        page: Page | Mapping[str, Any] | None = None,
    ) -> Page:
        """Append a detached page copy to its immutable version history."""

        current = self._page_data(page if page is not None else self._require_page(page_id))
        if current["id"] != page_id:
            raise ValueError(f"page id mismatch: expected {page_id}, got {current['id']}")

        history = self.page_versions.setdefault(page_id, [])
        history.append(deepcopy(current))
        return self._page_model(current)

    def update_page(
        self,
        page_id: str,
        updates: Mapping[str, Any] | Page | None = None,
        *,
        title: str | None = None,
        body: str | None = None,
        expected_version: int | None = None,
    ) -> Page:
        """Conditionally apply page changes under an optimistic-concurrency guard.

        When ``expected_version`` is given and does not match the current page
        version, no change is made and :class:`VersionConflictError` is raised.
        Version bump and history append happen together with the guarded check.
        """

        page = self._require_page(page_id)
        if expected_version is not None:
            current = int(page.get("version", 1))
            if current != expected_version:
                raise VersionConflictError(
                    f"page {page_id} is at version {current}; expected {expected_version}"
                )
        if updates is not None:
            changes = self._page_data(updates) if isinstance(updates, Page) else dict(updates)
            changes.pop("id", None)
            changes.pop("version", None)
            page.update(changes)
        if title is not None:
            page["title"] = title
        if body is not None:
            page["body"] = body

        self.bump_version(page_id)
        self.append_version(page_id)
        return self._page_model(page)

    def get_page_versions(self, page_id: str) -> list[PageData]:
        """Return detached copies of a page's immutable version history."""

        return deepcopy(self.page_versions.get(page_id, []))

    def _require_page(self, page_id: str) -> PageData:
        try:
            return self.pages[page_id]
        except KeyError as error:
            raise KeyError(f"unknown page: {page_id}") from error

    @staticmethod
    def _copy_mapping(value: Any) -> dict[str, Any]:
        return deepcopy(cast(dict[str, Any], value))

    @staticmethod
    def _page_model(page: Page | Mapping[str, Any]) -> Page:
        return Page.model_validate(deepcopy(page))

    @classmethod
    def _page_data(cls, page: Page | Mapping[str, Any]) -> PageData:
        if isinstance(page, Page):
            return page.model_dump(mode="python")
        return cls._page_model(page).model_dump(mode="python")


InMemoryStateStore = InMemoryConfluenceStore
ConfluenceStateStore = InMemoryConfluenceStore


class VersionConflictError(Exception):
    """Raised when a conditional page update targets a stale version."""
