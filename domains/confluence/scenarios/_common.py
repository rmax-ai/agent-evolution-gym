"""Shared deterministic helpers for Confluence scenario families."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, ClassVar

from agentgym.core.scenario import write_snapshot
from agentgym.core.task import Task
from agentgym.world.store import InMemoryConfluenceStore

DEFAULT_SNAPSHOT_DIR = Path("experiments/.snapshots")
VERIFIER_ID = "confluence-safe-page-edit-v1"
SNAPSHOT_TIMESTAMP = "2026-09-06T00:00:00+00:00"


class ConfluenceScenario:
    """Base implementation for a seeded, snapshot-producing scenario family."""

    id: ClassVar[str]

    def __init__(self, snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR) -> None:
        self.snapshot_dir = Path(snapshot_dir)

    def _task(
        self,
        *,
        seed: int,
        store: InMemoryConfluenceStore,
        goal: str,
        actor_id: str,
        difficulty: str,
        verifier_config: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
    ) -> Task:
        """Stage ``store`` and return the common task contract."""

        task_id = f"{self.id}-{seed:04d}"
        snapshot_ref = f"snapshots/{task_id}.json"
        snapshot_path = self.snapshot_dir / snapshot_ref
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        write_snapshot(
            store.snapshot(snapshot_id=task_id, timestamp=SNAPSHOT_TIMESTAMP),
            snapshot_path,
        )

        task_metadata: dict[str, Any] = {
            "family": self.id,
            "difficulty": difficulty,
            "verifier_config": dict(verifier_config),
        }
        if metadata is not None:
            task_metadata.update(metadata)

        return Task(
            id=task_id,
            scenario_id=self.id,
            split="train",
            goal=goal,
            actor_id=actor_id,
            initial_snapshot_ref=snapshot_ref,
            verifier_id=VERIFIER_ID,
            metadata=task_metadata,
        )


def set_page(
    store: InMemoryConfluenceStore,
    page_id: str,
    *,
    title: str | None = None,
    body: str | None = None,
) -> None:
    """Change fixture content while keeping the initial version history coherent."""

    page = store.pages[page_id]
    changes: dict[str, str] = {}
    if title is not None:
        changes["title"] = title
        page["title"] = title
    if body is not None:
        changes["body"] = body
        page["body"] = body

    current_version = page.get("version", 1)
    for version in store.page_versions.get(page_id, []):
        if version.get("version", 1) == current_version:
            version.update(changes)


def sectioned_body(*sections: tuple[str, str]) -> str:
    """Render a compact Markdown page body with stable section boundaries."""

    return "\n\n".join(f"## {heading}\n{content}" for heading, content in sections)


def replace_section(body: str, heading: str, content: str) -> str:
    """Replace one Markdown section while leaving every other section byte-stable."""

    marker = f"## {heading}\n"
    sections = body.split("\n\n")
    for index, section in enumerate(sections):
        if section.startswith(marker):
            sections[index] = f"{marker}{content}"
            return "\n\n".join(sections)
    raise ValueError(f"section {heading!r} not found")


def append_section(body: str, heading: str, content: str) -> str:
    """Append one complete Markdown section to a sectioned body."""

    return f"{body}\n\n## {heading}\n{content}"


def append_to_section(body: str, heading: str, text: str) -> str:
    """Append a note to an existing section without rewriting neighboring sections."""

    marker = f"## {heading}\n"
    sections = body.split("\n\n")
    for index, section in enumerate(sections):
        if section.startswith(marker):
            sections[index] = f"{section}\n{text}"
            return "\n\n".join(sections)
    raise ValueError(f"section {heading!r} not found")


def section_texts(body: str, *, excluding: str | None = None) -> list[str]:
    """Return complete section texts, optionally excluding one named section."""

    sections = body.split("\n\n")
    if excluding is None:
        return sections
    marker = f"## {excluding}\n"
    return [section for section in sections if not section.startswith(marker)]


def page_space_id(store: InMemoryConfluenceStore, page_id: str) -> str:
    """Return a page's space id as a validated string."""

    value = store.pages[page_id].get("space_id")
    if not isinstance(value, str):
        raise TypeError(f"page {page_id!r} has a non-string space id")
    return value


def page_space_name(store: InMemoryConfluenceStore, page_id: str) -> str:
    """Return the display name of a page's space."""

    space_id = page_space_id(store, page_id)
    space = store.spaces[space_id]
    name = space.get("name", space_id)
    return str(name)


def page_owner_id(store: InMemoryConfluenceStore, page_id: str) -> str:
    """Return the actor that owns a fixture page."""

    owner_id = store.pages[page_id].get("owner_id")
    if not isinstance(owner_id, str):
        raise TypeError(f"page {page_id!r} has a non-string owner id")
    return owner_id


def page_title(store: InMemoryConfluenceStore, page_id: str) -> str:
    """Return a page title as text for actor-facing goals."""

    return str(store.pages[page_id].get("title", page_id))


def verifier_config(
    page_id: str,
    fragment: str | None,
    *,
    expected_final_body: str | None = None,
    preserved_body_fragments: Sequence[str] | None = None,
    expected_response: str | None = None,
) -> dict[str, Any]:
    """Build the small page-oriented configuration consumed by the verifier."""

    fragments = {} if fragment is None else {page_id: fragment}
    config: dict[str, Any] = {
        "expected_page_ids": [page_id],
        "expected_content_fragments": fragments,
    }
    if expected_final_body is not None:
        config["expected_final_body"] = expected_final_body
    if preserved_body_fragments is not None:
        config["preserved_body_fragments"] = list(preserved_body_fragments)
    if expected_response is not None:
        config["expected_response"] = expected_response
    return config


__all__ = [
    "DEFAULT_SNAPSHOT_DIR",
    "SNAPSHOT_TIMESTAMP",
    "VERIFIER_ID",
    "ConfluenceScenario",
    "append_section",
    "append_to_section",
    "page_owner_id",
    "page_space_id",
    "page_space_name",
    "page_title",
    "replace_section",
    "section_texts",
    "sectioned_body",
    "set_page",
    "verifier_config",
]
