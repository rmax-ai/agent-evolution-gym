"""Coverage for the deterministic Confluence scenario families."""

from pathlib import Path

import pytest
from domains.confluence.scenarios.concurrency import ConcurrentEditScenario
from domains.confluence.scenarios.edit_page import EditPageScenario
from domains.confluence.scenarios.permissions import PermissionsScenario
from domains.confluence.scenarios.preservation import PreservationScenario
from domains.confluence.scenarios.retrieval import RetrievalScenario

from agentgym.core.scenario import ScenarioRegistry, read_snapshot

_FAMILIES = (
    ("retrieval", RetrievalScenario, 1000),
    ("edit_page", EditPageScenario, 1100),
    ("preservation", PreservationScenario, 1200),
    ("concurrent_edit", ConcurrentEditScenario, 1300),
    ("permissions", PermissionsScenario, 3000),
)


def test_registry_discovers_one_generator_per_family() -> None:
    registry = ScenarioRegistry.from_modules(
        [
            "domains.confluence.scenarios.retrieval",
            "domains.confluence.scenarios.edit_page",
            "domains.confluence.scenarios.preservation",
            "domains.confluence.scenarios.concurrency",
            "domains.confluence.scenarios.permissions",
        ]
    )

    assert registry.ids == (
        "retrieval",
        "edit_page",
        "preservation",
        "concurrent_edit",
        "permissions",
    )


@pytest.mark.parametrize(("family", "scenario_type", "seed"), _FAMILIES)
def test_family_generation_is_deterministic_and_stages_snapshot(
    family: str,
    scenario_type: type,
    seed: int,
    tmp_path: Path,
) -> None:
    generator = scenario_type(snapshot_dir=tmp_path)

    first = generator.generate(seed)
    first_path = tmp_path / first.initial_snapshot_ref
    first_snapshot = read_snapshot(first_path)
    second = generator.generate(seed)
    second_snapshot = read_snapshot(first_path)

    assert first == second
    assert first.id == f"{family}-{seed:04d}"
    assert first.scenario_id == family
    assert first.split == "train"
    assert first.verifier_id == "confluence-safe-page-edit-v1"
    assert first.metadata["family"] == family
    assert first.metadata["difficulty"] in {"easy", "medium", "hard"}
    assert first.metadata["verifier_config"]["expected_page_ids"]
    assert first_snapshot == second_snapshot
    assert first_snapshot.id == first.id
    assert first_snapshot.domain_id == "enterprise-confluence"


@pytest.mark.parametrize(("_family", "scenario_type", "seed"), _FAMILIES)
def test_task_ids_are_unique_across_seeds(
    _family: str,
    scenario_type: type,
    seed: int,
    tmp_path: Path,
) -> None:
    generator = scenario_type(snapshot_dir=tmp_path)
    tasks = [generator.generate(seed + offset) for offset in range(3)]

    assert len({task.id for task in tasks}) == 3


@pytest.mark.parametrize(("_family", "scenario_type", "seed"), _FAMILIES)
def test_goals_do_not_leak_verifier_details(
    _family: str,
    scenario_type: type,
    seed: int,
    tmp_path: Path,
) -> None:
    task = scenario_type(snapshot_dir=tmp_path).generate(seed)
    goal = task.goal.casefold()

    for forbidden in ("verifier", "expected", "must have version"):
        assert forbidden not in goal


def test_permissions_seed_range_covers_all_modes(tmp_path: Path) -> None:
    generator = PermissionsScenario(snapshot_dir=tmp_path)
    modes = {generator.generate(seed).metadata["mode"] for seed in range(3000, 3005)}

    assert modes == {"denied_read", "denied_write", "allowed"}


def test_concurrency_metadata_describes_unapplied_human_edit(tmp_path: Path) -> None:
    task = ConcurrentEditScenario(snapshot_dir=tmp_path).generate(1300)
    concurrency = task.metadata["concurrency"]
    snapshot = read_snapshot(tmp_path / task.initial_snapshot_ref)
    page_id = concurrency["page_id"]
    page = snapshot.resources["pages"][page_id]

    assert set(concurrency) == {"page_id", "human_edit"}
    assert concurrency["human_edit"]["body"] != page["body"]
    assert page["version"] == 1
    assert "human editor note" not in page["body"].casefold()
