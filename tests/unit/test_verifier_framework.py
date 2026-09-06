"""Unit tests for the domain-agnostic verifier framework."""

from typing import Any

from agentgym.core.task import Task
from agentgym.core.verification import AssertionResult
from agentgym.verifier.base import Verifier, build_result
from agentgym.verifier.predicates import (
    FORBIDDEN,
    INVARIANT,
    REQUIRED,
    assert_equal,
    assert_field_contains,
    assert_field_unchanged,
    assert_no_other_pages_changed,
    assert_unchanged,
    assert_version_bumped_by,
)
from agentgym.verifier.state_diff import compare, preserved, unchanged
from agentgym.world.snapshot import WorldSnapshot


def _resources() -> dict[str, Any]:
    return {
        "pages": {
            "page-1": {
                "id": "page-1",
                "space_id": "space-1",
                "title": "Runbook",
                "body": "Old body",
                "version": 1,
                "owner_id": "alice",
            },
            "page-2": {
                "id": "page-2",
                "space_id": "space-1",
                "title": "Unrelated",
                "body": "Keep me",
                "version": 3,
                "owner_id": "alice",
            },
        },
        "users": {"alice": {"id": "alice"}},
    }


def _snapshots() -> tuple[WorldSnapshot, WorldSnapshot]:
    initial_resources = _resources()
    final_resources = _resources()
    final_resources["pages"]["page-1"]["body"] = "New body"
    final_resources["pages"]["page-1"]["version"] = 2
    del final_resources["pages"]["page-2"]
    final_resources["pages"]["page-3"] = {
        "id": "page-3",
        "space_id": "space-2",
        "title": "Created",
        "body": "New page",
        "version": 1,
        "owner_id": "alice",
    }
    initial = WorldSnapshot(
        id="initial",
        domain_id="test",
        schema_version="1",
        timestamp="2026-09-06T00:00:00+00:00",
        resources=initial_resources,
    )
    final = initial.model_copy(update={"id": "final", "resources": final_resources})
    return initial, final


def test_compare_detects_page_update_create_delete_and_version_delta() -> None:
    initial, final = _snapshots()

    diff = compare(initial.resources, final.resources)

    assert diff["pages"]["created"] == ["page-3"]
    assert diff["pages"]["deleted"] == ["page-2"]
    assert diff["pages"]["updated"] == ["page-1"]
    assert diff["pages"]["changes"]["page-1"] == {
        "changed_fields": {
            "body": {"old": "Old body", "new": "New body"},
            "version": {"old": 1, "new": 2},
        },
        "version_delta": 1,
    }


def test_unchanged_and_preserved_have_positive_and_negative_cases() -> None:
    initial, final = _snapshots()

    assert unchanged(initial.resources, initial.resources, "page-2", "pages")
    assert not unchanged(initial.resources, final.resources, "page-2", "pages")
    assert not unchanged(initial.resources, final.resources, "missing", "pages")

    assert preserved("Old", "Old body and more")
    assert preserved({"body": "New"}, final.resources["pages"]["page-1"])
    assert not preserved({"body": "Not present"}, final.resources["pages"]["page-1"])
    assert preserved(initial.resources, initial.resources, "page-2", "pages")
    assert not preserved(initial.resources, final.resources, "page-2", "pages")


def test_predicates_produce_expected_categories_and_pass_flags() -> None:
    initial, final = _snapshots()

    assertions = [
        assert_equal("title", "Runbook", initial.resources["pages"]["page-1"]["title"]),
        assert_field_contains(final.resources, "page-1", "body", "New body"),
        assert_version_bumped_by(initial.resources, final.resources, "page-1"),
        assert_no_other_pages_changed(
            initial.resources, final.resources, {"page-1", "page-2", "page-3"}
        ),
        assert_no_other_pages_changed(initial.resources, final.resources, {"page-1"}),
        assert_field_unchanged(initial.resources, final.resources, "page-1", "title"),
        assert_unchanged(initial.resources, final.resources, "page-2"),
    ]

    assert [assertion.category for assertion in assertions] == [
        REQUIRED,
        REQUIRED,
        REQUIRED,
        FORBIDDEN,
        FORBIDDEN,
        INVARIANT,
        INVARIANT,
    ]
    assert [assertion.passed for assertion in assertions] == [
        True,
        True,
        True,
        True,
        False,
        True,
        False,
    ]


def test_build_result_aggregates_mixed_outcomes_by_category() -> None:
    assertions = [
        AssertionResult(
            id="required-pass",
            passed=True,
            category=REQUIRED,
            expected=1,
            actual=1,
            message="ok",
        ),
        AssertionResult(
            id="required-fail",
            passed=False,
            category=REQUIRED,
            expected=2,
            actual=1,
            message="wrong",
        ),
        AssertionResult(
            id="forbidden-pass",
            passed=True,
            category=FORBIDDEN,
            expected=[],
            actual=[],
            message="ok",
        ),
        AssertionResult(
            id="invariant-pass",
            passed=True,
            category=INVARIANT,
            expected="same",
            actual="same",
            message="ok",
        ),
    ]

    result = build_result(assertions, metadata={"source": "unit-test"})

    assert not result.passed
    assert result.score == 0.75
    assert not result.required_changes_passed
    assert result.forbidden_changes_passed
    assert result.invariants_passed
    assert result.metadata == {"source": "unit-test"}


async def test_wrong_oracle_fails_from_world_state_even_when_trajectory_claims_success() -> None:
    initial, final = _snapshots()

    class WrongOracle:
        async def verify(
            self,
            task: Task,
            initial_snapshot: WorldSnapshot,
            final_snapshot: WorldSnapshot,
            trajectory: object,
        ):
            del task, initial_snapshot, trajectory
            return build_result(
                [
                    assert_field_contains(
                        final_snapshot.resources, "page-1", "body", "agent said done"
                    )
                ]
            )

    verifier: Verifier = WrongOracle()
    result = await verifier.verify(
        Task(
            id="task-1",
            scenario_id="test",
            split="train",
            goal="Update page",
            actor_id="alice",
            initial_snapshot_ref="initial",
            verifier_id="test",
            metadata={},
        ),
        initial,
        final,
        {"final_answer": "success"},
    )

    assert not result.passed
    assert not result.assertions[0].passed
