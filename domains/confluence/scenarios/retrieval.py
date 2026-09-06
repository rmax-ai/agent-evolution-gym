"""Retrieval-focused Confluence scenario family (Family A)."""

from __future__ import annotations

from random import Random

from domains.confluence.world.fixtures.builder import build_store

from ._common import (
    ConfluenceScenario,
    page_owner_id,
    page_space_id,
    page_space_name,
    page_title,
    set_page,
    verifier_config,
)

_TARGET_PAGE_IDS = ("page-1", "page-3", "page-4", "page-5")
_CANONICAL_TITLES = {
    "page-1": "Deployment Runbook",
    "page-2": "Deployment Guide",
    "page-3": "Deployment Runbook",
    "page-4": "Payments Architecture",
    "page-5": "Payments Architecture",
    "page-6": "Deployment Change Policy",
}


class RetrievalScenario(ConfluenceScenario):
    """Generate page-location and current-content retrieval tasks."""

    id = "retrieval"

    def generate(self, seed: int):
        rng = Random(seed)
        mode = rng.choice(("space_disambiguation", "similar_title", "latest_guidance"))
        store = build_store(seed, variant="default")

        for page_id, title in _CANONICAL_TITLES.items():
            set_page(store, page_id, title=title)

        target_id = rng.choice(_TARGET_PAGE_IDS)
        title = page_title(store, target_id)
        space_name = page_space_name(store, target_id)
        distractor_ids: list[str] = []

        if mode == "similar_title":
            target_space_id = page_space_id(store, target_id)
            distractor_id = next(
                page_id
                for page_id in store.pages
                if page_id != target_id and page_space_id(store, page_id) != target_space_id
            )
            set_page(store, distractor_id, title=f"{title} Notes")
            distractor_ids.append(distractor_id)

        if "Payments" in title:
            topic = "service-boundary guidance"
            current_fragment = (
                "Payment service boundaries and event flow remain the source of truth."
            )
        else:
            topic = "production rollout guidance"
            current_fragment = "Production deployment guidance for the engineering team."

        set_page(store, target_id, body=current_fragment)
        if mode == "latest_guidance":
            latest_fragment = rng.choice(
                (
                    "Current guidance: stage the rollout through the canary environment.",
                    "Current guidance: confirm the service owner's approval before rollout.",
                    "Current guidance: record rollback readiness before opening the window.",
                )
            )
            store.update_page(
                target_id,
                body=f"{current_fragment}\n\n{latest_fragment}",
            )
            expected_fragment = latest_fragment
            goal = (
                f"Open the “{title}” page in the {space_name} space and read the current {topic}."
            )
        elif mode == "similar_title":
            expected_fragment = current_fragment
            goal = (
                f"Find the “{title}” page in the {space_name} space, rather than the "
                f"similarly named page elsewhere, and read its {topic}."
            )
        else:
            expected_fragment = current_fragment
            goal = f"Locate the “{title}” page in the {space_name} space and read its {topic}."

        config = verifier_config(target_id, expected_fragment)
        config["operation"] = "retrieve"
        return self._task(
            seed=seed,
            store=store,
            goal=goal,
            actor_id=page_owner_id(store, target_id),
            difficulty={
                "space_disambiguation": "easy",
                "similar_title": "medium",
                "latest_guidance": "hard",
            }[mode],
            verifier_config=config,
            metadata={
                "retrieval_mode": mode,
                "distractor_page_ids": distractor_ids,
            },
        )


RetrievalGenerator = RetrievalScenario
GENERATOR = RetrievalScenario()

__all__ = ["GENERATOR", "RetrievalGenerator", "RetrievalScenario"]
