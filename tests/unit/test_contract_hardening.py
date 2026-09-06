"""Regression tests for persisted-contract hardening."""

import hashlib
from pathlib import Path

import pytest
import yaml

from agentgym.core.generation import Generation
from agentgym.core.package import (
    AgentPackage,
    KnowledgeArtifact,
    PackageIntegrityError,
    SkillArtifact,
    ToolPackage,
    _sha256_path,
)
from agentgym.core.task import Task
from agentgym.core.trajectory import TrajectoryEvent, TrajectoryEventType
from agentgym.core.verification import AssertionResult, VerificationResult


def _task(metadata: object) -> Task:
    return Task(
        id="task-1",
        scenario_id="scenario-1",
        split="train",
        goal="Complete the task.",
        actor_id="actor-1",
        initial_snapshot_ref="snapshots/task-1.json",
        verifier_id="verifier-1",
        metadata=metadata,
    )


def _event(payload: object) -> TrajectoryEvent:
    return TrajectoryEvent(
        sequence=1,
        timestamp="2026-09-06T00:00:00+00:00",
        type=TrajectoryEventType.TOOL_RESULT,
        actor="agent",
        payload=payload,
    )


def _package() -> AgentPackage:
    return AgentPackage(
        id="package-1",
        version="0.1",
        generation=0,
        parent_id=None,
        knowledge=[KnowledgeArtifact(path="facts.md", sha256="pending", tags=[])],
        skills=[SkillArtifact(path="skill.md", sha256="pending")],
        tools=ToolPackage(
            root="mcp",
            server_entrypoint="server.py",
            sha256="pending",
            declared_capabilities=[],
        ),
        metadata={"purpose": "hardening"},
    )


def _write_package(package_dir: Path) -> AgentPackage:
    (package_dir / "knowledge").mkdir(parents=True)
    (package_dir / "skills").mkdir()
    (package_dir / "mcp").mkdir()
    (package_dir / "knowledge" / "facts.md").write_text("facts\n", encoding="utf-8")
    (package_dir / "skills" / "skill.md").write_text("skill\n", encoding="utf-8")
    (package_dir / "mcp" / "server.py").write_text("server\n", encoding="utf-8")
    package = _package()
    package.save(package_dir)
    return package


def test_json_safe_persistence_rejects_non_json_values() -> None:
    with pytest.raises(ValueError, match="JSON-safe"):
        AssertionResult(
            id="assertion-1",
            passed=False,
            category="required",
            expected={"value": object()},
            actual=None,
            message="invalid expected value",
        )

    with pytest.raises(ValueError, match="JSON-safe"):
        _task({"unsupported": (1, 2)})

    with pytest.raises(ValueError, match="JSON-safe"):
        _event({"unsupported": {"nested": object()}})

    with pytest.raises(ValueError, match="JSON-safe"):
        VerificationResult(
            passed=False,
            score=0.0,
            assertions=[],
            required_changes_passed=False,
            forbidden_changes_passed=True,
            invariants_passed=True,
            metadata={"unsupported": float("nan")},
        )

    with pytest.raises(ValueError, match="JSON-safe"):
        AgentPackage(
            id="package-1",
            version="0.1",
            generation=0,
            parent_id=None,
            knowledge=[],
            skills=[],
            tools=ToolPackage(
                root="mcp",
                server_entrypoint="server.py",
                sha256="pending",
                declared_capabilities=[],
            ),
            metadata={"unsupported": object()},
        )


def test_json_safe_persistence_accepts_nested_values_and_round_trips() -> None:
    event = _event({"items": ["one", {"enabled": True, "count": 2}]})
    assert TrajectoryEvent.model_validate(event.model_dump(mode="json")) == event

    assertion = AssertionResult(
        id="assertion-1",
        passed=True,
        category="required",
        expected={"items": [1, 2]},
        actual={"items": [1, 2]},
        message="equal",
    )
    assert AssertionResult.model_validate(assertion.model_dump(mode="json")) == assertion


def test_trajectory_event_type_remains_closed() -> None:
    with pytest.raises(ValueError):
        TrajectoryEvent(
            sequence=1,
            timestamp="2026-09-06T00:00:00+00:00",
            type="domain.future_event",
            actor="agent",
            payload={},
        )


def test_generation_freezes_nested_containers_and_still_dumps_as_json() -> None:
    generation = Generation(
        number=1,
        package_id="package-1",
        parent_package_id=None,
        mutation_ids=["mutation-1"],
        train_metrics={"nested": {"values": [1, 2]}},
        validation_metrics={"success_rate": 0.8},
        created_at="2026-09-06T00:00:00+00:00",
    )

    with pytest.raises(TypeError):
        generation.mutation_ids.append("mutation-2")
    with pytest.raises(TypeError):
        generation.train_metrics["nested"]["values"].append(3)
    with pytest.raises(TypeError):
        generation.validation_metrics["success_rate"] = 1.0

    dumped = generation.model_dump(mode="json")
    assert dumped["mutation_ids"] == ["mutation-1"]
    assert dumped["train_metrics"] == {"nested": {"values": [1, 2]}}
    assert Generation.model_validate(dumped) == generation


def test_package_load_rejects_tampered_artifact(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    _write_package(package_dir)
    (package_dir / "knowledge" / "facts.md").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(PackageIntegrityError):
        AgentPackage.load(package_dir)


def test_tool_tree_hash_binds_relative_paths_and_file_boundaries(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root in (first, second):
        (root / "nested").mkdir(parents=True)
    (first / "a.txt").write_bytes(b"ab")
    (first / "nested" / "b.txt").write_bytes(b"cd")
    (second / "renamed.txt").write_bytes(b"ab")
    (second / "nested" / "b.txt").write_bytes(b"cd")

    assert _sha256_path(first) != _sha256_path(second)

    expected = hashlib.sha256()
    for relative_path, contents in (("a.txt", b"ab"), ("nested/b.txt", b"cd")):
        encoded_path = relative_path.encode("utf-8")
        expected.update(len(encoded_path).to_bytes(8, "big"))
        expected.update(encoded_path)
        expected.update(len(contents).to_bytes(8, "big"))
        expected.update(contents)
    assert _sha256_path(first) == expected.hexdigest()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("knowledge_path", "mcp/server.py"),
        ("knowledge_path", "../mcp/server.py"),
        ("tool_root", "."),
        ("tool_root", "skills"),
        ("entrypoint", "../package.yaml"),
    ],
)
def test_package_paths_are_confined_to_declared_layers(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    package_dir = tmp_path / "package"
    _write_package(package_dir)
    manifest_path = package_dir / "package.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))

    if field == "knowledge_path":
        manifest["knowledge"][0]["path"] = value
    elif field == "tool_root":
        manifest["tools"]["root"] = value
    else:
        manifest["tools"]["server_entrypoint"] = value
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    with pytest.raises((ValueError, FileNotFoundError)):
        AgentPackage.load(package_dir)
