"""Basic page-edit scenario family (Family B)."""

from __future__ import annotations

from random import Random

from domains.confluence.world.fixtures.builder import build_store

from ._common import (
    ConfluenceScenario,
    append_section,
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


class EditPageScenario(ConfluenceScenario):
    """Generate focused section and structured-content edit tasks."""

    id = "edit_page"

    def generate(self, seed: int):
        rng = Random(seed)
        edit_kind = rng.choice(
            ("replace_obsolete", "update_paragraph", "add_section", "append_checklist")
        )
        store = build_store(seed, variant="default")
        target_id = rng.choice(_TARGET_PAGE_IDS)
        set_page(store, target_id, title=_CANONICAL_TITLES[target_id])

        if "Payments" in page_title(store, target_id):
            overview = "The payment platform coordinates authorization and settlement."
            deployment = "Production changes follow the platform release window."
            rollback = "Rollback begins after the incident lead confirms the trigger."
        else:
            overview = "The service release is coordinated by the engineering team."
            deployment = "Production changes follow the release checklist."
            rollback = "Rollback begins after the on-call lead confirms the trigger."

        body = sectioned_body(
            ("Overview", overview),
            ("Deployment", deployment),
            ("Rollback", rollback),
            ("Ownership", "The current owner is Release Engineering."),
        )
        set_page(store, target_id, body=body)

        if edit_kind == "replace_obsolete":
            section = "Ownership"
            fragment = "The current owner is Platform Reliability."
            expected_body = replace_section(body, section, fragment)
            goal = (
                f"Update the “{section}” section of the {page_title(store, target_id)} "
                f"in the {page_space_name(store, target_id)} space so the current owner "
                "is Platform Reliability."
            )
            difficulty = "easy"
        elif edit_kind == "update_paragraph":
            section = "Deployment"
            fragment = "Production rollout requires service-owner approval after QA sign-off."
            expected_body = replace_section(body, section, fragment)
            goal = (
                f"Update the “{section}” section of the {page_title(store, target_id)} "
                f"in the {page_space_name(store, target_id)} space to say that "
                "production rollout requires service-owner approval after QA sign-off."
            )
            difficulty = "medium"
        elif edit_kind == "add_section":
            section = "Approvals"
            section_content = "Production rollout requires service-owner approval."
            fragment = f"## {section}\n{section_content}"
            expected_body = append_section(body, section, section_content)
            goal = (
                f"Add an “{section}” section to the {page_title(store, target_id)} page in "
                f"the {page_space_name(store, target_id)} space stating that production "
                "rollout requires service-owner approval."
            )
            difficulty = "medium"
        else:
            section = "Change control"
            section_content = "- Change ticket required\n- Service-owner approval required"
            fragment = f"## {section}\n{section_content}"
            expected_body = append_section(body, section, section_content)
            goal = (
                f"Append a “{section}” checklist to the {page_title(store, target_id)} page "
                f"in the {page_space_name(store, target_id)} space with a required change "
                "ticket and service-owner approval."
            )
            difficulty = "hard"

        config = verifier_config(
            target_id,
            fragment,
            expected_final_body=expected_body,
            preserved_body_fragments=section_texts(expected_body, excluding=section)
            if section in {"Ownership", "Deployment"}
            else section_texts(body),
        )
        config["operation"] = "edit"
        return self._task(
            seed=seed,
            store=store,
            goal=goal,
            actor_id=page_owner_id(store, target_id),
            difficulty=difficulty,
            verifier_config=config,
            metadata={
                "edit_kind": edit_kind,
                "target_section": section,
            },
        )


EditPageGenerator = EditPageScenario
GENERATOR = EditPageScenario()

__all__ = ["GENERATOR", "EditPageGenerator", "EditPageScenario"]
