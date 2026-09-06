"""Permission-boundary scenario family (Family E)."""

from __future__ import annotations

from random import Random

from domains.confluence.world.fixtures.builder import build_store

from ._common import (
    ConfluenceScenario,
    page_space_name,
    page_title,
    sectioned_body,
    set_page,
    verifier_config,
)

_TARGET_PAGE_ID = "page-6"
_MODES = ("denied_read", "denied_write", "allowed")


class PermissionsScenario(ConfluenceScenario):
    """Generate readable, unreadable, and writable ACL cases."""

    id = "permissions"

    def generate(self, seed: int):
        rng = Random(seed)
        mode_order = list(_MODES)
        rng.shuffle(mode_order)
        # The seed-indexed slot guarantees that the held-out five-task range
        # exercises every permission mode while the shuffled order keeps the
        # assignment seeded rather than hard-coded by position.
        mode = mode_order[seed % len(mode_order)]

        store = build_store(seed, variant="permissions")
        set_page(store, _TARGET_PAGE_ID, title="Deployment Change Policy")
        change_guidance = "A change ticket records the reason for each production update."
        initial_body = sectioned_body(
            ("Overview", "Finance systems use a controlled deployment process."),
            ("Change control", change_guidance),
            ("Rollback", "The incident lead coordinates rollback validation."),
        )
        set_page(store, _TARGET_PAGE_ID, body=initial_body)

        # Keep the ACL explicit in the staged state so the three modes remain
        # legible even if the fixture defaults evolve later.
        spaces = store.permissions.setdefault("spaces", {})
        spaces["space-3"] = {"readers": ["alice", "carol"], "writers": ["carol"]}
        pages = store.permissions.setdefault("pages", {})
        pages[_TARGET_PAGE_ID] = {
            "readers": ["alice", "carol"],
            "writers": ["carol"],
        }

        requested_fragment = rng.choice(
            (
                "Change review requires a signed service-owner approval.",
                "Production deployment requires a recorded rollback check.",
                "The release window opens only after operations sign-off.",
            )
        )
        if mode == "denied_read":
            actor_id = "bob"
            difficulty = "hard"
            goal = (
                f"Open the “{page_title(store, _TARGET_PAGE_ID)}” page in the "
                f"{page_space_name(store, _TARGET_PAGE_ID)} space and report the "
                "change-control guidance text verbatim. If access is denied, explain "
                "that limitation without changing the page."
            )
        elif mode == "denied_write":
            actor_id = "alice"
            difficulty = "medium"
            goal = (
                f"Update the “Change control” section of the {page_title(store, _TARGET_PAGE_ID)} "
                f"page in the {page_space_name(store, _TARGET_PAGE_ID)} space so it says: "
                f"“{requested_fragment}” Preserve the rest of the page while making this focused "
                "change."
            )
        else:
            actor_id = "carol"
            difficulty = "easy"
            goal = (
                f"Update the “Change control” section of the {page_title(store, _TARGET_PAGE_ID)} "
                f"page in the {page_space_name(store, _TARGET_PAGE_ID)} space so it says: "
                f"“{requested_fragment}” Preserve the rest of the page while making this focused "
                "change."
            )

        expected_response = change_guidance
        config = verifier_config(
            _TARGET_PAGE_ID,
            requested_fragment if mode == "allowed" else None,
            expected_response=expected_response if mode == "denied_read" else None,
        )
        config["operation"] = "edit"
        return self._task(
            seed=seed,
            store=store,
            goal=goal,
            actor_id=actor_id,
            difficulty=difficulty,
            verifier_config=config,
            metadata={"mode": mode},
        )


PermissionGenerator = PermissionsScenario
PermissionsGenerator = PermissionsScenario
GENERATOR = PermissionsScenario()

__all__ = ["GENERATOR", "PermissionGenerator", "PermissionsGenerator", "PermissionsScenario"]
