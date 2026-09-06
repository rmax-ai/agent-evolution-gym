"""Tests for domain spec loading, fixture determinism, and snapshot restore."""

import json
import shutil

import pytest
from domains.confluence.world.fixtures.builder import build_store

from agentgym.core.domain import DomainSpec
from agentgym.world.docker import DockerProviderUnavailable, DockerWorldProvider
from agentgym.world.store import InMemoryConfluenceStore

DOMAIN_YAML = "domains/confluence/domain.yaml"


def _resources_json(store: InMemoryConfluenceStore) -> str:
    return json.dumps(store.snapshot().resources, sort_keys=True)


def test_domain_yaml_loads_into_domainspec() -> None:
    spec = DomainSpec.from_yaml(DOMAIN_YAML)
    assert spec.id == "enterprise-confluence"
    assert spec.version == "0.1"
    assert spec.world_provider == "docker"
    assert spec.capabilities == [
        "confluence.pages.read",
        "confluence.pages.write",
        "confluence.search",
    ]
    assert spec.train_split == "splits/train.yaml"
    assert spec.scenario_modules == [
        "scenarios.retrieval",
        "scenarios.edit_page",
        "scenarios.preservation",
        "scenarios.concurrent_edit",
        "scenarios.permissions",
    ]


def test_build_store_is_deterministic_for_a_seed() -> None:
    first = build_store(seed=42)
    second = build_store(seed=42)
    assert _resources_json(first) == _resources_json(second)


def test_build_store_default_is_reproducible() -> None:
    assert _resources_json(build_store()) == _resources_json(build_store())


def test_build_store_variant_shapes() -> None:
    assert len(build_store(variant="default").pages) == 6
    assert len(build_store(variant="minimal").pages) == 2
    permissions = build_store(variant="permissions")
    assert "page-6" in permissions.pages
    assert "page-4" not in permissions.pages


def test_snapshot_restore_roundtrip_is_byte_identical() -> None:
    original = build_store(seed=7)
    before = _resources_json(original)

    restored = InMemoryConfluenceStore()
    restored.restore(original.snapshot())

    assert _resources_json(restored) == before
    # The restored store is fully detached: mutating it does not alter the snapshot.
    restored.pages["page-1"]["body"] = "Changed after restore"
    assert original.pages["page-1"]["body"] != "Changed after restore"
    assert _resources_json(original) == before


@pytest.mark.skipif(shutil.which("docker") is not None, reason="docker present on host")
async def test_docker_provider_raises_when_docker_unavailable() -> None:
    provider = DockerWorldProvider()
    with pytest.raises(DockerProviderUnavailable):
        await provider.start()
    # capabilities() is declarative and works without docker.
    assert {capability.id for capability in await provider.capabilities()} == {
        "confluence.pages.read",
        "confluence.pages.write",
        "confluence.search",
    }
