"""Unit tests for the initial persisted core and world contracts."""

from pathlib import Path
from typing import Any

from agentgym.core.domain import DomainSpec
from agentgym.core.task import Task
from agentgym.world.capabilities import Capability
from agentgym.world.snapshot import WorldSnapshot


def test_domain_spec_loads_confluence_yaml_shape(tmp_path: Path) -> None:
    domain_path = tmp_path / "domain.yaml"
    domain_path.write_text(
        """
id: enterprise-confluence
version: "0.1"
description: >
  Stateful simulated knowledge-management environment.
world_provider: process
scenario_modules:
  - scenarios.edit_page
  - scenarios.concurrent_edit
  - scenarios.permissions
verifier_modules:
  - verifiers.page_edit
train_split: splits/train.yaml
validation_split: splits/validation.yaml
test_split: splits/test.yaml
capabilities:
  - confluence.pages.read
  - confluence.pages.write
  - confluence.search
""".lstrip(),
        encoding="utf-8",
    )

    domain = DomainSpec.from_yaml(domain_path)

    assert domain.id == "enterprise-confluence"
    assert domain.version == "0.1"
    assert domain.world_provider == "process"
    assert domain.scenario_modules == [
        "scenarios.edit_page",
        "scenarios.concurrent_edit",
        "scenarios.permissions",
    ]
    assert domain.verifier_modules == ["verifiers.page_edit"]
    assert domain.train_split == "splits/train.yaml"
    assert domain.validation_split == "splits/validation.yaml"
    assert domain.test_split == "splits/test.yaml"
    assert domain.capabilities == [
        "confluence.pages.read",
        "confluence.pages.write",
        "confluence.search",
    ]


def test_domain_spec_json_round_trip() -> None:
    domain = DomainSpec(
        id="enterprise-confluence",
        version="0.1",
        description="Stateful simulated knowledge-management environment.",
        world_provider="process",
        scenario_modules=["scenarios.edit_page"],
        verifier_modules=["verifiers.page_edit"],
        train_split="splits/train.yaml",
        validation_split="splits/validation.yaml",
        test_split="splits/test.yaml",
        capabilities=["confluence.pages.read"],
    )

    assert DomainSpec.model_validate(domain.model_dump(mode="json")) == domain


def test_task_json_round_trip_preserves_json_safe_metadata() -> None:
    metadata: dict[str, Any] = {
        "difficulty": "medium",
        "seed": 42,
        "flags": ["preserve-unrelated-content", "concurrent-edit"],
        "expected": {"page_id": "page-42", "version": 7},
    }
    task = Task(
        id="page-edit-0042",
        scenario_id="concurrent-page-edit",
        split="train",
        goal="Update the Deployment section while preserving unrelated content.",
        actor_id="employee-max",
        initial_snapshot_ref="snapshots/page-edit-0042.json",
        verifier_id="confluence-safe-page-edit-v1",
        metadata=metadata,
    )

    dumped = task.model_dump(mode="json")

    assert dumped["metadata"] == metadata
    assert Task.model_validate(dumped) == task


def test_world_snapshot_json_round_trip() -> None:
    snapshot = WorldSnapshot(
        id="snapshot-page-edit-0042",
        domain_id="enterprise-confluence",
        schema_version="1",
        timestamp="2026-09-06T00:00:00+00:00",
        resources={
            "pages": {},
            "page_versions": {},
            "users": {},
            "permissions": {},
        },
    )

    assert WorldSnapshot.model_validate(snapshot.model_dump(mode="json")) == snapshot


def test_capability_json_round_trip() -> None:
    capability = Capability(
        id="confluence.pages.read",
        system="confluence",
        operation="pages.read",
    )

    assert Capability.model_validate(capability.model_dump(mode="json")) == capability
