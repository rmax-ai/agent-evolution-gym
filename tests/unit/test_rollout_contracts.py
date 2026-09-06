"""Unit tests for trajectory, verification, and rollout contracts."""

import json
from datetime import date
from decimal import Decimal

from agentgym.core.rollout import Rollout, RolloutMetrics
from agentgym.core.trajectory import TrajectoryEvent, TrajectoryEventType
from agentgym.core.verification import AssertionResult, VerificationResult


def test_trajectory_event_taxonomy_matches_spec() -> None:
    expected_types = {
        "run.started",
        "agent.started",
        "model.request",
        "model.response",
        "tool.call",
        "tool.result",
        "tool.error",
        "world.api.request",
        "world.api.response",
        "artifact.created",
        "agent.error",
        "agent.completed",
        "verification.assertion",
        "verification.completed",
        "run.completed",
    }

    assert {event_type.value for event_type in TrajectoryEventType} == expected_types


def test_trajectory_event_json_round_trip() -> None:
    event = TrajectoryEvent(
        sequence=3,
        timestamp="2026-09-06T00:00:00+00:00",
        type=TrajectoryEventType.TOOL_RESULT,
        actor="agent",
        payload={"tool": "read_page", "status": 200},
    )

    dumped = event.model_dump(mode="json")

    assert dumped["type"] == "tool.result"
    assert TrajectoryEvent.model_validate(dumped) == event


def test_verification_result_json_round_trip_preserves_categories() -> None:
    result = VerificationResult(
        passed=False,
        score=0.5,
        assertions=[
            AssertionResult(
                id="required-target-updated",
                passed=True,
                category="required",
                expected={"version": 2},
                actual={"version": 2},
                message="The target page was updated.",
            ),
            AssertionResult(
                id="forbidden-unrelated-change",
                passed=False,
                category="forbidden",
                expected=None,
                actual={"changed": True},
                message="An unrelated page changed.",
            ),
        ],
        required_changes_passed=True,
        forbidden_changes_passed=False,
        invariants_passed=True,
        metadata={"verifier": "safe-page-edit-v1"},
    )

    dumped = result.model_dump(mode="json")

    assert dumped["required_changes_passed"] is True
    assert dumped["forbidden_changes_passed"] is False
    assert dumped["invariants_passed"] is True
    assert VerificationResult.model_validate(dumped) == result


def test_assertion_observed_values_are_json_safe_when_persisted() -> None:
    assertion = AssertionResult(
        id="observed-value",
        passed=True,
        category="invariant",
        expected={"observed_on": date(2026, 9, 6), "cost": Decimal("1.25")},
        actual=object(),
        message="The observed value is recorded.",
    )

    dumped = assertion.model_dump(mode="json")

    assert dumped["expected"] == {"observed_on": "2026-09-06", "cost": "1.25"}
    assert isinstance(dumped["actual"], str)
    json.dumps(dumped)


def test_rollout_json_round_trip_includes_typed_verification_and_metrics() -> None:
    rollout = Rollout(
        id="rollout-0042",
        task_id="page-edit-0042",
        package_id="baseline",
        initial_state_ref="snapshots/initial.json",
        final_state_ref="snapshots/final.json",
        trajectory_ref="runs/rollout-0042/trajectory.jsonl",
        verification=VerificationResult(
            passed=True,
            score=1.0,
            assertions=[],
            required_changes_passed=True,
            forbidden_changes_passed=True,
            invariants_passed=True,
            metadata={},
        ),
        metrics=RolloutMetrics(
            wall_seconds=2.5,
            model_turns=4,
            tool_calls=3,
            input_tokens=120,
            output_tokens=80,
            estimated_cost=0.0042,
        ),
    )

    dumped = rollout.model_dump(mode="json")

    assert dumped["verification"]["passed"] is True
    assert dumped["metrics"]["tool_calls"] == 3
    assert Rollout.model_validate(dumped) == rollout
