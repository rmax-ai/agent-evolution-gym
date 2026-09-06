"""Unit tests for mutation, generation, diagnosis, and taxonomy contracts."""

import pytest
from pydantic import ValidationError

from agentgym.core.generation import Generation
from agentgym.core.mutation import Mutation, MutationBudget, ToolMutationType
from agentgym.core.rollout import RunStatus
from agentgym.solver.diagnosis import Diagnosis, DiagnosisLayer


def test_run_status_values_match_spec() -> None:
    assert {status.value for status in RunStatus} == {
        "pass",
        "task_fail",
        "partial",
        "agent_error",
        "tool_error",
        "environment_error",
        "verifier_error",
        "timeout",
        "budget_exceeded",
        "policy_violation",
    }


def test_tool_mutation_type_values_match_spec() -> None:
    assert {mutation_type.value for mutation_type in ToolMutationType} == {
        "create_tool",
        "edit_tool",
        "delete_tool",
    }


def test_diagnosis_layer_values_match_spec() -> None:
    assert {layer.value for layer in DiagnosisLayer} == {
        "knowledge",
        "skill",
        "tool",
        "unknown",
    }


def test_mutation_json_round_trip() -> None:
    mutation = Mutation(
        id="mutation-001",
        package_id="baseline",
        layer="tool",
        operation=ToolMutationType.CREATE_TOOL,
        target="safe_patch_page",
        rationale="Repeated page-update sequences need conflict handling.",
        evidence_refs=["rollout-001", "rollout-002"],
        patch="diff --git a/mcp/server.py b/mcp/server.py",
    )

    assert Mutation.model_validate(mutation.model_dump(mode="json")) == mutation


def test_mutation_budget_json_round_trip_preserves_defaults() -> None:
    budget = MutationBudget()

    assert MutationBudget.model_validate(budget.model_dump(mode="json")) == budget
    assert budget.model_dump(mode="json") == {
        "max_files_changed": 3,
        "max_added_lines": 200,
        "max_deleted_lines": 200,
        "allow_tool_creation": True,
        "max_new_tools": 1,
        "max_new_skills": 1,
    }


def test_generation_json_round_trip_and_frozen_model() -> None:
    generation = Generation(
        number=1,
        package_id="package-001",
        parent_package_id="baseline",
        mutation_ids=["mutation-001"],
        train_metrics={"success_rate": 0.8},
        validation_metrics={"success_rate": 0.7},
        created_at="2026-09-06T00:00:00+00:00",
    )

    assert Generation.model_validate(generation.model_dump(mode="json")) == generation
    with pytest.raises(ValidationError, match="frozen"):
        generation.package_id = "package-002"


def test_diagnosis_json_round_trip_uses_typed_layer() -> None:
    diagnosis = Diagnosis(
        id="diagnosis-001",
        task_ids=["task-001", "task-002"],
        summary="The workflow does not preserve concurrent edits.",
        suspected_layer=DiagnosisLayer.TOOL,
        confidence=0.88,
        evidence=["rollout-001 failed with a version conflict."],
        suggested_mutation_type=ToolMutationType.CREATE_TOOL,
    )

    dumped = diagnosis.model_dump(mode="json")

    assert dumped["suspected_layer"] == "tool"
    assert Diagnosis.model_validate(dumped) == diagnosis
