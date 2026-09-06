"""Optimistic-concurrency scenario family (Family D)."""

from __future__ import annotations

from random import Random

from domains.confluence.world.fixtures.builder import build_store

from ._common import (
    ConfluenceScenario,
    append_to_section,
    page_owner_id,
    page_space_name,
    page_title,
    replace_section,
    section_texts,
    sectioned_body,
    set_page,
    verifier_config,
)

_TARGET_PAGE_IDS = ("page-1", "page-2", "page-4", "page-5")
_CANONICAL_TITLES = {
    "page-1": "Deployment Runbook",
    "page-2": "Deployment Guide",
    "page-4": "Payments Architecture",
    "page-5": "Payments Architecture",
}


class ConcurrentEditScenario(ConfluenceScenario):
    """Generate tasks where a runner-injected human edit must survive a retry."""

    id = "concurrent_edit"

    def generate(self, seed: int):
        rng = Random(seed)
        change_kind = rng.choice(("approval", "rollback", "ownership"))

        # The concurrent_edit fixture variant already applies a human update.  The
        # runner story injects that update after the first read, so this family
        # deliberately starts from the ordinary, untouched fixture.
        store = build_store(seed, variant="default")
        target_id = rng.choice(_TARGET_PAGE_IDS)
        set_page(store, target_id, title=_CANONICAL_TITLES[target_id])

        body = sectioned_body(
            ("Overview", "The team maintains a controlled release process."),
            ("Deployment", "Production rollout follows the release checklist."),
            ("Rollback", "Rollback starts after the incident lead confirms the trigger."),
            ("Ownership", "The service owner reviews changes before publication."),
        )
        set_page(store, target_id, body=body)

        if change_kind == "approval":
            section = "Deployment"
            requested_fragment = "Production rollout requires service-owner approval."
            human_fragment = (
                "Human editor note: the maintenance window is confirmed with Operations."
            )
            human_section = "Overview"
        elif change_kind == "rollback":
            section = "Rollback"
            requested_fragment = "Rollback starts after the incident lead confirms the smoke test."
            human_fragment = "Human editor note: rollback validation now includes a smoke test."
            human_section = "Deployment"
        else:
            section = "Ownership"
            requested_fragment = "The platform team remains the service owner for publication."
            human_fragment = (
                "Human editor note: the service owner is reviewing the release calendar."
            )
            human_section = "Overview"

        # The expected order is part of the verifier contract: first the runner
        # applies the human note to ``human_section`` with a CAS update; then the
        # agent refreshes and replaces ``section`` with its requested content in a
        # second CAS update.  The human and agent sections are intentionally
        # different so an agent that rewrites the stale body loses observable work.
        human_body = append_to_section(body, human_section, human_fragment)
        expected_body = replace_section(human_body, section, requested_fragment)
        goal = (
            f"Update the “{section}” section of the {page_title(store, target_id)} page in "
            f"the {page_space_name(store, target_id)} space so it says: "
            f"“{requested_fragment}” Keep any note added by another editor after you first "
            "read the page, and apply only this focused change."
        )
        config = verifier_config(
            target_id,
            requested_fragment,
            expected_final_body=expected_body,
            preserved_body_fragments=section_texts(expected_body, excluding=section),
        )
        config["preserve_concurrent_fragment"] = human_fragment
        return self._task(
            seed=seed,
            store=store,
            goal=goal,
            actor_id=page_owner_id(store, target_id),
            difficulty=rng.choice(("medium", "hard")),
            verifier_config=config,
            metadata={
                "change_kind": change_kind,
                "target_section": section,
                "concurrency": {
                    "page_id": target_id,
                    "human_edit": {
                        "section": human_section,
                        "text": human_fragment,
                        "body": human_body,
                    },
                },
            },
        )


ConcurrencyScenario = ConcurrentEditScenario
ConcurrencyGenerator = ConcurrentEditScenario
GENERATOR = ConcurrentEditScenario()

__all__ = [
    "GENERATOR",
    "ConcurrencyGenerator",
    "ConcurrencyScenario",
    "ConcurrentEditScenario",
]
