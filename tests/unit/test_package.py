"""Unit tests for AgentPackage contracts and filesystem persistence."""

import hashlib
from pathlib import Path

import pytest

from agentgym.core.domain import DomainSpec
from agentgym.core.package import (
    AgentPackage,
    KnowledgeArtifact,
    SkillArtifact,
    ToolPackage,
)
from agentgym.world.capabilities import Capability


def _domain() -> DomainSpec:
    return DomainSpec(
        id="enterprise-confluence",
        version="0.1",
        description="Stateful simulated knowledge-management environment.",
        world_provider="process",
        scenario_modules=["scenarios.edit_page"],
        verifier_modules=["verifiers.page_edit"],
        train_split="splits/train.yaml",
        validation_split="splits/validation.yaml",
        test_split="splits/test.yaml",
        capabilities=["confluence.pages.read", "confluence.pages.write"],
    )


def _write_artifacts(package_dir: Path) -> None:
    (package_dir / "knowledge").mkdir(parents=True)
    (package_dir / "skills" / "safely-edit-page").mkdir(parents=True)
    (package_dir / "mcp" / "tools").mkdir(parents=True)
    (package_dir / "knowledge" / "confluence.md").write_bytes(b"knowledge bytes\n")
    (package_dir / "skills" / "safely-edit-page" / "SKILL.md").write_bytes(b"skill bytes\n")
    (package_dir / "mcp" / "server.py").write_bytes(b"server bytes\n")
    (package_dir / "mcp" / "tools" / "safe.py").write_bytes(b"tool bytes\n")


def _package() -> AgentPackage:
    return AgentPackage(
        id="baseline",
        version="0.1",
        generation=0,
        parent_id=None,
        knowledge=[
            KnowledgeArtifact(
                path="confluence.md",
                sha256="not-yet-computed",
                tags=["confluence"],
            )
        ],
        skills=[SkillArtifact(path="safely-edit-page/SKILL.md", sha256="not-yet-computed")],
        tools=ToolPackage(
            root="mcp",
            server_entrypoint="server.py",
            sha256="not-yet-computed",
            declared_capabilities=["confluence.pages.read", "confluence.pages.write"],
        ),
        metadata={"purpose": "baseline", "seed": 42},
    )


def test_package_save_loads_yaml_and_hashes_artifact_bytes(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    _write_artifacts(package_dir)
    package = _package()

    package.save(package_dir, domain=_domain())
    loaded = AgentPackage.from_yaml(package_dir / "package.yaml", domain=_domain())

    knowledge_hash = hashlib.sha256(
        (package_dir / "knowledge" / "confluence.md").read_bytes()
    ).hexdigest()
    skill_hash = hashlib.sha256(
        (package_dir / "skills" / "safely-edit-page" / "SKILL.md").read_bytes()
    ).hexdigest()
    tool_digest = hashlib.sha256()
    for relative_path in ("server.py", "tools/safe.py"):
        encoded_path = relative_path.encode("utf-8")
        contents = (package_dir / "mcp" / relative_path).read_bytes()
        tool_digest.update(len(encoded_path).to_bytes(8, "big"))
        tool_digest.update(encoded_path)
        tool_digest.update(len(contents).to_bytes(8, "big"))
        tool_digest.update(contents)

    assert package.knowledge[0].sha256 == knowledge_hash
    assert package.skills[0].sha256 == skill_hash
    assert package.tools.sha256 == tool_digest.hexdigest()
    assert loaded == package
    package.verify_hashes(package_dir)


def test_package_json_round_trip() -> None:
    package = _package()

    assert AgentPackage.model_validate(package.model_dump(mode="json")) == package


def test_package_validates_declared_capabilities_against_domain() -> None:
    package = _package()
    package.validate_capabilities(_domain())
    package.validate_capabilities(
        [
            Capability(
                id="confluence.pages.read",
                system="confluence",
                operation="pages.read",
            ),
            Capability(
                id="confluence.pages.write",
                system="confluence",
                operation="pages.write",
            ),
        ]
    )

    package.tools.declared_capabilities.append("confluence.search")
    with pytest.raises(ValueError, match=r"confluence\.search"):
        package.validate_capabilities(_domain())
