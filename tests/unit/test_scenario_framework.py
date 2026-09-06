"""Tests for the scenario framework: splits, snapshot staging, registry."""

import json
from pathlib import Path

import pytest
from domains.confluence.world.fixtures.builder import build_store

from agentgym.core.scenario import (
    ScenarioRegistry,
    read_snapshot,
    write_snapshot,
    write_snapshot_async,
)
from agentgym.core.splits import SplitEntry, SplitSpec, load_split


class _FakeGenerator:
    id = "fake"

    def __init__(self, scenario_id: str = "fake") -> None:
        self.id = scenario_id

    def generate(self, seed: int):
        from agentgym.core.task import Task

        return Task(
            id=f"{self.id}-{seed:04d}",
            scenario_id=self.id,
            split="train",
            goal=f"Fake goal for {self.id} seed {seed}",
            actor_id="alice",
            initial_snapshot_ref=f"snapshots/{self.id}-{seed:04d}.json",
            verifier_id="fake-verifier-v1",
            metadata={"seed": seed},
        )


def test_split_manifests_load_and_expand() -> None:
    train = load_split("domains/confluence/splits/train.yaml")
    validation = load_split("domains/confluence/splits/validation.yaml")
    test = load_split("domains/confluence/splits/test.yaml")

    assert train.total_count == 20
    assert validation.total_count == 12
    assert test.total_count == 5

    seeds = list(train.iter_seeded())
    assert seeds[0] == ("retrieval", 1000)
    assert seeds[4] == ("retrieval", 1004)
    assert ("concurrent_edit", 1304) in seeds
    assert len(seeds) == 20

    test_ids = set(test.scenario_ids)
    assert test_ids == {"permissions"}
    # Held-out family: permissions appears in test only (SPEC §3.6 structure split).
    assert "permissions" not in set(train.scenario_ids) | set(validation.scenario_ids)
    assert list(test.iter_seeded())[-1] == ("permissions", 3004)


def test_split_entry_seed_validation() -> None:
    with pytest.raises(ValueError):
        SplitEntry(scenario_id="x", count=3)  # no seed source
    with pytest.raises(ValueError):
        SplitEntry(scenario_id="x", count=3, seeds=[1, 2, 2])  # duplicates
    with pytest.raises(ValueError):
        SplitEntry(scenario_id="x", count=5, seed_range=[10, 12])  # too few seeds
    assert SplitEntry(scenario_id="x", count=3, seed_range=[10, 12]).resolved_seeds == (10, 11, 12)


def test_split_spec_supports_entries_mapping(tmp_path: Path) -> None:
    manifest = tmp_path / "split.yaml"
    manifest.write_text(
        "entries:\n  - scenario_id: a\n    count: 2\n    seeds: [1, 2]\n",
        encoding="utf-8",
    )
    spec = SplitSpec.from_yaml(manifest)
    assert spec.total_count == 2
    assert spec.for_scenario("a")[0].resolved_seeds == (1, 2)


def test_write_and_read_snapshot_roundtrip(tmp_path: Path) -> None:
    store = build_store(seed=3)
    expected = store.snapshot(snapshot_id="snap-1", timestamp="2026-09-06T00:00:00+00:00")

    path = write_snapshot(expected, tmp_path / "initial.json")
    loaded = read_snapshot(path)

    assert loaded.id == "snap-1"
    assert json.dumps(loaded.resources, sort_keys=True) == json.dumps(
        expected.resources, sort_keys=True
    )


async def test_write_snapshot_async_roundtrip(tmp_path: Path) -> None:
    store = build_store(seed=5)
    path = await write_snapshot_async(store.snapshot(), tmp_path / "initial.json")
    loaded = read_snapshot(path)
    assert loaded.domain_id == "enterprise-confluence"
    assert "pages" in loaded.resources
    assert len(loaded.resources["pages"]) == len(store.pages)


def test_registry_register_get_require() -> None:
    registry = ScenarioRegistry()
    generator = _FakeGenerator()
    registry.register(generator)

    assert registry.require("fake") is generator
    assert registry.get("missing") is None
    assert "fake" in registry
    assert len(registry) == 1
    with pytest.raises(KeyError):
        registry.require("missing")


def test_registry_generate_is_deterministic_per_seed() -> None:
    registry = ScenarioRegistry()
    registry.register(_FakeGenerator())

    first = registry.generate("fake", 42)
    second = registry.generate("fake", 42)
    assert first == second
    assert first.id == "fake-0042"  # type: ignore[attr-defined]


def test_registry_from_modules_discovers_nothing_in_empty_scenario_pkg() -> None:
    registry = ScenarioRegistry.from_modules(["domains.confluence.scenarios"])
    assert registry.ids == ()
