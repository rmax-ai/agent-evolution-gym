"""Run-scoped curriculum materialization tests."""

import sys
from pathlib import Path
from types import ModuleType

import pytest
from domains.confluence.verifiers.page_edit import VERIFIER

from agentgym.core.splits import SplitSpec, load_split
from agentgym.core.task import Task
from agentgym.runner.curriculum import load_verifier, materialize


def test_materialize_stamps_split_and_stages_under_snapshot_root(tmp_path: Path) -> None:
    split = load_split("domains/confluence/splits/train.yaml")
    snapshot_root = tmp_path / "run-1"

    tasks = materialize(
        split,
        "domains.confluence",
        snapshot_root=snapshot_root,
        split_name="train",
    )

    assert len(tasks) == 20
    assert {task.split for task in tasks} == {"train"}
    assert all((snapshot_root / task.initial_snapshot_ref).is_file() for task in tasks)


def test_load_verifier_resolves_domain_relative_module() -> None:
    assert load_verifier("domains.confluence", "verifiers.page_edit") is VERIFIER


def test_materialize_rejects_duplicate_generator_ids_across_modules(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_name = "tests_fake_curriculum"
    scenarios_name = f"{package_name}.scenarios"

    package = ModuleType(package_name)
    package.__path__ = []  # type: ignore[attr-defined]
    scenarios = ModuleType(scenarios_name)
    scenarios.__path__ = []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, package_name, package)
    monkeypatch.setitem(sys.modules, scenarios_name, scenarios)

    class DuplicateGenerator:
        id = "duplicate"

        def __init__(self, snapshot_dir: Path) -> None:
            self.snapshot_dir = snapshot_dir

        def generate(self, seed: int) -> Task:
            return Task(
                id=f"duplicate-{seed}",
                scenario_id="duplicate",
                split="train",
                goal="test",
                actor_id="alice",
                initial_snapshot_ref="snapshots/test.json",
                verifier_id="test",
                metadata={},
            )

    for scenario_name in ("one", "two"):
        module_name = f"{scenarios_name}.{scenario_name}"
        module = ModuleType(module_name)
        module.GENERATOR = DuplicateGenerator(tmp_path)
        monkeypatch.setitem(sys.modules, module_name, module)

    split = SplitSpec(
        entries=[
            {"scenario_id": "one", "count": 1, "seeds": [1]},
            {"scenario_id": "two", "count": 1, "seeds": [2]},
        ]
    )

    with pytest.raises(ValueError, match="scenario generator already registered: duplicate"):
        materialize(
            split,
            package_name,
            snapshot_root=tmp_path,
            split_name="train",
        )
