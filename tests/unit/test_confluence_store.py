"""Unit tests for the in-memory Confluence state store."""

from agentgym.world.store import InMemoryConfluenceStore


def _page() -> dict[str, object]:
    return {
        "id": "page-1",
        "space_id": "space-1",
        "title": "Deployment",
        "body": "Draft",
        "version": 1,
        "owner_id": "user-1",
    }


def test_snapshot_deep_copies_all_resource_collections() -> None:
    store = InMemoryConfluenceStore(
        users={"user-1": {"name": "Max"}},
        spaces={"space-1": {"name": "Engineering"}},
        pages={"page-1": _page()},
        page_versions={"page-1": [_page()]},
        permissions={"space-1": ["user-1"]},
    )

    snapshot = store.snapshot()
    store.pages["page-1"]["body"] = "Changed"
    store.page_versions["page-1"][0]["body"] = "Changed history"
    store.permissions["space-1"].append("user-2")

    assert snapshot.resources["pages"]["page-1"]["body"] == "Draft"
    assert snapshot.resources["page_versions"]["page-1"][0]["body"] == "Draft"
    assert snapshot.resources["permissions"]["space-1"] == ["user-1"]


def test_page_updates_increment_version_and_append_detached_history() -> None:
    store = InMemoryConfluenceStore()
    store.add_page(_page())

    updated = store.update_page("page-1", body="Published")

    assert updated.version == 2
    assert store.pages["page-1"]["version"] == 2
    assert [version["version"] for version in store.page_versions["page-1"]] == [1, 2]
    assert store.page_versions["page-1"][-1]["body"] == "Published"

    history = store.get_page_versions("page-1")
    history[-1]["body"] = "Mutated outside the store"
    assert store.page_versions["page-1"][-1]["body"] == "Published"


def test_restore_replaces_state_without_aliasing_snapshot() -> None:
    original = InMemoryConfluenceStore(pages={"page-1": _page()})
    snapshot = original.snapshot()
    restored = InMemoryConfluenceStore()

    restored.restore(snapshot)
    restored.pages["page-1"]["body"] = "Changed after restore"

    assert snapshot.resources["pages"]["page-1"]["body"] == "Draft"
    assert restored.pages["page-1"]["body"] == "Changed after restore"
